from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _load_env_file() -> None:
    try:
        from dotenv import load_dotenv

        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        load_dotenv(env_path)
    except ImportError:
        pass


def _env_str(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RagSettings:
    gemini_api_key: str
    gemini_model: str
    gemini_vision_model: str
    gemini_enable_explicit_cache: bool
    gemini_cache_ttl_seconds: int
    gemini_cache_refresh_buffer_ms: int
    gemini_cache_reuse_log_cooldown_ms: int
    gemini_log_token_usage: bool
    gemini_embedding_char_estimate_divisor: int
    embedding_model: str
    embedding_dimension: int
    embedding_task_type_query: str
    embedding_task_type_document: str
    embedding_batch_size: int
    embedding_max_retries: int
    embedding_retry_base_ms: int
    ocr_chunk_size: int
    ocr_chunk_overlap: int
    retrieval_top_k: int
    upsert_batch_size: int
    upsert_max_retries: int
    upsert_retry_base_ms: int
    pinecone_api_key: str
    pinecone_index_ocr: str
    pinecone_namespace_prefix: str

    @property
    def pinecone_configured(self) -> bool:
        return bool(self.pinecone_api_key and self.pinecone_index_ocr)

    @property
    def embeddings_configured(self) -> bool:
        return bool(self.gemini_api_key and self.embedding_model)

    @property
    def retrieval_configured(self) -> bool:
        return self.pinecone_configured and self.embeddings_configured


@lru_cache(maxsize=1)
def get_rag_settings() -> RagSettings:
    _load_env_file()
    return RagSettings(
        gemini_api_key=_env_str("GEMINI_API_KEY"),
        gemini_model=_env_str("GEMINI_MODEL", "gemini-2.0-flash"),
        gemini_vision_model=_env_str("GEMINI_VISION_MODEL", "gemini-2.0-flash"),
        gemini_enable_explicit_cache=_env_bool("GEMINI_ENABLE_EXPLICIT_CACHE", True),
        gemini_cache_ttl_seconds=max(60, _env_int("GEMINI_CACHE_TTL_SECONDS", 3600)),
        gemini_cache_refresh_buffer_ms=max(0, _env_int("GEMINI_CACHE_REFRESH_BUFFER_MS", 45000)),
        gemini_cache_reuse_log_cooldown_ms=max(0, _env_int("GEMINI_CACHE_REUSE_LOG_COOLDOWN_MS", 60000)),
        gemini_log_token_usage=_env_bool("GEMINI_LOG_TOKEN_USAGE", True),
        gemini_embedding_char_estimate_divisor=max(1, _env_int("GEMINI_EMBEDDING_CHAR_ESTIMATE_DIVISOR", 4)),
        embedding_model=_env_str("EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_dimension=max(0, _env_int("EMBEDDING_DIMENSION", 1024)),
        embedding_task_type_query=_env_str("EMBEDDING_TASK_TYPE_QUERY", "RETRIEVAL_QUERY"),
        embedding_task_type_document=_env_str("EMBEDDING_TASK_TYPE_DOCUMENT", "RETRIEVAL_DOCUMENT"),
        embedding_batch_size=max(1, _env_int("EMBEDDING_BATCH_SIZE", 50)),
        embedding_max_retries=max(1, _env_int("EMBEDDING_MAX_RETRIES", 6)),
        embedding_retry_base_ms=max(100, _env_int("EMBEDDING_RETRY_BASE_MS", 1200)),
        ocr_chunk_size=max(200, _env_int("OCR_CHUNK_SIZE", 1200)),
        ocr_chunk_overlap=max(0, _env_int("OCR_CHUNK_OVERLAP", 200)),
        retrieval_top_k=max(1, _env_int("RETRIEVAL_TOP_K", 6)),
        upsert_batch_size=max(1, _env_int("UPSERT_BATCH_SIZE", 30)),
        upsert_max_retries=max(1, _env_int("UPSERT_MAX_RETRIES", 5)),
        upsert_retry_base_ms=max(100, _env_int("UPSERT_RETRY_BASE_MS", 2000)),
        pinecone_api_key=_env_str("PINECONE_API_KEY"),
        pinecone_index_ocr=_env_str("PINECONE_INDEX_OCR", "document-categorizer-ocr"),
        pinecone_namespace_prefix=_env_str("PINECONE_NAMESPACE_PREFIX", "case"),
    )
