"""
AI Verification Service -- uses Gemini to verify QC checklist questions.

Supports three modes:
  1) Image + text  (vision model, page images + OCR context)
  2) Text-only RAG (text model, Gemini OCR evidence only, no images)
  3) Batch RAG     (text model, multiple questions with per-question evidence)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import PIL.Image
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from .extraction_service import _get_client
from .rag_config import get_rag_settings

log = logging.getLogger("qc_autopilot")

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"

# ---------------------------------------------------------------------------
# Form context (ported from OCRDocPinecone checklist.prompts.js)
# ---------------------------------------------------------------------------
FORM_CONTEXT: dict[str, str] = {
    "i-914a": (
        "Estructura del formulario I-914A:\n"
        "- Part 1: Relacion familiar (Spouse/Child/Parent/Sibling under 18)\n"
        "- Part 2: Info del principal (nombre, DOB, A-Number, status del I-914)\n"
        "- Part 3: Info del derivado (nombre, direccion, A-Number, SSN, sexo, "
        "estado civil, DOB, pasaporte, status migratorio, historial de entradas)\n"
        "- Part 4: Procesamiento (criminal, prostitucion, terrorismo, "
        "presencia cerca de dano, proceedings migratorios)\n"
        "- Part 5: Declaracion y firma del aplicante\n"
        "- Part 6: Interprete\n"
        "- Part 7: Preparador\n"
        "- Part 8: Informacion adicional"
    ),
    "i-914": (
        "Estructura del formulario I-914:\n"
        "- Part 1: Proposito (seleccion A o B segun el caso T-1)\n"
        "- Part 2: Info general (sexo, estado civil, DOB - items 8-10)\n"
        "- Part 3: Elegibilidad de trata (3.1-3.11: victima de trata severa, "
        "cooperacion con LEA, presencia fisica, hardship, reporte, edad, "
        "entradas previas, EAD, familiares)\n"
        "- Part 4: Procesamiento (4.1: criminal/LEA, 4.2: prostitucion/"
        "contrabando/drogas, 4.3: seguridad/terrorismo/espionaje, "
        "4.4: presencia cerca de dano/proceedings, 4.5: tortura/genocidio, "
        "4.6: militar/paramilitar, 4.7: penalidades civiles/fraude, 4.8: salud)\n"
        "- Part 5: Miembros familiares (5.1-5.13)\n"
        "- Part 6: Declaracion y firma\n"
        "- Part 7: Interprete\n"
        "- Part 8: Preparador\n"
        "- Part 9: Informacion adicional"
    ),
}

COMMON_VERIFICATION_SOURCES = (
    "Fuentes de verificacion comunes: Bio Call, Intake, "
    "Declaration/Affidavit, Birth Certificate, Passport, LEA Report, FBI, "
    "FOIA, Court Disposition, Criminal Record, Marriage Certificate, "
    "Form I-94, EOIR Portal, Contract, BOS."
)

OCR_MARKERS_INSTRUCTIONS = (
    "- La evidencia puede contener texto de formularios USCIS con checkboxes "
    "([X] marcado, [ ] no marcado), campos de formulario (etiqueta: valor), "
    "tablas y texto libre.\n"
    "- Busca datos especificos: A-Numbers (formato numerico), "
    "fechas (mm/dd/yyyy), nombres completos (Family/Given/Middle), "
    "direcciones, numeros de telefono, SSN, numeros de pasaporte.\n"
    "- Si la evidencia contiene texto manuscrito marcado como "
    "[[texto_probable]], consideralo con confianza media.\n"
    "- Si la evidencia contiene [?] o [SIGNATURE] o [OFFICIAL STAMP], "
    "esos son marcadores de contenido ilegible/no-texto."
)


def get_form_context(form_type: str = "") -> str:
    key = form_type.strip().lower().replace(" ", "-") if form_type else ""
    return FORM_CONTEXT.get(key, "")


# ---------------------------------------------------------------------------
# Prompt: image-based verification (existing, keeps "na" for not-applicable)
# ---------------------------------------------------------------------------
VERIFY_PROMPT = """You are a legal document QC specialist reviewing immigration case documents.

You are given a document page image and a verification question from a QC checklist.

{form_context}

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
{ocr_markers}
3. Determine if the information is present, correct, and complete.
4. Return a JSON object that strictly follows the response schema.

RULES:
- "yes" = The information is present and verified correctly in this document.
- "no" = The information is missing, incorrect, or inconsistent.
- "na" = This question is not applicable to the content shown in this page.
- "insufficient" = There is not enough evidence to determine correctness.
- Be specific in your explanation, reference exact text/data you see in the image.
- If the document is not the right source for this question, answer "na".
- Respond in English."""

# ---------------------------------------------------------------------------
# Prompt: text-only RAG verification (uses "insufficient" like OCRDocPinecone)
# ---------------------------------------------------------------------------
RAG_VERIFY_PROMPT = """You are a legal document QC specialist for immigration case review.

You are given OCR-extracted text evidence from USCIS forms and supporting documents.
The evidence was obtained via Gemini Vision OCR.

{form_context}
{common_sources}

TASK: Using ONLY the text evidence provided, answer the verification question.

VERIFICATION QUESTION:
{question}

WHERE TO VERIFY (expected sources):
{where_to_verify}

OCR TEXT EVIDENCE:
{text_evidence}

INSTRUCTIONS:
1. Analyze the OCR text evidence for information relevant to the question.
{ocr_markers}
2. Determine if the information is present, correct, and complete.
3. Return a JSON object that strictly follows the response schema.
4. In explanation, indicate briefly what specific evidence you used and from which page/section.
5. In correction, indicate what value the field should have if the decision is "no".

RULES:
- "yes" = The evidence shows the field/information was verified/completed correctly.
- "no" = The evidence shows the field has an error, is incomplete, or contradicts another source.
- "insufficient" = There is not enough evidence in the provided text to determine correctness.
- Be specific: reference exact text, checkbox states, or field values from the evidence.
- If the evidence does not contain information about this question, answer "insufficient".
- Respond in English."""

# ---------------------------------------------------------------------------
# Prompt: batch RAG verification (per-question evidence, like OCRDocPinecone)
# ---------------------------------------------------------------------------
RAG_BATCH_PROMPT = """You are a legal document QC specialist for immigration case review.

You are given OCR-extracted text evidence from USCIS forms and supporting documents.
The evidence was obtained via Gemini Vision OCR.

{form_context}
{common_sources}

TASK: Answer ALL of the following verification questions using ONLY the evidence provided for each question.

QUESTIONS AND EVIDENCE:
{questions_block}

INSTRUCTIONS:
1. For each question, analyze ONLY its associated evidence for relevant information.
{ocr_markers}
2. Return a JSON object with an "answers" array, one entry per question, in the same order.
3. Use exactly the id received for each question; do not invent or modify ids.
4. In explanation, indicate briefly what specific evidence you used and from which page/section.
5. In correction, indicate what value the field should have if the decision is "no".

RULES:
- "yes" = The evidence confirms the field/information is correct/complete.
- "no" = The evidence shows an error, omission, or inconsistency.
- "insufficient" = Not enough evidence to determine correctness.
- Be specific: reference exact text from the evidence in each explanation.
- Respond in English."""


# ---------------------------------------------------------------------------
# Schema models
# ---------------------------------------------------------------------------
_ANSWER_LITERAL = Literal["yes", "no", "na", "insufficient"]
_CONFIDENCE_LITERAL = Literal["high", "medium", "low"]


class VerificationResult(BaseModel):
    answer: _ANSWER_LITERAL = Field(
        description="Final QC decision based on the document evidence."
    )
    confidence: _CONFIDENCE_LITERAL = Field(
        description="Confidence level for the QC decision."
    )
    explanation: str = Field(
        description="Short explanation referencing the evidence found in the document."
    )
    correction: str = Field(
        description="Required correction when answer is no, otherwise an empty string."
    )


class BatchAnswerItem(BaseModel):
    id: str = Field(description="Question identifier.")
    answer: _ANSWER_LITERAL = Field(description="QC decision.")
    confidence: _CONFIDENCE_LITERAL = Field(description="Confidence level.")
    explanation: str = Field(description="Short explanation referencing evidence.")
    correction: str = Field(description="Correction if answer is no, else empty.")


class BatchVerificationResult(BaseModel):
    answers: list[BatchAnswerItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _default_result(*, rag_mode: bool = False) -> dict:
    return {
        "answer": "insufficient" if rag_mode else "na",
        "confidence": "low",
        "explanation": "",
        "correction": "",
    }


def _generate_structured_response(
    contents: list,
    *,
    model_override: str | None = None,
    schema: type[BaseModel] = VerificationResult,
) -> dict:
    client = _get_client()
    settings = get_rag_settings()
    model = model_override or settings.gemini_vision_model or settings.gemini_model
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=4096,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
        ),
    )

    raw_text = (response.text or "").strip()
    try:
        result = schema.model_validate_json(raw_text)
        return result.model_dump()
    except ValidationError:
        fallback = _default_result()
        fallback["explanation"] = raw_text[:500]
        return fallback


# ---------------------------------------------------------------------------
# Mode 1: Image-based (existing)
# ---------------------------------------------------------------------------
def verify_question(
    image_path: str,
    question_text: str,
    where_to_verify: str,
    text_context: str = "",
    form_type: str = "",
) -> dict:
    """Send a page image + QC question to Gemini Vision."""
    img = PIL.Image.open(image_path)
    prompt = VERIFY_PROMPT.format(
        question=question_text,
        where_to_verify=where_to_verify or "Not specified",
        text_context=text_context or "No OCR context retrieved.",
        form_context=get_form_context(form_type),
        ocr_markers=OCR_MARKERS_INSTRUCTIONS,
    )
    return _generate_structured_response([prompt, img])


def verify_question_multi_page(
    image_paths: list[str],
    question_text: str,
    where_to_verify: str,
    text_context: str = "",
    form_type: str = "",
) -> dict:
    """Verify a question against multiple page images at once."""
    contents: list = [
        VERIFY_PROMPT.format(
            question=question_text,
            where_to_verify=where_to_verify or "Not specified",
            text_context=text_context or "No OCR context retrieved.",
            form_context=get_form_context(form_type),
            ocr_markers=OCR_MARKERS_INSTRUCTIONS,
        )
    ]
    for path in image_paths[:5]:
        contents.append(PIL.Image.open(path))
    return _generate_structured_response(contents)


# ---------------------------------------------------------------------------
# Mode 2: Text-only RAG
# ---------------------------------------------------------------------------
def verify_question_rag(
    question_text: str,
    where_to_verify: str,
    text_evidence: str,
    form_type: str = "",
) -> dict:
    """Verify a QC question using only OCR text evidence (no images)."""
    settings = get_rag_settings()
    prompt = RAG_VERIFY_PROMPT.format(
        question=question_text,
        where_to_verify=where_to_verify or "Not specified",
        text_evidence=text_evidence,
        form_context=get_form_context(form_type),
        common_sources=COMMON_VERIFICATION_SOURCES,
        ocr_markers=OCR_MARKERS_INSTRUCTIONS,
    )
    return _generate_structured_response(
        [prompt],
        model_override=settings.gemini_model,
        schema=VerificationResult,
    )


# ---------------------------------------------------------------------------
# Mode 3: Batch RAG (per-question evidence, like OCRDocPinecone)
# ---------------------------------------------------------------------------
def verify_question_batch_rag(
    questions: list[dict],
    evidence_by_id: dict[str, str],
    form_type: str = "",
) -> list[dict]:
    """
    Verify multiple QC questions in a single Gemini call.

    ``questions`` is a list of dicts with keys: id, description, where_to_verify.
    ``evidence_by_id`` maps question id -> formatted text evidence for that question.
    Returns a list of dicts with keys: id, answer, confidence, explanation, correction.
    """
    settings = get_rag_settings()

    lines: list[str] = []
    for q in questions:
        qid = q.get("id", "")
        desc = q.get("description", "")
        where = q.get("where_to_verify", "")
        evidence = evidence_by_id.get(qid, "")
        lines.append(f"[{qid}] {desc}")
        if where:
            lines.append(f"    Where to verify: {where}")
        lines.append("    Evidence:")
        if evidence.strip():
            for ev_line in evidence.strip().splitlines():
                lines.append(f"    {ev_line}")
        else:
            lines.append("    (no evidence available)")
        lines.append("")
    questions_block = "\n".join(lines)

    prompt = RAG_BATCH_PROMPT.format(
        questions_block=questions_block,
        form_context=get_form_context(form_type),
        common_sources=COMMON_VERIFICATION_SOURCES,
        ocr_markers=OCR_MARKERS_INSTRUCTIONS,
    )

    result = _generate_structured_response(
        [prompt],
        model_override=settings.gemini_model,
        schema=BatchVerificationResult,
    )

    answers_raw = result.get("answers", [])
    if not isinstance(answers_raw, list):
        return [_default_result(rag_mode=True) | {"id": q.get("id", "")} for q in questions]

    answers_by_id: dict[str, dict] = {}
    for ans in answers_raw:
        if isinstance(ans, dict) and "id" in ans:
            answers_by_id[ans["id"]] = ans

    ordered: list[dict] = []
    for q in questions:
        qid = q.get("id", "")
        if qid in answers_by_id:
            ordered.append(answers_by_id[qid])
        else:
            ordered.append(_default_result(rag_mode=True) | {"id": qid})
    return ordered
