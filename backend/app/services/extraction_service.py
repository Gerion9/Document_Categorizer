"""
Extraction service – uses Google Gemini Vision to extract text from page images.

Two modes:
  • has_tables=True  → Gemini interprets tables, outputs structured Markdown.
  • has_tables=False → Gemini performs plain OCR, outputs clean text.

Configuration:
  Set the environment variable GEMINI_API_KEY (or add it to backend/.env).
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

from .gemini_runtime_service import (
    GeminiTokenTracker,
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

    # Try loading from .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        load_dotenv(env_path)
    except ImportError:
        pass

    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY not set.  "
            "Create backend/.env with GEMINI_API_KEY=your-key or set the env var."
        )
    _CLIENT = genai.Client(api_key=key)
    return _CLIENT


from .paths import STORAGE_DIR

OCR_IMAGE_MAX_LONG_EDGE = int(os.getenv("OCR_IMAGE_MAX_LONG_EDGE", "1600"))
OCR_IMAGE_JPEG_QUALITY = int(os.getenv("OCR_IMAGE_JPEG_QUALITY", "80"))
OCR_REQUEST_TIMEOUT_MS = max(1000, int(os.getenv("OCR_REQUEST_TIMEOUT_MS", "45000")))
OCR_REQUEST_MAX_RETRIES = max(1, int(os.getenv("OCR_REQUEST_MAX_RETRIES", "3")))
OCR_RETRY_BASE_MS = max(100, int(os.getenv("OCR_RETRY_BASE_MS", "1500")))


def _prepare_image_for_ocr(img: PIL.Image.Image) -> PIL.Image.Image:
    """Downscale and convert to RGB so Gemini receives fewer image tokens."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    max_edge = OCR_IMAGE_MAX_LONG_EDGE
    w, h = img.size
    if max(w, h) > max_edge:
        ratio = max_edge / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), PIL.Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=OCR_IMAGE_JPEG_QUALITY, optimize=True)
    buf.seek(0)
    result = PIL.Image.open(buf)
    result.load()
    return result


def _sleep_ocr_backoff(attempt: int) -> None:
    delay_ms = OCR_RETRY_BASE_MS * (2 ** max(0, attempt - 1))
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
    config_kwargs: dict[str, object] = {
        "temperature": 0.1,
        "max_output_tokens": 8192,
        "http_options": types.HttpOptions(timeout=OCR_REQUEST_TIMEOUT_MS),
    }
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
    image_path: str,
    has_tables: bool = False,
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str | None = None,
) -> str:
    """
    Send a page image to Gemini Vision and get back the extracted text.

    Args:
        image_path: Absolute path to the page image (PNG).
        has_tables: If True, use the table-aware prompt; otherwise plain OCR.

    Returns:
        Extracted text (Markdown formatted if has_tables=True).
    """
    client = _get_client()
    settings = get_rag_settings()
    model = settings.gemini_vision_model or settings.gemini_model

    page_label = Path(image_path).name
    prompt_profile = "tables" if has_tables else "ocr"
    system_prompt = get_ocr_system_prompt(has_tables)
    with PIL.Image.open(image_path) as raw_img:
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

        for attempt in range(1, OCR_REQUEST_MAX_RETRIES + 1):
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
                if attempt >= OCR_REQUEST_MAX_RETRIES or not _should_retry_ocr_error(exc):
                    raise
                log.warning(
                    "[GEMINI] OCR attempt %d/%d failed for %s. Retrying: %s",
                    attempt,
                    OCR_REQUEST_MAX_RETRIES,
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
