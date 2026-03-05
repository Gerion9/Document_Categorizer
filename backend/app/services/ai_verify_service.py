"""
AI Verification Service – uses Gemini Vision to automatically verify QC checklist
questions by analyzing document page images.

Flow:
  1. Receive a QC question + page image(s)
  2. Build a prompt with the exact question + where_to_verify context
  3. Send to Gemini Vision
  4. Parse the response into yes/no/na + confidence + explanation
"""

import json
from pathlib import Path

import PIL.Image
from google import genai
from google.genai import types

from .extraction_service import _get_client, is_configured

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"

VERIFY_PROMPT = """You are a legal document QC specialist reviewing immigration case documents.

You are given a document page image and a verification question from a QC checklist.

TASK: Analyze the document image and answer the verification question.

VERIFICATION QUESTION:
{question}

WHERE TO VERIFY (expected sources):
{where_to_verify}

INSTRUCTIONS:
1. Carefully examine the document image for information relevant to the question.
2. Determine if the information is present, correct, and complete.
3. Respond ONLY in the following JSON format (no other text):

{{
  "answer": "yes" | "no" | "na",
  "confidence": "high" | "medium" | "low",
  "explanation": "Brief explanation of what you found or didn't find in the document.",
  "correction": "If answer is 'no', describe what needs to be corrected. Otherwise empty string."
}}

RULES:
- "yes" = The information is present and verified correctly in this document.
- "no" = The information is missing, incorrect, or inconsistent.
- "na" = This question is not applicable to the content shown in this page.
- Be specific in your explanation, reference exact text/data you see in the image.
- If the document is not the right source for this question, answer "na".
- Respond in English."""


def verify_question(
    image_path: str,
    question_text: str,
    where_to_verify: str,
) -> dict:
    """
    Send a page image + QC question to Gemini and get a structured verification response.

    Returns dict with keys: answer, confidence, explanation, correction
    """
    client = _get_client()

    img = PIL.Image.open(image_path)

    prompt = VERIFY_PROMPT.format(
        question=question_text,
        where_to_verify=where_to_verify or "Not specified",
    )

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[prompt, img],
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2048,
        ),
    )

    text = response.text.strip()

    # Parse JSON from the response (handle markdown code blocks)
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        result = json.loads(text)
        return {
            "answer": result.get("answer", "na"),
            "confidence": result.get("confidence", "low"),
            "explanation": result.get("explanation", ""),
            "correction": result.get("correction", ""),
        }
    except json.JSONDecodeError:
        # If Gemini didn't return valid JSON, extract what we can
        answer = "na"
        if '"yes"' in text.lower() or "'yes'" in text.lower():
            answer = "yes"
        elif '"no"' in text.lower() or "'no'" in text.lower():
            answer = "no"
        return {
            "answer": answer,
            "confidence": "low",
            "explanation": text[:500],
            "correction": "",
        }


def verify_question_multi_page(
    image_paths: list[str],
    question_text: str,
    where_to_verify: str,
) -> dict:
    """Verify a question against multiple page images at once."""
    client = _get_client()

    contents: list = [
        VERIFY_PROMPT.format(
            question=question_text,
            where_to_verify=where_to_verify or "Not specified",
        )
    ]
    for path in image_paths[:5]:  # Max 5 pages
        contents.append(PIL.Image.open(path))

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2048,
        ),
    )

    text = response.text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        result = json.loads(text)
        return {
            "answer": result.get("answer", "na"),
            "confidence": result.get("confidence", "low"),
            "explanation": result.get("explanation", ""),
            "correction": result.get("correction", ""),
        }
    except json.JSONDecodeError:
        answer = "na"
        if '"yes"' in text.lower():
            answer = "yes"
        elif '"no"' in text.lower():
            answer = "no"
        return {
            "answer": answer,
            "confidence": "low",
            "explanation": text[:500],
            "correction": "",
        }

