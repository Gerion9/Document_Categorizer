"""Router -- AI text extraction, indexing, and RAG query helpers."""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DocumentType, ExtractionStatus, Page
from ..services.case_extraction_service import extract_case_pages
from ..services.extraction_service import is_configured
from ..services.indexing_service import (
    index_existing_page_ocr,
    is_indexing_available,
    process_page_extraction,
    reindex_case_pages,
)
from ..services.pinecone_client import is_pinecone_configured
from ..services.retrieval_service import query_case_rag

router = APIRouter(tags=["extraction"])

STORAGE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "storage"


# ── Schemas ───────────────────────────────────────────────────────────────

class ExtractionResult(BaseModel):
    page_id: str
    extraction_status: str
    extraction_method: Optional[str] = None
    ocr_text: Optional[str] = None
    index_status: str = "pending"
    index_method: Optional[str] = None
    indexed_vector_count: int = 0
    pinecone_document_id: Optional[str] = None


class BatchExtractRequest(BaseModel):
    page_ids: list[str]
    has_tables: Optional[bool] = None


class ReindexResult(BaseModel):
    queued: int
    page_ids: list[str]


class RagQueryRequest(BaseModel):
    question: str
    top_k: Optional[int] = None
    page_ids: list[str] = []
    section_ids: list[str] = []
    document_type_ids: list[str] = []


class RagMatchOut(BaseModel):
    id: str
    score: float
    metadata: dict


class RagQueryResponse(BaseModel):
    question: str
    total_matches: int
    matches: list[RagMatchOut]


class BatchExtractionStatusResponse(BaseModel):
    case_id: str
    total_pages: int
    done: int
    processing: int
    pending: int
    error: int
    all_complete: bool


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


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/extraction/status")
def extraction_api_status():
    """Check if Gemini OCR and Pinecone indexing are configured."""
    return {
        "configured": is_configured(),
        "gemini_configured": is_configured(),
        "pinecone_configured": is_pinecone_configured(),
        "indexing_configured": is_indexing_available(),
    }


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

    background_tasks.add_task(process_page_extraction, page_id, use_tables)

    return ExtractionResult(
        page_id=page.id,
        extraction_status=ExtractionStatus.PROCESSING.value,
        extraction_method="gemini_tables" if use_tables else "gemini_ocr",
        index_status=page.index_status or "pending",
        index_method=page.index_method,
        indexed_vector_count=page.indexed_vector_count or 0,
        pinecone_document_id=page.pinecone_document_id,
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
        index_status=page.index_status or "pending",
        index_method=page.index_method,
        indexed_vector_count=page.indexed_vector_count or 0,
        pinecone_document_id=page.pinecone_document_id,
    )


@router.post("/cases/{case_id}/extract-batch")
def extract_batch(
    case_id: str,
    body: BatchExtractRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """
    Trigger extraction on multiple pages.
    All pages are processed in a single background task with controlled
    concurrency so the full document is OCR'd and persisted before
    downstream AI flows run.
    """
    if not is_configured():
        raise HTTPException(503, "GEMINI_API_KEY not configured. Add it to backend/.env")

    results = []
    page_ids: list[str] = []
    for pid in body.page_ids:
        page = db.query(Page).filter(Page.id == pid, Page.case_id == case_id).first()
        if not page:
            continue

        use_tables = _determine_has_tables(page, body.has_tables, db)
        page.extraction_status = ExtractionStatus.PROCESSING.value
        db.commit()

        page_ids.append(pid)
        results.append({
            "page_id": pid,
            "extraction_status": "processing",
            "method": "gemini_tables" if use_tables else "gemini_ocr",
        })

    if page_ids:
        background_tasks.add_task(extract_case_pages, case_id, page_ids=page_ids)

    return {"queued": len(results), "pages": results}


@router.post("/pages/{page_id}/reindex", response_model=ReindexResult)
def reindex_page(
    page_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Reindex an already extracted page into Pinecone."""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")
    if not page.ocr_text or not page.ocr_text.strip():
        raise HTTPException(400, "Page does not have OCR text yet")
    if not is_indexing_available():
        raise HTTPException(503, "Pinecone indexing is not configured")

    background_tasks.add_task(index_existing_page_ocr, page_id)
    return ReindexResult(queued=1, page_ids=[page_id])


@router.post("/cases/{case_id}/reindex", response_model=ReindexResult)
def reindex_case(
    case_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Queue OCR reindexing for all extracted pages in a case."""
    if not is_indexing_available():
        raise HTTPException(503, "Pinecone indexing is not configured")

    page_ids = [
        page.id
        for page in db.query(Page)
        .filter(Page.case_id == case_id)
        .order_by(Page.created_at.asc())
        .all()
        if page.ocr_text and page.ocr_text.strip()
    ]
    if not page_ids:
        raise HTTPException(400, "No extracted pages found for this case")

    background_tasks.add_task(reindex_case_pages, case_id)
    return ReindexResult(queued=len(page_ids), page_ids=page_ids)


@router.get("/cases/{case_id}/extraction-status", response_model=BatchExtractionStatusResponse)
def get_case_extraction_status(case_id: str, db: Session = Depends(get_db)):
    """Check how many pages in a case have completed OCR extraction."""
    pages = db.query(Page).filter(Page.case_id == case_id).all()
    total = len(pages)
    done = sum(1 for p in pages if (p.extraction_status or "") == ExtractionStatus.DONE.value)
    processing = sum(1 for p in pages if (p.extraction_status or "") == ExtractionStatus.PROCESSING.value)
    error = sum(1 for p in pages if (p.extraction_status or "") == ExtractionStatus.ERROR.value)
    pending = total - done - processing - error

    return BatchExtractionStatusResponse(
        case_id=case_id,
        total_pages=total,
        done=done,
        processing=processing,
        pending=pending,
        error=error,
        all_complete=(done + error) == total and total > 0,
    )


@router.get("/cases/{case_id}/extraction-json")
def get_extraction_json(case_id: str):
    """Return the full OCR extraction JSON for a case (generated after batch extraction)."""
    from ..services.json_export_service import read_extraction_json

    data = read_extraction_json(case_id)
    if data is None:
        raise HTTPException(404, "Extraction JSON not found. Run batch extraction first.")
    return data


@router.get("/cases/{case_id}/token-usage-json")
def get_token_usage_json(case_id: str):
    """Return the per-page + global token usage JSON for a case."""
    from ..services.json_export_service import read_token_usage_json

    data = read_token_usage_json(case_id)
    if data is None:
        raise HTTPException(404, "Token usage JSON not found. Run batch extraction first.")
    return data


@router.post("/cases/{case_id}/rag/query", response_model=RagQueryResponse)
def query_case_chunks(case_id: str, body: RagQueryRequest):
    """Run a semantic query against OCR chunks indexed for a case."""
    if not is_indexing_available():
        raise HTTPException(503, "Pinecone indexing is not configured")

    matches = query_case_rag(
        body.question,
        case_id=case_id,
        page_ids=body.page_ids,
        section_ids=body.section_ids,
        document_type_ids=body.document_type_ids,
        top_k=body.top_k,
    )
    return RagQueryResponse(
        question=body.question,
        total_matches=len(matches),
        matches=[RagMatchOut(**match) for match in matches],
    )

