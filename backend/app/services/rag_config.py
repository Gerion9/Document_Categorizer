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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
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
    gemini_log_token_details: bool
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
    evidence_context_max_chars: int
    db_fallback_max_chars: int
    pinecone_api_key: str
    pinecone_index_ocr: str
    pinecone_namespace_prefix: str
    qc_batch_use_prompt_cache: bool
    qc_batch_model: str
    qc_batch_max_output_tokens: int
    qc_batch_fast_prompt: bool
    autopilot_evidence_top_k: int
    autopilot_evidence_max_chars: int
    autopilot_evidence_workers: int
    autopilot_batch_size: int
    retrieval_prefer_scoped_document: bool
    retrieval_document_fallback_enabled: bool
    autopilot_llm_batch_concurrency: int
    verify_temperature: float
    verify_max_retries: int
    
    # OCR and Extraction Settings
    ocr_image_max_long_edge: int
    ocr_image_jpeg_quality: int
    ocr_request_timeout_ms: int
    ocr_request_max_retries: int
    ocr_retry_base_ms: int
    ocr_temperature: float
    ocr_max_output_tokens: int
    
    # Form Detection Settings
    form_detection_temperature: float
    form_detection_max_output_tokens: int
    
    # PDF Rendering Settings
    page_dpi: int
    page_image_quality: int
    page_image_format: str
    
    # Parallelism and Workers
    max_extraction_workers: int
    extraction_batch_size: int
    case_extraction_parallel_batches: int

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
        gemini_log_token_details=_env_bool("GEMINI_LOG_TOKEN_DETAILS", False),
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
        retrieval_top_k=max(1, _env_int("RETRIEVAL_TOP_K", 12)),
        upsert_batch_size=max(1, _env_int("UPSERT_BATCH_SIZE", 30)),
        upsert_max_retries=max(1, _env_int("UPSERT_MAX_RETRIES", 5)),
        upsert_retry_base_ms=max(100, _env_int("UPSERT_RETRY_BASE_MS", 2000)),
        evidence_context_max_chars=max(2000, _env_int("EVIDENCE_CONTEXT_MAX_CHARS", 12000)),
        db_fallback_max_chars=max(4000, _env_int("DB_FALLBACK_MAX_CHARS", 30000)),
        pinecone_api_key=_env_str("PINECONE_API_KEY"),
        pinecone_index_ocr=_env_str("PINECONE_INDEX_OCR", "document-categorizer-ocr"),
        pinecone_namespace_prefix=_env_str("PINECONE_NAMESPACE_PREFIX", "case"),
        qc_batch_use_prompt_cache=_env_bool("QC_AUTOPILOT_BATCH_USE_PROMPT_CACHE", True),
        qc_batch_model=_env_str("QC_AUTOPILOT_BATCH_MODEL", ""),
        qc_batch_max_output_tokens=max(512, _env_int("QC_AUTOPILOT_BATCH_MAX_OUTPUT_TOKENS", 65536)),
        qc_batch_fast_prompt=_env_bool("QC_AUTOPILOT_FAST_BATCH_PROMPT", False),
        autopilot_evidence_top_k=max(1, _env_int("QC_AUTOPILOT_EVIDENCE_TOP_K", 6)),
        autopilot_evidence_max_chars=max(1200, _env_int("QC_AUTOPILOT_EVIDENCE_MAX_CHARS", 12000)),
        autopilot_evidence_workers=max(1, _env_int("QC_AUTOPILOT_EVIDENCE_WORKERS", 8)),
        autopilot_batch_size=max(1, _env_int("QC_AUTOPILOT_BATCH_SIZE", 25)),
        retrieval_prefer_scoped_document=_env_bool("RETRIEVAL_PREFER_SCOPED_DOCUMENT", True),
        retrieval_document_fallback_enabled=_env_bool("RETRIEVAL_DOCUMENT_FALLBACK_ENABLED", True),
        autopilot_llm_batch_concurrency=max(1, _env_int("QC_AUTOPILOT_LLM_BATCH_CONCURRENCY", 5)),
        verify_temperature=max(0.0, min(1.0, _env_float("VERIFY_TEMPERATURE", 0.25))),
        verify_max_retries=max(1, _env_int("VERIFY_MAX_RETRIES", 2)),
        
        # OCR and Extraction Settings
        ocr_image_max_long_edge=max(800, _env_int("OCR_IMAGE_MAX_LONG_EDGE", 1600)),
        ocr_image_jpeg_quality=max(10, min(100, _env_int("OCR_IMAGE_JPEG_QUALITY", 80))),
        ocr_request_timeout_ms=max(1000, _env_int("OCR_REQUEST_TIMEOUT_MS", 45000)),
        ocr_request_max_retries=max(1, _env_int("OCR_REQUEST_MAX_RETRIES", 3)),
        ocr_retry_base_ms=max(100, _env_int("OCR_RETRY_BASE_MS", 1500)),
        ocr_temperature=max(0.0, min(1.0, _env_float("OCR_TEMPERATURE", 0.1))),
        ocr_max_output_tokens=max(1024, _env_int("OCR_MAX_OUTPUT_TOKENS", 16384)),
        
        # Form Detection Settings
        form_detection_temperature=max(0.0, min(1.0, _env_float("FORM_DETECTION_TEMPERATURE", 0.1))),
        form_detection_max_output_tokens=max(128, _env_int("FORM_DETECTION_MAX_OUTPUT_TOKENS", 1024)),
        
        # PDF Rendering Settings
        page_dpi=max(72, _env_int("PAGE_DPI", 150)),
        page_image_quality=max(10, min(100, _env_int("PAGE_IMAGE_QUALITY", 85))),
        page_image_format=_env_str("PAGE_IMAGE_FORMAT", "JPEG").upper(),
        
        # Parallelism and Workers
        max_extraction_workers=max(1, _env_int("MAX_EXTRACTION_WORKERS", 10)),
        extraction_batch_size=max(1, _env_int("EXTRACTION_BATCH_SIZE", 10)),
        case_extraction_parallel_batches=max(1, _env_int("CASE_EXTRACTION_PARALLEL_BATCHES", 3)),
    )
