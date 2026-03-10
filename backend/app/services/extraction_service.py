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
    return PIL.Image.open(buf)


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

    raw_img = PIL.Image.open(image_path)
    img = _prepare_image_for_ocr(raw_img)
    page_label = Path(image_path).name
    prompt_profile = "tables" if has_tables else "ocr"
    system_prompt = get_ocr_system_prompt(has_tables)

    cached_content = get_or_create_ocr_prompt_cache(
        client,
        model=model,
        prompt_profile=prompt_profile,
        system_prompt=system_prompt,
        placeholder_text=OCR_CACHE_PLACEHOLDER,
    )
    page_prompt = build_ocr_page_prompt(page_label, using_cached_prompt=bool(cached_content))

    try:
        response = _generate_page_ocr(
            client,
            model=model,
            system_prompt=system_prompt,
            page_prompt=page_prompt,
            image=img,
            cached_content=cached_content,
        )
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
                image=img,
            )
        else:
            raise

    record_usage_from_response(
        tracker,
        step=step_label or f"ocr-{prompt_profile}",
        response=response,
        model=model,
    )
    return (response.text or "").strip()


def is_configured() -> bool:
    """Check whether the Gemini API key is available."""
    try:
        _get_client()
        return True
    except RuntimeError:
        return False
