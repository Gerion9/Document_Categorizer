"""
Prompts for QC verification (ai_verify_service).

Shared instruction base aligned with v1 (checklist.prompts.js), used by all modes:
  1) Image + text  (VERIFY_PROMPT)
  2) Text-only RAG (build_rag_verify_system_prompt / build_rag_verify_request_prompt)
  3) Batch RAG     (build_rag_batch_system_prompt / build_rag_batch_request_prompt)
"""

from .forms import FORM_PROMPT_REGISTRY, get_form_prompt_spec, try_get_form_prompt_spec


# `FORM_CONTEXT` and `FORM_LABELS` are kept as public re-exports for backward
# compatibility (some tests and external scripts read them directly). They are
# DERIVED from the central `FORM_PROMPT_REGISTRY` — do NOT edit them in place;
# add a new `<form>_rules.py` under `app/prompts/forms/` instead.
FORM_CONTEXT: dict[str, str] = {
    ft: spec.verification_context
    for ft, spec in FORM_PROMPT_REGISTRY.items()
    if spec.verification_context
}

FORM_LABELS: dict[str, str] = {
    ft: spec.form_label for ft, spec in FORM_PROMPT_REGISTRY.items()
}

COMMON_VERIFICATION_SOURCES = (
    "Fuentes de verificacion comunes: Bio Call, Intake, "
    "Declaration/Affidavit, Birth Certificate, Passport, LEA Report, FBI, "
    "FOIA, Court Disposition, Criminal Record, Marriage Certificate, "
    "Form I-94, EOIR Portal, Contract, BOS."
)

SOURCE_HIERARCHY_INSTRUCTIONS = (
    "Jerarquia obligatoria de fuentes (de mayor a menor confiabilidad):\n"
    "- Tier 1 (oficial/gobierno): FBI Records, FOIA, LEA Report, Court Disposition, Criminal Record\n"
    "- Tier 2 (declaraciones juradas): Declaration / Affidavit del aplicante\n"
    "- Tier 3 (registros internos): BIO Call, Intake\n"
    "Si multiples fuentes proveen informacion sobre el mismo evento, "
    "prioriza la fuente de mayor rango.\n"
    "Si un FBI record o LEA Report confirma una detencion, arresto u otro evento, "
    "esa informacion DEBE reflejarse obligatoriamente en la respuesta, sin excepcion.\n"
    "Consolida toda la informacion en una sola linea de tiempo coherente antes de responder; "
    "no respondas directamente desde texto suelto de una sola fuente."
)

OCR_MARKERS_INSTRUCTIONS = (
    "- La evidencia puede estar en formato 'Pregunta: ... / Respuesta: ...' "
    "que representa campos extraidos del formulario por OCR.\n"
    "- La evidencia puede contener texto de formularios USCIS con checkboxes "
    "([X] marcado, [ ] no marcado), campos de formulario (etiqueta: valor), "
    "tablas y texto libre.\n"
    "- Busca datos especificos: A-Numbers (formato numerico), "
    "fechas en formato 'Mmm DD YYYY' (p. ej. 'Mar 21 1979', con la abreviatura "
    "del mes en ingles), nombres completos (Family/Given/Middle), "
    "direcciones, numeros de telefono, SSN, numeros de pasaporte.\n"
    "- Si la evidencia contiene [?], es un segmento ilegible. "
    "[FIRMA] o [SIGNATURE] indican firma. "
    "[SELLO OFICIAL] o [OFFICIAL STAMP] indican sello oficial. "
    "Ninguno de estos marcadores es texto real del documento.\n"
    "- Si la evidencia dice '(no evidence available)' o esta vacia, "
    "responde INSUFFICIENT sin forzar YES o NO."
)

VERIFY_CACHE_PLACEHOLDER = (
    "Contexto compartido de verificacion QC para ejecucion por lotes."
)

PAGE_CITATION_RULE = (
    '- Cuando refieras paginas en justification, usa solo numeros de pagina '
    '(ej. "p.22, p.27"). No incluyas el nombre del archivo fuente.'
)

# ---------------------------------------------------------------------------
# Pydantic schema field descriptions (sent to Gemini as response_json_schema)
# ---------------------------------------------------------------------------
VERIFY_DECISION_DESC = (
    "Return YES, NO, NA, or INSUFFICIENT according to the prompt semantics for the current form type."
)
VERIFY_JUSTIFICATION_DESC = (
    "Short justification referencing specific evidence and page numbers used."
)
VERIFY_CORRECTION_DESC = (
    "Correction to apply only when the evidence shows the form value should change; otherwise an empty string."
)
VERIFY_QUESTION_ID_DESC = "Question identifier."


from ..services.form_registry import normalize_form_type as _normalize_canonical_form_type  # noqa: E402


def _normalize_form_type(form_type: str = "") -> str:
    """Thin str-returning wrapper around the canonical normalizer."""
    return _normalize_canonical_form_type(form_type) or ""


def _uses_question_value_semantics(form_type: str = "") -> bool:
    spec = try_get_form_prompt_spec(form_type)
    return bool(spec and spec.uses_question_value_semantics)


def get_form_context(form_type: str = "") -> str:
    spec = try_get_form_prompt_spec(form_type)
    return spec.verification_context if spec else ""


_GENERIC_FORM_LABEL = "el formulario USCIS configurado"


def _get_form_label(form_type: str = "") -> str:
    """Resolve the verification form label.

    There is NO silent fallback to I-914 when an unknown form_type is supplied.
    Historical bugs (e.g. I-765 jobs verified with the I-914 label) traced back
    to that fallback. Callers MUST pass a registered form_type; an empty input
    yields a neutral label for the generic prompt path only.
    """
    normalized = _normalize_form_type(form_type)
    if not normalized:
        return _GENERIC_FORM_LABEL
    return get_form_prompt_spec(normalized).form_label


def _build_decision_rules(form_type: str = "") -> list[str]:
    if _uses_question_value_semantics(form_type):
        return [
            "- Para I-914, YES/NO representan el valor real de la pregunta, no si el formulario fue llenado correctamente.",
            '- YES: La evidencia indica que la afirmacion es verdadera o que la opcion "Yes" del item exacto esta marcada.',
            '- NO: La evidencia indica que la afirmacion es falsa o que la opcion "No" del item exacto esta marcada.',
            '- NA: La pregunta condicional no aplica segun la evidencia. Ejemplo: un subitem "If Yes..." cuyo antecedente esta marcado como No.',
            "- INSUFFICIENT: No hay suficiente evidencia para decidir la respuesta del item exacto.",
            '- Si el OCR muestra "[ ] Yes [X] No" para el item exacto, responde NO. Si muestra "[X] Yes [ ] No", responde YES.',
            "- Anclate al item exacto. No mezcles checkboxes o respuestas de preguntas vecinas.",
            "- Si el formulario y otras fuentes se contradicen, responde segun la evidencia mas confiable sobre el hecho preguntado y menciona el conflicto.",
            "- No conviertas un NO bien marcado en YES solo porque el formulario este completo o sea consistente.",
            "- Para preguntas sobre checkboxes del formulario, busca corroborar con documentos de soporte "
            "(Declaration, FBI Report, LEA Report, Court Records) cuando esten disponibles en la evidencia.",
        ]

    return [
        "- YES: La evidencia muestra que el campo fue completado o verificado correctamente. Incluye casos donde la informacion esta presente y es consistente, aunque no sea exhaustiva.",
        "- NO: La evidencia muestra un error verificable, falta informacion obligatoria que deberia estar presente, o los datos contradicen otra fuente. Datos parciales pero correctos NO son motivo de NO; usa YES.",
        '- NA: La pregunta condicional no aplica segun la evidencia. Ejemplo: un subitem "If Yes..." cuyo antecedente esta marcado como No.',
        "- INSUFFICIENT: No hay suficiente evidencia para decidir si la respuesta debe ser YES, NO o NA.",
        "- Prefiere YES, NO o NA cuando la evidencia lo permita. Usa INSUFFICIENT solo cuando la evidencia no alcance para decidir.",
    ]


def _build_image_task_instruction(form_type: str = "") -> str:
    if _uses_question_value_semantics(form_type):
        return (
            "3. Determina si la afirmacion de la pregunta es verdadera, falsa, no aplicable, "
            "o insuficiente segun la evidencia del item exacto."
        )
    return "3. Determina si la informacion esta presente, es correcta y esta completa."


def _build_base_instructions(form_type: str = "") -> str:
    """Shared instruction block matching v1's buildChecklistInstructions()."""
    form_label = _get_form_label(form_type)
    form_context = get_form_context(form_type)
    return "\n".join([
        f"Eres un asistente legal de control de calidad para revision de checklist del formulario {form_label}.",
        "",
        form_context,
        "",
        COMMON_VERIFICATION_SOURCES,
        "",
        SOURCE_HIERARCHY_INSTRUCTIONS,
        "",
        "Instrucciones para decidir cada pregunta:",
        "- Analiza la evidencia proporcionada del OCR del documento.",
        OCR_MARKERS_INSTRUCTIONS,
        "- Cada pregunta incluye un campo 'whereToVerify' que indica fuentes de verificacion prioritarias "
        "(ej. 'BIO CALL', 'Declaration', 'FBI Report'). Cuando la evidencia incluya datos de esas fuentes, "
        "prioriza esa informacion para tu decision.",
        "- Si la evidencia contiene datos tanto del formulario como de documentos de soporte, "
        "verifica que ambos sean consistentes. Reporta cualquier conflicto en la justificacion.",
        *_build_decision_rules(form_type),
        "- Usa exactamente el id recibido en cada pregunta; no inventes ni modifiques ids.",
        "- En justification, indica brevemente que evidencia especifica usaste y de que pagina/seccion.",
        "- En correction, indica el valor correcto solo cuando la evidencia muestre que el formulario debe corregirse; si no hay correccion concreta, dejalo vacio.",
        PAGE_CITATION_RULE,
    ])


# ---------------------------------------------------------------------------
# Batch RAG verification (primary autopilot path)
# ---------------------------------------------------------------------------
_BATCH_OUTPUT_SCHEMA = (
    'Output JSON solamente con esta forma:\n'
    '{"answers":[{"id":"string","decision":"YES|NO|NA|INSUFFICIENT",'
    '"justification":"texto corto","correction":"texto corto o vacio"}]}'
)


def build_rag_batch_system_prompt(form_type: str = "") -> str:
    base = _build_base_instructions(form_type)
    return f"{base}\n\n{_BATCH_OUTPUT_SCHEMA}".strip()


def build_rag_batch_request_prompt(questions_payload: str) -> str:
    return f"INPUT:\n{questions_payload}".strip()


# ---------------------------------------------------------------------------
# Single-question RAG verification
# ---------------------------------------------------------------------------
_SINGLE_OUTPUT_SCHEMA = (
    'Output JSON solamente con esta forma:\n'
    '{"decision":"YES|NO|NA|INSUFFICIENT",'
    '"justification":"texto corto","correction":"texto corto o vacio"}'
)


def build_rag_verify_system_prompt(form_type: str = "") -> str:
    base = _build_base_instructions(form_type)
    return f"{base}\n\n{_SINGLE_OUTPUT_SCHEMA}".strip()


def build_rag_verify_request_prompt(request_payload: str) -> str:
    return f"INPUT:\n{request_payload}".strip()


# ---------------------------------------------------------------------------
# Image-based verification
# ---------------------------------------------------------------------------
def build_verify_prompt(
    *,
    question: str,
    where_to_verify: str,
    text_context: str = "",
    form_type: str = "",
) -> str:
    return VERIFY_PROMPT.format(
        question=question,
        where_to_verify=where_to_verify or "Not specified",
        text_context=text_context or "No OCR context retrieved.",
        form_context=get_form_context(form_type),
        ocr_markers=OCR_MARKERS_INSTRUCTIONS,
        task_instruction=_build_image_task_instruction(form_type),
        decision_rules="\n".join(_build_decision_rules(form_type)),
        output_schema=_SINGLE_OUTPUT_SCHEMA,
    )


VERIFY_PROMPT = """Eres un asistente legal de control de calidad revisando documentos de casos de inmigracion.

Se te proporciona una imagen de pagina de documento y una pregunta de verificacion de un checklist QC.

{form_context}

TAREA: Analiza la imagen del documento y responde la pregunta de verificacion.

PREGUNTA DE VERIFICACION:
{question}

DONDE VERIFICAR (fuentes esperadas):
{where_to_verify}

CONTEXTO OCR RECUPERADO:
{text_context}

INSTRUCCIONES:
1. Examina cuidadosamente la imagen del documento para informacion relevante a la pregunta.
2. Usa el contexto OCR recuperado como texto de soporte, pero confia en la imagen de pagina si hay conflicto.
{ocr_markers}
{task_instruction}
4. Devuelve un objeto JSON que siga estrictamente el esquema de respuesta.

REGLAS:
{decision_rules}
- En correction, indica el valor correcto solo cuando la evidencia muestre que el formulario debe corregirse; si no hay correccion concreta, dejalo vacio.
- Se especifico en la justificacion, referencia texto/datos exactos que ves en la imagen.
- Cuando refieras paginas en justification, usa solo numeros de pagina (ej. "p.22, p.27"). No incluyas el nombre del archivo fuente.

{output_schema}"""

