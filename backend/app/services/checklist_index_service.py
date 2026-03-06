from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import QCChecklist, QCQuestion
from .chunking_service import sanitize_identifier
from .embedding_service import get_embedding, get_embedding_batch
from .ocr_index_service import _normalize_matches, _with_retries
from .pinecone_client import get_index, get_namespace
from .rag_config import get_rag_settings


def _question_record_id(checklist: QCChecklist, question: QCQuestion) -> str:
    case_part = sanitize_identifier(checklist.case_id or "template", 24) or "template"
    checklist_part = sanitize_identifier(checklist.id, 24) or "checklist"
    question_part = sanitize_identifier(question.id, 24) or "question"
    return f"{case_part}-{checklist_part}-{question_part}"


def upsert_qc_question_answer(
    checklist: QCChecklist,
    question: QCQuestion,
    *,
    source_page_ids: list[str] | None = None,
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
    )
    if not embeddings or not embeddings[0]:
        return {"vectors_count": 0}

    metadata = {
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
    vector = {
        "id": _question_record_id(checklist, question),
        "values": embeddings[0],
        "metadata": metadata,
    }
    _with_retries(lambda: index.upsert(vectors=[vector], namespace=namespace))
    return {"vectors_count": 1, "namespace": namespace}


def query_checklist_answers(
    question: str,
    *,
    case_id: str | None = None,
    checklist_id: str | None = None,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    settings = get_rag_settings()
    if not question or not question.strip():
        return []

    filter_payload: dict[str, Any] = {"record_type": {"$eq": "checklist-answer"}}
    if case_id:
        filter_payload["case_id"] = {"$eq": str(case_id)}
    if checklist_id:
        filter_payload["checklist_id"] = {"$eq": str(checklist_id)}

    vector = get_embedding(question, task_type=settings.embedding_task_type_query)
    index = get_index()
    namespace = get_namespace(case_id)
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
    return _normalize_matches(result)
