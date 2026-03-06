"""
Prompts for QC verification (ai_verify_service).

Three verification modes:
  1) Image + text  (VERIFY_PROMPT)
  2) Text-only RAG (RAG_VERIFY_PROMPT)
  3) Batch RAG     (RAG_BATCH_PROMPT)
"""

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
# Image-based verification
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
# Text-only RAG verification
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
# Batch RAG verification
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
