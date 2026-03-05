"""Router – AI text extraction (Gemini Vision OCR / Table extraction)."""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, DocumentType, ExtractionStatus, Page
from ..schemas import PageOut
from ..services.extraction_service import extract_text, is_configured

router = APIRouter(tags=["extraction"])

STORAGE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "storage"


# ── Schemas ───────────────────────────────────────────────────────────────

class ExtractionResult(BaseModel):
    page_id: str
    extraction_status: str
    extraction_method: Optional[str] = None
    ocr_text: Optional[str] = None


class BatchExtractRequest(BaseModel):
    page_ids: list[str]
    has_tables: Optional[bool] = None  # override; if None, infer from DocumentType


# ── Helpers ───────────────────────────────────────────────────────────────

def _determine_has_tables(page: Page, override: Optional[bool], db: Session) -> bool:
    """Determine whether to use table extraction for this page."""
    if override is not None:
        return override
    if page.document_type_id:
        dt = db.query(DocumentType).filter(DocumentType.id == page.document_type_id).first()
        if dt:
            return dt.has_tables or False
    return False


def _do_extraction(page_id: str, has_tables: bool):
    """Run extraction synchronously (called from background task)."""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        page = db.query(Page).filter(Page.id == page_id).first()
        if not page:
            return

        page.extraction_status = ExtractionStatus.PROCESSING.value
        db.commit()

        abs_path = str(STORAGE_DIR / page.file_path)
        method = "gemini_tables" if has_tables else "gemini_ocr"

        try:
            text = extract_text(abs_path, has_tables=has_tables)
            page.ocr_text = text
            page.extraction_status = ExtractionStatus.DONE.value
            page.extraction_method = method
            db.add(
                AuditLog(
                    case_id=page.case_id,
                    action="extracted",
                    entity_type="page",
                    entity_id=page.id,
                    details={"method": method, "chars": len(text)},
                )
            )
        except Exception as exc:
            page.extraction_status = ExtractionStatus.ERROR.value
            page.extraction_method = method
            page.ocr_text = f"[Error] {str(exc)}"
            db.add(
                AuditLog(
                    case_id=page.case_id,
                    action="extraction_error",
                    entity_type="page",
                    entity_id=page.id,
                    details={"method": method, "error": str(exc)},
                )
            )

        db.commit()
    finally:
        db.close()


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/extraction/status")
def extraction_api_status():
    """Check if the Gemini API key is configured."""
    return {"configured": is_configured()}


@router.post("/pages/{page_id}/extract", response_model=ExtractionResult)
def extract_page(
    page_id: str,
    has_tables: Optional[bool] = Query(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """
    Trigger text extraction on a single page.
    If `has_tables` is not provided, the value is inherited from the page's DocumentType.
    Extraction runs in a background task; poll the result with GET /pages/{page_id}/extraction.
    """
    if not is_configured():
        raise HTTPException(503, "GEMINI_API_KEY not configured. Add it to backend/.env")

    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")

    use_tables = _determine_has_tables(page, has_tables, db)

    # Mark as processing immediately
    page.extraction_status = ExtractionStatus.PROCESSING.value
    db.commit()

    background_tasks.add_task(_do_extraction, page_id, use_tables)

    return ExtractionResult(
        page_id=page.id,
        extraction_status=ExtractionStatus.PROCESSING.value,
        extraction_method="gemini_tables" if use_tables else "gemini_ocr",
    )


@router.get("/pages/{page_id}/extraction", response_model=ExtractionResult)
def get_extraction(page_id: str, db: Session = Depends(get_db)):
    """Get the current extraction result for a page."""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")

    return ExtractionResult(
        page_id=page.id,
        extraction_status=page.extraction_status or ExtractionStatus.PENDING.value,
        extraction_method=page.extraction_method,
        ocr_text=page.ocr_text,
    )


@router.post("/cases/{case_id}/extract-batch")
def extract_batch(
    case_id: str,
    body: BatchExtractRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """
    Trigger extraction on multiple pages at once.
    Pages are queued in background tasks.
    """
    if not is_configured():
        raise HTTPException(503, "GEMINI_API_KEY not configured. Add it to backend/.env")

    results = []
    for pid in body.page_ids:
        page = db.query(Page).filter(Page.id == pid, Page.case_id == case_id).first()
        if not page:
            continue

        use_tables = _determine_has_tables(page, body.has_tables, db)
        page.extraction_status = ExtractionStatus.PROCESSING.value
        db.commit()

        background_tasks.add_task(_do_extraction, pid, use_tables)
        results.append({
            "page_id": pid,
            "extraction_status": "processing",
            "method": "gemini_tables" if use_tables else "gemini_ocr",
        })

    return {"queued": len(results), "pages": results}

