from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any
from typing import Callable

from ..database import SessionLocal
from ..models import IndexStatus, Page
from .chunking_service import (
    chunk_text,
    extract_section_label,
    is_garbage_chunk,
    sanitize_identifier,
)
from .embedding_service import get_embedding, get_embedding_batch
from .gemini_runtime_service import GeminiTokenTracker
from .json_export_service import read_extraction_json
from .pinecone_client import get_index, get_namespace
from .rag_config import get_rag_settings


def _should_retry_network_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_tokens = (
        "fetch failed",
        "network",
        "timeout",
        "timed out",
        "temporar",
        "resource exhausted",
        "rate limit",
        "econnreset",
        "503",
        "502",
        "500",
        "429",
    )
    return any(token in message for token in retryable_tokens)


def _with_retries(fn, *, max_retries: int | None = None):
    settings = get_rag_settings()
    retry_limit = max_retries or settings.upsert_max_retries
    last_exc: Exception | None = None

    for attempt in range(1, retry_limit + 1):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - network dependent
            last_exc = exc
            if attempt >= retry_limit or not _should_retry_network_error(exc):
                raise
            delay_ms = settings.upsert_retry_base_ms * (2 ** max(0, attempt - 1))
            delay_ms += random.randint(0, 600)
            time.sleep(delay_ms / 1000)

    raise last_exc or RuntimeError("Network operation failed")


def _section_scopes_for_page(page: Page) -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = []
    document_type = page.document_type
    document_type_id = page.document_type_id or ""
    document_type_code = document_type.code if document_type else ""
    document_type_name = document_type.name if document_type else ""

    links = sorted(
        list(page.section_links or []),
        key=lambda link: (0 if getattr(link, "is_primary", False) else 1, getattr(link, "order_in_section", 0)),
    )
    for link in links:
        section = getattr(link, "section", None)
        scopes.append(
            {
                "scope_id": sanitize_identifier(link.section_id or "unassigned", 24) or "unassigned",
                "section_id": link.section_id or "",
                "section_path_code": getattr(section, "path_code", "") if section else "",
                "section_name": getattr(section, "name", "") if section else "",
                "is_primary_section": bool(getattr(link, "is_primary", False)),
                "document_type_id": document_type_id,
                "document_type_code": document_type_code,
                "document_type_name": document_type_name,
            }
        )

    if scopes:
        return scopes

    section = page.section
    return [
        {
            "scope_id": sanitize_identifier(page.section_id or "unassigned", 24) or "unassigned",
            "section_id": page.section_id or "",
            "section_path_code": getattr(section, "path_code", "") if section else "",
            "section_name": getattr(section, "name", "") if section else "",
            "is_primary_section": bool(page.section_id),
            "document_type_id": document_type_id,
            "document_type_code": document_type_code,
            "document_type_name": document_type_name,
        }
    ]


def _build_chunk_records_for_page_text(
    page: Page,
    text: str,
    *,
    source_type: str | None = None,
    document_id: str | None = None,
) -> list[dict[str, Any]]:
    settings = get_rag_settings()
    if not text or not text.strip():
        return []

    chunk_size = max(400, settings.ocr_chunk_size)
    chunk_overlap = max(0, min(chunk_size - 50, settings.ocr_chunk_overlap))
    resolved_source_type = source_type or page.extraction_method or "gemini_ocr"
    created_at = datetime.now(timezone.utc).isoformat()
    base_chunks = chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
    valid_chunks = [chunk for chunk in base_chunks if chunk.strip() and not is_garbage_chunk(chunk)]
    if not valid_chunks:
        return []

    records: list[dict[str, Any]] = []
    scopes = _section_scopes_for_page(page)

    for scope in scopes:
        document_title = " | ".join(
            part
            for part in [
                str(scope.get("document_type_code", "") or ""),
                str(scope.get("section_path_code", "") or ""),
                str(page.original_filename or ""),
                f"page {int(page.original_page_number or 0)}",
            ]
            if part
        )
        for idx, chunk in enumerate(valid_chunks, start=1):
            base_document_id = sanitize_identifier(document_id or page.id, 40) or str(page.id)
            chunk_id = f"{base_document_id}-{page.id}-{scope['scope_id']}-c{idx}"
            records.append(
                {
                    "id": chunk_id,
                    "text": chunk,
                    "metadata": {
                        "record_type": "ocr-chunk",
                        "case_id": str(page.case_id),
                        "page_id": str(page.id),
                        "page_number": int(page.original_page_number or 0),
                        "original_filename": str(page.original_filename or ""),
                        "document_type_id": str(scope["document_type_id"] or ""),
                        "document_type_code": str(scope["document_type_code"] or ""),
                        "document_type_name": str(scope["document_type_name"] or ""),
                        "section_id": str(scope["section_id"] or ""),
                        "section_path_code": str(scope["section_path_code"] or ""),
                        "section_name": str(scope["section_name"] or ""),
                        "is_primary_section": bool(scope["is_primary_section"]),
                        "chunk_order": idx,
                        "source_type": resolved_source_type,
                        "document_id": str(document_id or page.id),
                        "document_title": document_title[:500],
                        "section_label": extract_section_label(chunk),
                        "created_at": created_at,
                        "text": chunk,
                    },
                }
            )

    return records


def _build_chunk_records_for_page(page: Page) -> list[dict[str, Any]]:
    return _build_chunk_records_for_page_text(page, page.ocr_text or "")


def delete_page_ocr_chunks(page_id: str, case_id: str | None = None) -> None:
    index = get_index()
    namespace = get_namespace(case_id)
    _with_retries(
        lambda: index.delete(
            namespace=namespace,
            filter={"page_id": {"$eq": str(page_id)}},
        )
    )


def delete_case_ocr_chunks(case_id: str) -> None:
    index = get_index()
    namespace = get_namespace(case_id)
    _with_retries(
        lambda: index.delete(
            namespace=namespace,
            filter={"record_type": {"$eq": "ocr-chunk"}},
        )
    )


def upsert_page_ocr_chunks(
    page: Page,
    *,
    tracker: GeminiTokenTracker | None = None,
) -> dict[str, Any]:
    index = get_index()
    settings = get_rag_settings()
    namespace = get_namespace(page.case_id)
    records = _build_chunk_records_for_page(page)
    if not records:
        return {
            "vectors_count": 0,
            "document_id": str(page.id),
            "index_name": settings.pinecone_index_ocr,
            "namespace": namespace,
        }

    delete_page_ocr_chunks(page.id, page.case_id)
    embeddings = get_embedding_batch(
        [record["text"] for record in records],
        task_type=settings.embedding_task_type_document,
        titles=[str(record["metadata"].get("document_title", "") or "") for record in records],
        tracker=tracker,
        step_label=f"ocr-upsert-{str(page.id)[:8]}",
    )
    vectors = []
    for record, embedding in zip(records, embeddings, strict=False):
        if not embedding:
            continue
        vectors.append(
            {
                "id": record["id"],
                "values": embedding,
                "metadata": record["metadata"],
            }
        )

    batch_size = settings.upsert_batch_size
    for start in range(0, len(vectors), batch_size):
        batch = vectors[start:start + batch_size]
        _with_retries(lambda batch=batch: index.upsert(vectors=batch, namespace=namespace))

    return {
        "vectors_count": len(vectors),
        "document_id": str(page.id),
        "index_name": settings.pinecone_index_ocr,
        "namespace": namespace,
    }


def _build_chunk_records_for_case_json(case_id: str) -> list[dict[str, Any]]:
    payload = read_extraction_json(case_id) or {}
    page_payloads = payload.get("pages", []) or []
    if not isinstance(page_payloads, list):
        return []

    db = SessionLocal()
    try:
        pages = db.query(Page).filter(Page.case_id == case_id).all()
        pages_by_id = {str(page.id): page for page in pages}
        records: list[dict[str, Any]] = []
        document_id = f"case-{case_id}"

        for page_payload in page_payloads:
            if not isinstance(page_payload, dict):
                continue
            page_id = str(page_payload.get("page_id", "") or "")
            text = str(page_payload.get("ocr_text", "") or "").strip()
            status = str(page_payload.get("extraction_status", "") or "")
            if not page_id or not text or status == "error":
                continue
            page = pages_by_id.get(page_id)
            if page is None:
                continue
            records.extend(
                _build_chunk_records_for_page_text(
                    page,
                    text,
                    source_type=str(page_payload.get("extraction_method", "") or page.extraction_method or "gemini_ocr"),
                    document_id=document_id,
                )
            )
        return records
    finally:
        db.close()


def index_case_ocr_json(
    case_id: str,
    *,
    tracker: GeminiTokenTracker | None = None,
    progress_callback: Callable[[dict[str, int | str]], None] | None = None,
) -> dict[str, Any]:
    index = get_index()
    settings = get_rag_settings()
    namespace = get_namespace(case_id)
    records = _build_chunk_records_for_case_json(case_id)
    total_chunks = len(records)

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "indexing_document",
                "index_total_chunks": total_chunks,
                "index_processed_chunks": 0,
                "index_error_chunks": 0,
            }
        )

    db = SessionLocal()
    try:
        pages = db.query(Page).filter(Page.case_id == case_id).all()
        for page in pages:
            if not (page.ocr_text or "").strip():
                continue
            page.index_status = IndexStatus.PROCESSING.value
            page.index_method = "gemini_embedding_pinecone"
            page.indexed_vector_count = 0
            page.pinecone_document_id = None
        db.commit()
    finally:
        db.close()

    delete_case_ocr_chunks(case_id)

    if not records:
        return {
            "vectors_count": 0,
            "document_id": str(case_id),
            "index_name": settings.pinecone_index_ocr,
            "namespace": namespace,
            "total_chunks": 0,
        }

    embeddings = get_embedding_batch(
        [record["text"] for record in records],
        task_type=settings.embedding_task_type_document,
        tracker=tracker,
        step_label=f"ocr-case-upsert-{str(case_id)[:8]}",
        progress_callback=(
            None
            if progress_callback is None
            else lambda processed, total: progress_callback(
                {
                    "phase": "indexing_document",
                    "index_total_chunks": total,
                    "index_processed_chunks": processed,
                    "index_error_chunks": 0,
                }
            )
        ),
    )

    vectors = []
    for record, embedding in zip(records, embeddings, strict=False):
        if not embedding:
            continue
        vectors.append(
            {
                "id": record["id"],
                "values": embedding,
                "metadata": record["metadata"],
            }
        )

    batch_size = settings.upsert_batch_size
    processed_vectors = 0
    for start in range(0, len(vectors), batch_size):
        batch = vectors[start:start + batch_size]
        _with_retries(lambda batch=batch: index.upsert(vectors=batch, namespace=namespace))
        processed_vectors += len(batch)
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "indexing_document",
                    "index_total_chunks": len(vectors),
                    "index_processed_chunks": processed_vectors,
                    "index_error_chunks": 0,
                }
            )

    db = SessionLocal()
    try:
        vectors_by_page: dict[str, int] = {}
        for vector in vectors:
            metadata = vector.get("metadata", {}) or {}
            page_id = str(metadata.get("page_id", "") or "")
            if not page_id:
                continue
            vectors_by_page[page_id] = vectors_by_page.get(page_id, 0) + 1

        pages = db.query(Page).filter(Page.case_id == case_id).all()
        now = datetime.now(timezone.utc)
        for page in pages:
            if not (page.ocr_text or "").strip():
                continue
            page.index_status = IndexStatus.DONE.value
            page.index_method = "gemini_embedding_pinecone"
            page.indexed_vector_count = vectors_by_page.get(str(page.id), 0)
            page.pinecone_document_id = str(case_id)
            page.indexed_at = now
        db.commit()
    finally:
        db.close()

    return {
        "vectors_count": len(vectors),
        "document_id": str(case_id),
        "index_name": settings.pinecone_index_ocr,
        "namespace": namespace,
        "total_chunks": total_chunks,
    }


def _normalize_matches(result: Any) -> list[dict[str, Any]]:
    matches = getattr(result, "matches", None)
    if matches is None and isinstance(result, dict):
        matches = result.get("matches", [])
    normalized: list[dict[str, Any]] = []

    for match in matches or []:
        metadata = getattr(match, "metadata", None)
        if metadata is None and isinstance(match, dict):
            metadata = match.get("metadata", {})
        normalized.append(
            {
                "id": getattr(match, "id", None) or (match.get("id") if isinstance(match, dict) else ""),
                "score": getattr(match, "score", None) or (match.get("score") if isinstance(match, dict) else 0),
                "metadata": metadata or {},
            }
        )

    return normalized


def query_ocr_chunks(
    question: str,
    *,
    case_id: str | None = None,
    page_ids: list[str] | None = None,
    section_ids: list[str] | None = None,
    document_type_ids: list[str] | None = None,
    top_k: int | None = None,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "ocr-query",
) -> list[dict[str, Any]]:
    settings = get_rag_settings()
    if not question or not question.strip():
        return []

    filter_payload: dict[str, Any] = {"record_type": {"$eq": "ocr-chunk"}}
    if case_id:
        filter_payload["case_id"] = {"$eq": str(case_id)}
    if page_ids:
        filter_payload["page_id"] = {"$in": [str(page_id) for page_id in page_ids]}
    if section_ids:
        filter_payload["section_id"] = {"$in": [str(section_id) for section_id in section_ids]}
    if document_type_ids:
        filter_payload["document_type_id"] = {"$in": [str(doc_id) for doc_id in document_type_ids]}

    vector = get_embedding(
        question,
        task_type=settings.embedding_task_type_query,
        tracker=tracker,
        step_label=step_label,
    )
    index = get_index()
    namespace = get_namespace(case_id)
    result = _with_retries(
        lambda: index.query(
            namespace=namespace,
            vector=vector,
            top_k=max(1, top_k or settings.retrieval_top_k),
            include_metadata=True,
            include_values=False,
            filter=filter_payload,
        )
    )
    return _normalize_matches(result)
