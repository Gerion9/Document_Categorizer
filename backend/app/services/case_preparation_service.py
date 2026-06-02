"""Run OCR, indexing, and shared autofill context detection for a case."""

from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Page, PageStatus
from .autofill_case_cache import (
    get_case_readiness_snapshot,
    store_autofill_context,
    store_case_readiness_snapshot,
)
from .case_extraction_service import extract_case_pages
from .case_pipeline_lock import CasePipelineBusy, case_pipeline_lock
from .case_preparation_jobs import (
    CasePreparationJob,
    find_active_job,
    mark_context_phase,
    start_job,
    update_from_index_progress,
    update_from_ocr_progress,
    wait_for_active_job,
)
from .extraction_service import is_configured as is_ocr_configured
from .gemini_runtime_service import create_token_tracker
from .indexing_service import is_indexing_available
from .ocr_index_service import index_case_ocr_json

log = logging.getLogger(__name__)


def is_organization_complete(db: Session, case_id: str) -> bool:
    total_pages = (
        db.query(Page.id)
        .filter(Page.case_id == case_id, Page.deleted_at.is_(None))
        .count()
    )
    if total_pages <= 0:
        return False
    unclassified = (
        db.query(Page.id)
        .filter(
            Page.case_id == case_id,
            Page.deleted_at.is_(None),
            Page.status == PageStatus.UNCLASSIFIED.value,
        )
        .count()
    )
    return unclassified == 0


def _load_all_case_pages(db: Session, case_id: str) -> list[Page]:
    return (
        db.query(Page)
        .filter(Page.case_id == case_id, Page.deleted_at.is_(None))
        .order_by(Page.original_page_number.asc(), Page.created_at.asc())
        .all()
    )


def case_needs_preparation(db: Session, case_id: str) -> bool:
    snapshot = get_case_readiness_snapshot(case_id)
    if snapshot and snapshot.get("ready"):
        return False

    from .form_filling_service import _summarize_case_page_readiness

    pages = _load_all_case_pages(db, case_id)
    readiness = _summarize_case_page_readiness(pages)
    if readiness["total_pages"] <= 0:
        return False
    if readiness["missing_ocr_pages"] > 0:
        return True
    if is_indexing_available() and readiness.get("needs_index_pages", 0) > 0:
        return True
    return False


def run_case_preparation(job: CasePreparationJob) -> dict[str, Any]:
    from ..models import Case
    from ..prompts.form_filling_prompts import build_applicant_context_instruction
    from .form_filling_service import (
        _detect_case_form_type,
        _detect_principal_applicant_name,
        _get_source_document_ids,
        _summarize_case_page_readiness,
    )

    db = SessionLocal()
    tracker = create_token_tracker(label=f"case-prep-{job.case_id[:8]}")
    try:
        pages = _load_all_case_pages(db, job.case_id)
        readiness_before = _summarize_case_page_readiness(pages)
        if readiness_before["total_pages"] <= 0:
            return {"ready": False, "reason": "no_pages", "readiness_before": readiness_before}

        if readiness_before["missing_ocr_pages"] > 0:
            if not is_ocr_configured():
                raise RuntimeError("GEMINI_API_KEY is required for case preparation OCR.")
            job.status = "ocr_preparing"
            job.phase = "extracting_document"

            def _ocr_progress(payload: dict[str, int | str]) -> None:
                update_from_ocr_progress(job.id, payload)

            with case_pipeline_lock(job.case_id, timeout=600):
                ocr_summary = extract_case_pages(
                    job.case_id,
                    only_missing=True,
                    progress_callback=_ocr_progress,
                )
        else:
            ocr_summary = {
                "queued": 0,
                "processed": 0,
                "errors": 0,
                "already_done": readiness_before["usable_ocr_pages"],
            }

        db.expire_all()
        pages = _load_all_case_pages(db, job.case_id)
        readiness_after_ocr = _summarize_case_page_readiness(pages)
        if readiness_after_ocr["usable_ocr_pages"] <= 0:
            raise RuntimeError("Case preparation finished OCR but no usable text is available.")

        index_summary = None
        if is_indexing_available() and readiness_after_ocr.get("needs_index_pages", 0) > 0:
            job.phase = "indexing_document"
            job.progress_message = "Preparing evidence search..."

            def _index_progress(payload: dict[str, int | str]) -> None:
                update_from_index_progress(job.id, payload)

            try:
                with case_pipeline_lock(job.case_id, timeout=600):
                    index_summary = index_case_ocr_json(
                        job.case_id,
                        tracker=tracker,
                        progress_callback=_index_progress,
                    )
            except CasePipelineBusy:
                log.warning("Case preparation %s: pipeline busy during indexing", job.case_id[:8])

        db.expire_all()
        pages = _load_all_case_pages(db, job.case_id)
        readiness_after = _summarize_case_page_readiness(pages)

        mark_context_phase(job.id)
        source_document_ids = _get_source_document_ids(db, job.case_id)
        form_type = _detect_case_form_type(db, job.case_id)
        detected_name = _detect_principal_applicant_name(
            job.case_id,
            tracker,
            source_document_ids=source_document_ids,
        )
        if not detected_name:
            case_row = db.query(Case).filter(Case.id == job.case_id).first()
            detected_name = (case_row.name or "").strip() if case_row else ""
        applicant_context = build_applicant_context_instruction(detected_name)
        store_autofill_context(
            job.case_id,
            source_document_ids,
            form_type=form_type,
            detected_name=detected_name,
            applicant_context=applicant_context,
        )

        summary = {
            "ready": True,
            "readiness_before": readiness_before,
            "readiness_after": readiness_after,
            "ocr": ocr_summary,
            "indexing": index_summary,
            "form_type": form_type,
            "detected_name": detected_name,
        }
        store_case_readiness_snapshot(job.case_id, summary)
        return summary
    finally:
        db.close()


def ensure_questionnaire_autofill_ready(
    db: Session,
    case_id: str,
    *,
    source_document_ids: list[str] | None,
    progress_callback: Callable[[float, str], None] | None = None,
    wait_for_case_preparation: bool = True,
) -> dict[str, Any]:
    from .form_filling_service import _load_case_pages, _summarize_case_page_readiness

    if wait_for_case_preparation:
        active = find_active_job(case_id)
        if active is not None:
            if progress_callback is not None:
                progress_callback(5.0, "Waiting for case preparation to finish...")
            finished = wait_for_active_job(case_id)
            if finished is not None and finished.status == "failed":
                raise RuntimeError(finished.error or "Case preparation failed.")

    snapshot = get_case_readiness_snapshot(case_id)
    pages = _load_case_pages(db, case_id, source_document_ids=source_document_ids)
    readiness = _summarize_case_page_readiness(pages)

    if readiness["total_pages"] <= 0:
        if source_document_ids is not None:
            raise ValueError(
                "No documents are selected for form filling. Choose at least one case document in the forms panel."
            )
        raise ValueError(
            "No case pages are available. Upload the supporting documents before using OCR autofill."
        )

    if snapshot and snapshot.get("ready") and readiness["missing_ocr_pages"] == 0:
        if not is_indexing_available() or readiness.get("needs_index_pages", 0) == 0:
            if progress_callback is not None:
                progress_callback(15.0, "Using prepared case documents...")
            return readiness

    if readiness["missing_ocr_pages"] > 0:
        if not is_ocr_configured():
            raise RuntimeError("GEMINI_API_KEY is required to run OCR autofill.")
        if progress_callback is not None:
            progress_callback(2.0, "Reading documents...")

        def _ocr_progress(payload: dict[str, int | str]) -> None:
            if progress_callback is None:
                return
            total = int(payload.get("ocr_total_pages") or readiness["total_pages"] or 0)
            processed = int(payload.get("ocr_processed_pages") or 0)
            pct = 0.0 if total <= 0 else max(2.0, min(50.0, (processed / total) * 50.0))
            progress_callback(
                pct,
                f"Reading documents... ({processed}/{total} pages)",
            )

        with case_pipeline_lock(case_id, timeout=600):
            extract_case_pages(
                case_id,
                page_ids=[page.id for page in pages] if source_document_ids is not None else None,
                only_missing=True,
                progress_callback=_ocr_progress,
            )
        db.expire_all()
        pages = _load_case_pages(db, case_id, source_document_ids=source_document_ids)
        readiness = _summarize_case_page_readiness(pages)

    if readiness["usable_ocr_pages"] <= 0:
        raise ValueError(
            "Automatic OCR completed, but no usable text is available for the selected form-filling documents."
            if source_document_ids is not None
            else "Automatic OCR completed, but no usable document text is available to autofill the questionnaire."
        )

    if is_indexing_available() and readiness.get("needs_index_pages", 0) > 0:
        if progress_callback is not None:
            progress_callback(10.0, "Preparing evidence search...")
        try:
            with case_pipeline_lock(case_id, timeout=600):
                index_case_ocr_json(
                    case_id,
                    tracker=create_token_tracker(label=f"autofill-index-{case_id[:8]}"),
                    source_document_ids=source_document_ids,
                )
        except CasePipelineBusy:
            log.warning("Autofill %s: pipeline busy during scoped indexing", case_id[:8])
        db.expire_all()
        pages = _load_case_pages(db, case_id, source_document_ids=source_document_ids)
        readiness = _summarize_case_page_readiness(pages)

    store_case_readiness_snapshot(
        case_id,
        {
            "ready": readiness["missing_ocr_pages"] == 0
            and (not is_indexing_available() or readiness.get("needs_index_pages", 0) == 0),
            "readiness_after": readiness,
            "scope": source_document_ids,
        },
    )
    return readiness


def resolve_autofill_case_context(
    db: Session,
    case_id: str,
    tracker: Any,
    *,
    source_document_ids: list[str] | None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> tuple[str, str, str]:
    from ..models import Case
    from ..prompts.form_filling_prompts import build_applicant_context_instruction
    from .autofill_case_cache import get_autofill_context
    from .form_filling_service import _detect_case_form_type, _detect_principal_applicant_name

    cached = get_autofill_context(case_id, source_document_ids)
    if cached is not None:
        if progress_callback is not None:
            progress_callback(15.0, "Using prepared case context...")
        return cached.form_type, cached.detected_name, cached.applicant_context

    if progress_callback is not None:
        progress_callback(15.0, "Detecting case context...")

    form_type = _detect_case_form_type(db, case_id)
    detected_name = _detect_principal_applicant_name(
        case_id,
        tracker,
        source_document_ids=source_document_ids,
    )
    if not detected_name:
        case_row = db.query(Case).filter(Case.id == case_id).first()
        detected_name = (case_row.name or "").strip() if case_row else ""
    applicant_context = build_applicant_context_instruction(detected_name)
    store_autofill_context(
        case_id,
        source_document_ids,
        form_type=form_type,
        detected_name=detected_name,
        applicant_context=applicant_context,
    )
    return form_type, detected_name, applicant_context


def maybe_start_case_preparation(case_id: str) -> None:
    db = SessionLocal()
    try:
        if not is_organization_complete(db, case_id):
            return
        if not case_needs_preparation(db, case_id):
            return
        if find_active_job(case_id) is not None:
            return
        log.info("Queueing case preparation for organized case %s", case_id[:8])
        start_job(case_id, run_case_preparation)
    finally:
        db.close()
