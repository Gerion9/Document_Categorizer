"""
Extraction service – uses Google Gemini Vision to extract text from page images.

Two modes:
  • has_tables=True  → Gemini interprets tables, outputs structured Markdown.
  • has_tables=False → Gemini performs plain OCR, outputs clean text.

Configuration:
  Set the environment variable GEMINI_API_KEY (or add it to backend/.env).
"""

import os
from pathlib import Path

import PIL.Image
from google import genai
from google.genai import types

from .rag_config import get_rag_settings
from ..prompts import PROMPT_TABLES, PROMPT_OCR

# ── Configuration ─────────────────────────────────────────────────────────

_CLIENT: genai.Client | None = None


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


STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"


# ── Core extraction function ─────────────────────────────────────────────

def extract_text(image_path: str, has_tables: bool = False) -> str:
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

    img = PIL.Image.open(image_path)

    prompt = PROMPT_TABLES if has_tables else PROMPT_OCR

    response = client.models.generate_content(
        model=settings.gemini_vision_model or settings.gemini_model,
        contents=[prompt, img],
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=8192,
        ),
    )

    return response.text.strip()


def is_configured() -> bool:
    """Check whether the Gemini API key is available."""
    try:
        _get_client()
        return True
    except RuntimeError:
        return False
