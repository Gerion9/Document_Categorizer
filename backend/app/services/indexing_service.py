from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from ..database import SessionLocal
from ..models import AuditLog, ExtractionStatus, IndexStatus, Page
from .embedding_service import is_embeddings_configured
from .extraction_service import extract_text
from .gemini_runtime_service import create_token_tracker, log_token_summary
from .ocr_index_service import index_case_ocr_json, upsert_page_ocr_chunks
from .pinecone_client import is_pinecone_configured


STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"
INDEX_METHOD = "gemini_embedding_pinecone"
log = logging.getLogger("gemini_usage")


def is_indexing_available() -> bool:
    return is_embeddings_configured() and is_pinecone_configured()


def _set_page_index_state(
    page: Page,
    *,
    status: str,
    method: str | None = None,
    vectors_count: int | None = None,
    pinecone_document_id: str | None = None,
) -> None:
    page.index_status = status
    if method is not None:
        page.index_method = method
    if vectors_count is not None:
        page.indexed_vector_count = vectors_count
    if pinecone_document_id is not None:
        page.pinecone_document_id = pinecone_document_id
    if status == IndexStatus.DONE.value:
        page.indexed_at = datetime.now(timezone.utc)


def _audit(db, *, case_id: str, action: str, entity_id: str, details: dict) -> None:
    db.add(
        AuditLog(
            case_id=case_id,
            action=action,
            entity_type="page",
            entity_id=entity_id,
            details=details,
        )
    )


def _compact_token_summary(summary: dict) -> dict[str, int]:
    return {
        "input": int(summary.get("input", 0)),
        "output": int(summary.get("output", 0)),
        "cached": int(summary.get("cached", 0)),
        "thoughts": int(summary.get("thoughts", 0)),
        "embedding": int(summary.get("embedding", 0)),
        "grand_total": int(summary.get("grand_total", 0)),
    }


def index_existing_page_ocr(page_id: str) -> None:
    db = SessionLocal()
    tracker = create_token_tracker(label=f"reindex-{page_id[:8]}")
    try:
        page = db.query(Page).filter(Page.id == page_id).first()
        if not page:
            return

        if not page.ocr_text or not page.ocr_text.strip():
            _set_page_index_state(page, status=IndexStatus.SKIPPED.value, method=INDEX_METHOD, vectors_count=0)
            db.commit()
            return

        if not is_indexing_available():
            _set_page_index_state(page, status=IndexStatus.SKIPPED.value, method=INDEX_METHOD, vectors_count=0)
            db.commit()
            return

        _set_page_index_state(page, status=IndexStatus.PROCESSING.value, method=INDEX_METHOD)
        db.commit()

        result = upsert_page_ocr_chunks(page, tracker=tracker)
        tracker_summary = _compact_token_summary(tracker.get_summary())
        _set_page_index_state(
            page,
            status=IndexStatus.DONE.value,
            method=INDEX_METHOD,
            vectors_count=result["vectors_count"],
            pinecone_document_id=result["document_id"],
        )
        _audit(
            db,
            case_id=page.case_id,
            action="indexed_ocr",
            entity_id=page.id,
            details={
                "vectors": result["vectors_count"],
                "index_name": result["index_name"],
                "index_method": INDEX_METHOD,
                "token_summary": tracker_summary,
            },
        )
        db.commit()
        log_token_summary(tracker, label=f"Reindex page {page.id[:8]}", logger=log)
    except Exception as exc:
        db.rollback()
        page = db.query(Page).filter(Page.id == page_id).first()
        if page:
            _set_page_index_state(page, status=IndexStatus.ERROR.value, method=INDEX_METHOD, vectors_count=0)
            _audit(
                db,
                case_id=page.case_id,
                action="index_error",
                entity_id=page.id,
                details={"error": str(exc), "index_method": INDEX_METHOD},
            )
            db.commit()
    finally:
        db.close()


def process_page_extraction(page_id: str, has_tables: bool) -> dict | None:
    """Extract a single page and persist OCR text. Returns a summary dict or None on skip."""
    db = SessionLocal()
    tracker = create_token_tracker(label=f"page-extraction-{page_id[:8]}")
    try:
        page = db.query(Page).filter(Page.id == page_id).first()
        if not page:
            return None

        page.extraction_status = ExtractionStatus.PROCESSING.value
        _set_page_index_state(page, status=IndexStatus.PENDING.value, method=INDEX_METHOD, vectors_count=0)
        db.commit()

        abs_path = str(STORAGE_DIR / page.file_path)
        method = "gemini_tables" if has_tables else "gemini_ocr"

        try:
            text = extract_text(
                abs_path,
                has_tables=has_tables,
                tracker=tracker,
                step_label=f"ocr-extract-{page.id[:8]}",
            )
            tracker_summary = _compact_token_summary(tracker.get_summary())
            page.ocr_text = text
            page.extraction_status = ExtractionStatus.DONE.value
            page.extraction_method = method
            _audit(
                db,
                case_id=page.case_id,
                action="extracted",
                entity_id=page.id,
                details={
                    "method": method,
                    "chars": len(text),
                    "token_summary": tracker_summary,
                },
            )
        except Exception as exc:
            page.extraction_status = ExtractionStatus.ERROR.value
            page.extraction_method = method
            page.ocr_text = f"[Error] {str(exc)}"
            _set_page_index_state(page, status=IndexStatus.ERROR.value, method=INDEX_METHOD, vectors_count=0)
            _audit(
                db,
                case_id=page.case_id,
                action="extraction_error",
                entity_id=page.id,
                details={"method": method, "error": str(exc), "index_method": INDEX_METHOD},
            )
            db.commit()
            return None

        if is_indexing_available():
            _set_page_index_state(
                page,
                status=IndexStatus.PENDING.value,
                method=INDEX_METHOD,
                vectors_count=0,
            )
        else:
            _set_page_index_state(
                page,
                status=IndexStatus.SKIPPED.value,
                method=INDEX_METHOD,
                vectors_count=0,
                pinecone_document_id=page.id,
            )
            _audit(
                db,
                case_id=page.case_id,
                action="index_skipped",
                entity_id=page.id,
                details={"reason": "Pinecone or embeddings not configured", "index_method": INDEX_METHOD},
            )

        db.commit()

        return {
            "page_id": page.id,
            "page_number": page.original_page_number or 0,
            "original_filename": page.original_filename or "",
            "extraction_method": page.extraction_method or method,
            "extraction_status": page.extraction_status,
            "ocr_text": page.ocr_text or "",
            "chars": len(page.ocr_text or ""),
            "token_summary": _compact_token_summary(tracker.get_summary()),
        }
    finally:
        db.close()


def reindex_case_pages(case_id: str) -> None:
    tracker = create_token_tracker(label=f"case-reindex-{case_id[:8]}")
    try:
        index_case_ocr_json(case_id, tracker=tracker)
        log_token_summary(tracker, label=f"Reindex case {case_id[:8]}", logger=log)
    except Exception:
        log.exception("Case reindex failed for %s", case_id[:8])
