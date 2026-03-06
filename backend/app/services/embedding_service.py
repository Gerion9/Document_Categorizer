from __future__ import annotations

import logging
import random
import time
from typing import Any

from google.genai import types

from .extraction_service import _get_client
from .gemini_runtime_service import GeminiTokenTracker
from .rag_config import get_rag_settings

log = logging.getLogger("gemini_usage")


def is_embeddings_configured() -> bool:
    return get_rag_settings().embeddings_configured


def _should_retry_embedding_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_tokens = (
        "timeout",
        "timed out",
        "rate limit",
        "resource exhausted",
        "temporar",
        "network",
        "connection reset",
        "503",
        "502",
        "500",
        "429",
    )
    return any(token in message for token in retryable_tokens)


def _sleep_backoff(attempt: int) -> None:
    settings = get_rag_settings()
    delay_ms = settings.embedding_retry_base_ms * (2 ** max(0, attempt - 1))
    delay_ms += random.randint(0, 500)
    time.sleep(delay_ms / 1000)


def _coerce_embedding_values(item: Any) -> list[float]:
    if item is None:
        return []

    if isinstance(item, dict):
        if isinstance(item.get("values"), list):
            return [float(v) for v in item["values"]]
        if isinstance(item.get("embedding"), dict) and isinstance(item["embedding"].get("values"), list):
            return [float(v) for v in item["embedding"]["values"]]

    values = getattr(item, "values", None)
    if isinstance(values, list):
        return [float(v) for v in values]

    embedding = getattr(item, "embedding", None)
    if embedding is not None:
        nested_values = getattr(embedding, "values", None)
        if isinstance(nested_values, list):
            return [float(v) for v in nested_values]

    return []


def _extract_embeddings(response: Any) -> list[list[float]]:
    embeddings = getattr(response, "embeddings", None)
    if isinstance(embeddings, list):
        return [_coerce_embedding_values(item) for item in embeddings]

    single_embedding = getattr(response, "embedding", None)
    if single_embedding is not None:
        values = _coerce_embedding_values(single_embedding)
        return [values] if values else []

    if isinstance(response, dict):
        if isinstance(response.get("embeddings"), list):
            return [_coerce_embedding_values(item) for item in response["embeddings"]]
        if response.get("embedding") is not None:
            values = _coerce_embedding_values(response["embedding"])
            return [values] if values else []

    return []


def _embed_batch(
    texts: list[str],
    task_type: str,
    title: str | None = None,
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "embedding",
) -> list[list[float]]:
    settings = get_rag_settings()
    client = _get_client()
    last_exc: Exception | None = None

    for attempt in range(1, settings.embedding_max_retries + 1):
        try:
            response = client.models.embed_content(
                model=settings.embedding_model,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=settings.embedding_dimension or None,
                    title=title or None,
                ),
            )
            if tracker is not None:
                token_info = tracker.record_embedding_response(
                    step_label,
                    response,
                    texts,
                    model=settings.embedding_model,
                )
                if settings.gemini_log_token_usage:
                    log.info(
                        "[GEMINI] %s model=%s embedding_tokens=%d estimated=%s",
                        step_label,
                        settings.embedding_model,
                        token_info["token_count"],
                        token_info["estimated"],
                    )
            embeddings = _extract_embeddings(response)
            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f"Expected {len(texts)} embeddings, received {len(embeddings)}"
                )
            return embeddings
        except Exception as exc:  # pragma: no cover - network dependent
            last_exc = exc
            if attempt >= settings.embedding_max_retries or not _should_retry_embedding_error(exc):
                raise
            _sleep_backoff(attempt)

    raise last_exc or RuntimeError("Embedding request failed")


def get_embedding_batch(
    texts: list[str],
    task_type: str | None = None,
    titles: list[str] | None = None,
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "embedding",
) -> list[list[float]]:
    clean_texts = [str(text or "").strip() for text in texts]
    if not clean_texts:
        return []

    settings = get_rag_settings()
    batch_size = settings.embedding_batch_size
    resolved_task_type = task_type or settings.embedding_task_type_document
    all_embeddings: list[list[float]] = []

    if titles:
        clean_titles = [str(title or "").strip() for title in titles]
        if len(clean_titles) != len(clean_texts):
            raise ValueError("titles length must match texts length")
        for index, (text, title) in enumerate(zip(clean_texts, clean_titles, strict=False), start=1):
            all_embeddings.extend(
                _embed_batch(
                    [text],
                    resolved_task_type,
                    title=title or None,
                    tracker=tracker,
                    step_label=f"{step_label}-{index}",
                )
            )
        return all_embeddings

    for start in range(0, len(clean_texts), batch_size):
        batch = clean_texts[start:start + batch_size]
        batch_number = (start // batch_size) + 1
        all_embeddings.extend(
            _embed_batch(
                batch,
                resolved_task_type,
                tracker=tracker,
                step_label=f"{step_label}-{batch_number}",
            )
        )

    return all_embeddings


def get_embedding(
    text: str,
    task_type: str | None = None,
    title: str | None = None,
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "embedding-query",
) -> list[float]:
    settings = get_rag_settings()
    embeddings = get_embedding_batch(
        [text],
        task_type=task_type or settings.embedding_task_type_query,
        titles=[title] if title is not None else None,
        tracker=tracker,
        step_label=step_label,
    )
    return embeddings[0] if embeddings else []
