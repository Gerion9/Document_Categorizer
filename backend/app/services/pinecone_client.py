from __future__ import annotations

from functools import lru_cache
import re

from .rag_config import get_rag_settings


@lru_cache(maxsize=1)
def _get_client():
    from pinecone import Pinecone

    settings = get_rag_settings()
    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY not configured")
    return Pinecone(api_key=settings.pinecone_api_key)


def is_pinecone_configured() -> bool:
    return get_rag_settings().pinecone_configured


def get_index(index_name: str | None = None):
    settings = get_rag_settings()
    if not settings.pinecone_configured:
        raise RuntimeError("Pinecone is not configured")
    client = _get_client()
    return client.Index(index_name or settings.pinecone_index_ocr)


def get_namespace(case_id: str | None = None) -> str:
    settings = get_rag_settings()
    raw = str(case_id or "shared").strip().lower()
    clean = re.sub(r"[^a-z0-9-]", "-", raw)
    clean = re.sub(r"-+", "-", clean).strip("-") or "shared"
    return f"{settings.pinecone_namespace_prefix}-{clean}"
