from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import QCChecklist, QCQuestion
from .chunking_service import sanitize_identifier
from .embedding_service import get_embedding, get_embedding_batch
from .gemini_runtime_service import GeminiTokenTracker
from .ocr_index_service import _is_namespace_not_found_error, _normalize_matches, _with_retries
from .pinecone_client import get_index, get_namespace
from .rag_config import get_rag_settings


def _question_record_id(checklist: QCChecklist, question: QCQuestion) -> str:
    case_part = sanitize_identifier(checklist.case_id or "template", 24) or "template"
    checklist_part = sanitize_identifier(checklist.id, 24) or "checklist"
    question_part = sanitize_identifier(question.id, 24) or "question"
    return f"{case_part}-{checklist_part}-{question_part}"


def _question_metadata(
    checklist: QCChecklist,
    question: QCQuestion,
    *,
    source_page_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "record_type": "checklist-answer",
        "case_id": str(checklist.case_id or ""),
        "checklist_id": str(checklist.id),
        "checklist_name": str(checklist.name or ""),
        "question_id": str(question.id),
        "question_code": str(question.code or ""),
        "question": str(question.description or "")[:2000],
        "document_title": f"{checklist.name} | {question.code or question.id}"[:500],
        "where_to_verify": str(question.where_to_verify or "")[:1200],
        "answer": str(question.ai_answer or question.answer or ""),
        "confidence": str(question.ai_confidence or ""),
        "explanation": str(question.ai_notes or question.notes or "")[:2000],
        "correction": str(question.correction or "")[:1200],
        "source_page_ids": ",".join(str(page_id) for page_id in (source_page_ids or []) if page_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def upsert_qc_question_answer(
    checklist: QCChecklist,
    question: QCQuestion,
    *,
    source_page_ids: list[str] | None = None,
    tracker: GeminiTokenTracker | None = None,
) -> dict[str, Any]:
    if not question.description.strip():
        return {"vectors_count": 0}

    settings = get_rag_settings()
    index = get_index()
    namespace = get_namespace(checklist.case_id)
    embeddings = get_embedding_batch(
        [question.description],
        task_type=settings.embedding_task_type_document,
        titles=[f"{checklist.name} | {question.code or question.id}"[:500]],
        tracker=tracker,
        step_label=f"checklist-upsert-{str(question.id)[:8]}",
    )
    if not embeddings or not embeddings[0]:
        return {"vectors_count": 0}

    vector = {
        "id": _question_record_id(checklist, question),
        "values": embeddings[0],
        "metadata": _question_metadata(
            checklist,
            question,
            source_page_ids=source_page_ids,
        ),
    }
    _with_retries(lambda: index.upsert(vectors=[vector], namespace=namespace))
    return {"vectors_count": 1, "namespace": namespace}


def upsert_qc_question_answers(
    checklist: QCChecklist,
    question_entries: list[tuple[QCQuestion, list[str] | None]],
    *,
    tracker: GeminiTokenTracker | None = None,
) -> dict[str, Any]:
    valid_entries = [
        (question, source_page_ids)
        for question, source_page_ids in question_entries
        if (question.description or "").strip()
    ]
    if not valid_entries:
        return {"vectors_count": 0}

    settings = get_rag_settings()
    index = get_index()
    namespace = get_namespace(checklist.case_id)
    embeddings = get_embedding_batch(
        [question.description for question, _ in valid_entries],
        task_type=settings.embedding_task_type_document,
        tracker=tracker,
        step_label=f"checklist-upsert-batch-{str(checklist.id)[:8]}",
    )
    vectors: list[dict[str, Any]] = []
    for (question, source_page_ids), embedding in zip(valid_entries, embeddings, strict=False):
        if not embedding:
            continue
        vectors.append(
            {
                "id": _question_record_id(checklist, question),
                "values": embedding,
                "metadata": _question_metadata(
                    checklist,
                    question,
                    source_page_ids=source_page_ids,
                ),
            }
        )

    if not vectors:
        return {"vectors_count": 0, "namespace": namespace}

    batch_size = max(1, settings.upsert_batch_size)
    for start in range(0, len(vectors), batch_size):
        batch = vectors[start:start + batch_size]
        _with_retries(lambda batch=batch: index.upsert(vectors=batch, namespace=namespace))
    return {"vectors_count": len(vectors), "namespace": namespace}


def query_checklist_answers(
    question: str,
    *,
    case_id: str | None = None,
    checklist_id: str | None = None,
    top_k: int | None = None,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "checklist-query",
) -> list[dict[str, Any]]:
    settings = get_rag_settings()
    if not question or not question.strip():
        return []

    filter_payload: dict[str, Any] = {"record_type": {"$eq": "checklist-answer"}}
    if case_id:
        filter_payload["case_id"] = {"$eq": str(case_id)}
    if checklist_id:
        filter_payload["checklist_id"] = {"$eq": str(checklist_id)}

    vector = get_embedding(
        question,
        task_type=settings.embedding_task_type_query,
        tracker=tracker,
        step_label=step_label,
    )
    index = get_index()
    namespace = get_namespace(case_id)
    try:
        result = _with_retries(
            lambda: index.query(
                namespace=namespace,
                vector=vector,
                top_k=max(1, top_k or min(3, settings.retrieval_top_k)),
                include_metadata=True,
                include_values=False,
                filter=filter_payload,
            )
        )
    except Exception as exc:
        if _is_namespace_not_found_error(exc):
            return []
        raise
    return _normalize_matches(result)
