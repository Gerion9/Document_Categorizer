"""
Extraction service – uses Google Gemini Vision to extract text from page images.

Two modes:
  • has_tables=True  → Gemini interprets tables, outputs structured Markdown.
  • has_tables=False → Gemini performs plain OCR, outputs clean text.

Configuration:
  Set the environment variable GEMINI_API_KEY (or add it to the repo-level .env).
"""

import io
import logging
import os
import random
import time
from pathlib import Path

import PIL.Image
from google import genai
from google.genai import types

from ..core.env import load_project_env
from .gemini_runtime_service import (
    GeminiTokenTracker,
    apply_thinking_config,
    get_or_create_ocr_prompt_cache,
    invalidate_ocr_prompt_cache,
    is_cached_content_error,
    record_usage_from_response,
)
from .rag_config import get_rag_settings
from ..prompts import (
    OCR_CACHE_PLACEHOLDER,
    build_ocr_page_prompt,
    get_ocr_system_prompt,
)

# ── Configuration ─────────────────────────────────────────────────────────

_CLIENT: genai.Client | None = None
log = logging.getLogger("gemini_usage")


def _get_client() -> genai.Client:
    """Lazy-load the Gemini client with API key from environment or .env file."""
    global _CLIENT
    if _CLIENT:
        return _CLIENT

    load_project_env()

    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY not set.  "
            "Set GEMINI_API_KEY in the repo-level .env or in the environment."
        )
    _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def _prepare_image_for_ocr(img: PIL.Image.Image) -> PIL.Image.Image:
    """Downscale and convert to RGB so Gemini receives fewer image tokens."""
    settings = get_rag_settings()
    if img.mode != "RGB":
        img = img.convert("RGB")
    max_edge = settings.ocr_image_max_long_edge
    w, h = img.size
    if max(w, h) > max_edge:
        ratio = max_edge / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), PIL.Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=settings.ocr_image_jpeg_quality, optimize=True)
    buf.seek(0)
    result = PIL.Image.open(buf)
    result.load()
    return result


def _sleep_ocr_backoff(attempt: int) -> None:
    settings = get_rag_settings()
    delay_ms = settings.ocr_retry_base_ms * (2 ** max(0, attempt - 1))
    delay_ms += random.randint(0, 400)
    time.sleep(delay_ms / 1000)


def _should_retry_ocr_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_tokens = (
        "timeout",
        "timed out",
        "deadline",
        "rate limit",
        "resource exhausted",
        "temporar",
        "network",
        "connection reset",
        "connection aborted",
        "503",
        "502",
        "500",
        "429",
        "408",
    )
    return any(token in message for token in retryable_tokens)


# ── Core extraction function ─────────────────────────────────────────────

def _generate_page_ocr(
    client: genai.Client,
    *,
    model: str,
    system_prompt: str,
    page_prompt: str,
    image: PIL.Image.Image,
    cached_content: str = "",
):
    settings = get_rag_settings()
    config_kwargs: dict[str, object] = {
        "temperature": settings.ocr_temperature,
        "max_output_tokens": settings.ocr_max_output_tokens,
        "http_options": types.HttpOptions(timeout=settings.ocr_request_timeout_ms),
    }
    apply_thinking_config(config_kwargs, settings.gemini_ocr_thinking_level)
    if cached_content:
        config_kwargs["cached_content"] = cached_content
        contents = [page_prompt, image]
    else:
        contents = [f"{system_prompt}\n\n{page_prompt}", image]

    return client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )


def _generate_page_ocr_with_cache_fallback(
    client: genai.Client,
    *,
    model: str,
    system_prompt: str,
    page_prompt: str,
    image: PIL.Image.Image,
    cached_content: str,
    page_label: str,
) -> tuple[object, str]:
    try:
        response = _generate_page_ocr(
            client,
            model=model,
            system_prompt=system_prompt,
            page_prompt=page_prompt,
            image=image,
            cached_content=cached_content,
        )
        return response, cached_content
    except Exception as exc:
        if cached_content and is_cached_content_error(exc):
            invalidate_ocr_prompt_cache(cached_content)
            log.warning(
                "[GEMINI] OCR cached content invalid for %s. Retrying without cache: %s",
                page_label,
                str(exc),
            )
            response = _generate_page_ocr(
                client,
                model=model,
                system_prompt=system_prompt,
                page_prompt=build_ocr_page_prompt(page_label, using_cached_prompt=False),
                image=image,
            )
            return response, ""
        raise


def extract_text(
    image_input: str | bytes,
    has_tables: bool = False,
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str | None = None,
    page_label: str | None = None,
) -> str:
    """
    Send a page image to Gemini Vision and get back the extracted text.

    Args:
        image_input: Raw image bytes (from S3) or a local file path (legacy).
        has_tables: If True, use the table-aware prompt; otherwise plain OCR.
        page_label: Label for logging; auto-derived from path when image_input is str.

    Returns:
        Extracted text (Markdown formatted if has_tables=True).
    """
    client = _get_client()
    settings = get_rag_settings()
    model = settings.gemini_vision_model or settings.gemini_model

    if isinstance(image_input, bytes):
        page_label = page_label or "s3_image"
        raw_img = PIL.Image.open(io.BytesIO(image_input))
    else:
        page_label = page_label or Path(image_input).name
        raw_img = PIL.Image.open(image_input)

    prompt_profile = "tables" if has_tables else "ocr"
    system_prompt = get_ocr_system_prompt(has_tables)
    with raw_img:
        img = _prepare_image_for_ocr(raw_img)

    log.debug("Prepared OCR image page=%s size=%s mode=%s", page_label, img.size, img.mode)
    try:
        cached_content = get_or_create_ocr_prompt_cache(
            client,
            model=model,
            prompt_profile=prompt_profile,
            system_prompt=system_prompt,
            placeholder_text=OCR_CACHE_PLACEHOLDER,
        )
        page_prompt = build_ocr_page_prompt(page_label, using_cached_prompt=bool(cached_content))

        for attempt in range(1, settings.ocr_request_max_retries + 1):
            try:
                response, cached_content = _generate_page_ocr_with_cache_fallback(
                    client,
                    model=model,
                    system_prompt=system_prompt,
                    page_prompt=page_prompt,
                    image=img,
                    cached_content=cached_content,
                    page_label=page_label,
                )
                record_usage_from_response(
                    tracker,
                    step=step_label or f"ocr-{prompt_profile}",
                    response=response,
                    model=model,
                )
                return (response.text or "").strip()
            except Exception as exc:
                if attempt >= settings.ocr_request_max_retries or not _should_retry_ocr_error(exc):
                    raise
                log.warning(
                    "[GEMINI] OCR attempt %d/%d failed for %s. Retrying: %s",
                    attempt,
                    settings.ocr_request_max_retries,
                    page_label,
                    str(exc),
                )
                _sleep_ocr_backoff(attempt)
    finally:
        img.close()


def is_configured() -> bool:
    """Check whether the Gemini API key is available."""
    try:
        _get_client()
        return True
    except RuntimeError:
        return False
