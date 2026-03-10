from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.genai import types

from .rag_config import get_rag_settings

log = logging.getLogger("gemini_usage")


def _metadata_value(source: Any, snake_name: str, camel_name: str) -> int:
    if source is None:
        return 0
    if isinstance(source, dict):
        raw = source.get(snake_name, source.get(camel_name, 0))
    else:
        raw = getattr(source, snake_name, getattr(source, camel_name, 0))
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _extract_usage_metadata(response: Any) -> Any:
    if response is None:
        return None
    if isinstance(response, dict):
        return response.get("usage_metadata") or response.get("usageMetadata")
    return getattr(response, "usage_metadata", None) or getattr(response, "usageMetadata", None)


def _estimate_text_tokens(texts: list[str]) -> int:
    settings = get_rag_settings()
    divisor = settings.gemini_embedding_char_estimate_divisor
    return sum(max(1, (len(str(text or "")) + divisor - 1) // divisor) for text in texts if str(text or "").strip())


@dataclass
class GeminiTokenRecord:
    step: str
    kind: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    thoughts_tokens: int
    total_tokens: int
    estimated: bool = False


class GeminiTokenTracker:
    def __init__(self, label: str = "") -> None:
        self.label = label
        self._records: list[GeminiTokenRecord] = []
        self._prompt_tokens = 0
        self._output_tokens = 0
        self._cached_tokens = 0
        self._thoughts_tokens = 0
        self._total_tokens = 0
        self._embedding_tokens = 0

    def record(self, step: str, usage_metadata: Any, *, model: str | None = None) -> None:
        if usage_metadata is None:
            return

        prompt = _metadata_value(usage_metadata, "prompt_token_count", "promptTokenCount")
        output = _metadata_value(usage_metadata, "candidates_token_count", "candidatesTokenCount")
        cached = _metadata_value(usage_metadata, "cached_content_token_count", "cachedContentTokenCount")
        thoughts = _metadata_value(usage_metadata, "thoughts_token_count", "thoughtsTokenCount")
        total = _metadata_value(usage_metadata, "total_token_count", "totalTokenCount") or (prompt + output)

        self._records.append(
            GeminiTokenRecord(
                step=step,
                kind="generate",
                model=model,
                input_tokens=prompt,
                output_tokens=output,
                cached_tokens=cached,
                thoughts_tokens=thoughts,
                total_tokens=total,
            )
        )
        self._prompt_tokens += prompt
        self._output_tokens += output
        self._cached_tokens += cached
        self._thoughts_tokens += thoughts
        self._total_tokens += total

    def record_embedding_tokens(
        self,
        count: int,
        *,
        step: str = "embedding",
        model: str | None = None,
        estimated: bool = False,
    ) -> None:
        value = max(0, int(count or 0))
        self._embedding_tokens += value
        self._records.append(
            GeminiTokenRecord(
                step=step,
                kind="embedding",
                model=model,
                input_tokens=value,
                output_tokens=0,
                cached_tokens=0,
                thoughts_tokens=0,
                total_tokens=value,
                estimated=estimated,
            )
        )

    def record_embedding_response(
        self,
        step: str,
        response: Any,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        embeddings = []
        if isinstance(response, dict):
            embeddings = response.get("embeddings") or []
            if not embeddings and response.get("embedding") is not None:
                embeddings = [response.get("embedding")]
        else:
            embeddings = getattr(response, "embeddings", None) or []
            single_embedding = getattr(response, "embedding", None)
            if not embeddings and single_embedding is not None:
                embeddings = [single_embedding]

        token_count = 0
        for item in embeddings:
            if isinstance(item, dict):
                stats = item.get("statistics") or {}
            else:
                stats = getattr(item, "statistics", None) or {}
            token_count += _metadata_value(stats, "token_count", "tokenCount")

        estimated = False
        if token_count <= 0:
            token_count = _estimate_text_tokens(texts)
            estimated = True

        self.record_embedding_tokens(token_count, step=step, model=model, estimated=estimated)
        return {"token_count": token_count, "estimated": estimated}

    def merge(self, other: "GeminiTokenTracker | None") -> None:
        if other is None:
            return
        self._records.extend(other._records)
        self._prompt_tokens += other._prompt_tokens
        self._output_tokens += other._output_tokens
        self._cached_tokens += other._cached_tokens
        self._thoughts_tokens += other._thoughts_tokens
        self._total_tokens += other._total_tokens
        self._embedding_tokens += other._embedding_tokens

    def get_summary(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "input": self._prompt_tokens,
            "output": self._output_tokens,
            "cached": self._cached_tokens,
            "thoughts": self._thoughts_tokens,
            "total": self._total_tokens,
            "embedding": self._embedding_tokens,
            "grand_total": self._total_tokens + self._embedding_tokens,
            "records": [
                {
                    "step": record.step,
                    "kind": record.kind,
                    "model": record.model,
                    "input": record.input_tokens,
                    "output": record.output_tokens,
                    "cached": record.cached_tokens,
                    "thoughts": record.thoughts_tokens,
                    "total": record.total_tokens,
                    "estimated": record.estimated,
                }
                for record in self._records
            ],
        }


def create_token_tracker(label: str = "") -> GeminiTokenTracker:
    return GeminiTokenTracker(label=label)


def record_usage_from_response(
    tracker: GeminiTokenTracker | None,
    *,
    step: str,
    response: Any,
    model: str | None = None,
) -> None:
    usage_metadata = _extract_usage_metadata(response)
    if tracker is not None:
        tracker.record(step, usage_metadata, model=model)

    settings = get_rag_settings()
    if not settings.gemini_log_token_usage or not settings.gemini_log_token_details or usage_metadata is None:
        return

    log.info(
        "[GEMINI] %s model=%s input=%d output=%d cached=%d thoughts=%d total=%d",
        step,
        model or "",
        _metadata_value(usage_metadata, "prompt_token_count", "promptTokenCount"),
        _metadata_value(usage_metadata, "candidates_token_count", "candidatesTokenCount"),
        _metadata_value(usage_metadata, "cached_content_token_count", "cachedContentTokenCount"),
        _metadata_value(usage_metadata, "thoughts_token_count", "thoughtsTokenCount"),
        _metadata_value(usage_metadata, "total_token_count", "totalTokenCount"),
    )


def log_token_summary(
    tracker: GeminiTokenTracker | None,
    *,
    label: str,
    logger: logging.Logger | None = None,
) -> None:
    if tracker is None:
        return
    settings = get_rag_settings()
    if not settings.gemini_log_token_usage:
        return

    summary = tracker.get_summary()
    target_logger = logger or log
    target_logger.info(
        "[GEMINI] %s tokens input=%d output=%d cached=%d thoughts=%d embedding=%d total=%d",
        label,
        summary["input"],
        summary["output"],
        summary["cached"],
        summary["thoughts"],
        summary["embedding"],
        summary["grand_total"],
    )


@dataclass
class PromptCacheEntry:
    name: str
    expires_at_ms: int


_PROMPT_CACHE_LOCK = threading.Lock()
_OCR_PROMPT_CACHE_BY_KEY: dict[str, PromptCacheEntry] = {}
_OCR_PROMPT_CACHE_DISABLED_MODELS: set[str] = set()
_OCR_PROMPT_CACHE_REUSE_LOG_MS: dict[str, int] = {}

_CACHE_DISABLE_RE = re.compile(
    r"unsupported|minimum|min token|invalid argument|permission denied|forbidden",
    re.IGNORECASE,
)
_CACHE_MISS_RE = re.compile(
    r"cached.*(expired|invalid|not found|deleted|missing)|not found.*cached",
    re.IGNORECASE,
)


def _cache_key(model: str, prompt_profile: str) -> str:
    return f"{model.strip()}::{prompt_profile.strip()}"


def _resolve_cache_expire_at_ms(cache: Any, ttl_seconds: int) -> int:
    expire_time = None
    if isinstance(cache, dict):
        expire_time = cache.get("expire_time") or cache.get("expireTime")
    else:
        expire_time = getattr(cache, "expire_time", None) or getattr(cache, "expireTime", None)

    if isinstance(expire_time, datetime):
        return int(expire_time.timestamp() * 1000)

    if isinstance(expire_time, str):
        raw = expire_time.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return int(datetime.fromisoformat(raw).timestamp() * 1000)
        except ValueError:
            pass

    return int(time.time() * 1000) + (ttl_seconds * 1000)


def _should_log_cache_reuse(cache_key_value: str) -> bool:
    settings = get_rag_settings()
    cooldown_ms = settings.gemini_cache_reuse_log_cooldown_ms
    now_ms = int(time.time() * 1000)
    last_ms = _OCR_PROMPT_CACHE_REUSE_LOG_MS.get(cache_key_value, 0)
    if cooldown_ms <= 0 or now_ms - last_ms >= cooldown_ms:
        _OCR_PROMPT_CACHE_REUSE_LOG_MS[cache_key_value] = now_ms
        return True
    return False


def should_disable_prompt_cache(exc: Exception) -> bool:
    return bool(_CACHE_DISABLE_RE.search(str(exc)))


def is_cached_content_error(exc: Exception) -> bool:
    return bool(_CACHE_MISS_RE.search(str(exc)))


def invalidate_ocr_prompt_cache(cache_name: str) -> None:
    if not cache_name:
        return
    with _PROMPT_CACHE_LOCK:
        keys_to_delete = [
            key for key, entry in _OCR_PROMPT_CACHE_BY_KEY.items()
            if entry.name == cache_name
        ]
        for key in keys_to_delete:
            _OCR_PROMPT_CACHE_BY_KEY.pop(key, None)


_TOKEN_SUMMARY_KEYS = ("input", "output", "cached", "thoughts", "embedding", "grand_total")

ZERO_TOKEN_SUMMARY: dict[str, int] = {k: 0 for k in _TOKEN_SUMMARY_KEYS}


def compact_token_summary(raw: dict) -> dict[str, int]:
    """Extract a normalized {input, output, cached, thoughts, embedding, grand_total} dict."""
    return {k: int(raw.get(k, 0) or 0) for k in _TOKEN_SUMMARY_KEYS}


def sum_token_summaries(a: dict, b: dict) -> dict[str, int]:
    return {k: int(a.get(k, 0) or 0) + int(b.get(k, 0) or 0) for k in _TOKEN_SUMMARY_KEYS}


def get_or_create_ocr_prompt_cache(
    client: Any,
    *,
    model: str,
    prompt_profile: str,
    system_prompt: str,
    placeholder_text: str,
) -> str:
    settings = get_rag_settings()
    normalized_model = str(model or "").strip()
    normalized_profile = str(prompt_profile or "ocr").strip()

    if not settings.gemini_enable_explicit_cache or not normalized_model:
        return ""

    with _PROMPT_CACHE_LOCK:
        if normalized_model in _OCR_PROMPT_CACHE_DISABLED_MODELS:
            return ""

        key = _cache_key(normalized_model, normalized_profile)
        current = _OCR_PROMPT_CACHE_BY_KEY.get(key)
        if current and current.expires_at_ms - int(time.time() * 1000) > settings.gemini_cache_refresh_buffer_ms:
            if settings.gemini_log_token_details and _should_log_cache_reuse(key):
                log.info(
                    "[GEMINI] OCR prompt cache reused model=%s profile=%s cache=%s ttl_ms=%d",
                    normalized_model,
                    normalized_profile,
                    current.name,
                    max(0, current.expires_at_ms - int(time.time() * 1000)),
                )
            return current.name

    try:
        cache = client.caches.create(
            model=normalized_model,
            config=types.CreateCachedContentConfig(
                display_name=f"ocr-{normalized_profile}",
                system_instruction=system_prompt,
                contents=[placeholder_text],
                ttl=f"{settings.gemini_cache_ttl_seconds}s",
            ),
        )
        cache_name = ""
        if isinstance(cache, dict):
            cache_name = str(cache.get("name", "")).strip()
        else:
            cache_name = str(getattr(cache, "name", "") or "").strip()
        if not cache_name:
            raise RuntimeError("Gemini cache did not return a cache name.")

        expires_at_ms = _resolve_cache_expire_at_ms(cache, settings.gemini_cache_ttl_seconds)
        with _PROMPT_CACHE_LOCK:
            _OCR_PROMPT_CACHE_BY_KEY[_cache_key(normalized_model, normalized_profile)] = PromptCacheEntry(
                name=cache_name,
                expires_at_ms=expires_at_ms,
            )
        log.info(
            "[GEMINI] OCR prompt cache created model=%s profile=%s cache=%s ttl_seconds=%d",
            normalized_model,
            normalized_profile,
            cache_name,
            settings.gemini_cache_ttl_seconds,
        )
        return cache_name
    except Exception as exc:
        disable_cache = should_disable_prompt_cache(exc)
        if disable_cache:
            with _PROMPT_CACHE_LOCK:
                _OCR_PROMPT_CACHE_DISABLED_MODELS.add(normalized_model)
        log.warning(
            "[GEMINI] Explicit OCR prompt cache unavailable model=%s profile=%s disabled=%s reason=%s",
            normalized_model,
            normalized_profile,
            disable_cache,
            str(exc),
        )
        return ""
