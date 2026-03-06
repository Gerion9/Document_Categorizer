"""
AI Verification Service – uses Gemini Vision to automatically verify QC checklist
questions by analyzing document page images and returning structured JSON.
"""

from pathlib import Path
from typing import Literal

import PIL.Image
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from .extraction_service import _get_client
from .rag_config import get_rag_settings

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"

VERIFY_PROMPT = """You are a legal document QC specialist reviewing immigration case documents.

You are given a document page image and a verification question from a QC checklist.

TASK: Analyze the document image and answer the verification question.

VERIFICATION QUESTION:
{question}

WHERE TO VERIFY (expected sources):
{where_to_verify}

RETRIEVED OCR CONTEXT:
{text_context}

INSTRUCTIONS:
1. Carefully examine the document image for information relevant to the question.
2. Use the retrieved OCR context as supporting text, but trust the page image(s) if there is any conflict.
3. Determine if the information is present, correct, and complete.
4. Return a JSON object that strictly follows the response schema.

RULES:
- "yes" = The information is present and verified correctly in this document.
- "no" = The information is missing, incorrect, or inconsistent.
- "na" = This question is not applicable to the content shown in this page.
- Be specific in your explanation, reference exact text/data you see in the image.
- If the document is not the right source for this question, answer "na".
- Respond in English."""


class VerificationResult(BaseModel):
    answer: Literal["yes", "no", "na"] = Field(
        description="Final QC decision based on the document evidence."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence level for the QC decision."
    )
    explanation: str = Field(
        description="Short explanation referencing the evidence found in the document."
    )
    correction: str = Field(
        description="Required correction when answer is no, otherwise an empty string."
    )


def _default_result() -> dict:
    return {
        "answer": "na",
        "confidence": "low",
        "explanation": "",
        "correction": "",
    }


def _generate_structured_response(contents: list) -> dict:
    client = _get_client()
    settings = get_rag_settings()
    response = client.models.generate_content(
        model=settings.gemini_vision_model or settings.gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2048,
            response_mime_type="application/json",
            response_json_schema=VerificationResult.model_json_schema(),
        ),
    )

    raw_text = (response.text or "").strip()
    try:
        result = VerificationResult.model_validate_json(raw_text)
        return result.model_dump()
    except ValidationError:
        fallback = _default_result()
        fallback["explanation"] = raw_text[:500]
        return fallback


def verify_question(
    image_path: str,
    question_text: str,
    where_to_verify: str,
    text_context: str = "",
) -> dict:
    """
    Send a page image + QC question to Gemini and get a structured verification response.

    Returns dict with keys: answer, confidence, explanation, correction
    """
    img = PIL.Image.open(image_path)

    prompt = VERIFY_PROMPT.format(
        question=question_text,
        where_to_verify=where_to_verify or "Not specified",
        text_context=text_context or "No OCR context retrieved.",
    )

    return _generate_structured_response([prompt, img])


def verify_question_multi_page(
    image_paths: list[str],
    question_text: str,
    where_to_verify: str,
    text_context: str = "",
) -> dict:
    """Verify a question against multiple page images at once."""
    contents: list = [
        VERIFY_PROMPT.format(
            question=question_text,
            where_to_verify=where_to_verify or "Not specified",
            text_context=text_context or "No OCR context retrieved.",
        )
    ]
    for path in image_paths[:5]:  # Max 5 pages
        contents.append(PIL.Image.open(path))
    return _generate_structured_response(contents)

