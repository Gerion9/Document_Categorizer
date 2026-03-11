"""
Prompts for QC verification (ai_verify_service).

Shared instruction base aligned with v1 (checklist.prompts.js), used by all modes:
  1) Image + text  (VERIFY_PROMPT)
  2) Text-only RAG (build_rag_verify_system_prompt / build_rag_verify_request_prompt)
  3) Batch RAG     (build_rag_batch_system_prompt / build_rag_batch_request_prompt)
"""

FORM_CONTEXT: dict[str, str] = {
    "i-914a": "\n".join([
        "Estructura del formulario I-914A:",
        "- Part 1: Relacion familiar (Spouse/Child/Parent/Sibling under 18)",
        "- Part 2: Info del principal (nombre, DOB, A-Number, status del I-914)",
        "- Part 3: Info del derivado (nombre, direccion, A-Number, SSN, sexo, estado civil, DOB, pasaporte, status migratorio, historial de entradas)",
        "- Part 4: Procesamiento (criminal, prostitucion, terrorismo, presencia cerca de dano, proceedings migratorios)",
        "- Part 5: Declaracion y firma del aplicante",
        "- Part 6: Interprete",
        "- Part 7: Preparador",
        "- Part 8: Informacion adicional",
    ]),
    "i-914": "\n".join([
        "Estructura del formulario I-914:",
        "- Part 1: Proposito (seleccion A o B segun el caso T-1)",
        "- Part 2: Info general (sexo, estado civil, DOB - items 8-10)",
        "- Part 3: Elegibilidad de trata (3.1-3.11: victima de trata severa, cooperacion con LEA, presencia fisica, hardship, reporte, edad, entradas previas, EAD, familiares)",
        "- Part 4: Procesamiento (4.1: criminal/LEA, 4.2: prostitucion/contrabando/drogas, 4.3: seguridad/terrorismo/espionaje, 4.4: presencia cerca de dano/proceedings, 4.5: tortura/genocidio, 4.6: militar/paramilitar, 4.7: penalidades civiles/fraude, 4.8: salud)",
        "- Part 5: Miembros familiares (5.1-5.13)",
        "- Part 6: Declaracion y firma",
        "- Part 7: Interprete",
        "- Part 8: Preparador",
        "- Part 9: Informacion adicional",
    ]),
}

FORM_LABELS: dict[str, str] = {
    "i-914a": "I-914 Supplement A (I-914A) - Application for Derivative T Nonimmigrant Status",
    "i-914": "I-914 - Application for T Nonimmigrant Status",
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

VERIFY_CACHE_PLACEHOLDER = (
    "Contexto compartido de verificacion QC para ejecucion por lotes."
)

PAGE_CITATION_RULE = (
    '- Cuando refieras paginas en justification, usa solo numeros de pagina '
    '(ej. "p.22, p.27"). Nunca incluyas nombres de archivo, PDF, rutas ni '
    'texto entre parentesis como "(documento.pdf)". Si la evidencia muestra '
    '"p.22 (documento.pdf)", cita solo "p.22".'
)


def get_form_context(form_type: str = "") -> str:
    key = form_type.strip().lower().replace(" ", "-") if form_type else ""
    return FORM_CONTEXT.get(key, "")


def _get_form_label(form_type: str = "") -> str:
    key = form_type.strip().lower().replace(" ", "-") if form_type else ""
    return FORM_LABELS.get(key, FORM_LABELS["i-914"])


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
        "Instrucciones para decidir cada pregunta:",
        "- Analiza la evidencia proporcionada del OCR del documento.",
        OCR_MARKERS_INSTRUCTIONS,
        "- YES: La evidencia muestra claramente que el campo fue verificado/completado correctamente.",
        "- NO: La evidencia muestra que el campo tiene un error, esta incompleto, o contradice otra fuente.",
        "- INSUFFICIENT: No hay suficiente evidencia para determinar si el campo esta correcto.",
        "- Usa exactamente el id recibido en cada pregunta; no inventes ni modifiques ids.",
        "- En justification, indica brevemente que evidencia especifica usaste y de que pagina/seccion.",
        "- En correction, indica que valor deberia tener el campo si la decision es NO.",
        PAGE_CITATION_RULE,
    ])


# ---------------------------------------------------------------------------
# Batch RAG verification (primary autopilot path)
# ---------------------------------------------------------------------------
_BATCH_OUTPUT_SCHEMA = (
    'Output JSON solamente con esta forma:\n'
    '{"answers":[{"id":"string","decision":"YES|NO|INSUFFICIENT",'
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
    '{"decision":"YES|NO|INSUFFICIENT",'
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
3. Determina si la informacion esta presente, es correcta y esta completa.
4. Devuelve un objeto JSON que siga estrictamente el esquema de respuesta.

REGLAS:
- "YES" = La informacion esta presente y verificada correctamente en este documento.
- "NO" = La informacion falta, es incorrecta o es inconsistente.
- "INSUFFICIENT" = No hay suficiente evidencia para determinar si es correcto.
- Se especifico en la justificacion, referencia texto/datos exactos que ves en la imagen.
- Si el documento no es la fuente correcta para esta pregunta, responde "INSUFFICIENT".
- Cuando refieras paginas en justification, usa solo numeros de pagina (ej. "p.22, p.27"). Nunca incluyas nombres de archivo, PDF, rutas ni texto entre parentesis como "(documento.pdf)". Si la evidencia muestra "p.22 (documento.pdf)", cita solo "p.22".

Output JSON solamente con esta forma:
{{"decision":"YES|NO|INSUFFICIENT","justification":"texto corto","correction":"texto corto o vacio"}}"""

# ---------------------------------------------------------------------------
# Legacy template-based prompts (kept for backward compatibility)
# ---------------------------------------------------------------------------
RAG_VERIFY_PROMPT = """Eres un asistente legal de control de calidad para revision de checklist de inmigracion.

Se te proporciona texto extraido por OCR de formularios USCIS y documentos de soporte.

{form_context}
{common_sources}

TAREA: Usando SOLO la evidencia proporcionada, responde la pregunta de verificacion.

INPUT:
{request_payload}

INSTRUCCIONES:
1. Analiza la evidencia para informacion relevante a la pregunta.
{ocr_markers}
2. Determina si la informacion esta presente, es correcta y esta completa.
3. Devuelve un objeto JSON que siga estrictamente el esquema de respuesta.
4. En justification, indica brevemente que evidencia especifica usaste y de que pagina/seccion.
5. En correction, indica que valor deberia tener el campo si la decision es NO.

REGLAS:
- "YES" = La evidencia muestra que el campo/informacion fue verificado/completado correctamente.
- "NO" = La evidencia muestra que el campo tiene un error, esta incompleto, o contradice otra fuente.
- "INSUFFICIENT" = No hay suficiente evidencia para determinar si es correcto.
- Se especifico: referencia texto exacto, estados de checkbox o valores de campo de la evidencia.
- Si la evidencia no contiene informacion sobre esta pregunta, responde "INSUFFICIENT".
- Cuando cites paginas, usa solo "p.N". Nunca incluyas nombres de archivo, PDF, rutas ni texto entre parentesis."""

RAG_BATCH_PROMPT = """Eres un asistente legal de control de calidad para revision de checklist de inmigracion.

Se te proporciona texto extraido por OCR de formularios USCIS y documentos de soporte.

{form_context}
{common_sources}

TAREA: Responde TODAS las preguntas de verificacion usando SOLO la evidencia proporcionada para cada pregunta.

INPUT:
{questions_block}

INSTRUCCIONES:
1. Para cada pregunta, analiza SOLO su evidencia asociada para informacion relevante.
{ocr_markers}
2. Devuelve un objeto JSON con un array "answers", una entrada por pregunta, en el mismo orden.
3. Usa exactamente el id recibido en cada pregunta; no inventes ni modifiques ids.
4. En justification, indica brevemente que evidencia especifica usaste y de que pagina/seccion.
5. En correction, indica que valor deberia tener el campo si la decision es NO.

REGLAS:
- "YES" = La evidencia confirma que el campo/informacion es correcto/completo.
- "NO" = La evidencia muestra un error, omision, o inconsistencia.
- "INSUFFICIENT" = No hay suficiente evidencia para determinar si es correcto.
- Se especifico: referencia texto exacto de la evidencia en cada justification.
- Cuando cites paginas, usa solo "p.N". Nunca incluyas nombres de archivo, PDF, rutas ni texto entre parentesis."""
