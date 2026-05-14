"""Prompts for AI-assisted PDF form filling field extraction."""

from __future__ import annotations

import json
import re
from typing import Any

from .verification_prompts import (
    COMMON_VERIFICATION_SOURCES,
    SOURCE_HIERARCHY_INSTRUCTIONS,
    OCR_MARKERS_INSTRUCTIONS,
    get_form_context,
)
from ..schemas.field_extraction import (
    BatchFieldValueResult,
    FIELD_CONFIDENCE_DESC,
    FIELD_ID_DESC,
    FIELD_JUSTIFICATION_DESC,
    FIELD_VALUE_DESC,
    FieldValueResult,
    compact_schema_hint,
)
from ..utils.text import clean_text as _clean_text

FORM_FILL_CACHE_PLACEHOLDER = (
    "Contexto compartido de extraccion de valores para auto-llenado de formularios PDF."
)

_FIELD_EXTRACTION_OUTPUT_SCHEMA = (
    "Output JSON solamente con esta forma:\n"
    f"{compact_schema_hint(FieldValueResult)}"
)

_FIELD_EXTRACTION_BATCH_OUTPUT_SCHEMA = (
    "Output JSON solamente con esta forma:\n"
    f"{compact_schema_hint(BatchFieldValueResult)}"
)

# ---------------------------------------------------------------------------
# Applicant detection
# ---------------------------------------------------------------------------
PRINCIPAL_APPLICANT_SEARCH_QUERY = (
    "I-914 Part 2 Item 1 principal applicant Full Legal Name Family Name Given Name"
)


def build_applicant_context_instruction(name: str) -> str:
    if not name:
        return ""
    return (
        f"Aplicante principal: {name}. "
        "Extrae UNICAMENTE los datos de esta persona. "
        "El expediente puede contener formularios de familiares derivados "
        "(conyuge, hijos) con datos distintos; ignora esos datos para los campos del aplicante principal."
    )

_STOPWORDS = {
    "a",
    "an",
    "and",
    "be",
    "for",
    "from",
    "if",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


from ..services.form_registry import normalize_form_type as _normalize_canonical_form_type  # noqa: E402


def _normalize_form_type(form_type: str = "") -> str:
    """Thin str-returning wrapper around the canonical normalizer."""
    return _normalize_canonical_form_type(form_type) or ""


def _tokenize(text: Any) -> list[str]:
    tokens = [
        token
        for token in _TOKEN_RE.findall(_clean_text(text).lower())
        if token and token not in _STOPWORDS
    ]
    return list(dict.fromkeys(tokens))


def _dedupe_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for option in options:
        value = _clean_text(option.get("value"))
        label = _clean_text(option.get("label"))
        key = (value.lower(), label.lower())
        if not value and not label:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"value": value or label, "label": label or value})
    return deduped


def _format_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    formatted = dict(item)
    parts: list[str] = []
    page = item.get("pageNumber")
    if page is not None:
        parts.append(f"p.{page}")
    section = _clean_text(item.get("sectionName"))
    if section:
        parts.append(section)
    document_type = _clean_text(item.get("documentType"))
    if document_type:
        parts.append(document_type)
    original_filename = _clean_text(item.get("originalFilename"))
    if original_filename and not parts:
        parts.append(original_filename)
    if parts:
        formatted["source"] = " | ".join(parts)
    return formatted


def _normalize_evidence_payload(evidence: Any) -> Any:
    if isinstance(evidence, dict):
        structured = evidence.get("evidence")
        if isinstance(structured, list) and structured:
            return [_format_evidence_item(item) for item in structured if isinstance(item, dict)]
        text_context = _clean_text(evidence.get("text_context") or evidence.get("textContext"))
        if text_context:
            return text_context
        matches = evidence.get("matches")
        if isinstance(matches, list) and matches:
            normalized_matches: list[dict[str, Any]] = []
            for match in matches:
                if not isinstance(match, dict):
                    continue
                metadata = match.get("metadata", {}) or {}
                normalized_matches.append(
                    _format_evidence_item(
                        {
                            "pageNumber": metadata.get("page_number") or metadata.get("page_id"),
                            "sectionName": metadata.get("section_name", ""),
                            "documentType": metadata.get("document_type_code", ""),
                            "originalFilename": metadata.get("original_filename", ""),
                            "text": _clean_text(metadata.get("text") or metadata.get("explanation") or ""),
                        }
                    )
                )
            if normalized_matches:
                return normalized_matches
        return "(no evidence available)"

    if isinstance(evidence, list):
        return [_format_evidence_item(item) for item in evidence if isinstance(item, dict)] or "(no evidence available)"

    text = _clean_text(evidence)
    return text or "(no evidence available)"


def _normalize_questionnaire_options(field: dict[str, Any]) -> list[dict[str, str]]:
    raw_options = field.get("questionnaire_options") or field.get("options") or []
    normalized: list[dict[str, str]] = []

    if isinstance(raw_options, list):
        for option in raw_options:
            if isinstance(option, dict):
                normalized.append(
                    {
                        "value": _clean_text(option.get("value") or option.get("id") or option.get("label")),
                        "label": _clean_text(option.get("label") or option.get("value") or option.get("id")),
                    }
                )
            else:
                cleaned = _clean_text(option)
                normalized.append({"value": cleaned, "label": cleaned})

    for key in ("choice_values", "button_values"):
        raw_values = field.get(key) or []
        if isinstance(raw_values, list):
            for value in raw_values:
                cleaned = _clean_text(value)
                normalized.append({"value": cleaned, "label": cleaned})

    return _dedupe_options(normalized)


def _normalized_field_context(field: dict[str, Any]) -> str:
    return _clean_text(
        " ".join(
            str(part or "")
            for part in (
                field.get("id"),
                field.get("field_name"),
                field.get("field_label"),
                field.get("questionnaire_field_id"),
                field.get("questionnaire_label"),
                field.get("questionnaire_form_text"),
                field.get("questionnaire_section"),
            )
        )
    ).lower()


from .forms import FORM_PROMPT_REGISTRY, try_get_form_prompt_spec


def _all_narrative_markers() -> list[tuple[str, str]]:
    """Aggregate every (item_id, field_id) marker registered across forms."""
    markers: list[tuple[str, str]] = []
    for spec in FORM_PROMPT_REGISTRY.values():
        for marker in spec.narrative_fields:
            markers.append((marker.item_id.lower(), marker.field_id.lower()))
    return markers


_NARRATIVE_MARKERS: list[tuple[str, str]] = _all_narrative_markers()


def is_narrative_field(field: dict[str, Any]) -> bool:
    """Return True when the field expects a free-form Part-9-style paragraph.

    Narrative markers are now declared per-form in `FormPromptSpec.narrative_fields`
    instead of being hard-coded here. The canonical-id heuristic is preserved
    as a defensive fallback for legacy callers.
    """
    item_id = _clean_text(field.get("questionnaire_item_id")).lower()
    field_id = _clean_text(field.get("questionnaire_field_id")).lower()
    canonical = _clean_text(field.get("canonical_questionnaire_id")).lower()
    for marker_item, marker_field in _NARRATIVE_MARKERS:
        if marker_item and item_id != marker_item:
            continue
        if marker_field and field_id != marker_field:
            continue
        return True
    if "additional_information" in canonical and "p9" in canonical:
        return True
    return False


def _expected_output_hint(field: dict[str, Any]) -> str:
    field_type = _clean_text(field.get("field_type") or field.get("field_type_hint")).lower()
    options = _normalize_questionnaire_options(field)
    target_option = _clean_text(field.get("questionnaire_option_label") or field.get("questionnaire_option_value"))
    field_context = _normalized_field_context(field)

    questionnaire_item_id = _clean_text(field.get("questionnaire_item_id")).lower()
    if questionnaire_item_id:
        for prompt_spec in FORM_PROMPT_REGISTRY.values():
            hint = prompt_spec.item_hints.get(questionnaire_item_id)
            if hint:
                return hint

    if is_narrative_field(field):
        return (
            "Este campo es el parrafo narrativo de Part 9 (Additional Information). "
            "Escribe un parrafo factual COMPLETO y UNICO para este item, usando SOLO datos "
            "concretos del expediente: fechas exactas en formato 'Mmm DD YYYY' "
            "(p. ej. 'Mar 21 1979'), nombres de agencias (CBP, ICE, DHS, EOIR), lugares "
            "especificos (ciudad, estado), resultados concretos (released, NTA issued, "
            "order of removal, etc.). "
            "NO repitas frases identicas a las de otros items. "
            "NO uses frases genericas como 'details to be confirmed', 'see attached', "
            "'information will be provided' o 'please refer to supporting documents'. "
            "Si la evidencia no tiene datos suficientes para redactar un parrafo factual, "
            "devuelve una cadena vacia y confidence: low."
        )

    if "social security" in field_context or "ssn" in field_context or ".ssn" in field_context:
        return (
            "Este campo es un Social Security Number (SSN). Devuelve SOLO 9 digitos sin guiones, "
            "espacios ni separadores (ejemplo: 331810119, NO 331-81-0119). "
            "Si la evidencia no muestra un SSN valido, devuelve una cadena vacia."
        )
    if "alien registration number" in field_context or "a-number" in field_context or ".a_number" in field_context:
        return (
            "Este campo es un A-Number. Devuelve SOLO un A-number valido del aplicante principal: "
            "7 a 9 digitos, sin inventar y sin reemplazarlo por nombres, apodos u otros identificadores. "
            "Si la evidencia no muestra un A-number valido, devuelve una cadena vacia."
        )
    if "safe mailing address" in field_context or (
        "mailing address" in field_context and "safe" in field_context
    ):
        return (
            "Este campo pertenece a Safe Mailing Address. Devuelvelo SOLO si la evidencia muestra una "
            "direccion alternativa, segura y distinta de la direccion fisica actual. Si parece la misma "
            "direccion o no hay evidencia clara de una alternativa, devuelve una cadena vacia. "
            "No copies apellidos, nombres del campo 'In Care Of Name' ni valores de otros campos cercanos "
            "solo por proximidad visual; la ciudad, el estado y el ZIP deben venir de evidencia especifica "
            "de la direccion segura."
        )
    if (
        ("apt./ste./flr." in field_context or "apt ste flr" in field_context)
        and field_type in {"choice", "select", "combobox", "listbox", "text"}
    ):
        return (
            "Este campo corresponde al tipo de unidad de una direccion. "
            "Si la evidencia dice Apartment/Apt, devuelve exactamente 'Apt.'. "
            "Si dice Suite/Ste, devuelve exactamente 'Ste.'. "
            "Si dice Floor/Flr, devuelve exactamente 'Flr.'. "
            "Si no hay unidad, devuelve una cadena vacia."
        )
    if "passport" in field_context and "issue date" in field_context:
        return (
            "Este campo es la fecha de expedicion del pasaporte o travel document. "
            "Reconoce tambien etiquetas como 'Date of Issue', 'Fecha de expedicion' y 'Fecha de emision'. "
            "No la confundas con la fecha de expiracion. "
            "Devuelve la fecha en formato 'Mmm DD YYYY' (p. ej. 'Mar 21 1979') o cadena vacia."
        )
    if "passport" in field_context and "expiration date" in field_context:
        return (
            "Este campo es la fecha de expiracion del pasaporte o travel document. "
            "Reconoce tambien etiquetas como 'Expiry Date', 'Fecha de vencimiento' y 'Fecha de expiracion'. "
            "No la confundas con la fecha de expedicion. "
            "Devuelve la fecha en formato 'Mmm DD YYYY' (p. ej. 'Mar 21 1979') o cadena vacia."
        )
    if "country of citizenship" in field_context or "citizenship or nationality" in field_context:
        return (
            "Este campo debe contener un PAIS. Devuelve el nombre del pais en ingles cuando la evidencia lo "
            "permita. No devuelvas una ciudad, una nacionalidad en forma de adjetivo, ni un estatus migratorio. "
            "No copies el valor del campo anterior solo por cercania visual."
        )
    if "current nonimmigrant status" in field_context or "current immigration status" in field_context:
        return (
            "Este campo debe contener un ESTATUS migratorio actual, por ejemplo 'B-2 overstay', 'F-1', "
            "'Parole' o 'No Legal Status'. No devuelvas un pais, una ciudad ni una nacionalidad. "
            "No copies el valor del campo anterior solo por cercania visual."
        )
    if (
        " state " in f" {field_context} "
        and ("address" in field_context or "entry" in field_context or "lea" in field_context)
        and field_type in {"choice", "select", "combobox", "listbox", "text"}
    ):
        return (
            "Este campo es el estado en EE.UU. "
            "Devuelve la abreviatura USPS de 2 letras (por ejemplo 'TX' para Texas) "
            "solo cuando la evidencia mencione el estado explicitamente o como nombre completo. "
            "Si solo ves una ciudad, un ZIP o un puerto de entrada sin estado explicito, "
            "devuelve cadena vacia en lugar de adivinar; el backend resolvera los casos deterministas "
            "con ciudad o ZIP y evitara suposiciones en ciudades ambiguas."
        )

    if field_type in {"signature"}:
        return (
            "Este es un campo de firma. Devuelve una cadena vacia salvo que la evidencia indique "
            "un texto literal que deba imprimirse, lo cual normalmente no aplica."
        )
    if field_type in {"checkbox", "button"} and target_option:
        return (
            f"Este widget representa una opcion especifica ('{target_option}'). "
            "Devuelve 'true' si debe marcarse o 'false' si debe quedar sin marcar."
        )
    if field_type in {"checkbox", "radio", "button"} and options:
        readable = ", ".join(
            option["label"] if option["label"] == option["value"] else f'{option["label"]} ({option["value"]})'
            for option in options
        )
        return (
            "Este widget requiere seleccionar una opcion. "
            f"Devuelve exactamente una de estas opciones permitidas: {readable}. "
            "Si no hay evidencia suficiente, devuelve una cadena vacia."
        )
    if field_type in {"choice", "select", "combobox", "listbox"} and options:
        readable = ", ".join(
            option["label"] if option["label"] == option["value"] else f'{option["label"]} ({option["value"]})'
            for option in options
        )
        return (
            "Este campo es de seleccion. "
            f"Devuelve exactamente una de las opciones permitidas: {readable}. "
            "Si no hay evidencia suficiente, devuelve una cadena vacia."
        )
    if field_type == "date":
        return (
            "Devuelve la fecha en formato 'Mmm DD YYYY' (p. ej. 'Mar 21 1979'). "
            "Usa SIEMPRE la abreviatura del mes en ingles (Jan, Feb, Mar, Apr, May, Jun, "
            "Jul, Aug, Sep, Oct, Nov, Dec). Si la fecha es incierta o parcial, devuelve "
            "una cadena vacia."
        )
    return "Devuelve solo el valor literal que deberia escribirse en el PDF, sin etiquetas ni explicaciones."


def _field_summary(field: dict[str, Any]) -> dict[str, Any]:
    questionnaire_options = _normalize_questionnaire_options(field)
    return {
        "id": _clean_text(field.get("id") or field.get("field_name")),
        "field_name": _clean_text(field.get("field_name")),
        "field_label": _clean_text(field.get("field_label")),
        "field_type": _clean_text(field.get("field_type") or field.get("field_type_hint") or "text"),
        "page_number": field.get("page_number"),
        "nearby_text": _clean_text(field.get("nearby_text")),
        "button_values": [_clean_text(v) for v in field.get("button_values", []) if _clean_text(v)],
        "choice_values": [_clean_text(v) for v in field.get("choice_values", []) if _clean_text(v)],
        "questionnaire": {
            "canonical_questionnaire_id": _clean_text(field.get("canonical_questionnaire_id")),
            "item_id": _clean_text(field.get("questionnaire_item_id")),
            "field_id": _clean_text(field.get("questionnaire_field_id")),
            "option_value": _clean_text(field.get("questionnaire_option_value")),
            "option_label": _clean_text(field.get("questionnaire_option_label")),
            "label": _clean_text(field.get("questionnaire_label")),
            "form_text": _clean_text(field.get("questionnaire_form_text")),
            "section": _clean_text(field.get("questionnaire_section")),
            "responsible_party": _clean_text(field.get("questionnaire_responsible_party")),
            "item_type": _clean_text(field.get("questionnaire_item_type")),
            "options": questionnaire_options,
        },
        "search_query": _clean_text(field.get("search_query")),
        "expected_output": _expected_output_hint(field),
        "is_narrative": is_narrative_field(field),
        "semantic_tokens": _tokenize(
            " ".join(
                part
                for part in [
                    field.get("field_label"),
                    field.get("nearby_text"),
                    field.get("questionnaire_label"),
                    field.get("questionnaire_form_text"),
                    field.get("questionnaire_section"),
                    field.get("search_query"),
                ]
                if _clean_text(part)
            )
        ),
    }


_GENERIC_SHORT_LABEL = "el formulario USCIS configurado"


def _resolve_short_label(form_type: str) -> str:
    """Resolve the short uppercase label for the prompt opening line.

    Falls back to the generic legacy label when `form_type` is empty/unknown,
    matching the prior behavior. Unlike the verification path, the form-filling
    pipeline is sometimes invoked with a missing form_type during legacy code
    paths; keeping a neutral default here avoids breaking those.
    """
    spec = try_get_form_prompt_spec(form_type)
    if spec is not None:
        return spec.short_label
    normalized = _normalize_form_type(form_type)
    return normalized.upper() if normalized else _GENERIC_SHORT_LABEL


_BASE_FORM_FILLING_RULES: tuple[str, ...] = (
    "Objetivo:",
    "- Analiza la evidencia RAG del expediente y devuelve el valor exacto que debe escribirse en un campo del PDF.",
    "- No inventes datos. Si la evidencia no alcanza, devuelve una cadena vacia y confianza low.",
    "- Prioriza coincidencias literales y datos verificables sobre inferencias.",
    "- Si hay conflicto entre fuentes, elige la fuente de mayor rango en la jerarquia y menciona brevemente el conflicto en justification.",
    "",
    "Reglas de normalizacion:",
    OCR_MARKERS_INSTRUCTIONS,
    "- Nunca incluyas explicaciones dentro de value.",
    "- Para nombres, direcciones, identificadores y texto libre, devuelve solo el valor listo para pegar en el PDF.",
    "- Nunca copies el valor del campo anterior o cercano solo por proximidad visual; cada campo debe estar soportado por evidencia especifica de ese mismo campo.",
    "- Si la evidencia muestra una direccion completa en una sola linea, separa correctamente calle, tipo de unidad, numero de unidad, ciudad, estado y ZIP.",
    "- Para direcciones de EE.UU., normaliza el estado a la abreviatura USPS de 2 letras cuando la evidencia lo permita.",
    "- Para Apt./Ste./Flr., normaliza Apartment/Apt -> 'Apt.', Suite/Ste -> 'Ste.' y Floor/Flr. -> 'Flr.'.",
    "- Si un campo admite multiples valores (como alias, otros nombres), devuelve UNICAMENTE el valor principal o mas frecuente.",
    "  NO combines multiples valores con comas, punto y coma u otros separadores. Un solo valor por campo.",
    "- Para TODAS las fechas, devuelve el formato 'Mmm DD YYYY' (p. ej. 'Mar 21 1979') con la abreviatura del mes en ingles (Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec). Nunca devuelvas MM/DD/YYYY ni DD/MM/YYYY ni 'YYYY-MM-DD'.",
    "- Si el PDF tiene sub-cajas separadas para mes, dia y year, devuelve igualmente la fecha completa en formato 'Mmm DD YYYY'; el backend se encarga de la segmentacion final.",
    "- Para fechas de pasaporte, distingue cuidadosamente fecha de expedicion vs. fecha de expiracion; acepta tambien etiquetas en espanol como 'Fecha de expedicion' o 'Fecha de vencimiento'.",
    "- Para A-Number, devuelve solo 7 a 9 digitos validos del aplicante principal. Si no hay un A-Number valido, devuelve una cadena vacia.",
    "- Para Social Security Number (SSN), devuelve solo los 9 digitos sin guiones ni espacios. Si no hay un SSN valido, devuelve una cadena vacia.",
    "- Para 'Country of Citizenship or Nationality', devuelve un pais valido; no una ciudad, una nacionalidad como adjetivo ni un estatus migratorio.",
    "- Para 'Current Nonimmigrant Status' o 'Current Immigration Status', devuelve un estatus migratorio; no un pais, ciudad o nacionalidad.",
    "- Para Safe Mailing Address, solo devuelve valores cuando la evidencia muestre una direccion alternativa distinta de la direccion fisica actual.",
    "- Nunca copies a la ciudad, estado o ZIP de Safe Mailing Address un apellido, un nombre de oficina, ni un valor de otro campo cercano por arrastre visual.",
    "- Para casillas o radios que representan una opcion especifica, devuelve 'true' o 'false' cuando el input lo pida.",
    "- Para campos de seleccion, devuelve exactamente una opcion permitida cuando el input proporcione una lista cerrada.",
    "- Si el campo es una firma, normalmente devuelve una cadena vacia.",
)


_CONFIDENCE_SCALE: tuple[str, ...] = (
    "Escala de confianza:",
    "- high: la evidencia muestra el valor de forma explicita y directa.",
    "- medium: la evidencia es bastante consistente pero requiere una pequena normalizacion o inferencia controlada.",
    "- low: la evidencia es parcial, conflictiva o insuficiente.",
)


def _build_base_instructions(form_type: str = "") -> str:
    """Build the form-filling system instructions.

    The instructions are composed entirely from generic rules plus per-form
    knobs exposed by `FormPromptSpec` (extra rules and taxonomy block). No
    hard-coded `if form_type == "i-914"` branches here.
    """
    form_context = get_form_context(form_type)
    form_label = _resolve_short_label(form_type)
    spec = try_get_form_prompt_spec(form_type)
    extra_rules = spec.form_filling_extra_rules if spec else ()
    taxonomy_block = spec.taxonomy_rules if spec else ""

    sections: list[str] = [
        f"Eres un asistente legal experto en auto-llenado del formulario {form_label}.",
        "",
        form_context,
        "",
        COMMON_VERIFICATION_SOURCES,
        "",
        SOURCE_HIERARCHY_INSTRUCTIONS,
        "",
        *_BASE_FORM_FILLING_RULES,
    ]
    if extra_rules:
        sections.extend(extra_rules)
    if taxonomy_block:
        sections.extend(("", taxonomy_block))
    sections.extend(("", *_CONFIDENCE_SCALE))

    return "\n".join(section for section in sections if section or section == "").strip()


def build_field_extraction_system_prompt(form_type: str = "") -> str:
    base = _build_base_instructions(form_type)
    return f"{base}\n\n{_FIELD_EXTRACTION_OUTPUT_SCHEMA}".strip()


def build_field_extraction_request_prompt(request_payload: str) -> str:
    return f"INPUT:\n{request_payload}".strip()


_BATCH_BASE_RULES: tuple[str, ...] = (
    "Reglas adicionales para modo batch:",
    "- Conserva exactamente el id de cada campo.",
    "- Evalua cada campo de forma independiente usando solo su propia evidencia.",
    "- No copies valores entre campos parecidos salvo que la evidencia de ese campo lo soporte.",
    "- IMPORTANTE: Si el INPUT incluye un campo 'applicant_context', ese es el APLICANTE PRINCIPAL.",
    "  Extrae UNICAMENTE los datos de esa persona para TODOS los campos del aplicante principal.",
)


def _batch_family_member_rules(form_type: str) -> tuple[str, ...]:
    """Append form-specific guidance when the form has family-member sub-items.

    Currently only I-914 declares `batch_family_member_pivot_ids` (Part 5
    spouse / children) but the same mechanism scales to any future form with
    derivative-style sub-items.
    """
    spec = try_get_form_prompt_spec(form_type)
    pivot_ids = spec.batch_family_member_pivot_ids if spec else ()
    if not pivot_ids:
        return ()
    pivot_list = ", ".join(repr(pid) for pid in pivot_ids)
    return (
        f"- Excepcion familiar para {spec.short_label}: los campos con ids que empiezan con "
        f"{pivot_list} requieren datos de FAMILIARES, no del aplicante. Para esos campos, "
        "extrae datos del conyuge o hijos segun corresponda.",
        "  El expediente puede contener formularios de familiares derivados (conyuge, hijos) con",
        "  nombres y datos distintos; esos datos SON CORRECTOS para los campos familiares pero",
        "  INCORRECTOS para los demas campos del aplicante principal.",
    )


def build_batch_system_prompt(form_type: str = "") -> str:
    base = _build_base_instructions(form_type)
    batch_rules = "\n".join((*_BATCH_BASE_RULES, *_batch_family_member_rules(form_type)))
    return f"{base}\n\n{batch_rules}\n\n{_FIELD_EXTRACTION_BATCH_OUTPUT_SCHEMA}".strip()


def build_batch_request_prompt(request_payload: str) -> str:
    return f"INPUT:\n{request_payload}".strip()


def build_field_extraction_json_payload(*, field: dict[str, Any], evidence: Any) -> str:
    payload = {
        "field": _field_summary(field),
        "evidence": _normalize_evidence_payload(evidence),
    }
    return json.dumps(payload, ensure_ascii=False)


def build_field_extraction_batch_json_payload(
    fields: list[dict[str, Any]],
    evidence_by_id: dict[str, Any],
    *,
    applicant_context: str = "",
) -> str:
    payload_fields: list[dict[str, Any]] = []
    evidence_payload: dict[str, Any] = {}

    for field in fields:
        field_summary = _field_summary(field)
        field_id = field_summary["id"]
        payload_fields.append(field_summary)
        evidence_payload[field_id] = _normalize_evidence_payload(evidence_by_id.get(field_id))

    payload: dict[str, Any] = {}
    if applicant_context:
        payload["applicant_context"] = applicant_context
    payload["fields"] = payload_fields
    payload["evidence"] = evidence_payload
    return json.dumps(payload, ensure_ascii=False)

