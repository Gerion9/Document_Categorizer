"""Router for AI-assisted PDF form filling jobs."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_s3_service
from ..models import AuditLog, Case, FormFillingField, FormFillingJob
from ..schemas import (
    AutofillJobStatus,
    FormGenerationRequest,
    QuestionnaireAutofillResponse,
    FormFillingFieldOut,
    FormFillingFieldUpdate,
    FormFillingJobOut,
    FormFillingRegenerateRequest,
    QuestionnaireAnswersSaveRequest,
    QuestionnaireAnswersSaveResponse,
    QuestionnaireFormTypeOut,
    QuestionnairePageOut,
)
from ..services import form_filling_jobs
from ..services.autofill_jobs import (
    AutofillCancelled,
    AutofillJob,
    cancel_job as cancel_autofill_job,
    find_active_job as find_active_autofill_job,
    get_job as get_autofill_job,
    open_db_session as _open_autofill_db_session,
    start_job as start_autofill_job,
)
from ..services.form_filling_service import (
    ExtractionCircuitBreakerOpen,
    OCRPreparationInProgress,
    autofill_attorney_questionnaire,
    autofill_shared_questionnaire,
    build_generated_form_filename,
    create_job,
    delete_job,
    format_form_generation_validation_error,
    generate_form_from_answers,
    get_background_ocr_progress,
    get_job,
    list_jobs,
    regenerate_filled_pdf,
    run_form_filling_job,
    validate_form_generation_requirements,
)
from ..services.form_type_matcher import get_questionnaire_field_metadata_lookup
from ..services.paths import STORAGE_DIR
from ..services.pdf_service import save_uploaded_file
from ..services.questionnaire_service import (
    get_answers as get_questionnaire_answers,
    get_available_form_type_info,
    get_form_attorney_questions,
    get_form_client_questions,
    get_form_template_path,
    get_shared_questions,
    get_verifications as get_questionnaire_verifications,
    normalize_form_type as normalize_questionnaire_form_type,
    save_answers as save_questionnaire_answers,
)
from ..services.storage_service import S3StorageService
from ..utils.text import clean_text as _clean_text

router = APIRouter(tags=["form-filling"])


def _get_case_or_404(db: Session, case_id: str) -> Case:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def _get_job_or_404(db: Session, job_id: str) -> FormFillingJob:
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Form filling job not found")
    return job


def _field_or_404(db: Session, job_id: str, field_id: str) -> FormFillingField:
    field = (
        db.query(FormFillingField)
        .filter(FormFillingField.job_id == job_id, FormFillingField.id == field_id)
        .first()
    )
    if not field:
        raise HTTPException(404, "Form filling field not found")
    return field


def _as_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _job_out(job: FormFillingJob, *, include_fields: bool = False) -> FormFillingJobOut:
    payload = FormFillingJobOut.model_validate(job).model_dump()
    for key in ("created_at", "updated_at", "started_at", "completed_at"):
        normalized = _as_utc_datetime(payload.get(key))
        if normalized is not None:
            payload[key] = normalized
    if not include_fields:
        payload["fields"] = []
    return FormFillingJobOut(**payload)


def _metadata_lookup(form_type: str | None) -> dict[str, dict[str, object]]:
    if not _clean_text(form_type):
        return {}
    try:
        return get_questionnaire_field_metadata_lookup(form_type or "")
    except ValueError:
        return {}


def _field_metadata_key(field: FormFillingField) -> str:
    item_id = _clean_text(field.questionnaire_item_id)
    field_id = _clean_text(field.questionnaire_field_id)
    if not item_id:
        return ""
    return f"{item_id}.{field_id}" if field_id else item_id


def _field_out(
    field: FormFillingField,
    *,
    metadata_lookup: dict[str, dict[str, object]] | None = None,
) -> FormFillingFieldOut:
    payload = FormFillingFieldOut.model_validate(field).model_dump()
    metadata = (metadata_lookup or {}).get(_field_metadata_key(field), {})
    if metadata:
        payload["section"] = str(metadata.get("section") or "")
        payload["form_text"] = str(metadata.get("form_text") or "")
        payload["instruction"] = str(metadata.get("instruction") or "") or None
        payload["condition"] = str(metadata.get("condition") or "") or None
        payload["optional"] = bool(metadata.get("optional"))
        payload["questionnaire_options"] = list(metadata.get("questionnaire_options") or [])
    payload["requires_manual_confirmation"] = _clean_text(field.responsible_party).lower() == "client"
    return FormFillingFieldOut(**payload)


def _read_result_pdf_bytes(file_path: str, s3: S3StorageService) -> bytes:
    candidate = Path(file_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate.read_bytes()

    storage_candidate = STORAGE_DIR / candidate
    if storage_candidate.exists():
        return storage_candidate.read_bytes()

    return s3.download_bytes(file_path)


def _form_generation_validation_detail(issues: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "message": format_form_generation_validation_error(issues),
        "issues": issues,
    }


@router.get("/questionnaire/form-types", response_model=list[QuestionnaireFormTypeOut])
def list_questionnaire_form_types():
    return get_available_form_type_info()


@router.get("/questionnaire/shared-questions", response_model=list[QuestionnairePageOut])
def get_shared_questionnaire_pages():
    try:
        return get_shared_questions()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/questionnaire/{form_type}/client-questions", response_model=list[QuestionnairePageOut])
def get_form_client_questionnaire_pages(form_type: str):
    try:
        return get_form_client_questions(form_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/questionnaire/{form_type}/attorney-questions", response_model=list[QuestionnairePageOut])
def get_form_attorney_questionnaire_pages(form_type: str):
    try:
        return get_form_attorney_questions(form_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/cases/{case_id}/questionnaire/answers", response_model=dict[str, Any])
def get_case_questionnaire_answers(
    case_id: str,
    form_type: str | None = None,
    db: Session = Depends(get_db),
):
    _get_case_or_404(db, case_id)
    try:
        return get_questionnaire_answers(db, case_id, form_type=form_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get(
    "/cases/{case_id}/questionnaire/verifications",
    response_model=dict[str, Any],
)
def get_case_questionnaire_verifications(
    case_id: str,
    form_type: str | None = None,
    db: Session = Depends(get_db),
):
    _get_case_or_404(db, case_id)
    try:
        return get_questionnaire_verifications(db, case_id, form_type=form_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post(
    "/cases/{case_id}/questionnaire/answers",
    response_model=QuestionnaireAnswersSaveResponse,
)
def save_case_questionnaire_answers(
    case_id: str,
    body: QuestionnaireAnswersSaveRequest,
    db: Session = Depends(get_db),
):
    _get_case_or_404(db, case_id)
    saved_rows = save_questionnaire_answers(db, case_id, body.answers)
    db.add(
        AuditLog(
            case_id=case_id,
            action="questionnaire_answers_saved",
            entity_type="case",
            entity_id=case_id,
            details={
                "saved_count": len(saved_rows),
                "sources": sorted(
                    {_clean_text(row.source) for row in saved_rows if _clean_text(row.source)}
                ),
                "form_types": sorted(
                    {_clean_text(row.form_type) for row in saved_rows if _clean_text(row.form_type)}
                ),
            },
        )
    )
    db.commit()
    return QuestionnaireAnswersSaveResponse(saved_count=len(saved_rows))


def _autofill_audit_action(kind: str) -> str:
    return (
        "questionnaire_attorney_autofilled"
        if kind == "attorney"
        else "questionnaire_shared_autofilled"
    )


def _make_autofill_runner(case_id: str, kind: str):
    """Factory for the worker callable executed inside the autofill thread.

    The worker must own its own DB session because the request-scoped one is
    closed as soon as the POST returns.
    """

    def _runner(job: AutofillJob) -> dict[str, Any]:
        db_session = _open_autofill_db_session()
        try:
            job.progress_message = (
                "Preparing client documents..."
                if kind == "shared"
                else "Preparing attorney documents..."
            )
            job.progress_pct = 5

            def _publish_autofill_progress(progress_pct: float, progress_message: str) -> None:
                try:
                    bounded_pct = round(max(5.0, min(95.0, float(progress_pct))))
                except (TypeError, ValueError):
                    bounded_pct = round(float(job.progress_pct or 5.0))
                job.progress_pct = max(round(float(job.progress_pct or 0.0)), bounded_pct)
                if progress_message:
                    job.progress_message = progress_message

            while True:
                if job.cancel_requested:
                    raise AutofillCancelled()
                try:
                    job.status = "running"
                    if kind == "attorney":
                        result = autofill_attorney_questionnaire(
                            db_session,
                            case_id,
                            progress_callback=_publish_autofill_progress,
                        )
                    else:
                        result = autofill_shared_questionnaire(
                            db_session,
                            case_id,
                            progress_callback=_publish_autofill_progress,
                        )
                    break
                except OCRPreparationInProgress as exc:
                    job.status = "ocr_preparing"

                    def _publish_ocr_progress(
                        processed: int,
                        total: int,
                    ) -> None:
                        job.ocr_processed_pages = processed
                        job.ocr_total_pages = total
                        pct_local = 0
                        if total > 0:
                            pct_local = int((processed / total) * 50)
                        job.progress_pct = round(max(2, min(50, pct_local)))
                        job.progress_message = (
                            f"Reading documents... "
                            f"({processed}/{total} pages)"
                        )

                    _publish_ocr_progress(exc.processed_pages, exc.total_pages)

                    # Poll the live OCR snapshot every second so the UI reflects
                    # per-page progress instead of freezing on the value captured
                    # when the exception was raised.
                    for _ in range(15):
                        if job.cancel_requested:
                            raise AutofillCancelled()
                        time.sleep(1)
                        snapshot = get_background_ocr_progress(case_id)
                        if snapshot is None:
                            break
                        _publish_ocr_progress(
                            snapshot["processed"],
                            snapshot["total"],
                        )
                except ExtractionCircuitBreakerOpen as exc:
                    job.status = "failed"
                    job.progress_message = str(exc)
                    raise

            job.status = "running"
            job.progress_pct = 95
            job.progress_message = "Finalizing analysis..."

            db_session.add(
                AuditLog(
                    case_id=case_id,
                    action=_autofill_audit_action(kind),
                    entity_type="case",
                    entity_id=case_id,
                    details={
                        "suggested_count": int(result.get("suggested_count") or 0),
                        "total_targets": int(result.get("total_targets") or 0),
                        "job_id": job.id,
                    },
                )
            )
            db_session.commit()
            return result
        finally:
            db_session.close()

    return _runner


def _start_autofill(
    *,
    db: Session,
    case_id: str,
    kind: str,
) -> AutofillJobStatus:
    _get_case_or_404(db, case_id)

    try:
        job = start_autofill_job(
            case_id=case_id,
            kind=kind,  # type: ignore[arg-type]
            runner=_make_autofill_runner(case_id, kind),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    return AutofillJobStatus(**job.to_dict())


@router.post(
    "/cases/{case_id}/questionnaire/shared/autofill",
    response_model=AutofillJobStatus,
    status_code=202,
)
def autofill_shared_answers(
    case_id: str,
    db: Session = Depends(get_db),
):
    return _start_autofill(db=db, case_id=case_id, kind="shared")


@router.post(
    "/cases/{case_id}/questionnaire/attorney/autofill",
    response_model=AutofillJobStatus,
    status_code=202,
)
def autofill_attorney_answers(
    case_id: str,
    db: Session = Depends(get_db),
):
    return _start_autofill(db=db, case_id=case_id, kind="attorney")


@router.get(
    "/questionnaire/autofill-jobs/{job_id}",
    response_model=AutofillJobStatus,
)
def get_autofill_job_status(job_id: str):
    job = get_autofill_job(job_id)
    if job is None:
        raise HTTPException(404, "Autofill job not found or expired.")
    return AutofillJobStatus(**job.to_dict())


@router.delete(
    "/questionnaire/autofill-jobs/{job_id}",
    response_model=AutofillJobStatus,
)
def cancel_autofill_job_endpoint(job_id: str):
    job = cancel_autofill_job(job_id)
    if job is None:
        raise HTTPException(404, "Autofill job not found or expired.")
    return AutofillJobStatus(**job.to_dict())


@router.get(
    "/cases/{case_id}/questionnaire/{kind}/autofill-jobs/active",
    response_model=Optional[AutofillJobStatus],
)
def get_active_autofill_job(case_id: str, kind: str):
    if kind not in ("shared", "attorney"):
        raise HTTPException(400, "kind must be 'shared' or 'attorney'.")
    job = find_active_autofill_job(case_id, kind)  # type: ignore[arg-type]
    if job is None:
        return None
    return AutofillJobStatus(**job.to_dict())


@router.post("/cases/{case_id}/form-fill/generate", response_model=FormFillingJobOut)
def generate_filled_form_from_answers(
    case_id: str,
    body: FormGenerationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    _get_case_or_404(db, case_id)

    normalized_form_type = normalize_questionnaire_form_type(body.form_type)
    if not normalized_form_type:
        raise HTTPException(400, "Invalid form type.")

    validation_issues = validate_form_generation_requirements(
        db,
        case_id,
        form_type=normalized_form_type,
    )
    if validation_issues:
        db.add(
            AuditLog(
                case_id=case_id,
                action="form_filling_generation_blocked",
                entity_type="case",
                entity_id=case_id,
                details={
                    "form_type": normalized_form_type,
                    "validation_issues": validation_issues,
                },
            )
        )
        db.commit()
        raise HTTPException(409, _form_generation_validation_detail(validation_issues))

    try:
        template_path = get_form_template_path(normalized_form_type)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc

    job = create_job(
        db,
        case_id=case_id,
        original_pdf_path=str(template_path),
        form_type=normalized_form_type,
    )
    db.add(
        AuditLog(
            case_id=case_id,
            action="form_filling_generation_requested",
            entity_type="form_filling_job",
            entity_id=job.id,
            details={
                "form_type": job.form_type,
                "original_pdf_path": str(template_path),
            },
        )
    )
    db.commit()

    background_tasks.add_task(generate_form_from_answers, job.id)
    return _job_out(job)


@router.post("/cases/{case_id}/form-fill/upload", response_model=FormFillingJobOut, status_code=201)
async def upload_form_pdf(
    case_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    form_type: str | None = Form(None),
    db: Session = Depends(get_db),
    s3: S3StorageService = Depends(get_s3_service),
):
    _get_case_or_404(db, case_id)

    filename = file.filename or "form.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF uploads are supported for form filling.")

    content = await file.read()
    if not content:
        raise HTTPException(400, "The uploaded PDF is empty.")

    upload_path = save_uploaded_file(content, filename, s3)
    job = create_job(
        db,
        case_id=case_id,
        original_pdf_path=upload_path,
        form_type=form_type,
    )
    db.add(
        AuditLog(
            case_id=case_id,
            action="form_filling_uploaded",
            entity_type="form_filling_job",
            entity_id=job.id,
            details={
                "filename": filename,
                "original_pdf_path": upload_path,
                "form_type": job.form_type,
            },
        )
    )
    db.commit()

    background_tasks.add_task(run_form_filling_job, job.id)
    return _job_out(job)


@router.get("/cases/{case_id}/form-fill/jobs", response_model=list[FormFillingJobOut])
def list_case_jobs(
    case_id: str,
    db: Session = Depends(get_db),
):
    _get_case_or_404(db, case_id)
    jobs = list_jobs(db, case_id)
    return [_job_out(job) for job in jobs]


@router.get("/form-fill/jobs/{job_id}", response_model=FormFillingJobOut)
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = _get_job_or_404(db, job_id)
    return _job_out(job)


@router.get("/form-fill/jobs/{job_id}/fields", response_model=list[FormFillingFieldOut])
def get_job_fields(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = _get_job_or_404(db, job_id)
    metadata_lookup = _metadata_lookup(job.form_type)
    fields = (
        db.query(FormFillingField)
        .filter(FormFillingField.job_id == job_id)
        .order_by(FormFillingField.created_at.asc())
        .all()
    )
    return [_field_out(field, metadata_lookup=metadata_lookup) for field in fields]


@router.put("/form-fill/jobs/{job_id}/fields/{field_id}", response_model=FormFillingFieldOut)
def update_job_field(
    job_id: str,
    field_id: str,
    body: FormFillingFieldUpdate,
    db: Session = Depends(get_db),
):
    job = _get_job_or_404(db, job_id)
    if job.status in {"queued", "running"}:
        raise HTTPException(409, "Cannot edit fields while the form filling job is still running.")

    field = _field_or_404(db, job_id, field_id)
    field.extracted_value = body.extracted_value
    field.confidence = body.confidence
    field.evidence_source = body.evidence_source or field.evidence_source or ""
    field.manually_corrected = body.manually_corrected

    rows = db.query(FormFillingField).filter(FormFillingField.job_id == job_id).all()
    job.filled_count = sum(1 for row in rows if (_clean_text(row.extracted_value) if row.id != field.id else _clean_text(body.extracted_value)))
    job.client_filled_count = sum(1 for row in rows if (_clean_text(row.extracted_value) if row.id != field.id else _clean_text(body.extracted_value)) and row.responsible_party == "client")
    job.attorney_filled_count = sum(1 for row in rows if (_clean_text(row.extracted_value) if row.id != field.id else _clean_text(body.extracted_value)) and row.responsible_party == "attorney")
    db.add(field)
    db.add(job)
    db.add(
        AuditLog(
            case_id=job.case_id,
            action="form_filling_field_updated",
            entity_type="form_filling_field",
            entity_id=field.id,
            details={
                "job_id": job.id,
                "field_name": field.field_name,
                "manually_corrected": body.manually_corrected,
            },
        )
    )
    db.commit()
    db.refresh(field)
    return _field_out(field, metadata_lookup=_metadata_lookup(job.form_type))


@router.post("/form-fill/jobs/{job_id}/regenerate", response_model=FormFillingJobOut)
def regenerate_job_pdf(
    job_id: str,
    body: FormFillingRegenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = _get_job_or_404(db, job_id)
    if job.status in {"queued", "running"}:
        raise HTTPException(409, "Cannot regenerate the PDF while the job is still running.")

    validation_issues = validate_form_generation_requirements(
        db,
        job.case_id,
        form_type=job.form_type or "",
    )
    if validation_issues:
        db.add(
            AuditLog(
                case_id=job.case_id,
                action="form_filling_regeneration_blocked",
                entity_type="form_filling_job",
                entity_id=job.id,
                details={
                    "form_type": job.form_type,
                    "validation_issues": validation_issues,
                },
            )
        )
        db.commit()
        raise HTTPException(409, _form_generation_validation_detail(validation_issues))

    if body.preserve_manual_corrections:
        try:
            regenerated_job = regenerate_filled_pdf(db, job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditLog(
                case_id=regenerated_job.case_id,
                action="form_filling_regenerated",
                entity_type="form_filling_job",
                entity_id=regenerated_job.id,
                details={"preserve_manual_corrections": True},
            )
        )
        db.commit()
        return _job_out(regenerated_job)

    runtime_payload = form_filling_jobs.reset_job(
        job.id,
        phase="queued",
        form_type=job.form_type,
        original_pdf_path=job.original_pdf_path,
        field_count=job.field_count,
    )
    if runtime_payload is None:
        form_filling_jobs.create_job(
            case_id=job.case_id,
            original_pdf_path=job.original_pdf_path,
            form_type=job.form_type,
            field_count=job.field_count,
            job_id=job.id,
        )

    job.status = "queued"
    job.phase = "queued"
    job.progress_pct = 0.0
    job.filled_pdf_path = ""
    job.filled_count = 0
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    db.add(job)
    db.add(
        AuditLog(
            case_id=job.case_id,
            action="form_filling_requeued",
            entity_type="form_filling_job",
            entity_id=job.id,
            details={"preserve_manual_corrections": False},
        )
    )
    db.commit()
    background_tasks.add_task(run_form_filling_job, job.id)
    refreshed = _get_job_or_404(db, job.id)
    return _job_out(refreshed)


@router.delete("/form-fill/jobs/{job_id}", status_code=204)
def delete_job_endpoint(
    job_id: str,
    db: Session = Depends(get_db),
):
    _get_job_or_404(db, job_id)
    delete_job(db, job_id)


@router.get("/form-fill/jobs/{job_id}/download")
def download_job_pdf(
    job_id: str,
    db: Session = Depends(get_db),
    s3: S3StorageService = Depends(get_s3_service),
):
    job = _get_job_or_404(db, job_id)
    if not _clean_text(job.filled_pdf_path):
        raise HTTPException(404, "Filled PDF is not available for this job yet.")

    pdf_bytes = _read_result_pdf_bytes(job.filled_pdf_path, s3)
    filename = build_generated_form_filename(db, job)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Expires": "0",
            "Pragma": "no-cache",
        },
    )
