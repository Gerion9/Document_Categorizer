"""Background orchestrator for AI-assisted PDF form filling jobs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
import logging
import os
import re
import unicodedata
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..dependencies import get_s3_service
from ..models import (
    AuditLog,
    Case,
    ExtractionStatus,
    FormFillingField,
    FormFillingJob,
    IndexStatus,
    Page,
    PageStatus,
    QCChecklist,
    QCPart,
    QCQuestion,
)
from . import form_filling_jobs
from .case_document_scope_service import (
    get_case_scope_source_document_ids,
    load_case_pages_for_scope,
)
from .case_pipeline_lock import case_pipeline_lock
from ..utils.date_format import (
    LONG_DATE_EXAMPLE,
    LONG_DATE_FORMAT_HUMAN,
    format_long_date,
    parse_date_text,
)
from .case_extraction_service import extract_case_pages
from .embedding_service import get_embedding_batch
from .extraction_service import is_configured as is_ocr_configured
from .field_extraction_service import extract_field_value, extract_field_values_batch, paraphrase_reason_slot
from .form_filling_i914 import (
    apply_i914_family_answer_rules as _i914_apply_family_answer_rules,
    apply_i914_family_roster_override as _i914_apply_family_roster_override,
    apply_i914_forced_answer_rules as _i914_apply_forced_answer_rules,
    classify_family_block_role as _i914_classify_family_block_role,
    collect_i914_family_result_field_ids as _i914_collect_family_result_field_ids,
    collect_part5_evidence_text as _i914_collect_part5_evidence_text,
    i914_child_row_is_complete as _i914_helper_child_row_is_complete,
    i914_mapping_has_any_value as _i914_helper_mapping_has_any_value,
    i914_part9_row_has_content as _i914_helper_part9_row_has_content,
    i914_part9_row_key as _i914_helper_part9_row_key,
    normalize_i914_part9_row as _i914_normalize_part9_row,
    parse_i914_family_roster as _i914_parse_family_roster,
    postprocess_i914_family_roster as _i914_postprocess_family_roster,
    split_family_member_name as _i914_split_family_member_name,
    strip_i914_part9_header as _i914_strip_part9_header,
)
from .i914_event_taxonomy import (
    CATEGORY_TO_PART4_ITEMS as _I914_CATEGORY_TO_PART4_ITEMS,
    ClassifiedEvent as _I914ClassifiedEvent,
    EventCategory as _I914EventCategory,
    build_part4_table_rows as _i914_build_part4_table_rows,
    build_part9_text as _i914_build_part9_text,
    classify_evidence_events as _i914_classify_evidence_events,
    detect_category_conflicts as _i914_detect_category_conflicts,
    map_events_to_part4_items as _i914_map_events_to_part4_items,
    placeholder_event_for_item as _i914_placeholder_event_for_item,
)
from .form_type_matcher import (
    available_form_types,
    identify_form_type_from_pdf,
    list_questionnaire_field_definitions,
    map_pdf_fields_to_questionnaire_ids,
)
from .gemini_runtime_service import compact_token_summary, create_token_tracker, log_token_summary
from ..prompts.form_filling_prompts import (
    PRINCIPAL_APPLICANT_SEARCH_QUERY,
    build_applicant_context_instruction,
)
from .indexing_service import is_indexing_available
from .ocr_index_service import index_case_ocr_json
from .pdf_form_service import (
    detect_form_fields,
    draw_label_adjacent_text,
    fill_acroform_fields,
    fill_overlay_fields,
)
from .pdf_service import save_uploaded_file, split_pdf
from .paths import STORAGE_DIR
from .questionnaire_service import (
    get_answers as get_questionnaire_answers,
    get_form_attorney_questions,
    get_form_client_questions,
    get_form_template_path,
    get_shared_questions,
    save_verifications as save_questionnaire_verifications,
)
from .rag_config import get_rag_settings
from .retrieval_service import collect_evidence_bundle_for_question
from .state_resolution import (
    US_STATE_PATTERN as _US_STATE_PATTERN,
    infer_state_from_city as _shared_infer_state_from_city,
    infer_state_from_zip_code as _shared_infer_state_from_zip_code,
    normalize_us_state_code as _shared_normalize_us_state_code,
    resolve_us_state as _resolve_us_state,
)
from ..utils.text import clean_text as _clean_text

log = logging.getLogger("form_filling")
PREPARATION_PROGRESS_OCR_START_PCT = 0.0
PREPARATION_PROGRESS_OCR_COMPLETE_PCT = 50.0
PREPARATION_PROGRESS_INDEX_COMPLETE_PCT = 100.0

AutofillProgressCallback = Callable[[float, str], None]

_BACKGROUND_OCR_THRESHOLD = 20

_background_ocr_lock = Lock()
_background_ocr_running: dict[str, bool] = {}
_background_ocr_progress: dict[str, dict[str, int]] = {}
_EXTRACTION_CIRCUIT_BREAKER_MIN_ATTEMPTS = 10
_EXTRACTION_CIRCUIT_BREAKER_RATIO = 0.8


class OCRPreparationInProgress(RuntimeError):
    """Raised when OCR is running in the background and the caller should retry."""

    def __init__(self, missing_count: int, case_id: str):
        self.missing_count = missing_count
        self.case_id = case_id
        progress = _background_ocr_progress.get(case_id, {})
        self.total_pages = progress.get("total", missing_count)
        self.processed_pages = progress.get("processed", 0)
        super().__init__(
            f"OCR_PREPARING:{missing_count}"
        )


class ExtractionCircuitBreakerOpen(RuntimeError):
    """Raised when field extraction is failing systemically for a provider."""

    def __init__(
        self,
        *,
        exc_type: str,
        error_count: int,
        processed_count: int,
        total_targets: int,
        provider: str,
    ) -> None:
        self.exc_type = exc_type
        self.error_count = error_count
        self.processed_count = processed_count
        self.total_targets = total_targets
        self.provider = provider
        super().__init__(
            "Autofill aborted early: "
            f"{exc_type} in {error_count}/{processed_count} fields "
            f"(provider={provider}, total_targets={total_targets}). "
            "Likely provider outage, rate limit, or authentication failure."
        )


def _extraction_circuit_breaker_enabled() -> bool:
    value = (os.environ.get("EXTRACTION_CIRCUIT_BREAKER_ENABLED") or "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _truncate_log_value(value: Any, *, max_length: int = 200) -> str:
    text = _clean_text(value)
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3]}..."


def _dominant_extraction_error(
    error_breakdown: Mapping[str, int],
    processed_count: int,
) -> tuple[str, int] | None:
    if not _extraction_circuit_breaker_enabled():
        return None
    if processed_count < _EXTRACTION_CIRCUIT_BREAKER_MIN_ATTEMPTS:
        return None
    if not error_breakdown:
        return None

    exc_type, error_count = max(error_breakdown.items(), key=lambda item: item[1])
    if error_count < int(_EXTRACTION_CIRCUIT_BREAKER_MIN_ATTEMPTS * _EXTRACTION_CIRCUIT_BREAKER_RATIO):
        return None
    if (error_count / max(1, processed_count)) < _EXTRACTION_CIRCUIT_BREAKER_RATIO:
        return None
    return exc_type, error_count


def get_background_ocr_progress(case_id: str) -> dict[str, int] | None:
    """Return the live OCR progress snapshot for ``case_id`` if a background job
    is still active. Returns ``None`` when no background OCR is running, so
    callers can distinguish "still preparing" from "finished or never started".
    """
    with _background_ocr_lock:
        if not _background_ocr_running.get(case_id):
            return None
        snapshot = _background_ocr_progress.get(case_id)
        if not snapshot:
            return None
        return {
            "total": int(snapshot.get("total", 0) or 0),
            "processed": int(snapshot.get("processed", 0) or 0),
        }


def _launch_background_ocr_if_needed(
    case_id: str,
    *,
    page_ids: list[str] | None = None,
    missing_count: int = 0,
) -> None:
    if missing_count <= _BACKGROUND_OCR_THRESHOLD:
        with case_pipeline_lock(case_id, timeout=300):
            extract_case_pages(case_id, page_ids=page_ids, only_missing=True)
        return

    with _background_ocr_lock:
        if _background_ocr_running.get(case_id):
            raise OCRPreparationInProgress(missing_count, case_id)
        _background_ocr_running[case_id] = True
        _background_ocr_progress[case_id] = {"total": missing_count, "processed": 0}

    import threading

    def _ocr_progress_cb(payload: dict) -> None:
        processed = int(payload.get("ocr_processed_pages") or 0)
        total = int(payload.get("ocr_total_pages") or missing_count)
        _background_ocr_progress[case_id] = {"total": total, "processed": processed}

    def _run() -> None:
        try:
            log.info(
                "Background OCR started for case %s (%d pages)",
                case_id[:8],
                missing_count,
            )
            with case_pipeline_lock(case_id, timeout=300):
                extract_case_pages(
                    case_id,
                    page_ids=page_ids,
                    only_missing=True,
                    progress_callback=_ocr_progress_cb,
                )
            log.info("Background OCR finished for case %s", case_id[:8])
        except Exception:
            log.exception("Background OCR failed for case %s", case_id[:8])
        finally:
            with _background_ocr_lock:
                _background_ocr_running.pop(case_id, None)
                _background_ocr_progress.pop(case_id, None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    raise OCRPreparationInProgress(missing_count, case_id)


class ReviewRequiredError(ValueError):
    """Raised when a generated form must stop for manual review."""


@dataclass
class FormFillingExecutionState:
    preparation_result: dict[str, Any] = field(default_factory=dict)
    detection_result: dict[str, Any] = field(default_factory=dict)
    mapping_result: dict[str, Any] = field(default_factory=dict)
    pdf_fields_result: dict[str, Any] = field(default_factory=dict)
    write_result: dict[str, Any] = field(default_factory=dict)
    evidence_by_id: dict[str, Any] = field(default_factory=dict)
    extraction_error_count: int = 0
    imported_page_count: int = 0


def _i914_manual_review_bypass_enabled() -> bool:
    value = (os.environ.get("I914_BYPASS_MANUAL_REVIEW") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _normalize_hint_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return " ".join(text.lower().split())


def _normalize_value_token(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return " ".join(text.lower().split())


_A_NUMBER_DIGITS_RE = re.compile(r"^\d{1,9}$")
_US_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_ADDRESS_UNIT_RE = re.compile(
    r"(?i)\b(apartment|apt|suite|ste|floor|flr)\.?\s*#?\s*([A-Za-z0-9-]+)\b"
)
_PHONE_NUMBER_RE = re.compile(r"^(?:\+?1[\s().-]*)?(?:\d[\s().-]*){10}$")
_TEXTUAL_DATE_VALUE_PATTERN = (
    r"(?:"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{4}"
    r"|"
    r"\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}"
    r"|"
    r"\d{4}[\/\-.]\d{1,2}[\/\-.]\d{1,2}"
    r"|"
    r"\d{1,2}\s+[A-Za-zÁÉÍÓÚÜáéíóúü]{3,12}\s+\d{2,4}"
    r"|"
    r"[A-Za-zÁÉÍÓÚÜáéíóúü]{3,12}\s+\d{1,2},?\s+\d{2,4}"
    r")"
)
_IMMIGRATION_STATUS_CODE_RE = re.compile(r"(?i)\b[A-Z]{1,3}\s*[-/]?\s*\d[A-Z]?\b")
_FIELD_IDENTITY_STOPWORDS = {
    "a",
    "and",
    "application",
    "enter",
    "field",
    "for",
    "form",
    "if",
    "in",
    "item",
    "name",
    "number",
    "of",
    "or",
    "part",
    "question",
    "section",
    "select",
    "shared",
    "the",
    "this",
    "to",
    "your",
}
_ADDRESS_COMPONENT_FIELDS = {
    "in_care_of_name",
    "street_number_name",
    "unit_type",
    "unit_number",
    "city",
    "state",
    "zip_code",
    "province",
    "postal_code",
    "country",
}
_CANONICAL_VALUE_ALIASES = {
    "si": "yes",
    "yes": "yes",
    "no": "no",
    "male": "male",
    "masculino": "male",
    "hombre": "male",
    "female": "female",
    "femenino": "female",
    "mujer": "female",
    "single": "single",
    "single never married": "single",
    "soltero": "single",
    "soltera": "single",
    "soltero nunca casado": "single",
    "soltera nunca casada": "single",
    "married": "married",
    "casado": "married",
    "casada": "married",
    "divorced": "divorced",
    "divorciado": "divorced",
    "divorciada": "divorced",
    "widowed": "widowed",
    "viudo": "widowed",
    "viuda": "widowed",
    "annulled": "annulled",
    "anulado": "annulled",
    "anulada": "annulled",
    "separated": "separated",
    "separado": "separated",
    "separada": "separated",
    "united states": "united states",
    "american": "united states",
    "americana": "united states",
    "estadounidense": "united states",
    "ee uu": "united states",
    "eeuu": "united states",
    "estados unidos": "united states",
    "usa": "united states",
    "u s a": "united states",
    "u s": "united states",
    "mexican": "mexico",
    "mexicano": "mexico",
    "mexicana": "mexico",
    "guatemalan": "guatemala",
    "guatemalteco": "guatemala",
    "guatemalteca": "guatemala",
    "honduran": "honduras",
    "hondureno": "honduras",
    "hondurena": "honduras",
    "salvadoran": "el salvador",
    "salvadoreno": "el salvador",
    "salvadorena": "el salvador",
    "nicaraguan": "nicaragua",
    "nicaraguense": "nicaragua",
    "costa rican": "costa rica",
    "costarricense": "costa rica",
    "panamanian": "panama",
    "panameno": "panama",
    "panamena": "panama",
    "colombian": "colombia",
    "colombiano": "colombia",
    "colombiana": "colombia",
    "venezuelan": "venezuela",
    "venezolano": "venezuela",
    "venezolana": "venezuela",
    "ecuadorian": "ecuador",
    "ecuatoriano": "ecuador",
    "ecuatoriana": "ecuador",
    "peruvian": "peru",
    "peruano": "peru",
    "peruana": "peru",
    "bolivian": "bolivia",
    "boliviano": "bolivia",
    "boliviana": "bolivia",
    "chilean": "chile",
    "chileno": "chile",
    "chilena": "chile",
    "argentine": "argentina",
    "argentinian": "argentina",
    "argentino": "argentina",
    "argentina": "argentina",
    "paraguayan": "paraguay",
    "paraguayo": "paraguay",
    "paraguaya": "paraguay",
    "uruguayan": "uruguay",
    "uruguayo": "uruguay",
    "uruguaya": "uruguay",
    "brazilian": "brazil",
    "brasileno": "brazil",
    "brasilena": "brazil",
    "canadian": "canada",
    "canadiense": "canada",
    "spanish": "spain",
    "espanol": "spain",
    "espanola": "spain",
    "german": "germany",
    "aleman": "germany",
    "alemana": "germany",
    "italian": "italy",
    "italiano": "italy",
    "italiana": "italy",
    "french": "france",
    "frances": "france",
    "british": "united kingdom",
    "uk": "united kingdom",
    "u k": "united kingdom",
    "dominican": "dominican republic",
    "dominicano": "dominican republic",
    "dominicana": "dominican republic",
    "dutch": "netherlands",
    "holandes": "netherlands",
    "holandesa": "netherlands",
    "swiss": "switzerland",
    "suizo": "switzerland",
    "suiza": "switzerland",
    "turkish": "turkey",
    "turco": "turkey",
    "turca": "turkey",
    "greek": "greece",
    "griego": "greece",
    "griega": "greece",
    "japanese": "japan",
    "japones": "japan",
    "japonesa": "japan",
    "chinese": "china",
    "chino": "china",
    "china": "china",
    "sin papeles": "no legal status",
    "indocumentado": "no legal status",
    "indocumentada": "no legal status",
    "undocumented": "no legal status",
    "out of status": "no legal status",
    "no legal status": "no legal status",
    "sin estatus": "no legal status",
    "sin estatus legal": "no legal status",
    "sin estatus migratorio": "no legal status",
    "sin estado migratorio": "no legal status",
    "sin estado legal": "no legal status",
    "no tengo estatus": "no legal status",
    "ningun estatus": "no legal status",
    "ninguno": "no legal status",
}
_CANONICAL_VALUE_DISPLAY = {
    "yes": "Yes",
    "no": "No",
    "male": "Male",
    "female": "Female",
    "single": "Single",
    "married": "Married",
    "divorced": "Divorced",
    "widowed": "Widowed",
    "annulled": "Annulled",
    "separated": "Separated",
    "united states": "United States",
    "no legal status": "No Legal Status",
}
_COUNTRY_NAME_DISPLAY = {
    "united states": "United States",
    "mexico": "Mexico",
    "guatemala": "Guatemala",
    "honduras": "Honduras",
    "el salvador": "El Salvador",
    "nicaragua": "Nicaragua",
    "costa rica": "Costa Rica",
    "panama": "Panama",
    "colombia": "Colombia",
    "venezuela": "Venezuela",
    "ecuador": "Ecuador",
    "peru": "Peru",
    "bolivia": "Bolivia",
    "chile": "Chile",
    "argentina": "Argentina",
    "paraguay": "Paraguay",
    "uruguay": "Uruguay",
    "brasil": "Brazil",
    "brazil": "Brazil",
    "canada": "Canada",
    "espana": "Spain",
    "spain": "Spain",
    "alemania": "Germany",
    "germany": "Germany",
    "italia": "Italy",
    "italy": "Italy",
    "francia": "France",
    "france": "France",
    "reino unido": "United Kingdom",
    "united kingdom": "United Kingdom",
    "republica dominicana": "Dominican Republic",
    "dominican republic": "Dominican Republic",
    "paises bajos": "Netherlands",
    "netherlands": "Netherlands",
    "suiza": "Switzerland",
    "switzerland": "Switzerland",
    "turquia": "Turkey",
    "turkey": "Turkey",
    "grecia": "Greece",
    "greece": "Greece",
    "japon": "Japan",
    "japan": "Japan",
    "china": "China",
}
_MONTH_NAME_TO_NUMBER = {
    "jan": 1,
    "january": 1,
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "february": 2,
    "febrero": 2,
    "mar": 3,
    "march": 3,
    "marzo": 3,
    "apr": 4,
    "april": 4,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "june": 6,
    "junio": 6,
    "jul": 7,
    "july": 7,
    "julio": 7,
    "aug": 8,
    "august": 8,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "septiembre": 9,
    "oct": 10,
    "october": 10,
    "octubre": 10,
    "nov": 11,
    "november": 11,
    "noviembre": 11,
    "dec": 12,
    "december": 12,
    "dic": 12,
    "diciembre": 12,
}


def _normalize_identifier_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean_text(value).lower())


def _normalize_a_number_value(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    compact = re.sub(r"[^\dA-Za-z]", "", text.upper())
    if compact.startswith("A"):
        compact = compact[1:]
    digits_only = re.sub(r"[^0-9]", "", compact)
    return digits_only if _A_NUMBER_DIGITS_RE.fullmatch(digits_only) else ""


def _propagate_shared_a_number_to_p2_5(answers: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure ``p2_5`` contains a valid A-Number if one exists in shared identifiers.

    The PDF field ``Part2_Line5_AlienRegistrationNumber`` resolves primarily
    via ``p2_5``.  During autofill the AI sometimes writes the value only to
    ``shared.identifiers.a_number`` (or writes a non-numeric string to
    ``p2_5``).  This helper copies the shared value into ``p2_5`` when the
    latter is missing or invalid so that both the Part 2 and Part 9 header
    fields are populated in the generated PDF.
    """
    result = dict(answers)
    current_p2_5 = _normalize_a_number_value(result.get("p2_5"))
    if current_p2_5:
        return result

    shared_identifiers = result.get("shared.identifiers")
    if not isinstance(shared_identifiers, dict):
        return result

    shared_a = _normalize_a_number_value(shared_identifiers.get("a_number"))
    if shared_a:
        result["p2_5"] = shared_a
        log.debug(
            "Propagated shared.identifiers.a_number (%s) -> p2_5",
            shared_a,
        )
    return result


_I914_APPLICANT_NAME_FIELDS = ("family_name", "given_name", "middle_name")


def _propagate_shared_name_to_p2_1(answers: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure ``p2_1`` contains the applicant's legal name from ``shared.name``.

    The PDF fields ``Part1_FamilyName`` / ``Part1_GivenName`` / ``Part1_MiddleName``
    on page 1 and their mirrors on Part 9 (page 12) resolve via
    ``p2_1.{family,given,middle}_name``.  During autofill the extractor often
    populates only ``shared.name``; this helper copies any missing sub-field
    from ``shared.name`` into ``p2_1`` so the applicant's name appears in both
    locations without duplicating the data-entry step.
    """
    result = dict(answers)
    shared_name = result.get("shared.name")
    if not isinstance(shared_name, Mapping):
        return result

    current = result.get("p2_1")
    if isinstance(current, Mapping):
        merged = dict(current)
    elif current in (None, ""):
        merged = {}
    else:
        return result

    changed = False
    for field_id in _I914_APPLICANT_NAME_FIELDS:
        if _clean_text(merged.get(field_id)):
            continue
        shared_value = _clean_text(shared_name.get(field_id))
        if shared_value:
            merged[field_id] = shared_value
            changed = True

    if changed:
        result["p2_1"] = merged
        log.debug(
            "Propagated shared.name -> p2_1 (family=%r given=%r middle=%r)",
            merged.get("family_name"),
            merged.get("given_name"),
            merged.get("middle_name"),
        )
    return result


def _normalize_address_unit_type(value: Any) -> str:
    token = _normalize_identifier_token(value)
    if token in {"apt", "apartment"}:
        return "Apt."
    if token in {"ste", "suite"}:
        return "Ste."
    if token in {"flr", "floor"}:
        return "Flr."
    return ""


def _normalize_us_state_code(value: Any) -> str:
    return _shared_normalize_us_state_code(value)


def _infer_state_from_city(city: Any) -> str:
    return _shared_infer_state_from_city(city)


def _normalize_date_text(value: Any) -> str:
    """Normalize a free-form date string into the canonical ``Mmm DD YYYY`` form."""
    parsed = parse_date_text(value)
    if parsed is None:
        return ""
    return format_long_date(parsed)


def _extract_plain_text_from_evidence(evidence: Any) -> str:
    parts: list[str] = []

    def add(value: Any) -> None:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)

    if isinstance(evidence, Mapping):
        for item in evidence.get("evidence", []) or []:
            if isinstance(item, Mapping):
                add(item.get("text"))
        add(evidence.get("text_context") or evidence.get("textContext"))
        for match in evidence.get("matches", []) or []:
            if not isinstance(match, Mapping):
                continue
            metadata = match.get("metadata", {}) or {}
            if isinstance(metadata, Mapping):
                add(metadata.get("text") or metadata.get("explanation"))
        return "\n".join(parts)

    if isinstance(evidence, Iterable) and not isinstance(evidence, (str, bytes, dict)):
        for item in evidence:
            if isinstance(item, Mapping):
                add(item.get("text"))
            else:
                add(item)
        return "\n".join(parts)

    add(evidence)
    return "\n".join(parts)


def _extract_labeled_date_from_text(text: Any, labels: Iterable[str]) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    for label in labels:
        match = re.search(
            rf"(?i){label}[^0-9A-Za-z]{{0,24}}(?P<date>{_TEXTUAL_DATE_VALUE_PATTERN})",
            cleaned,
        )
        if not match:
            continue
        normalized = _normalize_date_text(match.group("date"))
        if normalized:
            return normalized
    return ""


def _looks_like_question_answer_dump(text: Any) -> bool:
    cleaned = _clean_text(text)
    if not cleaned:
        return False
    question_count = len(re.findall(r"(?i)\b(?:pregunta|question)\s*:", cleaned))
    answer_count = len(re.findall(r"(?i)\b(?:respuesta|answer)\s*:", cleaned))
    return question_count >= 2 or answer_count >= 2


def _extract_labeled_answer_from_text(text: Any, labels: Iterable[str]) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    for label in labels:
        match = re.search(
            rf"(?i){label}.*?(?:respuesta|answer)\s*:\s*(?P<value>.*?)(?=\b(?:pregunta|question)\s*:|$)",
            cleaned,
        )
        if not match:
            continue
        value = _clean_address_candidate_text(match.group("value"))
        if value:
            return value
    return ""


def _extract_a_number_from_text(text: Any) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    labeled = re.search(
        r"(?i)(?:alien registration number|a[- ]?number)[^0-9A-Za-z]{0,20}A?[-\s#:]*([0-9]{7,9})",
        cleaned,
    )
    if labeled:
        return labeled.group(1)
    standalone = re.search(r"(?i)\bA[-\s#:]*([0-9]{7,9})\b", cleaned)
    return standalone.group(1) if standalone else ""


def _normalized_target_context(target: Mapping[str, Any]) -> str:
    return _normalize_hint_text(
        " ".join(
            str(part or "")
            for part in (
                target.get("id"),
                target.get("field_name"),
                target.get("field_label"),
                target.get("questionnaire_item_id"),
                target.get("questionnaire_field_id"),
                target.get("questionnaire_label"),
                target.get("questionnaire_form_text"),
                target.get("questionnaire_section"),
            )
        )
    )


def _normalized_target_identity_context(target: Mapping[str, Any]) -> str:
    return _normalize_hint_text(
        " ".join(
            str(part or "")
            for part in (
                target.get("questionnaire_item_id"),
                target.get("questionnaire_field_id") or target.get("answer_field_id"),
                target.get("questionnaire_label") or target.get("field_label"),
                target.get("questionnaire_form_text"),
                target.get("questionnaire_section"),
            )
        )
    )


def _looks_like_a_number_target(target: Mapping[str, Any]) -> bool:
    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id")).lower()
    if field_id == "a_number":
        return True
    if field_id:
        return False
    context = _normalized_target_context(target)
    return "alien registration number" in context or "a number" in context


def _is_manual_lea_unit_target(target: Mapping[str, Any]) -> bool:
    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id")).lower()
    if field_id == "lea_unit_number":
        return True
    pdf_field_name = _clean_text(target.get("field_name")).lower()
    if "p3_line5_aptsteflrnumber" in pdf_field_name:
        return True
    if "p3_line5_number" in pdf_field_name or "p3_line5_unit_number" in pdf_field_name:
        nearby = _normalized_target_context(target)
        if "law enforcement" in nearby or "agency and office" in nearby:
            return True
    if (
        field_id == "lea_agency_office"
        and pdf_field_name
        and re.search(r"p3[_.]line5.*number", pdf_field_name)
    ):
        return True
    return False


def _looks_like_country_target(target: Mapping[str, Any]) -> bool:
    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id")).lower()
    if field_id == "country" or field_id.endswith("_country") or "country" in field_id:
        return True
    identity_context = _normalized_target_identity_context(target)
    if "country" in identity_context:
        return True
    return any(
        term in identity_context
        for term in (
            "citizenship or nationality",
            "country of citizenship",
            "country of nationality",
            "issuing country",
            "nationality",
        )
    )


def _looks_like_nonimmigrant_status(target: Mapping[str, Any]) -> bool:
    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id")).lower()
    if field_id in {"current_nonimmigrant_status", "current_immigration_status", "prior_entry_status"}:
        return True
    context = _normalized_target_context(target)
    if "marital status" in context:
        return False
    return (
        "current nonimmigrant status" in context
        or "current immigration status" in context
        or "prior entry status" in context
        or ("immigration status" in context and "current" in context)
    )


def _looks_like_city_target(target: Mapping[str, Any]) -> bool:
    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id")).lower()
    if field_id and "city" in field_id:
        return True
    context = _normalized_target_context(target)
    return any(
        term in context
        for term in ("city or town", "city town", "city of birth", "birth city")
    )


def _looks_like_case_number_target(target: Mapping[str, Any]) -> bool:
    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id")).lower()
    if field_id == "case_number" or field_id.endswith("_case_number"):
        return True
    context = _normalized_target_context(target)
    return "case number" in context or "case no" in context


def _looks_like_date_target(target: Mapping[str, Any]) -> bool:
    field_type = _clean_text(target.get("field_type") or target.get("questionnaire_item_type")).lower()
    if field_type == "date":
        return True
    if field_type in {"text", "textarea", "number"}:
        return False
    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id")).lower()
    if field_id and "date" in field_id:
        return True
    context = _normalized_target_context(target)
    return " date " in f" {context} "


def _is_safe_mailing_target(target: Mapping[str, Any]) -> bool:
    context = _normalized_target_context(target)
    return "safe mailing address" in context or ("mailing address" in context and "safe" in context)


def _is_current_physical_address_target(target: Mapping[str, Any]) -> bool:
    context = _normalized_target_context(target)
    if any(term in context for term in ("address history", "law enforcement", "employer", "mailing address", "safe mailing address")):
        return False
    return "current physical address" in context or "physical address" in context or "current address" in context


def _logical_address_field_id(target: Mapping[str, Any]) -> str:
    field_id = _normalize_address_field_id(
        target.get("answer_field_id") or target.get("questionnaire_field_id")
    )
    if field_id == "in_care_of_name":
        return ""
    if field_id in _ADDRESS_COMPONENT_FIELDS:
        return field_id
    return ""


_NAME_FIELD_IDS = {"family_name", "given_name", "middle_name"}
_NAME_VARIANT_EXCLUSIONS = ("other name", "other names used", "alias", "nickname", "maiden")
_NAME_CONTEXT_ROLES = (
    ("law enforcement", "law_enforcement"),
    ("interpreter", "interpreter"),
    ("preparer", "preparer"),
    ("attorney", "attorney"),
    ("spouse", "spouse"),
    ("child", "child"),
    ("parent", "parent"),
    ("beneficiary", "beneficiary"),
)
_BLANK_NAME_VALUES = {"", "[ ]", "(vacio)", "n/a", "none"}
_INDEXED_SLOT_RE = re.compile(r"\[(\d+)\]")


def _is_blank_name_value(value: Any) -> bool:
    cleaned = _clean_text(value)
    return not cleaned or cleaned.lower() in _BLANK_NAME_VALUES


def _normalized_name_field_id(target: Mapping[str, Any]) -> str:
    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id")).lower()
    if field_id.startswith("other_"):
        field_id = field_id[6:]

    context = _normalized_target_context(target)
    if any(term in context for term in _NAME_VARIANT_EXCLUSIONS):
        return ""
    if field_id in _NAME_FIELD_IDS:
        return field_id
    if "family name" in context or "last name" in context:
        return "family_name"
    if "given name" in context or "first name" in context:
        return "given_name"
    if "middle name" in context:
        return "middle_name"
    return ""


def _name_context_role(target: Mapping[str, Any]) -> str:
    context = _normalized_target_context(target)
    for needle, label in _NAME_CONTEXT_ROLES:
        if needle in context:
            return label
    return "applicant"


def _name_result_group_key(target: Mapping[str, Any]) -> str:
    if not _normalized_name_field_id(target):
        return ""
    page_number = str(_safe_int(target.get("page_number")))
    item_id = _clean_text(target.get("questionnaire_item_id") or target.get("question_id"))
    slot_index = _infer_target_repeatable_slot_index(target)
    slot_suffix = f"[{slot_index}]" if slot_index is not None else ""
    section = _clean_text(target.get("questionnaire_section") or target.get("section"))
    responsible_party = _clean_text(
        target.get("questionnaire_responsible_party") or target.get("responsible_party") or "client"
    )
    role = _name_context_role(target)
    if item_id:
        return "|".join((f"{item_id}{slot_suffix}", page_number, section, responsible_party, role))
    return "|".join((page_number, section, responsible_party, role))


def _infer_target_repeatable_slot_index(target: Mapping[str, Any]) -> int | None:
    explicit_slot = target.get("repeatable_slot_index")
    if explicit_slot is not None:
        explicit_int = _safe_int(explicit_slot)
        if explicit_int is not None and explicit_int >= 0:
            return explicit_int

    for candidate in (
        target.get("id"),
        target.get("field_name"),
        target.get("canonical_questionnaire_id"),
    ):
        text = _clean_text(candidate)
        if not text:
            continue
        matches = _INDEXED_SLOT_RE.findall(text)
        if matches:
            parsed = _safe_int(matches[-1])
            if parsed is not None and parsed >= 0:
                return parsed

    question_id = _clean_text(target.get("questionnaire_item_id") or target.get("question_id"))
    if question_id.startswith("p5_children"):
        occurrence = _safe_int(target.get("occurrence_index"))
        if occurrence is not None and occurrence >= 0:
            return occurrence

    return None


def _split_compound_given_name(
    given_name: Any,
    middle_name: Any,
    family_name: Any,
) -> tuple[str, str] | None:
    given_clean = _clean_text(given_name)
    family_clean = _clean_text(family_name)
    if _is_blank_name_value(given_clean) or _is_blank_name_value(family_clean):
        return None
    if not _is_blank_name_value(middle_name):
        return None

    given_tokens = given_clean.split()
    family_tokens = family_clean.split()
    if len(given_tokens) != 2 or len(family_tokens) != 2:
        return None
    return given_tokens[0], given_tokens[1]


def _postprocess_compound_name_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
) -> None:
    grouped_field_ids: dict[str, dict[str, str]] = {}
    for target in targets:
        name_field_id = _normalized_name_field_id(target)
        if not name_field_id:
            continue
        result_field_id = _clean_text(target.get("id") or target.get("field_name"))
        if not result_field_id or result_field_id not in results_by_id:
            continue
        group_key = _name_result_group_key(target)
        if not group_key:
            continue
        grouped_field_ids.setdefault(group_key, {})[name_field_id] = result_field_id

    for field_ids in grouped_field_ids.values():
        given_field_id = field_ids.get("given_name")
        middle_field_id = field_ids.get("middle_name")
        family_field_id = field_ids.get("family_name")
        if not given_field_id or not middle_field_id or not family_field_id:
            continue

        given_result = results_by_id.get(given_field_id) or {}
        middle_result = results_by_id.get(middle_field_id) or {}
        family_result = results_by_id.get(family_field_id) or {}
        split_name = _split_compound_given_name(
            given_result.get("value"),
            middle_result.get("value"),
            family_result.get("value"),
        )
        if not split_name:
            continue

        first_name, second_name = split_name
        confidence = _clean_text(given_result.get("confidence")).lower()
        if confidence not in _CONFIDENCE_RANK:
            confidence = "medium"
        justification = (
            "Split a combined given name into First Name and Middle Name "
            "because the name block matched a two-name, two-surname pattern."
        )
        _set_result_value(
            results_by_id,
            given_field_id,
            first_name,
            confidence=confidence,
            justification=justification,
        )
        _set_result_value(
            results_by_id,
            middle_field_id,
            second_name,
            confidence=confidence,
            justification=justification,
        )


def _clean_address_candidate_text(value: Any) -> str:
    text = _clean_text(value)
    if ":" in text:
        text = text.split(":", 1)[1]
    return text.strip(" ,.")


def _address_label_patterns_for_target(target: Mapping[str, Any]) -> tuple[str, ...]:
    if _is_safe_mailing_target(target):
        return (
            r"safe mailing address",
            r"alternate safe mailing address",
            r"u\.?\s*s\.?\s*mailing address",
            r"mailing address",
            r"direcci[oó]n postal segura",
            r"direcci[oó]n postal",
            r"direcci[oó]n para recibir correo",
        )
    if _is_current_physical_address_target(target):
        return (
            r"current physical address",
            r"physical address",
            r"current address",
            r"home address",
            r"direcci[oó]n actual",
            r"domicilio actual",
        )
    return ()


def _extract_address_candidate_for_target(target: Mapping[str, Any], text: Any) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    if _looks_like_question_answer_dump(cleaned):
        return _extract_labeled_answer_from_text(cleaned, _address_label_patterns_for_target(target))
    return _clean_address_candidate_text(cleaned)


def _parse_address_components_from_text(value: Any) -> dict[str, str]:
    text = _clean_address_candidate_text(value)
    if not text:
        return {}

    zip_match = _US_ZIP_RE.search(text)
    zip_code = zip_match.group(0) if zip_match else ""
    before_zip = text[:zip_match.start()].strip(" ,.") if zip_match else text

    state = ""
    before_state = before_zip
    if before_zip:
        state_match = re.search(rf"(?i)(?:^|[,\s])(?P<state>{_US_STATE_PATTERN})[.\s,]*$", before_zip)
        if state_match:
            state = _normalize_us_state_code(state_match.group("state"))
            before_state = before_zip[:state_match.start("state")].strip(" ,.")

    unit_type = ""
    unit_number = ""
    street = before_state
    city = ""

    unit_match = _ADDRESS_UNIT_RE.search(before_state)
    if unit_match:
        unit_type = _normalize_address_unit_type(unit_match.group(1))
        unit_number = _clean_text(unit_match.group(2)).strip(" ,.")
        street = before_state[:unit_match.start()].strip(" ,.")
        city = before_state[unit_match.end():].strip(" ,.")

    if not city:
        split_match = re.search(r"(?P<street>.+?)[,\.]\s*(?P<city>[A-Za-z][A-Za-z .'-]+)$", before_state)
        if split_match:
            candidate_street = split_match.group("street").strip(" ,.")
            candidate_city = split_match.group("city").strip(" ,.")
            normalized_candidate_city = _normalize_hint_text(candidate_city)
            looks_like_entity_fragment = any(
                token in normalized_candidate_city
                for token in (
                    "department",
                    "justice",
                    "office",
                    "offices",
                    "prosecution",
                    "unit",
                    "submission",
                )
            )
            if not (not state and not zip_code and looks_like_entity_fragment):
                street = candidate_street
                city = candidate_city

    street_unit_match = _ADDRESS_UNIT_RE.search(street)
    if street_unit_match:
        unit_type = unit_type or _normalize_address_unit_type(street_unit_match.group(1))
        unit_number = unit_number or _clean_text(street_unit_match.group(2)).strip(" ,.")
        street = street[:street_unit_match.start()].strip(" ,.")

    parsed = {
        "street_number_name": street,
        "unit_type": unit_type,
        "unit_number": unit_number,
        "city": city,
        "state": state,
        "zip_code": zip_code,
    }
    return {key: value for key, value in parsed.items() if value}


def _looks_like_composite_address_text(value: Any) -> bool:
    parsed = _parse_address_components_from_text(value)
    return bool(parsed.get("city") or parsed.get("state") or parsed.get("zip_code") or parsed.get("unit_type"))


def _group_targets_by_question_id(targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        question_id = _clean_text(target.get("question_id"))
        if question_id:
            grouped.setdefault(question_id, []).append(target)
    return grouped


def _address_target_group_key(target: Mapping[str, Any]) -> str:
    question_id = _clean_text(target.get("question_id"))
    if not question_id:
        return ""

    field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id"))
    occurrence_index = _safe_int(target.get("occurrence_index"))
    if question_id == "p3_8" and field_id.startswith("prior_entry_") and occurrence_index is not None:
        return f"{question_id}[{occurrence_index}]"
    return question_id


def _group_address_targets(targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    occurrence_by_field: dict[tuple[str, str], int] = {}

    for target in targets:
        group_key = _address_target_group_key(target)
        if not group_key:
            continue

        if group_key == _clean_text(target.get("question_id")):
            question_id = _clean_text(target.get("question_id"))
            field_id = _clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id"))
            if question_id == "p3_8" and field_id.startswith("prior_entry_"):
                occurrence_key = (question_id, field_id)
                occurrence_index = occurrence_by_field.get(occurrence_key, 0)
                occurrence_by_field[occurrence_key] = occurrence_index + 1
                group_key = f"{question_id}[{occurrence_index}]"

        grouped.setdefault(group_key, []).append(target)

    return grouped


def _set_result_value(
    results_by_id: dict[str, dict[str, str]],
    field_id: str,
    value: str,
    *,
    confidence: str = "medium",
    justification: str = "",
) -> None:
    existing = dict(results_by_id.get(field_id) or {})
    cleaned_value = _clean_text(value)
    existing["id"] = field_id
    existing["value"] = cleaned_value
    existing_confidence = _clean_text(existing.get("confidence")).lower() or "low"
    if not cleaned_value or _CONFIDENCE_RANK.get(confidence, 0) >= _CONFIDENCE_RANK.get(existing_confidence, 0):
        existing["confidence"] = confidence
    else:
        existing["confidence"] = existing_confidence
    existing["justification"] = _merge_result_justifications(existing, justification)
    results_by_id[field_id] = existing


def _merge_result_justifications(existing: Mapping[str, Any], justification: str) -> str:
    existing_justification = _clean_text(existing.get("justification"))
    justifications = [part for part in (existing_justification, _clean_text(justification)) if part]
    return " ".join(dict.fromkeys(justifications))


def _flag_result_for_review(
    results_by_id: dict[str, dict[str, str]],
    field_id: str,
    *,
    justification: str,
    value: Any | None = None,
) -> None:
    existing = dict(results_by_id.get(field_id) or {})
    existing["id"] = field_id
    existing["value"] = (
        _clean_text(existing.get("value"))
        if value is None
        else _clean_text(value)
    )
    existing["confidence"] = "low"
    existing["justification"] = _merge_result_justifications(existing, justification)
    results_by_id[field_id] = existing


from .form_registry import normalize_form_type as _normalize_form_type  # noqa: E402,F401


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_clean_list(values: Any) -> list[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes, dict)):
        return []
    items: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return items


def _chunked(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    batch_size = max(1, int(size or 1))
    for start in range(0, len(items), batch_size):
        yield items[start:start + batch_size]


def _apply_runtime_payload(job: FormFillingJob, runtime_payload: Mapping[str, Any] | None) -> None:
    if not runtime_payload:
        return
    if runtime_payload.get("form_type"):
        job.form_type = _clean_text(runtime_payload.get("form_type"))
    if "status" in runtime_payload:
        job.status = _clean_text(runtime_payload.get("status")) or job.status
    if "phase" in runtime_payload:
        job.phase = _clean_text(runtime_payload.get("phase")) or job.phase
    if "progress_pct" in runtime_payload:
        try:
            job.progress_pct = float(runtime_payload.get("progress_pct") or 0.0)
        except (TypeError, ValueError):
            pass
    if "original_pdf_path" in runtime_payload and runtime_payload.get("original_pdf_path") is not None:
        job.original_pdf_path = str(runtime_payload.get("original_pdf_path") or "")
    if "filled_pdf_path" in runtime_payload and runtime_payload.get("filled_pdf_path") is not None:
        job.filled_pdf_path = str(runtime_payload.get("filled_pdf_path") or "")
    if "field_count" in runtime_payload:
        job.field_count = int(runtime_payload.get("field_count") or 0)
    if "filled_count" in runtime_payload:
        job.filled_count = int(runtime_payload.get("filled_count") or 0)
    job.error_message = (
        _clean_text(runtime_payload.get("error_message"))
        if runtime_payload.get("error_message") is not None
        else job.error_message
    )
    if runtime_payload.get("started_at") is not None:
        job.started_at = runtime_payload.get("started_at")
    if runtime_payload.get("completed_at") is not None:
        job.completed_at = runtime_payload.get("completed_at")


def _persist_job_state(db: Session, job: FormFillingJob, runtime_payload: Mapping[str, Any] | None = None) -> None:
    _apply_runtime_payload(job, runtime_payload)
    db.add(job)
    db.commit()


_LOW_COVERAGE_WARNING_CODE = "low_document_ai_coverage"


def _record_job_warning(
    db: Session,
    job: FormFillingJob,
    *,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Append a structured warning to `job.warnings`, deduped by `code`.

    Warnings are advisory signals visible to operators (e.g. low Document AI
    coverage) and never fail the job. Each entry is `{"code", "message",
    "details"}`. We keep the latest entry for any given code.
    """
    current = list(job.warnings or [])
    current = [entry for entry in current if (entry or {}).get("code") != code]
    current.append(
        {
            "code": code,
            "message": message,
            "details": dict(details or {}),
        }
    )
    job.warnings = current
    db.add(job)
    db.commit()


def _record_low_coverage_warning_if_needed(
    db: Session,
    job: FormFillingJob,
    mapping_result: Mapping[str, Any] | None,
) -> None:
    if not mapping_result or not mapping_result.get("low_coverage_warning"):
        return

    coverage_ratio = float(mapping_result.get("coverage_ratio") or 0.0)
    expected_items = int(mapping_result.get("expected_item_count") or 0)
    matched_items = int(mapping_result.get("matched_item_count") or 0)
    message = (
        f"Document AI matched only {matched_items}/{expected_items} questionnaire "
        f"items ({coverage_ratio:.0%}). The PDF may be a scan or non-standard "
        "version; review the filled form carefully."
    )
    _record_job_warning(
        db,
        job,
        code=_LOW_COVERAGE_WARNING_CODE,
        message=message,
        details={
            "coverage_ratio": coverage_ratio,
            "matched_item_count": matched_items,
            "expected_item_count": expected_items,
            "form_type": mapping_result.get("form_type"),
        },
    )


def _ensure_runtime_job(job: FormFillingJob) -> dict:
    existing = form_filling_jobs.get_job(job.id)
    if existing:
        return existing
    return form_filling_jobs.create_job(
        case_id=job.case_id,
        original_pdf_path=job.original_pdf_path or "",
        form_type=job.form_type,
        field_count=job.field_count or 0,
        job_id=job.id,
    )


def overlay_runtime_status(job: FormFillingJob | None) -> FormFillingJob | None:
    """Overlay in-memory runtime status on top of the persisted job ORM instance."""
    if job is None:
        return None
    runtime_payload = form_filling_jobs.get_job(job.id)
    _apply_runtime_payload(job, runtime_payload)
    return job


def create_job(
    db: Session,
    *,
    case_id: str,
    original_pdf_path: str,
    form_type: str | None = None,
) -> FormFillingJob:
    """Create the persisted DB job and mirror it into the runtime store."""
    job = FormFillingJob(
        case_id=case_id,
        form_type=_normalize_form_type(form_type),
        status="queued",
        phase="queued",
        progress_pct=0.0,
        original_pdf_path=original_pdf_path,
        filled_pdf_path="",
        field_count=0,
        filled_count=0,
        error_message=None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    runtime_payload = form_filling_jobs.create_job(
        case_id=case_id,
        original_pdf_path=original_pdf_path,
        form_type=job.form_type,
        field_count=0,
        job_id=job.id,
    )
    _apply_runtime_payload(job, runtime_payload)
    return job


def get_job(db: Session, job_id: str) -> FormFillingJob | None:
    job = db.query(FormFillingJob).filter(FormFillingJob.id == job_id).first()
    return overlay_runtime_status(job)


def list_jobs(db: Session, case_id: str) -> list[FormFillingJob]:
    jobs = (
        db.query(FormFillingJob)
        .filter(FormFillingJob.case_id == case_id)
        .order_by(FormFillingJob.created_at.desc())
        .all()
    )
    return [overlay_runtime_status(job) or job for job in jobs]


def delete_job(db: Session, job_id: str) -> None:
    job = db.query(FormFillingJob).filter(FormFillingJob.id == job_id).first()
    if not job:
        return
    db.query(FormFillingField).filter(FormFillingField.job_id == job_id).delete(synchronize_session=False)
    db.delete(job)
    db.commit()
    form_filling_jobs.delete_job(job_id)


def _form_label_for_filename(form_type: str | None) -> str:
    normalized = _normalize_form_type(form_type)
    if normalized:
        return normalized.upper()
    fallback = _clean_text(form_type).upper()
    return fallback or "FORM"


def _clean_filename_text(value: Any, *, safe: bool) -> str:
    normalized = unicodedata.normalize("NFKD", _clean_text(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "", ascii_text)
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
    if safe:
        sanitized = sanitized.replace(" ", "_")
    return sanitized


def _client_name_from_answers(answers: Mapping[str, Any]) -> str:
    shared_name = answers.get("shared.name")
    if isinstance(shared_name, Mapping):
        given_name = _clean_text(shared_name.get("given_name"))
        middle_name = _clean_text(shared_name.get("middle_name"))
        family_name = _clean_text(shared_name.get("family_name"))
        full_name = " ".join(
            part for part in (given_name, middle_name, family_name) if part
        )
        if full_name:
            return full_name

    given_name = _clean_text(answers.get("shared.name.given_name"))
    middle_name = _clean_text(answers.get("shared.name.middle_name"))
    family_name = _clean_text(answers.get("shared.name.family_name"))
    return " ".join(part for part in (given_name, middle_name, family_name) if part)


def build_generated_form_filename(
    db: Session,
    job: FormFillingJob,
    *,
    safe: bool = False,
) -> str:
    answers = get_questionnaire_answers(db, job.case_id, form_type=job.form_type) or {}
    client_name = _client_name_from_answers(answers)
    if not client_name:
        case_row = db.query(Case).filter(Case.id == job.case_id).first()
        client_name = _clean_text(case_row.name) if case_row else ""

    form_label = _form_label_for_filename(job.form_type)
    if client_name:
        base_name = f"{form_label}_{client_name}"
    else:
        base_name = form_label

    cleaned_base_name = _clean_filename_text(base_name, safe=safe) or form_label
    return f"{cleaned_base_name}.pdf"


def build_generated_form_output_path(db: Session, job: FormFillingJob) -> str:
    return f"exports/form-fill/{job.id}/{build_generated_form_filename(db, job, safe=True)}"


def _generated_job_source_document_id(job_id: str) -> str:
    return f"form-filling-job:{job_id}"


def _resolve_generated_pdf_upload_key(pdf_path: str, filename: str) -> str:
    s3 = get_s3_service()
    candidate = Path(pdf_path)
    if candidate.is_absolute() and candidate.exists():
        return save_uploaded_file(candidate.read_bytes(), filename, s3)

    storage_candidate = STORAGE_DIR / candidate
    if storage_candidate.exists():
        return save_uploaded_file(storage_candidate.read_bytes(), filename, s3)

    return pdf_path


def _import_generated_pdf_pages(db: Session, job: FormFillingJob) -> int:
    source_document_id = _generated_job_source_document_id(job.id)
    existing_page = (
        db.query(Page)
        .filter(Page.source_document_id == source_document_id, Page.deleted_at.is_(None))
        .first()
    )
    if existing_page or not _clean_text(job.filled_pdf_path):
        return 0

    original_filename = build_generated_form_filename(db, job)
    upload_key = _resolve_generated_pdf_upload_key(job.filled_pdf_path, original_filename)
    page_infos = split_pdf(upload_key, get_s3_service())
    if not page_infos:
        return 0

    for info in page_infos:
        db.add(
            Page(
                case_id=job.case_id,
                source_document_id=source_document_id,
                original_filename=original_filename,
                original_page_number=int(info["page_number"]),
                file_path=str(info["file_path"]),
                thumbnail_path=str(info["thumbnail_path"]),
                status=PageStatus.UNCLASSIFIED.value,
                metadata_json={
                    "source": "form_filling",
                    "form_filling_job_id": job.id,
                    "form_type": _clean_text(job.form_type),
                    "filled_pdf_path": _clean_text(job.filled_pdf_path),
                },
            )
        )

    db.add(
        AuditLog(
            case_id=job.case_id,
            action="form_filling_pages_created",
            entity_type="form_filling_job",
            entity_id=job.id,
            details={
                "job_id": job.id,
                "form_type": _clean_text(job.form_type),
                "count": len(page_infos),
                "source_document_id": source_document_id,
                "original_filename": original_filename,
            },
        )
    )
    db.commit()
    return len(page_infos)


def _page_has_usable_ocr(page: Page) -> bool:
    text = str(page.ocr_text or "").strip()
    return (
        (page.extraction_status or "") == ExtractionStatus.DONE.value
        and bool(text)
        and not text.startswith("[Error]")
    )


def _page_needs_index(page: Page) -> bool:
    return _page_has_usable_ocr(page) and _clean_text(page.index_status).lower() != IndexStatus.DONE.value


def _get_source_document_ids(db: Session, case_id: str) -> list[str] | None:
    case_row = db.query(Case).filter(Case.id == case_id).first()
    return get_case_scope_source_document_ids(case_row, "form_filling")


def _load_case_pages(
    db: Session,
    case_id: str,
    *,
    source_document_ids: list[str] | None = None,
) -> list[Page]:
    return load_case_pages_for_scope(
        db,
        case_id,
        source_document_ids=source_document_ids,
    )


def _summarize_case_page_readiness(pages: list[Page]) -> dict[str, int]:
    total_pages = len(pages)
    usable_ocr_pages = sum(1 for page in pages if _page_has_usable_ocr(page))
    needs_index_pages = sum(1 for page in pages if _page_needs_index(page))
    return {
        "total_pages": total_pages,
        "usable_ocr_pages": usable_ocr_pages,
        "missing_ocr_pages": max(0, total_pages - usable_ocr_pages),
        "needs_index_pages": needs_index_pages,
    }


def _preparation_progress_from_counts(
    processed: int,
    total: int,
    *,
    base_pct: float,
    max_pct: float,
) -> float:
    if total <= 0:
        return max_pct
    ratio = max(0.0, min(1.0, processed / total))
    return round(base_pct + ((max_pct - base_pct) * ratio), 2)


def _prepare_case_documents_for_form_filling(
    db: Session,
    job: FormFillingJob,
    *,
    job_id: str,
    tracker: Any,
    source_document_ids: list[str] | None = None,
) -> dict[str, Any]:
    pages = _load_case_pages(
        db,
        job.case_id,
        source_document_ids=source_document_ids,
    )
    readiness_before = _summarize_case_page_readiness(pages)
    indexing_enabled = is_indexing_available()
    needs_ocr = readiness_before["missing_ocr_pages"] > 0
    needs_index = indexing_enabled and (
        needs_ocr or readiness_before["needs_index_pages"] > 0
    )
    preparation_summary: dict[str, Any] = {
        "readiness_before": readiness_before,
        "indexing_enabled": indexing_enabled,
        "ocr": None,
        "indexing": None,
    }

    if readiness_before["total_pages"] <= 0:
        if source_document_ids is not None:
            raise ValueError(
                "No documents are selected for form filling. Choose at least one case document in the forms panel."
            )
        raise ValueError(
            "No case pages are available for evidence retrieval. Upload the case documents before running PDF form filling."
        )

    if not needs_ocr and not needs_index:
        preparation_summary["readiness_after"] = readiness_before
        return preparation_summary

    if needs_ocr and not is_ocr_configured():
        raise RuntimeError(
            "GEMINI_API_KEY is required to extract the case pages before PDF form filling can continue."
        )

    _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="preparing_case"))
    _persist_job_state(
        db,
        job,
        form_filling_jobs.update_preparation_progress(
            job_id,
            progress_pct=0.0,
            phase="preparing_case",
        ),
    )

    def _ocr_progress(payload: Mapping[str, Any]) -> None:
        total_pages = int(payload.get("ocr_total_pages") or readiness_before["total_pages"] or 0)
        processed_pages = int(payload.get("ocr_processed_pages") or 0)
        form_filling_jobs.update_preparation_progress(
            job_id,
            progress_pct=_preparation_progress_from_counts(
                processed_pages,
                total_pages,
                base_pct=PREPARATION_PROGRESS_OCR_START_PCT,
                max_pct=PREPARATION_PROGRESS_OCR_COMPLETE_PCT,
            ),
            phase="preparing_case",
        )

    with case_pipeline_lock(job.case_id, timeout=300):
        extraction_summary = extract_case_pages(
            job.case_id,
            page_ids=[page.id for page in pages] if source_document_ids is not None else None,
            only_missing=True,
            progress_callback=_ocr_progress,
        )
        preparation_summary["ocr"] = extraction_summary

        db.expire_all()
        after_ocr = _summarize_case_page_readiness(
            _load_case_pages(
                db,
                job.case_id,
                source_document_ids=source_document_ids,
            )
        )
        preparation_summary["readiness_after_ocr"] = after_ocr

        if after_ocr["usable_ocr_pages"] <= 0:
            raise ValueError(
                "Automatic OCR preparation completed, but no usable text is available for the selected form-filling documents."
                if source_document_ids is not None
                else "Automatic OCR preparation completed, but no usable case text is available for evidence retrieval."
            )

        if not indexing_enabled:
            form_filling_jobs.update_preparation_progress(
                job_id,
                progress_pct=PREPARATION_PROGRESS_INDEX_COMPLETE_PCT,
                phase="preparing_case",
            )
            preparation_summary["readiness_after"] = after_ocr
            return preparation_summary

        if after_ocr["needs_index_pages"] <= 0:
            _persist_job_state(
                db,
                job,
                form_filling_jobs.update_preparation_progress(
                    job_id,
                    progress_pct=PREPARATION_PROGRESS_INDEX_COMPLETE_PCT,
                    phase="preparing_case",
                ),
            )
            preparation_summary["readiness_after"] = after_ocr
            return preparation_summary

        _persist_job_state(
            db,
            job,
            form_filling_jobs.update_preparation_progress(
                job_id,
                progress_pct=PREPARATION_PROGRESS_OCR_COMPLETE_PCT,
                phase="preparing_case",
            ),
        )

        def _index_progress(payload: Mapping[str, Any]) -> None:
            total_chunks = int(payload.get("index_total_chunks") or 0)
            processed_chunks = int(payload.get("index_processed_chunks") or 0)
            form_filling_jobs.update_preparation_progress(
                job_id,
                progress_pct=_preparation_progress_from_counts(
                    processed_chunks,
                    total_chunks,
                    base_pct=PREPARATION_PROGRESS_OCR_COMPLETE_PCT,
                    max_pct=PREPARATION_PROGRESS_INDEX_COMPLETE_PCT,
                ),
                phase="preparing_case",
            )

        index_summary = index_case_ocr_json(
            job.case_id,
            tracker=tracker,
            progress_callback=_index_progress,
        )
        preparation_summary["indexing"] = index_summary

        db.expire_all()
        readiness_after = _summarize_case_page_readiness(
            _load_case_pages(
                db,
                job.case_id,
                source_document_ids=source_document_ids,
            )
        )
        preparation_summary["readiness_after"] = readiness_after
        _persist_job_state(
            db,
            job,
            form_filling_jobs.update_preparation_progress(
                job_id,
                progress_pct=PREPARATION_PROGRESS_INDEX_COMPLETE_PCT,
                phase="preparing_case",
            ),
        )
        return preparation_summary


def _is_repeatable_question_item(item: Mapping[str, Any]) -> bool:
    fields = item.get("fields") or []
    item_type = _clean_text(item.get("type")).lower()
    return bool(fields) and (item_type == "repeatable_group" or bool(item.get("repeatable")))


def _normalize_questionnaire_options(
    item_type: str,
    raw_options: Any,
) -> list[dict[str, str]]:
    normalized_type = _clean_text(item_type).lower()
    if normalized_type == "yes_no" and not raw_options:
        return [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]

    if not isinstance(raw_options, list):
        return []

    options: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for option in raw_options:
        if isinstance(option, Mapping):
            value = _clean_text(option.get("value") or option.get("id") or option.get("label"))
            label = _clean_text(option.get("label") or option.get("value") or option.get("id"))
        else:
            value = _clean_text(option)
            label = value
        if not value and not label:
            continue
        normalized = (value or label, label or value)
        key = (normalized[0].lower(), normalized[1].lower())
        if key in seen:
            continue
        seen.add(key)
        options.append({"value": normalized[0], "label": normalized[1]})
    return options


def _questionnaire_default_metadata(
    item: Mapping[str, Any],
    field: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = field if field is not None else item
    return {
        "questionnaire_default_value": source.get("default_value"),
        "questionnaire_force_default": bool(source.get("force_default")),
    }


def _build_autofill_search_query(
    item: Mapping[str, Any],
    *,
    field: Mapping[str, Any] | None = None,
    slot_label: str = "",
) -> str:
    field_label = _clean_text(field.get("label")) if field else ""
    where_to_verify = _clean_text(
        (field.get("where_to_verify") if field else "")
        or item.get("where_to_verify")
    )
    parts: list[str] = []
    for part in (
        item.get("form_text"),
        field_label,
        item.get("section"),
        where_to_verify,
        item.get("instruction"),
        item.get("condition"),
        field.get("instruction") if field else "",
        field.get("condition") if field else "",
    ):
        cleaned = _clean_text(part)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)

    field_id = _clean_text(field.get("id")) if field else ""
    combined = _normalize_hint_text(
        " | ".join(
            part
            for part in (
                item.get("id"),
                field_id,
                field_label,
                item.get("form_text"),
                item.get("section"),
                where_to_verify,
            )
            if _clean_text(part)
        )
    )
    aliases: list[str] = []
    if field_id.endswith("unit_type") or "apt ste flr" in combined or "apartment suite or floor" in combined:
        aliases.append("Apartment Apt Suite Ste Floor Flr address unit")
    if (
        field_id in {"state", "safe_state", "last_entry_state", "prior_entry_state", "lea_state"}
        or ("state" in combined and ("address" in combined or "entry" in combined))
    ):
        aliases.append("State two letter abbreviation USPS state code")
    if field_id == "passport_issue_date" or ("passport" in combined and "issue date" in combined):
        aliases.append("Passport issue date date of issue fecha de expedicion fecha de emision")
    if field_id == "passport_expiration_date" or ("passport" in combined and "expiration date" in combined):
        aliases.append("Passport expiration date expiry date fecha de vencimiento fecha de expiracion")
    if field_id == "a_number" or "alien registration" in combined or "a number" in combined:
        aliases.append("Alien Registration Number A-Number A Number Numero A")
    if "safe mailing address" in combined or ("mailing address" in combined and "safe" in combined):
        aliases.append("alternate mailing address safe address different from physical address")

    item_id = _clean_text(item.get("id")) if item else ""
    if item_id == "p5_1" or ("spouse" in combined and "family member" in combined):
        _spouse_field_hints: dict[str, str] = {
            "spouse_family_name": "apellido del esposo esposa conyuge spouse last name family name",
            "spouse_given_name": "nombre de pila del esposo esposa conyuge spouse first name given name",
            "spouse_middle_name": "segundo nombre del esposo esposa conyuge spouse middle name",
            "spouse_date_of_birth": "fecha de nacimiento del esposo esposa conyuge spouse date of birth DOB",
            "spouse_country_of_birth": "pais de nacimiento del esposo esposa conyuge spouse country of birth",
            "spouse_residence_city": "ciudad de residencia del esposo esposa conyuge spouse city of residence",
            "spouse_residence_country": "pais de residencia del esposo esposa conyuge spouse country of residence",
        }
        base_alias = "spouse husband wife esposo esposa conyuge married casado casada"
        field_hint = _spouse_field_hints.get(field_id, "")
        aliases.append(f"{field_hint} {base_alias}".strip() if field_hint else base_alias)
    if item_id == "p5_children" or ("child" in combined and "family member" in combined):
        _child_field_hints: dict[str, str] = {
            "family_name": "apellido del hijo hija child last name family name",
            "given_name": "nombre de pila del hijo hija child first name given name",
            "middle_name": "segundo nombre del hijo hija child middle name",
            "date_of_birth": "fecha de nacimiento del hijo hija child date of birth DOB edad age",
            "country_of_birth": "pais de nacimiento del hijo hija child country of birth",
            "current_city": "ciudad de residencia del hijo hija child city of residence",
            "current_state": "estado de residencia del hijo hija child state of residence",
            "current_country": "pais de residencia del hijo hija child country of residence",
        }
        base_alias = "child children son daughter hijo hija menor de edad hijos dependientes"
        field_hint = _child_field_hints.get(field_id, "")
        aliases.append(f"{field_hint} {base_alias}".strip() if field_hint else base_alias)

    if slot_label:
        parts.insert(0, slot_label)

    for alias in aliases:
        if alias not in parts:
            parts.append(alias)
    return " | ".join(parts)


def _build_shared_autofill_targets(
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []

    for page in pages:
        page_number = _safe_int(page.get("page")) or 0
        for item in page.get("items", []) or []:
            if _clean_text(item.get("responsible_party") or "client").lower() != "client":
                continue

            item_id = _clean_text(item.get("id"))
            item_type = _clean_text(item.get("type") or "text").lower() or "text"
            section = _clean_text(item.get("section"))
            form_text = _clean_text(item.get("form_text"))
            item_where = _clean_text(item.get("where_to_verify"))
            is_repeatable = _is_repeatable_question_item(item)
            if not item_id:
                continue

            fields = item.get("fields") or []
            if fields:
                visible_slots = item.get("visible_slots") or []
                slot_indices = list(range(len(visible_slots))) if (is_repeatable and visible_slots) else [None]
                for slot_index in slot_indices:
                    slot_label = visible_slots[slot_index] if slot_index is not None else ""
                    for field in fields:
                        field_id = _clean_text(field.get("id"))
                        if not field_id:
                            continue

                        field_type = _clean_text(field.get("type") or item_type).lower() or "text"
                        label = _clean_text(field.get("label") or form_text or field_id)
                        field_where = _clean_text(field.get("where_to_verify")) or item_where
                        if slot_index is not None:
                            target_id = f"{item_id}[{slot_index}].{field_id}"
                            target_form_text = f"{form_text} - {slot_label}" if slot_label else form_text
                        else:
                            target_id = f"{item_id}.{field_id}"
                            target_form_text = form_text
                        canonical_id = f"{item_id}.{field_id}"
                        targets.append(
                            {
                                "id": target_id,
                                "field_name": target_id,
                                "field_label": f"{label} ({slot_label})" if slot_label else label,
                                "field_type": field_type,
                                "field_type_hint": field_type,
                                "page_number": page_number,
                                "question_id": item_id,
                                "answer_field_id": field_id,
                                "questionnaire_item_id": item_id,
                                "questionnaire_field_id": field_id,
                                "questionnaire_option_value": None,
                                "questionnaire_option_label": None,
                                "canonical_questionnaire_id": canonical_id,
                                "questionnaire_label": label,
                                "questionnaire_form_text": target_form_text,
                                "questionnaire_section": section,
                                "questionnaire_responsible_party": "client",
                                "questionnaire_item_type": item_type,
                                "questionnaire_where_to_verify": field_where,
                                "questionnaire_options": _normalize_questionnaire_options(
                                    field_type,
                                    field.get("options"),
                                ),
                                **_questionnaire_default_metadata(item, field),
                                "search_query": _build_autofill_search_query(
                                    item,
                                    field=field,
                                    slot_label=slot_label,
                                ),
                                "is_repeatable_first_slot": is_repeatable,
                                "repeatable_slot_index": slot_index,
                            }
                        )
                continue

            if item_type == "repeatable_group":
                continue

            label = form_text or section or item_id
            targets.append(
                {
                    "id": item_id,
                    "field_name": item_id,
                    "field_label": label,
                    "field_type": item_type,
                    "field_type_hint": item_type,
                    "page_number": page_number,
                    "question_id": item_id,
                    "answer_field_id": None,
                    "questionnaire_item_id": item_id,
                    "questionnaire_field_id": None,
                    "questionnaire_option_value": None,
                    "questionnaire_option_label": None,
                    "canonical_questionnaire_id": item_id,
                    "questionnaire_label": label,
                    "questionnaire_form_text": form_text,
                    "questionnaire_section": section,
                    "questionnaire_responsible_party": "client",
                    "questionnaire_item_type": item_type,
                    "questionnaire_where_to_verify": item_where,
                    "questionnaire_options": _normalize_questionnaire_options(
                        item_type,
                        item.get("options"),
                    ),
                    **_questionnaire_default_metadata(item),
                    "search_query": _build_autofill_search_query(item),
                    "is_repeatable_first_slot": False,
                }
            )

    targets.sort(key=lambda item: (item.get("page_number") or 0, item.get("field_name") or ""))
    return targets


def _build_attorney_autofill_targets(
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []

    for page in pages:
        page_number = _safe_int(page.get("page")) or 0
        for item in page.get("items", []) or []:
            if _clean_text(item.get("responsible_party") or "").lower() != "attorney":
                continue

            item_id = _clean_text(item.get("id"))
            item_type = _clean_text(item.get("type") or "text").lower() or "text"
            section = _clean_text(item.get("section"))
            form_text = _clean_text(item.get("form_text"))
            item_where = _clean_text(item.get("where_to_verify"))
            is_repeatable = _is_repeatable_question_item(item)
            if not item_id:
                continue

            fields = item.get("fields") or []
            if fields:
                for field in fields:
                    field_id = _clean_text(field.get("id"))
                    if not field_id:
                        continue

                    field_type = _clean_text(field.get("type") or item_type).lower() or "text"
                    label = _clean_text(field.get("label") or form_text or field_id)
                    field_where = _clean_text(field.get("where_to_verify")) or item_where
                    canonical_id = f"{item_id}.{field_id}"
                    targets.append(
                        {
                            "id": canonical_id,
                            "field_name": canonical_id,
                            "field_label": label,
                            "field_type": field_type,
                            "field_type_hint": field_type,
                            "page_number": page_number,
                            "question_id": item_id,
                            "answer_field_id": field_id,
                            "questionnaire_item_id": item_id,
                            "questionnaire_field_id": field_id,
                            "questionnaire_option_value": None,
                            "questionnaire_option_label": None,
                            "canonical_questionnaire_id": canonical_id,
                            "questionnaire_label": label,
                            "questionnaire_form_text": form_text,
                            "questionnaire_section": section,
                            "questionnaire_responsible_party": "attorney",
                            "questionnaire_item_type": item_type,
                            "questionnaire_where_to_verify": field_where,
                            "questionnaire_options": _normalize_questionnaire_options(
                                field_type,
                                field.get("options"),
                            ),
                            **_questionnaire_default_metadata(item, field),
                            "search_query": _build_autofill_search_query(
                                item,
                                field=field,
                            ),
                            "is_repeatable_first_slot": is_repeatable,
                        }
                    )
                continue

            if item_type == "repeatable_group":
                continue

            label = form_text or section or item_id
            targets.append(
                {
                    "id": item_id,
                    "field_name": item_id,
                    "field_label": label,
                    "field_type": item_type,
                    "field_type_hint": item_type,
                    "page_number": page_number,
                    "question_id": item_id,
                    "answer_field_id": None,
                    "questionnaire_item_id": item_id,
                    "questionnaire_field_id": None,
                    "questionnaire_option_value": None,
                    "questionnaire_option_label": None,
                    "canonical_questionnaire_id": item_id,
                    "questionnaire_label": label,
                    "questionnaire_form_text": form_text,
                    "questionnaire_section": section,
                    "questionnaire_responsible_party": "attorney",
                    "questionnaire_item_type": item_type,
                    "questionnaire_where_to_verify": item_where,
                    "questionnaire_options": _normalize_questionnaire_options(
                        item_type,
                        item.get("options"),
                    ),
                    **_questionnaire_default_metadata(item),
                    "search_query": _build_autofill_search_query(item),
                    "is_repeatable_first_slot": False,
                }
            )

    targets.sort(key=lambda item: (item.get("page_number") or 0, item.get("field_name") or ""))
    return targets


_FAMILY_GROUP_PREFIXES = ("p5_1", "p5_children")


def _share_family_group_evidence(
    targets: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> None:
    """Merge evidence across all fields in the same family group.

    Part 5 fields (spouse, children) are semantically related but each field
    retrieves evidence independently.  A single Pinecone chunk that mentions
    "esposo: Juan, born 01/02/1985" might only be retrieved for the name
    field but not for the date-of-birth field.  By merging all retrieved
    matches within the same group and sharing the combined set, every field
    in the group sees the richest possible evidence.
    """
    groups: dict[str, list[str]] = {}
    for target in targets:
        field_id = _clean_text(target.get("id"))
        question_id = _clean_text(target.get("question_id"))
        if not field_id or not question_id:
            continue
        if not any(question_id.startswith(prefix) for prefix in _FAMILY_GROUP_PREFIXES):
            continue
        slot_index = target.get("repeatable_slot_index")
        group_key = f"{question_id}[{slot_index}]" if slot_index is not None else question_id
        groups.setdefault(group_key, []).append(field_id)

    for group_key, field_ids in groups.items():
        if len(field_ids) <= 1:
            continue
        all_matches: list[dict[str, Any]] = []
        seen_texts: set[str] = set()
        richest_bundle: dict[str, Any] = {}
        richest_match_count = 0
        for fid in field_ids:
            bundle = evidence_by_id.get(fid)
            if not bundle:
                continue
            matches = bundle.get("matches") or []
            if len(matches) > richest_match_count:
                richest_match_count = len(matches)
                richest_bundle = bundle
            for match in matches:
                text_key = _clean_text(
                    (match.get("metadata") or {}).get("text", "")
                )[:200]
                if text_key and text_key not in seen_texts:
                    seen_texts.add(text_key)
                    all_matches.append(match)

        if not all_matches or not richest_bundle:
            continue

        merged_bundle = dict(richest_bundle)
        merged_bundle["matches"] = all_matches
        merged_bundle["stage"] = "family_group_merged"

        from .retrieval_service import format_match_as_evidence, format_match_context
        max_chars = 8000
        merged_bundle["evidence"] = format_match_as_evidence(all_matches, max_chars=max_chars)
        merged_bundle["text_context"] = format_match_context(all_matches, max_chars=max_chars)

        for fid in field_ids:
            evidence_by_id[fid] = merged_bundle


_FAMILY_NAME_BLOCK_RE = re.compile(
    r"(?P<label>(?:nombre\s+completo|full\s+name))"
    r"(?!\s+(?:del|de\s+la|of)\s+)"
    r"\s*:?\s*(?P<name>[^\n\r]+?)"
    r"(?:[\n\r]+(?:(?!(?:nombre\s+completo|full\s+name))[^\n\r]*[\n\r]+){0,4}?)"
    r"\s*(?:fecha\s+de\s+nacimiento|date\s+of\s+birth|dob)\s*:?\s*(?P<dob>[^\n\r]+)",
    re.IGNORECASE,
)

_SPOUSE_SECTION_RE = re.compile(
    r"(?i)(esta\s+casad[oa]\??|estado\s+civil|conyuge|c[oó]nyuge|esposo|esposa|spouse|married|matrimonio)"
)
_CHILDREN_SECTION_RE = re.compile(
    r"(?i)(tiene\s+hijos|informaci[oó]n\s+(?:de|sobre)\s+hij[oa]s|children|son\s+o\s+hija|dependientes)"
)
_PARENT_EXCLUSION_RE = re.compile(
    r"(?i)(padre|madre|mother|father|progenitor|applicant|aplicante|solicitante)"
)

_NAME_TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'\-]+")


def _split_family_member_name(full_name: str) -> dict[str, str]:
    return _i914_split_family_member_name(full_name, clean_text=_clean_text)


def _classify_family_block_role(prefix_text: str) -> str:
    return _i914_classify_family_block_role(prefix_text)


def _parse_i914_family_roster(text: str) -> dict[str, Any]:
    return _i914_parse_family_roster(
        text,
        clean_text=_clean_text,
        normalize_date_text=_normalize_date_text,
    )


def _collect_part5_evidence_text(
    targets: list[dict[str, Any]],
    evidence_by_id: Mapping[str, Any],
) -> str:
    return _i914_collect_part5_evidence_text(
        targets,
        evidence_by_id,
        clean_text=_clean_text,
    )


def _apply_i914_family_roster_override(
    answers: dict[str, Any],
    targets: list[dict[str, Any]],
    evidence_by_id: Mapping[str, Any],
) -> None:
    _i914_apply_family_roster_override(
        answers,
        targets,
        evidence_by_id,
        clean_text=_clean_text,
        normalize_date_text=_normalize_date_text,
        logger=log,
    )


def _collect_i914_family_result_field_ids(
    targets: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], dict[int, dict[str, str]]]:
    return _i914_collect_family_result_field_ids(
        targets,
        clean_text=_clean_text,
        infer_target_repeatable_slot_index=_infer_target_repeatable_slot_index,
    )


def _postprocess_i914_family_roster(
    targets: Sequence[Mapping[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: Mapping[str, Any],
) -> None:
    _i914_postprocess_family_roster(
        targets,
        results_by_id,
        evidence_by_id,
        clean_text=_clean_text,
        normalize_date_text=_normalize_date_text,
        infer_target_repeatable_slot_index=_infer_target_repeatable_slot_index,
        set_result_value=_set_result_value,
        logger=log,
    )


def _collect_evidence_for_targets_sync(
    targets: list[dict[str, Any]],
    *,
    case_id: str,
    tracker: Any,
    source_document_ids: list[str] | None = None,
    progress_callback: AutofillProgressCallback | None = None,
    progress_start_pct: float = 25.0,
    progress_end_pct: float = 55.0,
    progress_label: str = "Gathering evidence",
) -> dict[str, dict[str, Any]]:
    settings = get_rag_settings()
    evidence_by_id: dict[str, dict[str, Any]] = {}
    query_vectors: dict[str, list[float]] = {}

    queries = [
        _clean_text(target.get("search_query") or target.get("field_label") or target.get("field_name"))
        for target in targets
    ]
    embedding_end_pct = progress_start_pct + ((progress_end_pct - progress_start_pct) * 0.25)
    if progress_callback is not None:
        progress_callback(progress_start_pct, f"{progress_label}...")
    try:
        if queries:
            embeddings = get_embedding_batch(
                queries,
                task_type=settings.embedding_task_type_query,
                tracker=tracker,
                step_label="questionnaire-autofill-evidence-embeddings",
                progress_callback=(
                    None
                    if progress_callback is None
                    else lambda processed, total: progress_callback(
                        progress_start_pct
                        + ((embedding_end_pct - progress_start_pct) * (processed / max(1, total))),
                        f"Preparing evidence search... ({processed}/{total})",
                    )
                ),
            )
            for target, embedding in zip(targets, embeddings, strict=False):
                field_id = _clean_text(target.get("id"))
                if field_id and embedding:
                    query_vectors[field_id] = embedding
    except Exception as exc:
        log.warning("Questionnaire autofill query embedding batch fallback: %s", exc)

    def _collect_single(target: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        field_id = _clean_text(target.get("id"))
        query_text = _clean_text(target.get("search_query") or target.get("field_label") or field_id)
        try:
            if not query_text:
                bundle = {
                    "evidence": [],
                    "text_context": "",
                    "source_pages": [],
                    "stage": "empty-query",
                    "matches": [],
                }
            else:
                bundle = collect_evidence_bundle_for_question(
                    query_text,
                    case_id=case_id,
                    where_to_verify=_clean_text(target.get("questionnaire_where_to_verify")),
                    source_document_ids=source_document_ids,
                    top_k=settings.autopilot_evidence_top_k,
                    query_vector=query_vectors.get(field_id),
                    max_context_chars=settings.autopilot_evidence_max_chars,
                    tracker=None,
                    document_fallback_enabled=False if source_document_ids is not None else None,
                )
        except Exception as exc:
            log.warning("Questionnaire autofill evidence collection failed for %s: %s", field_id or "unknown", exc)
            bundle = {
                "evidence": [],
                "text_context": "",
                "source_pages": [],
                "stage": "error",
                "matches": [],
            }
        return field_id, bundle

    max_workers = max(1, min(len(targets), int(settings.autopilot_evidence_workers or 1)))
    total_targets = max(1, len(targets))
    processed_targets = 0
    evidence_start_pct = embedding_end_pct if queries else progress_start_pct
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_collect_single, target) for target in targets]
        for future in as_completed(futures):
            field_id, bundle = future.result()
            evidence_by_id[field_id] = bundle
            processed_targets += 1
            if progress_callback is not None:
                pct = evidence_start_pct + (
                    (progress_end_pct - evidence_start_pct)
                    * (processed_targets / total_targets)
                )
                progress_callback(
                    pct,
                    f"{progress_label} ({processed_targets}/{total_targets})",
                )

    _share_family_group_evidence(targets, evidence_by_id)

    return evidence_by_id


def _postprocess_a_number_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: Mapping[str, Any],
) -> None:
    for target in targets:
        if not _looks_like_a_number_target(target):
            continue
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue

        current_value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
        normalized = _normalize_a_number_value(current_value)
        if normalized:
            if normalized != current_value:
                _set_result_value(
                    results_by_id,
                    field_id,
                    normalized,
                    justification="Normalized A-number to digits only.",
                )
            continue

        evidence_text = _extract_plain_text_from_evidence(evidence_by_id.get(field_id))
        derived = _extract_a_number_from_text(evidence_text)
        if derived:
            _set_result_value(
                results_by_id,
                field_id,
                derived,
                justification="Recovered A-number from labeled evidence.",
            )
            continue

        _set_result_value(
            results_by_id,
            field_id,
            "",
            confidence="low",
            justification="Discarded invalid A-number because the evidence did not support a valid identifier.",
        )


def _postprocess_passport_date_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: Mapping[str, Any],
) -> None:
    issue_labels = (
        r"issue date",
        r"date of issue",
        r"fecha de expedici[oó]n",
        r"fecha de emisi[oó]n",
    )
    expiration_labels = (
        r"expiration date",
        r"date of expiration",
        r"expiry date",
        r"fecha de vencimiento",
        r"fecha de expiraci[oó]n",
    )

    for question_id, group_targets in _group_targets_by_question_id(targets).items():
        combined_evidence_parts: list[str] = []
        for target in group_targets:
            field_id = _clean_text(target.get("id"))
            if not field_id:
                continue
            evidence_text = _extract_plain_text_from_evidence(evidence_by_id.get(field_id))
            if evidence_text and evidence_text not in combined_evidence_parts:
                combined_evidence_parts.append(evidence_text)
        if not combined_evidence_parts:
            continue

        combined_evidence = "\n".join(combined_evidence_parts)
        for target in group_targets:
            answer_field_id = _clean_text(
                target.get("answer_field_id") or target.get("questionnaire_field_id")
            ).lower()
            if answer_field_id not in {"passport_issue_date", "passport_expiration_date"}:
                continue

            field_id = _clean_text(target.get("id"))
            current_value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
            normalized_current = _normalize_date_text(current_value)
            if normalized_current:
                if normalized_current != current_value:
                    _set_result_value(
                        results_by_id,
                        field_id,
                        normalized_current,
                        justification=f"Normalized passport date to {LONG_DATE_FORMAT_HUMAN}.",
                    )
                continue

            labels = issue_labels if answer_field_id == "passport_issue_date" else expiration_labels
            derived = _extract_labeled_date_from_text(combined_evidence, labels)
            if derived:
                _set_result_value(
                    results_by_id,
                    field_id,
                    derived,
                    justification=f"Recovered {answer_field_id} from labeled passport evidence.",
                )


_IMMIGRATION_STATUS_KEYWORDS = (
    "status",
    "visa",
    "visitor",
    "tourist",
    "student",
    "exchange",
    "worker",
    "employment authorization",
    "ead",
    "overstay",
    "parole",
    "paroled",
    "asylum",
    "asylee",
    "refugee",
    "tps",
    "temporary protected status",
    "daca",
    "deferred action",
    "nonimmigrant",
    "immigrant",
    "permanent resident",
    "lawful permanent resident",
    "lpr",
    "adjustment",
    "pending asylum",
    "pending t",
    "pending u",
)


def _normalize_nonimmigrant_status(value: Any) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""

    normalized = _normalize_option_answer(cleaned)
    if normalized == "no legal status":
        return "No Legal Status"

    if _normalize_country_value_for_pdf(cleaned):
        return ""

    normalized_hint = _normalize_hint_text(cleaned)
    if _IMMIGRATION_STATUS_CODE_RE.search(cleaned):
        return cleaned
    if any(keyword in normalized_hint for keyword in _IMMIGRATION_STATUS_KEYWORDS):
        return cleaned
    return ""


def _requires_complete_city_state_pair(group_targets: list[dict[str, Any]]) -> bool:
    combined_context = " ".join(_normalized_target_context(target) for target in group_targets)
    return "last entry" in combined_context or "prior entry" in combined_context


def _postprocess_country_and_status_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
) -> None:
    for target in targets:
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue

        current_value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
        if not current_value:
            continue

        if _looks_like_country_target(target):
            normalized_country = _normalize_country_value_for_pdf(current_value)
            if normalized_country:
                if normalized_country != current_value:
                    _set_result_value(
                        results_by_id,
                        field_id,
                        normalized_country,
                        justification="Normalized country value to a recognized country name.",
                    )
                continue

            _set_result_value(
                results_by_id,
                field_id,
                "",
                confidence="low",
                justification=(
                    "Discarded invalid country value because it was not a recognized country "
                    "and may have come from nearby field text."
                ),
            )
            continue

        if _looks_like_nonimmigrant_status(target):
            normalized_status = _normalize_nonimmigrant_status(current_value)
            if normalized_status:
                if normalized_status != current_value:
                    _set_result_value(
                        results_by_id,
                        field_id,
                        normalized_status,
                        justification="Normalized current nonimmigrant status value.",
                    )
                continue

            _set_result_value(
                results_by_id,
                field_id,
                "",
                confidence="low",
                justification=(
                    "Discarded invalid current nonimmigrant status because it did not look like "
                    "an immigration status and may have come from nearby field text."
                ),
            )


def _postprocess_address_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: Mapping[str, Any],
) -> None:
    for group_targets in _group_address_targets(targets).values():
        field_ids_by_key: dict[str, str] = {}
        candidate_texts: list[str] = []

        for target in group_targets:
            logical_field_id = _logical_address_field_id(target)
            if not logical_field_id:
                continue
            field_id = _clean_text(target.get("id"))
            if not field_id:
                continue
            if _is_manual_lea_unit_target(target):
                if _clean_text((results_by_id.get(field_id) or {}).get("value")):
                    _set_result_value(
                        results_by_id,
                        field_id,
                        "",
                        confidence="low",
                        justification=(
                            "Cleared the Part 3.5 Number field because it must be reviewed "
                            "and entered manually."
                        ),
                    )
                continue
            field_ids_by_key[logical_field_id] = field_id

            raw_current_value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
            current_value = raw_current_value
            extracted_candidate = _extract_address_candidate_for_target(target, raw_current_value)
            if raw_current_value and _looks_like_question_answer_dump(raw_current_value):
                if raw_current_value != extracted_candidate:
                    _set_result_value(
                        results_by_id,
                        field_id,
                        "",
                        confidence="low",
                        justification="Discarded a raw question-and-answer dump that did not isolate a single address component.",
                    )
                current_value = ""
                if extracted_candidate and extracted_candidate not in candidate_texts:
                    candidate_texts.append(extracted_candidate)
            if current_value:
                if logical_field_id == "unit_type":
                    normalized_unit_type = _normalize_address_unit_type(current_value)
                    if normalized_unit_type and normalized_unit_type != current_value:
                        _set_result_value(
                            results_by_id,
                            field_id,
                            normalized_unit_type,
                            justification="Normalized address unit type to a supported option.",
                        )
                        current_value = normalized_unit_type
                elif logical_field_id == "state":
                    normalized_state = _normalize_us_state_code(current_value)
                    if normalized_state:
                        if normalized_state != current_value:
                            _set_result_value(
                                results_by_id,
                                field_id,
                                normalized_state,
                                justification="Normalized state value to a USPS abbreviation.",
                            )
                        current_value = normalized_state
                    else:
                        _flag_result_for_review(
                            results_by_id,
                            field_id,
                            value="",
                            justification=(
                                "Cleared invalid state because state fields only accept valid "
                                "USPS abbreviations or U.S. state names."
                            ),
                        )
                        current_value = ""
                if current_value not in candidate_texts:
                    candidate_texts.append(current_value)

            evidence_text = _extract_plain_text_from_evidence(evidence_by_id.get(field_id))
            evidence_candidate = _extract_address_candidate_for_target(target, evidence_text)
            if evidence_candidate and evidence_candidate not in candidate_texts:
                candidate_texts.append(evidence_candidate)

        best_parsed: dict[str, str] = {}
        for candidate in sorted(candidate_texts, key=len, reverse=True):
            parsed = _parse_address_components_from_text(candidate)
            if len(parsed) > len(best_parsed):
                best_parsed = parsed

        street_field_id = field_ids_by_key.get("street_number_name")
        if street_field_id and best_parsed:
            current_street = _clean_text((results_by_id.get(street_field_id) or {}).get("value"))
            if best_parsed.get("street_number_name") and (not current_street or _looks_like_composite_address_text(current_street)):
                _set_result_value(
                    results_by_id,
                    street_field_id,
                    best_parsed["street_number_name"],
                    justification="Derived structured street value from a full address string.",
                )

        for logical_field_id in ("unit_type", "unit_number", "city", "state", "zip_code"):
            field_id = field_ids_by_key.get(logical_field_id)
            derived_value = _clean_text(best_parsed.get(logical_field_id)) if best_parsed else ""
            if not field_id or not derived_value:
                continue
            current_value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
            if logical_field_id == "unit_type":
                derived_value = _normalize_address_unit_type(derived_value)
                current_value = _normalize_address_unit_type(current_value)
            elif logical_field_id == "state":
                derived_value = _normalize_us_state_code(derived_value)
                current_value = _normalize_us_state_code(current_value)
            if derived_value and (not current_value or current_value != derived_value):
                _set_result_value(
                    results_by_id,
                    field_id,
                    derived_value,
                    justification=f"Derived address {logical_field_id} from a full address string.",
                )

        state_field_id = field_ids_by_key.get("state")
        if not state_field_id:
            continue

        city_field_id = field_ids_by_key.get("city")
        zip_field_id = field_ids_by_key.get("zip_code")
        current_state_raw = _clean_text((results_by_id.get(state_field_id) or {}).get("value"))
        current_state = _normalize_us_state_code(current_state_raw)
        current_city = _clean_text((results_by_id.get(city_field_id) or {}).get("value")) if city_field_id else ""
        current_zip = _clean_text((results_by_id.get(zip_field_id) or {}).get("value")) if zip_field_id else ""
        if not current_zip and best_parsed:
            current_zip = _clean_text(best_parsed.get("zip_code"))
        resolution_candidates = [
            candidate for candidate in candidate_texts if _clean_text(candidate) != current_state_raw
        ]

        resolution = _resolve_us_state(
            state_value="" if current_state else current_state_raw,
            city_value=current_city,
            zip_value=current_zip,
            text_candidates=resolution_candidates,
        )
        if not resolution.code:
            continue

        zip_backed_state = _shared_infer_state_from_zip_code(current_zip) if current_zip else ""

        should_update = False
        if not current_state:
            should_update = True
        elif resolution.code != current_state and resolution.source in {"explicit_text", "zip"}:
            if (
                resolution.source == "explicit_text"
                and zip_backed_state
                and zip_backed_state == current_state
            ):
                should_update = False
            else:
                should_update = True

        if not should_update:
            continue

        if resolution.source == "zip":
            justification = f"Resolved state from ZIP code '{resolution.matched_value}'."
        elif resolution.source == "explicit_text":
            justification = f"Resolved state from explicit state text in '{resolution.matched_value}'."
        else:
            justification = f"Inferred state from city '{resolution.matched_value}'."

        _set_result_value(
            results_by_id,
            state_field_id,
            resolution.code,
            justification=justification,
        )

        if state_field_id and city_field_id and _requires_complete_city_state_pair(group_targets):
            current_state = _clean_text((results_by_id.get(state_field_id) or {}).get("value"))
            current_city = _clean_text((results_by_id.get(city_field_id) or {}).get("value"))
            if current_city and not current_state:
                justification = (
                    "Cleared partial entry location because this field group requires both city "
                    "and state, and the state could not be validated or inferred."
                )
                _flag_result_for_review(
                    results_by_id,
                    city_field_id,
                    value="",
                    justification=justification,
                )
                _flag_result_for_review(
                    results_by_id,
                    state_field_id,
                    value="",
                    justification=justification,
                )


def _address_bucket_from_results(
    group_targets: list[dict[str, Any]],
    results_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    bucket: dict[str, str] = {}
    for target in group_targets:
        logical_field_id = _logical_address_field_id(target)
        if not logical_field_id:
            continue
        field_id = _clean_text(target.get("id"))
        value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
        if value:
            if logical_field_id == "unit_type":
                value = _normalize_address_unit_type(value) or value
            elif logical_field_id == "state":
                value = _normalize_us_state_code(value) or value
            bucket[logical_field_id] = value
    return bucket


def _safe_mailing_duplicates_physical(
    safe_bucket: Mapping[str, str],
    physical_bucket: Mapping[str, str],
) -> bool:
    comparable_keys = [
        key
        for key in ("street_number_name", "unit_type", "unit_number", "city", "state", "zip_code")
        if safe_bucket.get(key)
    ]
    if not comparable_keys:
        return False
    if not any(safe_bucket.get(key) for key in ("street_number_name", "city", "state", "zip_code")):
        return False
    return all(_clean_text(safe_bucket.get(key)) == _clean_text(physical_bucket.get(key)) for key in comparable_keys)


def _clear_duplicate_safe_mailing_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
) -> None:
    grouped_targets = _group_targets_by_question_id(targets)
    physical_groups: list[tuple[str, int, list[dict[str, Any]]]] = []
    safe_groups: list[tuple[str, int, list[dict[str, Any]]]] = []

    for question_id, group_targets in grouped_targets.items():
        page_number = min(int(target.get("page_number") or 0) for target in group_targets) if group_targets else 0
        if any(_is_current_physical_address_target(target) for target in group_targets):
            physical_groups.append((question_id, page_number, group_targets))
        if any(_is_safe_mailing_target(target) for target in group_targets):
            safe_groups.append((question_id, page_number, group_targets))

    if not physical_groups or not safe_groups:
        return

    for safe_question_id, safe_page, safe_targets in safe_groups:
        safe_bucket = _address_bucket_from_results(safe_targets, results_by_id)
        if not safe_bucket:
            continue
        closest_physical = min(physical_groups, key=lambda item: abs(item[1] - safe_page))
        physical_bucket = _address_bucket_from_results(closest_physical[2], results_by_id)
        if not physical_bucket or not _safe_mailing_duplicates_physical(safe_bucket, physical_bucket):
            continue
        for target in safe_targets:
            field_id = _clean_text(target.get("id"))
            if field_id:
                _set_result_value(
                    results_by_id,
                    field_id,
                    "",
                    confidence="low",
                    justification="Cleared Safe Mailing Address because the evidence did not show a distinct alternate address.",
                )


def _tokenize_simple_words(value: Any) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z'.-]+", _clean_text(value))
        if _clean_text(token)
    }


def _postprocess_us_address_foreign_fields(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
) -> None:
    """Clear Province/Postal Code for U.S. addresses.

    The PDF province and postal code widgets are physically close to the ZIP code
    and state fields. When the country is the United States, those foreign-address
    fields must remain blank; otherwise the LLM or the address normalizer can
    carry over the ZIP code or state into them.
    """
    for group_targets in _group_address_targets(targets).values():
        field_ids_by_key: dict[str, str] = {}
        for target in group_targets:
            logical_field_id = _logical_address_field_id(target)
            if logical_field_id not in {"country", "province", "postal_code"}:
                continue
            field_id = _clean_text(target.get("id"))
            if not field_id:
                continue
            field_ids_by_key.setdefault(logical_field_id, field_id)

        country_field_id = field_ids_by_key.get("country")
        if not country_field_id:
            continue
        country_value = _clean_text(
            (results_by_id.get(country_field_id) or {}).get("value")
        )
        if not country_value:
            continue
        normalized_country = _normalize_country_value_for_pdf(country_value)
        if normalized_country != "United States":
            continue

        for logical_field_id in ("province", "postal_code"):
            foreign_field_id = field_ids_by_key.get(logical_field_id)
            if not foreign_field_id:
                continue
            existing_value = _clean_text(
                (results_by_id.get(foreign_field_id) or {}).get("value")
            )
            if not existing_value:
                continue
            _set_result_value(
                results_by_id,
                foreign_field_id,
                "",
                confidence="medium",
                justification=(
                    "Cleared because the country is the United States; Province and "
                    "Postal Code only apply to foreign mailing addresses."
                ),
            )


def _postprocess_address_cross_check(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
) -> None:
    grouped_targets = _group_targets_by_question_id(targets)
    for group_targets in grouped_targets.values():
        if not any(_is_safe_mailing_target(target) for target in group_targets):
            continue
        for target in group_targets:
            logical_field_id = _logical_address_field_id(target)
            if logical_field_id not in {"city", "state"}:
                continue
            field_id = _clean_text(target.get("id"))
            if not field_id:
                continue
            current_value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
            if not current_value:
                continue
            current_value_normalized = current_value.lower()
            if _clean_text((results_by_id.get(field_id) or {}).get("confidence")).lower() == "high":
                continue

            contamination_sources: list[str] = []
            for other_target in group_targets:
                other_field_id = _clean_text(other_target.get("id"))
                if not other_field_id or other_field_id == field_id:
                    continue
                other_value = _clean_text((results_by_id.get(other_field_id) or {}).get("value"))
                if not other_value:
                    continue
                other_logical_field_id = _logical_address_field_id(other_target)
                if other_logical_field_id in {"city", "state"}:
                    continue
                if (
                    current_value_normalized == other_value.lower()
                    or (
                        len(current_value.split()) == 1
                        and current_value_normalized in _tokenize_simple_words(other_value)
                    )
                ):
                    contamination_sources.append(
                        _clean_text(other_target.get("field_label"))
                        or _clean_text(other_target.get("questionnaire_label"))
                        or other_field_id
                    )

            if not contamination_sources:
                continue
            _flag_result_for_review(
                results_by_id,
                field_id,
                value="",
                justification=(
                    "Cleared Safe Mailing Address carryover because the extracted value matched "
                    f"sibling non-location field(s): {', '.join(dict.fromkeys(contamination_sources))}."
                ),
            )


def _looks_like_phone_number(value: Any) -> bool:
    cleaned = _clean_text(value)
    if not cleaned or re.search(r"[A-Za-z]", cleaned):
        return False
    digits_only = re.sub(r"[^0-9]", "", cleaned)
    if len(digits_only) == 11 and digits_only.startswith("1"):
        digits_only = digits_only[1:]
    if len(digits_only) != 10:
        return False
    return bool(_PHONE_NUMBER_RE.fullmatch(cleaned) or digits_only.isdigit())


def _value_is_labeled_as_case_number(text: Any, value: Any) -> bool:
    cleaned_text = _clean_text(text)
    cleaned_value = _clean_text(value)
    if not cleaned_text or not cleaned_value:
        return False
    return bool(
        re.search(
            rf"(?i)(?:case\s*(?:number|no\.?))[^A-Za-z0-9]{{0,24}}{re.escape(cleaned_value)}",
            cleaned_text,
        )
    )


def _field_identity_tokens(target: Mapping[str, Any]) -> set[str]:
    combined = _normalize_hint_text(
        " ".join(
            str(part or "")
            for part in (
                target.get("field_name"),
                target.get("field_label"),
                target.get("answer_field_id"),
                target.get("questionnaire_field_id"),
                target.get("questionnaire_label"),
            )
        )
    )
    return {
        token
        for token in combined.split()
        if len(token) > 1 and token not in _FIELD_IDENTITY_STOPWORDS
    }


def _should_flag_duplicate_previous_result(
    previous_target: Mapping[str, Any],
    current_target: Mapping[str, Any],
    value: Any,
) -> bool:
    cleaned_value = _clean_text(value)
    if len(cleaned_value) < 4:
        return False

    previous_page = _safe_int(previous_target.get("page_number"))
    current_page = _safe_int(current_target.get("page_number"))
    if previous_page is not None and current_page is not None and previous_page != current_page:
        return False

    previous_field_type = _clean_text(previous_target.get("field_type")).lower()
    current_field_type = _clean_text(current_target.get("field_type")).lower()
    if previous_field_type in {"checkbox", "radio", "button"} or current_field_type in {"checkbox", "radio", "button"}:
        return False

    previous_question_id = _clean_text(previous_target.get("question_id"))
    current_question_id = _clean_text(current_target.get("question_id"))
    if previous_question_id and previous_question_id == current_question_id:
        return False

    previous_field_id = _clean_text(
        previous_target.get("questionnaire_field_id") or previous_target.get("answer_field_id")
    ).lower()
    current_field_id = _clean_text(
        current_target.get("questionnaire_field_id") or current_target.get("answer_field_id")
    ).lower()
    if previous_field_id and previous_field_id == current_field_id:
        return False

    for detector in (
        _looks_like_a_number_target,
        _looks_like_country_target,
        _looks_like_city_target,
        _looks_like_case_number_target,
        _looks_like_date_target,
    ):
        if detector(previous_target) and detector(current_target):
            return False

    previous_tokens = _field_identity_tokens(previous_target)
    current_tokens = _field_identity_tokens(current_target)
    if previous_tokens and current_tokens:
        shared_token_ratio = len(previous_tokens & current_tokens) / max(
            1,
            min(len(previous_tokens), len(current_tokens)),
        )
        if shared_token_ratio >= 0.5:
            return False

    return True


def _postprocess_result_sanity_checks(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: Mapping[str, Any],
) -> None:
    previous_target: Mapping[str, Any] | None = None
    previous_value = ""

    for target in targets:
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue

        current_value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
        if not current_value:
            continue

        if _looks_like_city_target(target) and _normalize_date_text(current_value):
            _flag_result_for_review(
                results_by_id,
                field_id,
                value="",
                justification=(
                    "Cleared city value because it looked like a date and may have been copied "
                    "from a nearby date field."
                ),
            )
            continue

        if _looks_like_case_number_target(target) and _looks_like_phone_number(current_value):
            evidence_text = _extract_plain_text_from_evidence(evidence_by_id.get(field_id))
            if not _value_is_labeled_as_case_number(evidence_text, current_value):
                _flag_result_for_review(
                    results_by_id,
                    field_id,
                    value="",
                    justification=(
                        "Cleared case number because the extracted value looked like a phone "
                        "number and was not explicitly labeled as a case number in the evidence."
                    ),
                )
                continue

        if (
            previous_target is not None
            and previous_value
            and current_value.lower() == previous_value.lower()
            and _should_flag_duplicate_previous_result(previous_target, target, current_value)
        ):
            _flag_result_for_review(
                results_by_id,
                field_id,
                justification=(
                    "Flagged for review because it duplicated the previous field unexpectedly, "
                    "which may indicate nearby-field carryover."
                ),
            )

        previous_target = target
        previous_value = current_value


_FORCED_NO_QUESTION_IDS: set[str] = {
    "p4_4a",
    "p4_7",
}

_FORCED_TEXT_ANSWERS: dict[str, str] = {
    "p6_1.interpreter_language": "Spanish",
    "p7_7.interpreter_fluent_language": "Spanish",
}

_FORCED_TEXT_FIELD_PATTERNS: list[tuple[str, list[str], list[str]]] = [
    (
        "p6_1.interpreter_language",
        ["language"],
        ["pt6", "part 6", "applicant statement", "1b", "1 b"],
    ),
    (
        "p7_7.interpreter_fluent_language",
        ["language"],
        ["pt7", "part 7", "interpreter", "certification", "fluent"],
    ),
]


def _postprocess_forced_no_questions(
    results_by_id: dict[str, dict[str, str]],
) -> None:
    for field_id in _FORCED_NO_QUESTION_IDS:
        if field_id in results_by_id:
            results_by_id[field_id] = {
                "id": field_id,
                "value": "no",
                "confidence": "high",
                "justification": "Forced to 'no' by policy.",
            }


def _match_forced_text_by_field_context(
    target: Mapping[str, Any],
) -> str:
    field_type = _clean_text(target.get("field_type")).lower()
    if field_type in {"checkbox", "radio", "button"}:
        return ""
    field_name_norm = _normalize_hint_text(target.get("id") or target.get("field_name"))
    label_norm = _normalize_hint_text(target.get("field_label"))
    nearby_norm = _normalize_hint_text(target.get("nearby_text"))
    combined = " ".join(part for part in (field_name_norm, label_norm, nearby_norm) if part)
    if not combined:
        return ""
    for forced_key, name_keywords, context_keywords in _FORCED_TEXT_FIELD_PATTERNS:
        if not any(kw in field_name_norm or kw in label_norm for kw in name_keywords):
            continue
        if any(kw in combined for kw in context_keywords):
            return forced_key
    return ""


def _postprocess_i914_forced_pdf_values(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
) -> set[str]:
    """Force policy-required values and return the set of PDF field IDs that were forced."""
    forced_field_ids: set[str] = set()
    applied_forced_keys: set[str] = set()

    for target in targets:
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        q_item_id = _clean_text(target.get("questionnaire_item_id")).lower()
        canonical_id = _clean_text(target.get("canonical_questionnaire_id")).lower()
        option_value = _normalize_option_answer(
            target.get("questionnaire_option_value")
        )
        field_type = _clean_text(target.get("field_type")).lower()

        if q_item_id in _FORCED_NO_QUESTION_IDS or canonical_id in _FORCED_NO_QUESTION_IDS:
            if field_type in {"checkbox", "radio", "button"}:
                pdf_value = "yes" if option_value == "no" else "off"
            else:
                pdf_value = "no"
            results_by_id[field_id] = {
                "id": field_id,
                "value": pdf_value,
                "confidence": "high",
                "justification": "Forced to 'No' by policy.",
            }
            forced_field_ids.add(field_id)
            continue

        for forced_key, forced_value in _FORCED_TEXT_ANSWERS.items():
            if canonical_id == forced_key or (
                "." in forced_key
                and q_item_id == forced_key.split(".")[0]
                and _clean_text(target.get("questionnaire_field_id")).lower()
                == forced_key.split(".", 1)[1]
            ):
                if field_type not in {"checkbox", "radio", "button"}:
                    results_by_id[field_id] = {
                        "id": field_id,
                        "value": forced_value,
                        "confidence": "high",
                        "justification": "Forced default by policy.",
                    }
                    forced_field_ids.add(field_id)
                    applied_forced_keys.add(forced_key)
                break

    remaining = {k: v for k, v in _FORCED_TEXT_ANSWERS.items() if k not in applied_forced_keys}
    if not remaining:
        return forced_field_ids

    for target in targets:
        if not remaining:
            break
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        matched_key = _match_forced_text_by_field_context(target)
        if matched_key and matched_key in remaining:
            results_by_id[field_id] = {
                "id": field_id,
                "value": remaining[matched_key],
                "confidence": "high",
                "justification": "Forced default by policy (field-context fallback).",
            }
            forced_field_ids.add(field_id)
            log.info(
                "Forced text fallback: field %r matched pattern for %r",
                field_id, matched_key,
            )
            del remaining[matched_key]

    return forced_field_ids


def _postprocess_autofill_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    _postprocess_a_number_results(targets, results_by_id, evidence_by_id)
    _postprocess_country_and_status_results(targets, results_by_id)
    _postprocess_address_results(targets, results_by_id, evidence_by_id)
    _postprocess_us_address_foreign_fields(targets, results_by_id)
    _postprocess_address_cross_check(targets, results_by_id)
    _postprocess_passport_date_results(targets, results_by_id, evidence_by_id)
    _clear_duplicate_safe_mailing_results(targets, results_by_id)
    _postprocess_result_sanity_checks(targets, results_by_id, evidence_by_id)
    _postprocess_forced_no_questions(results_by_id)
    return results_by_id


def _default_extraction_result(field_id: str, justification: str) -> dict[str, str]:
    return {
        "id": field_id,
        "value": "",
        "confidence": "low",
        "justification": justification,
    }


def _normalize_extraction_result_item(result: Mapping[str, Any]) -> dict[str, str]:
    return {
        "id": _clean_text(result.get("id")),
        "value": _clean_text(result.get("value")),
        "confidence": _clean_text(result.get("confidence")) or "low",
        "justification": _clean_text(result.get("justification")),
    }


def _extract_target_batch_with_fallback(
    batch: Sequence[Mapping[str, Any]],
    *,
    evidence_by_id: Mapping[str, Any],
    form_type: str,
    tracker: Any,
    batch_step_label: str,
    single_step_label_prefix: str,
    warning_message: str,
    warning_args: tuple[Any, ...],
    applicant_context: str = "",
) -> tuple[dict[str, dict[str, str]], int, dict[str, int]]:
    settings = get_rag_settings()
    extraction_error_count = 0
    error_breakdown: Counter[str] = Counter()

    def _extract_single_fallback(item_index: int, target: Mapping[str, Any]) -> tuple[dict[str, str], int, dict[str, int]]:
        field_id = _clean_text(target.get("id"))
        try:
            single = extract_field_value(
                target,
                evidence_by_id.get(field_id),
                form_type=form_type,
                tracker=tracker,
                step_label=f"{single_step_label_prefix}-{item_index}",
            )
            return {"id": field_id, **single}, 0, {}
        except Exception as single_exc:
            exc_type = type(single_exc).__name__
            log.warning(
                "[FORM_FILL] Field extraction failed form_type=%s field_id=%s provider=%s exc_type=%s error=%s",
                form_type,
                field_id,
                getattr(settings, "extraction_provider", ""),
                exc_type,
                _truncate_log_value(single_exc),
            )
            return (
                _default_extraction_result(
                    field_id,
                    f"Field extraction failed: {single_exc}",
                ),
                1,
                {exc_type: 1},
            )

    def _extract_singles_parallel() -> tuple[list[dict[str, str]], int, dict[str, int]]:
        single_results: list[dict[str, str]] = []
        single_error_count = 0
        single_error_breakdown: Counter[str] = Counter()
        max_workers = max(
            1,
            min(
                len(batch),
                int(getattr(settings, "autopilot_llm_batch_concurrency", 1) or 1),
            ),
        )
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(_extract_single_fallback, item_index, target)
                for item_index, target in enumerate(batch, start=1)
            ]
            for future in as_completed(futures):
                result, error_count, future_breakdown = future.result()
                single_results.append(result)
                single_error_count += error_count
                single_error_breakdown.update(future_breakdown)
        return single_results, single_error_count, dict(single_error_breakdown)

    if getattr(settings, "extraction_provider", "") == "anthropic":
        batch_results, extraction_error_count, batch_error_breakdown = _extract_singles_parallel()
        error_breakdown.update(batch_error_breakdown)
    else:
        batch_results = []
        try:
            batch_results = extract_field_values_batch(
                batch,
                evidence_by_id,
                form_type=form_type,
                tracker=tracker,
                step_label=batch_step_label,
                applicant_context=applicant_context,
            )
        except Exception as exc:
            log.warning(warning_message, *warning_args, exc)
            batch_results, extraction_error_count, batch_error_breakdown = _extract_singles_parallel()
            error_breakdown.update(batch_error_breakdown)

    batch_by_id = {
        normalized["id"]: normalized
        for normalized in (
            _normalize_extraction_result_item(result)
            for result in batch_results
        )
        if normalized["id"]
    }
    return batch_by_id, extraction_error_count, dict(error_breakdown)


def _extract_values_for_targets_sync(
    targets: list[dict[str, Any]],
    *,
    evidence_by_id: dict[str, Any],
    form_type: str,
    tracker: Any,
    applicant_context: str = "",
    progress_callback: AutofillProgressCallback | None = None,
    progress_start_pct: float = 55.0,
    progress_end_pct: float = 88.0,
    progress_label: str = "Extracting values",
) -> tuple[dict[str, dict[str, str]], int, dict[str, int]]:
    settings = get_rag_settings()
    results_by_id: dict[str, dict[str, str]] = {}
    extraction_error_count = 0
    error_breakdown: Counter[str] = Counter()

    skipped_targets = [target for target in targets if _skip_reason(target)]
    extractable_targets = [target for target in targets if not _skip_reason(target)]

    for target in skipped_targets:
        field_id = _clean_text(target.get("id"))
        results_by_id[field_id] = _default_extraction_result(field_id, _skip_reason(target))

    total_extractable = max(1, len(extractable_targets))
    processed_extractable = 0
    if progress_callback is not None:
        progress_callback(progress_start_pct, f"{progress_label} (0/{total_extractable})")
    for batch_index, batch in enumerate(_chunked(extractable_targets, settings.autopilot_batch_size), start=1):
        if progress_callback is not None:
            progress_callback(
                progress_start_pct + (
                    (progress_end_pct - progress_start_pct)
                    * (processed_extractable / total_extractable)
                ),
                f"{progress_label}...",
            )
        batch_by_id, batch_error_count, batch_error_breakdown = _extract_target_batch_with_fallback(
            batch,
            evidence_by_id=evidence_by_id,
            form_type=form_type,
            tracker=tracker,
            batch_step_label=f"questionnaire-autofill-batch-{batch_index}",
            single_step_label_prefix=f"questionnaire-autofill-single-{batch_index}",
            warning_message=(
                "Questionnaire autofill batch extraction failed for batch %d. "
                "Falling back to single extraction: %s"
            ),
            warning_args=(batch_index,),
            applicant_context=applicant_context,
        )
        extraction_error_count += batch_error_count
        error_breakdown.update(batch_error_breakdown)
        processed_extractable += len(batch)
        dominant_error = _dominant_extraction_error(error_breakdown, processed_extractable)
        if dominant_error is not None:
            exc_type, error_count = dominant_error
            raise ExtractionCircuitBreakerOpen(
                exc_type=exc_type,
                error_count=error_count,
                processed_count=processed_extractable,
                total_targets=len(extractable_targets),
                provider=getattr(settings, "extraction_provider", ""),
            )
        if progress_callback is not None:
            pct = progress_start_pct + (
                (progress_end_pct - progress_start_pct)
                * (processed_extractable / total_extractable)
            )
            progress_callback(
                pct,
                f"{progress_label} ({processed_extractable}/{total_extractable})",
            )

        for target in batch:
            field_id = _clean_text(target.get("id"))
            results_by_id[field_id] = batch_by_id.get(
                field_id,
                _default_extraction_result(
                    field_id,
                    "No extraction result was returned for this field.",
                ),
            )

    processed_results = _postprocess_autofill_results(targets, results_by_id, evidence_by_id)
    _postprocess_compound_name_results(targets, processed_results)
    if _normalize_form_type(form_type) == "i-914":
        _postprocess_i914_family_roster(targets, processed_results, evidence_by_id)
    return processed_results, extraction_error_count, dict(error_breakdown)


_AUTOFILL_MIN_CONFIDENCE = "medium"
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def _build_autofill_answer_map(
    targets: list[dict[str, Any]],
    results_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], int, dict[str, Any], int]:
    answers: dict[str, Any] = {}
    confidence_map: dict[str, Any] = {}
    suggested_count = 0
    skipped_low = 0
    min_rank = _CONFIDENCE_RANK.get(_AUTOFILL_MIN_CONFIDENCE, 2)

    indexed_repeatable_buckets: dict[str, dict[int, dict[str, str]]] = {}
    indexed_repeatable_conf: dict[str, dict[int, dict[str, str]]] = {}
    unindexed_repeatable_buckets: dict[str, dict[str, str]] = {}
    unindexed_repeatable_conf: dict[str, dict[str, str]] = {}

    for target in targets:
        field_id = _clean_text(target.get("id"))
        result = results_by_id.get(field_id) or {}
        value = _clean_text(result.get("value"))
        confidence = _clean_text(result.get("confidence")).lower() or "low"
        if not value:
            continue

        question_id = _clean_text(target.get("question_id"))
        is_family_field = question_id.startswith("p5_1") or question_id.startswith("p5_children")
        effective_min_rank = 1 if is_family_field else min_rank
        if _CONFIDENCE_RANK.get(confidence, 0) < effective_min_rank:
            skipped_low += 1
            continue

        answer_field_id = _clean_text(target.get("answer_field_id"))
        if not question_id:
            continue

        is_repeatable = bool(target.get("is_repeatable_first_slot"))
        slot_index = target.get("repeatable_slot_index")

        if is_repeatable and answer_field_id:
            if slot_index is not None:
                indexed_repeatable_buckets.setdefault(question_id, {}).setdefault(slot_index, {})[answer_field_id] = value
                indexed_repeatable_conf.setdefault(question_id, {}).setdefault(slot_index, {})[answer_field_id] = confidence
            else:
                unindexed_repeatable_buckets.setdefault(question_id, {})[answer_field_id] = value
                unindexed_repeatable_conf.setdefault(question_id, {})[answer_field_id] = confidence
            suggested_count += 1
            continue

        if answer_field_id:
            existing = answers.get(question_id)
            if not isinstance(existing, dict):
                existing = {}
            existing[answer_field_id] = value
            answers[question_id] = existing

            existing_conf = confidence_map.get(question_id)
            if not isinstance(existing_conf, dict):
                existing_conf = {}
            existing_conf[answer_field_id] = confidence
            confidence_map[question_id] = existing_conf
        else:
            answers[question_id] = value
            confidence_map[question_id] = confidence
        suggested_count += 1

    for question_id, slots in indexed_repeatable_buckets.items():
        rows: list[dict[str, str]] = []
        conf_rows: list[dict[str, str]] = []
        for idx in sorted(slots):
            row = slots[idx]
            if any(_clean_text(v) for v in row.values()):
                rows.append(row)
                conf_rows.append(indexed_repeatable_conf.get(question_id, {}).get(idx, {}))
        if rows:
            answers[question_id] = rows
            confidence_map[question_id] = conf_rows

    for question_id, row_data in unindexed_repeatable_buckets.items():
        if question_id in answers:
            continue
        if row_data:
            answers[question_id] = [row_data]
            conf_row = unindexed_repeatable_conf.get(question_id, {})
            confidence_map[question_id] = [conf_row]

    return answers, suggested_count, confidence_map, skipped_low


def _detect_principal_applicant_name(
    case_id: str,
    tracker: Any,
    *,
    source_document_ids: list[str] | None = None,
) -> str:
    """Identify the principal applicant name from the earliest form pages via Pinecone."""
    import re as _re
    try:
        bundle = collect_evidence_bundle_for_question(
            PRINCIPAL_APPLICANT_SEARCH_QUERY,
            case_id=case_id,
            source_document_ids=source_document_ids,
            top_k=8,
            max_context_chars=4000,
            tracker=tracker,
            document_fallback_enabled=False if source_document_ids is not None else None,
        )
        matches = bundle.get("matches") or []
        for m in sorted(matches, key=lambda x: (x.get("metadata") or {}).get("page_number", 9999)):
            txt = (m.get("metadata") or {}).get("text", "")
            fam = _re.search(r'Family Name[^:]*?Respuesta:\s*([^\n]+)', txt)
            giv = _re.search(r'Given Name[^:]*?Respuesta:\s*([^\n]+)', txt)
            if fam and giv:
                fn = fam.group(1).strip()
                gn = giv.group(1).strip()
                blanks = {"", "[ ]", "(vacio)", "N/A", "None"}
                if fn not in blanks and gn not in blanks:
                    return f"{gn} {fn}"
    except Exception as exc:
        log.debug("Could not detect principal applicant name: %s", exc)
    return ""


def _detect_case_form_type(db: Session, case_id: str) -> str:
    row = (
        db.query(FormFillingJob.form_type)
        .filter(FormFillingJob.case_id == case_id, FormFillingJob.form_type.isnot(None))
        .first()
    )
    if row and _clean_text(row[0]):
        return _clean_text(row[0])
    from ..models import QuestionnaireAnswer
    row = (
        db.query(QuestionnaireAnswer.form_type)
        .filter(
            QuestionnaireAnswer.case_id == case_id,
            QuestionnaireAnswer.form_type.isnot(None),
            QuestionnaireAnswer.form_type != "",
        )
        .first()
    )
    if row and _clean_text(row[0]):
        return _clean_text(row[0])
    return ""


def autofill_shared_questionnaire(
    db: Session,
    case_id: str,
    *,
    progress_callback: AutofillProgressCallback | None = None,
) -> dict[str, Any]:
    tracker = create_token_tracker()
    source_document_ids = _get_source_document_ids(db, case_id)
    pages = _load_case_pages(
        db,
        case_id,
        source_document_ids=source_document_ids,
    )
    readiness = _summarize_case_page_readiness(pages)

    if readiness["total_pages"] <= 0:
        if source_document_ids is not None:
            raise ValueError(
                "No documents are selected for form filling. Choose at least one case document in the forms panel."
            )
        raise ValueError(
            "No case pages are available. Upload the supporting documents before using OCR autofill."
        )

    if readiness["missing_ocr_pages"] > 0:
        if not is_ocr_configured():
            raise RuntimeError(
                "GEMINI_API_KEY is required to run OCR autofill on the client questionnaire."
            )
        _launch_background_ocr_if_needed(
            case_id,
            page_ids=[page.id for page in pages] if source_document_ids is not None else None,
            missing_count=readiness["missing_ocr_pages"],
        )
        db.expire_all()
        pages = _load_case_pages(
            db,
            case_id,
            source_document_ids=source_document_ids,
        )
        readiness = _summarize_case_page_readiness(pages)

    if readiness["usable_ocr_pages"] <= 0:
        raise ValueError(
            "Automatic OCR completed, but no usable text is available for the selected form-filling documents."
            if source_document_ids is not None
            else "Automatic OCR completed, but no usable document text is available to autofill the client questionnaire."
        )

    if is_indexing_available() and readiness.get("needs_index_pages", 0) > 0:
        if progress_callback is not None:
            progress_callback(10.0, "Preparing evidence search...")
        log.info(
            "Shared autofill: indexing %d pending pages for case %s",
            readiness["needs_index_pages"],
            case_id[:8],
        )
        with case_pipeline_lock(case_id, timeout=120):
            index_case_ocr_json(case_id, tracker=tracker)

    if progress_callback is not None:
        progress_callback(15.0, "Detecting case context...")

    form_type = _detect_case_form_type(db, case_id)

    detected_name = _detect_principal_applicant_name(
        case_id,
        tracker,
        source_document_ids=source_document_ids,
    )
    if not detected_name:
        case_row = db.query(Case).filter(Case.id == case_id).first()
        detected_name = _clean_text(case_row.name) if case_row else ""

    applicant_context = build_applicant_context_instruction(detected_name)

    shared_pages = get_shared_questions()
    targets = _build_shared_autofill_targets(shared_pages)
    if not targets:
        return {"answers": {}, "total_targets": 0, "suggested_count": 0, "confidence_map": {}, "skipped_low_confidence": 0}

    evidence_by_id = _collect_evidence_for_targets_sync(
        targets,
        case_id=case_id,
        tracker=tracker,
        source_document_ids=source_document_ids,
        progress_callback=progress_callback,
        progress_start_pct=20.0,
        progress_end_pct=38.0,
        progress_label="Searching for client information",
    )
    results_by_id, extraction_error_count, extraction_error_breakdown = _extract_values_for_targets_sync(
        targets,
        evidence_by_id=evidence_by_id,
        form_type=form_type,
        tracker=tracker,
        applicant_context=applicant_context,
        progress_callback=progress_callback,
        progress_start_pct=38.0,
        progress_end_pct=52.0,
        progress_label="Completing client answers",
    )
    answers, suggested_count, confidence_map, skipped_low = _build_autofill_answer_map(targets, results_by_id)

    from .verification_service import verify_autofill_batch
    if progress_callback is not None:
        progress_callback(54.0, "Reviewing suggested answers...")
    verification_map = verify_autofill_batch(
        results_by_id=results_by_id,
        evidence_by_id=evidence_by_id,
        targets=targets,
    )

    if extraction_error_count:
        log.warning(
            "Questionnaire shared autofill finished with %d extraction errors for case %s breakdown=%s",
            extraction_error_count,
            case_id,
            extraction_error_breakdown,
        )
    if skipped_low:
        log.info(
            "Shared autofill: skipped %d low-confidence results for case %s",
            skipped_low,
            case_id[:8],
        )

    form_answers: dict[str, dict[str, Any]] = {}
    form_confidence_map: dict[str, dict[str, Any]] = {}
    form_verification_map: dict[str, dict[str, Any]] = {}
    form_suggested_total = 0
    form_skipped_total = 0
    form_total_targets = 0

    form_types = list(available_form_types())
    form_segment_size = 33.0 / max(1, len(form_types))
    for form_index, ft in enumerate(form_types, start=1):
        try:
            ft_pages = get_form_client_questions(ft)
        except (FileNotFoundError, ValueError):
            continue
        ft_targets = _build_shared_autofill_targets(ft_pages)
        if not ft_targets:
            continue
        form_total_targets += len(ft_targets)
        log.info(
            "Autofill: processing %d form-specific targets for %s (case %s)",
            len(ft_targets), ft, case_id[:8],
        )
        segment_start = 55.0 + ((form_index - 1) * form_segment_size)
        segment_end = 55.0 + (form_index * form_segment_size)
        segment_mid = segment_start + ((segment_end - segment_start) * 0.45)
        ft_evidence = _collect_evidence_for_targets_sync(
            ft_targets,
            case_id=case_id,
            tracker=tracker,
            source_document_ids=source_document_ids,
            progress_callback=progress_callback,
            progress_start_pct=segment_start,
            progress_end_pct=segment_mid,
            progress_label=f"Searching for {ft.upper()} information",
        )
        ft_results, ft_errors, ft_error_breakdown = _extract_values_for_targets_sync(
            ft_targets,
            evidence_by_id=ft_evidence,
            form_type=ft,
            tracker=tracker,
            applicant_context=applicant_context,
            progress_callback=progress_callback,
            progress_start_pct=segment_mid,
            progress_end_pct=segment_end,
            progress_label=f"Completing {ft.upper()} answers",
        )
        ft_ans, ft_ct, ft_cf, ft_sk = _build_autofill_answer_map(ft_targets, ft_results)
        ft_verification = verify_autofill_batch(
            results_by_id=ft_results,
            evidence_by_id=ft_evidence,
            targets=ft_targets,
        )
        if ft_ans and ft.lower() in {"i914", "i-914"}:
            try:
                _apply_i914_family_roster_override(ft_ans, ft_targets, ft_evidence)
            except Exception as exc:
                log.warning(
                    "[FORM_FILL] i914 family roster override failed for case %s: %s",
                    case_id[:8],
                    exc,
                )
        if ft_ans:
            form_answers[ft] = ft_ans
            form_confidence_map[ft] = ft_cf
        if ft_verification:
            form_verification_map[ft] = ft_verification
        form_suggested_total += ft_ct
        form_skipped_total += ft_sk
        if ft_errors:
            log.warning(
                "Autofill %s: %d extraction errors for case %s breakdown=%s",
                ft, ft_errors, case_id[:8], ft_error_breakdown,
            )

    total_suggested = suggested_count + form_suggested_total
    total_skipped = skipped_low + form_skipped_total
    total_targets = len(targets) + form_total_targets

    if verification_map or form_verification_map:
        try:
            if progress_callback is not None:
                progress_callback(90.0, "Saving suggested answers...")
            save_questionnaire_verifications(
                db,
                case_id,
                verification_map=verification_map,
                form_verification_map=form_verification_map,
            )
        except Exception as exc:
            log.warning("Failed to persist shared verification metadata for case %s: %s", case_id[:8], exc)

    log_token_summary(tracker, label=f"Questionnaire autofill {case_id[:8]}", logger=log)
    return {
        "answers": answers,
        "total_targets": total_targets,
        "suggested_count": total_suggested,
        "confidence_map": confidence_map,
        "skipped_low_confidence": total_skipped,
        "form_answers": form_answers,
        "form_confidence_map": form_confidence_map,
        "verification_map": verification_map,
        "form_verification_map": form_verification_map,
    }


def autofill_attorney_questionnaire(
    db: Session,
    case_id: str,
    *,
    progress_callback: AutofillProgressCallback | None = None,
) -> dict[str, Any]:
    tracker = create_token_tracker()
    source_document_ids = _get_source_document_ids(db, case_id)
    pages = _load_case_pages(
        db,
        case_id,
        source_document_ids=source_document_ids,
    )
    readiness = _summarize_case_page_readiness(pages)

    if readiness["total_pages"] <= 0:
        if source_document_ids is not None:
            raise ValueError(
                "No documents are selected for form filling. Choose at least one case document in the forms panel."
            )
        raise ValueError(
            "No case pages are available. Upload the supporting documents before using OCR autofill."
        )

    if readiness["missing_ocr_pages"] > 0:
        if not is_ocr_configured():
            raise RuntimeError(
                "GEMINI_API_KEY is required to run OCR autofill on the attorney questionnaire."
            )
        _launch_background_ocr_if_needed(
            case_id,
            page_ids=[page.id for page in pages] if source_document_ids is not None else None,
            missing_count=readiness["missing_ocr_pages"],
        )
        db.expire_all()
        pages = _load_case_pages(
            db,
            case_id,
            source_document_ids=source_document_ids,
        )
        readiness = _summarize_case_page_readiness(pages)

    if readiness["usable_ocr_pages"] <= 0:
        raise ValueError(
            "Automatic OCR completed, but no usable text is available for the selected form-filling documents."
            if source_document_ids is not None
            else "Automatic OCR completed, but no usable document text is available to autofill the attorney questionnaire."
        )

    if is_indexing_available() and readiness.get("needs_index_pages", 0) > 0:
        if progress_callback is not None:
            progress_callback(10.0, "Preparing evidence search...")
        log.info(
            "Attorney autofill: indexing %d pending pages for case %s",
            readiness["needs_index_pages"],
            case_id[:8],
        )
        with case_pipeline_lock(case_id, timeout=120):
            index_case_ocr_json(case_id, tracker=tracker)

    if progress_callback is not None:
        progress_callback(15.0, "Detecting case context...")

    form_type = _detect_case_form_type(db, case_id)

    detected_name = _detect_principal_applicant_name(
        case_id,
        tracker,
        source_document_ids=source_document_ids,
    )
    if not detected_name:
        case_row = db.query(Case).filter(Case.id == case_id).first()
        detected_name = _clean_text(case_row.name) if case_row else ""

    applicant_context = build_applicant_context_instruction(detected_name)

    from .verification_service import verify_autofill_batch

    form_answers: dict[str, dict[str, Any]] = {}
    form_confidence_map: dict[str, dict[str, Any]] = {}
    form_verification_map: dict[str, dict[str, Any]] = {}
    form_suggested_total = 0
    form_skipped_total = 0
    form_total_targets = 0

    form_types = list(available_form_types())
    form_segment_size = 73.0 / max(1, len(form_types))
    for form_index, ft in enumerate(form_types, start=1):
        try:
            ft_pages = get_form_attorney_questions(ft)
        except (FileNotFoundError, ValueError):
            continue
        ft_targets = _build_attorney_autofill_targets(ft_pages)
        if not ft_targets:
            continue
        form_total_targets += len(ft_targets)
        log.info(
            "Attorney autofill: processing %d targets for %s (case %s)",
            len(ft_targets), ft, case_id[:8],
        )
        segment_start = 15.0 + ((form_index - 1) * form_segment_size)
        segment_end = 15.0 + (form_index * form_segment_size)
        segment_mid = segment_start + ((segment_end - segment_start) * 0.45)
        ft_evidence = _collect_evidence_for_targets_sync(
            ft_targets,
            case_id=case_id,
            tracker=tracker,
            source_document_ids=source_document_ids,
            progress_callback=progress_callback,
            progress_start_pct=segment_start,
            progress_end_pct=segment_mid,
            progress_label=f"Searching for {ft.upper()} information",
        )
        ft_results, ft_errors, ft_error_breakdown = _extract_values_for_targets_sync(
            ft_targets,
            evidence_by_id=ft_evidence,
            form_type=ft,
            tracker=tracker,
            applicant_context=applicant_context,
            progress_callback=progress_callback,
            progress_start_pct=segment_mid,
            progress_end_pct=segment_end,
            progress_label=f"Completing {ft.upper()} answers",
        )
        ft_ans, ft_ct, ft_cf, ft_sk = _build_autofill_answer_map(ft_targets, ft_results)
        ft_verification = verify_autofill_batch(
            results_by_id=ft_results,
            evidence_by_id=ft_evidence,
            targets=ft_targets,
        )
        if ft_ans:
            form_answers[ft] = ft_ans
            form_confidence_map[ft] = ft_cf
        if ft_verification:
            form_verification_map[ft] = ft_verification
        form_suggested_total += ft_ct
        form_skipped_total += ft_sk
        if ft_errors:
            log.warning(
                "Attorney autofill %s: %d extraction errors for case %s breakdown=%s",
                ft, ft_errors, case_id[:8], ft_error_breakdown,
            )

    all_answers: dict[str, Any] = {}
    all_confidence: dict[str, Any] = {}
    all_verification: dict[str, Any] = {}
    for ft_ans in form_answers.values():
        all_answers.update(ft_ans)
    for ft_cf in form_confidence_map.values():
        all_confidence.update(ft_cf)
    for ft_vf in form_verification_map.values():
        all_verification.update(ft_vf)

    if all_verification or form_verification_map:
        try:
            if progress_callback is not None:
                progress_callback(90.0, "Saving suggested answers...")
            save_questionnaire_verifications(
                db,
                case_id,
                verification_map=all_verification,
                form_verification_map=form_verification_map,
            )
        except Exception as exc:
            log.warning("Failed to persist attorney verification metadata for case %s: %s", case_id[:8], exc)

    log_token_summary(tracker, label=f"Attorney autofill {case_id[:8]}", logger=log)
    return {
        "answers": all_answers,
        "total_targets": form_total_targets,
        "suggested_count": form_suggested_total,
        "confidence_map": all_confidence,
        "skipped_low_confidence": form_skipped_total,
        "form_answers": form_answers,
        "form_confidence_map": form_confidence_map,
        "verification_map": all_verification,
        "form_verification_map": form_verification_map,
    }


def _build_questionnaire_index(form_type: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for definition in list_questionnaire_field_definitions(form_type):
        canonical_id = _clean_text(definition.get("canonical_questionnaire_id"))
        if not canonical_id:
            continue
        bucket = index.setdefault(
            canonical_id,
            {"base": None, "options": [], "definitions": []},
        )
        normalized = dict(definition)
        bucket["definitions"].append(normalized)

        option_value = _clean_text(normalized.get("option_value"))
        option_label = _clean_text(normalized.get("option_label"))
        if option_value or option_label:
            option = {
                "value": option_value or option_label,
                "label": option_label or option_value,
            }
            if option not in bucket["options"]:
                bucket["options"].append(option)

        if bucket["base"] is None or (not option_value and not option_label):
            bucket["base"] = normalized

    for bucket in index.values():
        if bucket["base"] is None and bucket["definitions"]:
            bucket["base"] = dict(bucket["definitions"][0])
    return index


def _resolve_option_label(bundle: Mapping[str, Any], option_value: str) -> str:
    target = _clean_text(option_value)
    if not target:
        return ""
    for option in bundle.get("options", []) or []:
        value = _clean_text(option.get("value"))
        label = _clean_text(option.get("label"))
        if value.lower() == target.lower():
            return label or value
    return target


def _looks_like_yes_no_pdf_field(pdf_field: Mapping[str, Any]) -> bool:
    field_type = _clean_text(pdf_field.get("field_type")).lower()
    if field_type not in {"checkbox", "radio", "button"}:
        return False

    field_name = _normalize_hint_text(pdf_field.get("field_name"))
    field_label = _normalize_hint_text(pdf_field.get("field_label"))
    nearby_text = _normalize_hint_text(pdf_field.get("nearby_text"))
    combined = " | ".join(part for part in [field_name, field_label, nearby_text] if part)
    if not combined:
        return False

    return (
        bool(re.search(r"\b(?:yes|no)\b", field_name))
        or "select yes" in field_label
        or "select no" in field_label
        or "yes | no" in nearby_text
        or "no | yes" in nearby_text
    )


def _fallback_yes_no_mapping(
    pdf_field: Mapping[str, Any],
    questionnaire_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not _looks_like_yes_no_pdf_field(pdf_field):
        return {}

    field_label = _normalize_hint_text(pdf_field.get("field_label"))
    nearby_text = _normalize_hint_text(pdf_field.get("nearby_text"))
    combined_text = " | ".join(part for part in [field_label, nearby_text] if part)
    if not combined_text:
        return {}
    field_label_tokens = {
        token
        for token in field_label.split()
        if token and (len(token) > 1 or token in {"a", "b", "c"})
    }
    nearby_tokens = {
        token
        for token in nearby_text.split()
        if token and (len(token) > 1 or token in {"a", "b", "c"})
    }
    combined_tokens = {
        token
        for token in combined_text.split()
        if token and (len(token) > 1 or token in {"a", "b", "c"})
    }

    pdf_page = _safe_int(pdf_field.get("page_number")) or 0
    candidates: list[tuple[tuple[int, int, int], str, Mapping[str, Any], Mapping[str, Any]]] = []
    for canonical_id, bundle in questionnaire_index.items():
        base = bundle.get("base") or {}
        if _clean_text(base.get("item_type")).lower() != "yes_no":
            continue

        candidate_phrases = [
            _normalize_hint_text(base.get("form_text")),
            _normalize_hint_text(base.get("label")),
        ]
        matched_phrase = ""
        matched_label_token_count = 0
        matched_token_count = 0
        matched_ratio = 0.0
        for phrase in candidate_phrases:
            if not phrase:
                continue
            candidate_tokens = {
                token
                for token in phrase.split()
                if token and (len(token) > 1 or token in {"a", "b", "c"})
            }
            if not candidate_tokens:
                continue
            shared_label_tokens = candidate_tokens & field_label_tokens
            shared_nearby_tokens = candidate_tokens & nearby_tokens
            shared_tokens = shared_label_tokens | shared_nearby_tokens
            token_ratio = len(shared_tokens) / len(candidate_tokens)
            if phrase in combined_text:
                token_ratio = 1.0
            if token_ratio < 0.72:
                continue
            if (
                len(shared_label_tokens) > matched_label_token_count
                or (
                    len(shared_label_tokens) == matched_label_token_count
                    and len(shared_tokens) > matched_token_count
                )
                or (
                    len(shared_label_tokens) == matched_label_token_count
                    and len(shared_tokens) == matched_token_count
                    and token_ratio > matched_ratio
                )
                or (
                    len(shared_label_tokens) == matched_label_token_count
                    and len(shared_tokens) == matched_token_count
                    and token_ratio == matched_ratio
                    and len(phrase) > len(matched_phrase)
                )
            ):
                matched_phrase = phrase
                matched_label_token_count = len(shared_label_tokens)
                matched_token_count = len(shared_tokens)
                matched_ratio = token_ratio
        if not matched_phrase:
            continue

        definition_page = _safe_int(base.get("page_number")) or 0
        page_score = 2 if pdf_page and definition_page and pdf_page == definition_page else 0
        near_page_score = 1 if pdf_page and definition_page and abs(pdf_page - definition_page) <= 1 else 0
        score = (
            matched_label_token_count,
            matched_token_count,
            int(round(matched_ratio * 100)),
            len(matched_phrase),
            page_score + near_page_score,
        )
        candidates.append((score, canonical_id, bundle, base))

    if not candidates:
        return {}

    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return {}

    _, canonical_id, bundle, base = candidates[0]
    inferred_option_value = _infer_target_option_value(
        {
            "field_name": _clean_text(pdf_field.get("field_name")),
            "field_label": _clean_text(pdf_field.get("field_label")),
            "questionnaire_options": list(bundle.get("options", []) or []),
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
        }
    ) or None
    return {
        "questionnaire_item_id": _clean_text(base.get("item_id")) or None,
        "questionnaire_field_id": _clean_text(base.get("field_id")) or None,
        "questionnaire_option_value": inferred_option_value,
        "canonical_questionnaire_id": canonical_id or None,
        "matched_label": _clean_text(base.get("label") or base.get("form_text")) or None,
        "matched_section": _clean_text(base.get("section")) or None,
        "matched_responsible_party": _clean_text(base.get("responsible_party")) or None,
        "source_file": _clean_text(base.get("source_file")) or None,
    }


def _fallback_i914_part3_reporting(
    pdf_field: Mapping[str, Any],
    questionnaire_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    field_type = _clean_text(pdf_field.get("field_type")).lower()
    if field_type in {"checkbox", "radio", "button"}:
        return {}

    field_name_text = _normalize_hint_text(pdf_field.get("field_name"))
    name_and_label_text = " | ".join(
        part
        for part in (
            field_name_text,
            _normalize_hint_text(pdf_field.get("field_label")),
        )
        if part
    )
    combined_text = " | ".join(
        part
        for part in (
            name_and_label_text,
            _normalize_hint_text(pdf_field.get("nearby_text")),
        )
        if part
    )
    if not combined_text:
        return {}
    if "law enforcement agency and office" not in combined_text:
        return {}
    if "part 3" not in combined_text and "p3 line5" not in combined_text:
        return {}

    canonical_id = ""
    if "circumstances" in name_and_label_text:
        canonical_id = "p3_5.lea_circumstances"
    elif "city or town" in name_and_label_text:
        canonical_id = "p3_5.lea_city"
    elif "case number" in name_and_label_text:
        canonical_id = "p3_5.lea_case_number"
    elif "daytime telephone" in name_and_label_text or "telephone number" in name_and_label_text:
        canonical_id = "p3_5.lea_daytime_telephone"
    elif "zip code" in name_and_label_text:
        canonical_id = "p3_5.lea_zip_code"
    elif "street" in name_and_label_text and "number" in name_and_label_text:
        canonical_id = "p3_5.lea_street_number_name"
    elif (
        "state" in name_and_label_text
        and "statement" not in name_and_label_text
        and "united states" not in name_and_label_text
    ):
        canonical_id = "p3_5.lea_state"
    elif "agency and office" in name_and_label_text or "agency office" in name_and_label_text:
        canonical_id = "p3_5.lea_agency_office"
    if not canonical_id:
        return {}

    bundle = questionnaire_index.get(canonical_id) or {}
    base = dict(bundle.get("base") or {})
    if not base:
        return {}
    return {
        "questionnaire_item_id": _clean_text(base.get("item_id")) or None,
        "questionnaire_field_id": _clean_text(base.get("field_id")) or None,
        "questionnaire_option_value": None,
        "canonical_questionnaire_id": canonical_id,
        "matched_label": _clean_text(base.get("label") or base.get("form_text")) or None,
        "matched_section": _clean_text(base.get("section")) or None,
        "matched_responsible_party": _clean_text(base.get("responsible_party")) or None,
        "source_file": _clean_text(base.get("source_file")) or None,
    }


def _fallback_i914_entry_mapping(
    pdf_field: Mapping[str, Any],
    questionnaire_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    field_type = _clean_text(pdf_field.get("field_type")).lower()
    if field_type in {"checkbox", "radio", "button"}:
        return {}

    field_name_text = _normalize_hint_text(pdf_field.get("field_name"))
    label_text = _normalize_hint_text(pdf_field.get("field_label"))
    nearby_text = _normalize_hint_text(pdf_field.get("nearby_text"))
    name_and_label_text = " | ".join(part for part in (field_name_text, label_text) if part)
    combined_text = " | ".join(part for part in (name_and_label_text, nearby_text) if part)
    if not combined_text:
        return {}

    is_last_entry_block = (
        "last entry into the united states" in combined_text
        or "place of your last entry into the united states" in combined_text
        or "date of your last entry into the united states" in combined_text
    )
    is_prior_entry_block = (
        "part 3" in combined_text
        and (
            "this is the first time i have entered the united states" in combined_text
            or "place of entry" in combined_text
            or "date of entry" in combined_text
            or "past five years" in combined_text
        )
    )

    canonical_id = ""
    if is_last_entry_block:
        if "city or town" in name_and_label_text:
            canonical_id = "p2_last_entry.last_entry_city"
        elif "state" in name_and_label_text:
            canonical_id = "p2_last_entry.last_entry_state"
    elif is_prior_entry_block:
        if "date of entry" in name_and_label_text:
            canonical_id = "p3_8.prior_entry_date"
        elif "city or town" in name_and_label_text:
            canonical_id = "p3_8.prior_entry_city"
        elif "state" in name_and_label_text:
            canonical_id = "p3_8.prior_entry_state"
        elif "status" in name_and_label_text:
            canonical_id = "p3_8.prior_entry_status"

    if not canonical_id:
        return {}

    bundle = questionnaire_index.get(canonical_id) or {}
    base = dict(bundle.get("base") or {})
    if not base:
        return {}

    return {
        "questionnaire_item_id": _clean_text(base.get("item_id")) or None,
        "questionnaire_field_id": _clean_text(base.get("field_id")) or None,
        "questionnaire_option_value": None,
        "canonical_questionnaire_id": canonical_id,
        "matched_label": _clean_text(base.get("label") or base.get("form_text")) or None,
        "matched_section": _clean_text(base.get("section")) or None,
        "matched_responsible_party": _clean_text(base.get("responsible_party")) or None,
        "source_file": _clean_text(base.get("source_file")) or None,
    }


def _yes_no_pair_group_key(field_name: Any) -> str:
    normalized = _clean_text(field_name).lower()
    if not normalized:
        return ""
    return re.sub(r"_(?:yes|no)\[\d+\]$", "", normalized)


def _apply_questionnaire_bundle_to_target(
    target: dict[str, Any],
    *,
    form_type: str,
    canonical_id: str,
    bundle: Mapping[str, Any],
) -> None:
    base = dict(bundle.get("base") or {})
    if not base:
        return

    target["questionnaire_item_id"] = _clean_text(base.get("item_id")) or None
    target["questionnaire_field_id"] = _clean_text(base.get("field_id")) or None
    target["canonical_questionnaire_id"] = canonical_id or None
    target["questionnaire_label"] = _clean_text(base.get("label") or base.get("form_text"))
    target["questionnaire_form_text"] = _clean_text(base.get("form_text"))
    target["questionnaire_section"] = _clean_text(base.get("section"))
    target["questionnaire_qc_description"] = _clean_text(base.get("qc_description"))
    target["questionnaire_where_to_verify"] = _clean_text(base.get("qc_where_to_verify"))
    target["questionnaire_responsible_party"] = _clean_text(base.get("responsible_party"))
    target["questionnaire_item_type"] = _clean_text(base.get("item_type"))
    target["questionnaire_options"] = list(bundle.get("options", []) or [])
    target["source_file"] = _clean_text(base.get("source_file"))

    inferred_option_value = _infer_target_option_value(
        {
            "field_name": target.get("field_name"),
            "field_label": target.get("field_label"),
            "questionnaire_options": target.get("questionnaire_options"),
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
        }
    )
    target["questionnaire_option_value"] = inferred_option_value or None
    target["questionnaire_option_label"] = (
        _resolve_option_label(bundle, inferred_option_value)
        if inferred_option_value
        else None
    )
    target["search_query"] = _build_search_query(
        form_type,
        target,
        {
            "questionnaire_option_value": target.get("questionnaire_option_value"),
            "matched_label": target.get("questionnaire_label"),
            "matched_section": target.get("questionnaire_section"),
            "matched_responsible_party": target.get("questionnaire_responsible_party"),
            "source_file": target.get("source_file"),
        },
        bundle,
    )


def _repair_yes_no_target_groups(
    form_type: str,
    targets: list[dict[str, Any]],
    questionnaire_index: Mapping[str, Mapping[str, Any]],
) -> None:
    grouped_targets: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        group_key = _yes_no_pair_group_key(target.get("field_name"))
        if not group_key or not _looks_like_yes_no_pdf_field(target):
            continue
        grouped_targets.setdefault(group_key, []).append(target)

    for group_targets in grouped_targets.values():
        if len(group_targets) < 2:
            continue

        canonical_ids = {
            _clean_text(target.get("canonical_questionnaire_id"))
            for target in group_targets
            if _clean_text(target.get("canonical_questionnaire_id"))
        }
        if len(canonical_ids) == 1:
            continue

        fallback_ids = {
            _clean_text(
                _fallback_yes_no_mapping(target, questionnaire_index).get(
                    "canonical_questionnaire_id"
                )
            )
            for target in group_targets
        } - {""}
        if len(fallback_ids) != 1:
            continue

        canonical_id = next(iter(fallback_ids))
        bundle = questionnaire_index.get(canonical_id)
        if not bundle:
            continue

        for target in group_targets:
            _apply_questionnaire_bundle_to_target(
                target,
                form_type=form_type,
                canonical_id=canonical_id,
                bundle=bundle,
            )


def _field_like_attr(field_like: Any, key: str) -> Any:
    if isinstance(field_like, Mapping):
        return field_like.get(key)
    return getattr(field_like, key, None)


def _is_pdf417_barcode_field(field_like: Any) -> bool:
    combined = "".join(
        _clean_text(_field_like_attr(field_like, key)).lower()
        for key in ("field_name", "field_label")
        if _clean_text(_field_like_attr(field_like, key))
    )
    compact = "".join(ch for ch in combined if ch.isalnum())
    return "pdf417barcode" in compact


def _build_search_query(
    form_type: str,
    pdf_field: Mapping[str, Any],
    mapping: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> str:
    base = bundle.get("base") or {}
    option_label = _resolve_option_label(bundle, _clean_text(mapping.get("questionnaire_option_value")))
    parts: list[str] = [
        (form_type or "").upper(),
        _clean_text(base.get("section") or mapping.get("matched_section")),
        _clean_text(base.get("form_text")),
        _clean_text(base.get("label") or mapping.get("matched_label")),
        _clean_text(base.get("item_id") or mapping.get("questionnaire_item_id")),
        _clean_text(base.get("field_id") or mapping.get("questionnaire_field_id")),
        _clean_text(base.get("qc_description")),
        _clean_text(base.get("qc_where_to_verify")),
        option_label,
    ]

    cleaned_parts: list[str] = []
    for part in parts:
        if part and part not in cleaned_parts:
            cleaned_parts.append(part)

    if not cleaned_parts:
        for fallback in (
            pdf_field.get("field_label"),
            pdf_field.get("nearby_text"),
            pdf_field.get("field_name"),
        ):
            cleaned = _clean_text(fallback)
            if cleaned and cleaned not in cleaned_parts:
                cleaned_parts.append(cleaned)
    return " | ".join(cleaned_parts)


def _classify_i914_part5_role(label_lower: str) -> tuple[str, int | None]:
    """Return (role, slot_index). role in {'spouse','child',''}."""
    if "child 1" in label_lower:
        return "child", 0
    if "child 2" in label_lower:
        return "child", 1
    if "child 3" in label_lower:
        return "child", 2
    if "spouse" in label_lower:
        return "spouse", None
    return "", None


def _classify_i914_part5_field_kind(label_lower: str) -> tuple[str, str]:
    """Return (child_field_id, spouse_field_id) for a Part 5 PDF label.

    Either element is empty when the sub-field has no counterpart in the
    corresponding questionnaire row (e.g. children have ``current_state``,
    spouse does not). Ordering matters: more specific phrases (``country of
    birth``, ``country of residence``) must be checked before the bare
    ``enter country`` fallback.
    """
    if "date of birth" in label_lower:
        return "date_of_birth", "spouse_date_of_birth"
    if "country of birth" in label_lower:
        return "country_of_birth", "spouse_country_of_birth"
    if "country of residence" in label_lower:
        return "current_country", "spouse_residence_country"
    if "city or town" in label_lower:
        return "current_city", "spouse_residence_city"
    if "family name" in label_lower or "last name" in label_lower:
        return "family_name", "spouse_family_name"
    if "given name" in label_lower or "first name" in label_lower:
        return "given_name", "spouse_given_name"
    if "middle name" in label_lower:
        return "middle_name", "spouse_middle_name"
    if "state from the list" in label_lower or "select state" in label_lower:
        return "current_state", ""
    if "enter country" in label_lower:
        return "current_country", ""
    return "", ""


def _force_i914_part5_target_mappings(targets: list[dict[str, Any]]) -> None:
    """Force deterministic mappings for I-914 Part 5 widgets using PDF labels.

    The USCIS Part 5 widgets share similar token patterns between the spouse
    and children rows, which causes the scoring matcher in
    ``form_type_matcher`` to leave some of them unmapped (notably the spouse
    ``FamilyName[0]``/``GivenName[0]``/``MiddleName[0]`` and Child 1's
    ``GivenName[1]``/``MiddleName[1]``). On top of that, the PDF widget
    indices do not correspond to the logical slot -- the spouse's DOB consumes
    widget index ``[1]`` so Child 1's DOB ends up at index ``[0]`` while Child
    1's names use index ``[1]``. Both issues corrupt
    ``_build_results_from_answers`` (dynamic counter shifts children up) and
    ``_postprocess_i914_family_roster`` (slot inference collapses
    two hijos into inconsistent slots).

    The field label text reliably names the role (``Spouse`` / ``Child 1/2/3``)
    and the specific sub-field, so we use it as the single source of truth.
    """
    for target in targets:
        label = target.get("field_label") or ""
        if not label:
            continue
        label_lower = label.lower()
        if (
            "part 5" not in label_lower
            and "part5" not in label_lower
            and "part e" not in label_lower
        ):
            continue

        role, slot = _classify_i914_part5_role(label_lower)
        if not role:
            continue

        child_field, spouse_field = _classify_i914_part5_field_kind(label_lower)

        if role == "spouse":
            if not spouse_field:
                continue
            item_id = "p5_1"
            field_id = spouse_field
            item_type = "group"
        else:
            if not child_field:
                continue
            item_id = "p5_children"
            field_id = child_field
            item_type = "repeatable_group"

        canonical = f"{item_id}.{field_id}"
        target["questionnaire_item_id"] = item_id
        target["question_id"] = item_id
        target["questionnaire_field_id"] = field_id
        target["answer_field_id"] = field_id
        target["canonical_questionnaire_id"] = canonical
        target["questionnaire_item_type"] = item_type
        target["mapping_confidence"] = "high"
        if role == "child" and isinstance(slot, int):
            target["occurrence_index"] = slot
            target["repeatable_slot_index"] = slot
        else:
            target["occurrence_index"] = 0
            target["repeatable_slot_index"] = None


_I914_PART9_ENTRY_POSITION_RE = re.compile(r"\b([3-6])\s*\.\s*([a-d])\b")


def _classify_i914_part9_entry_position(
    field_name: str, label_lower: str
) -> tuple[int, str] | None:
    """Return (slot_index, field_id) for an I-914 Part 9 entry widget.

    Slot index 0..3 maps to items 3..6 on page 12 of the form.
    """
    name_lower = (field_name or "").lower()
    field_id = ""
    if "pagenumber" in name_lower or "page number" in label_lower:
        field_id = "page_number"
    elif "partnumber" in name_lower or "part number" in label_lower:
        field_id = "part_number"
    elif "itemnumber" in name_lower or "item number" in label_lower:
        field_id = "item_number"
    elif "additionalinfo" in name_lower or "additional information" in label_lower:
        field_id = "additional_information"
    if not field_id:
        return None

    slot: int | None = None
    match = _I914_PART9_ENTRY_POSITION_RE.search(label_lower)
    if match:
        try:
            item_number = int(match.group(1))
            if 3 <= item_number <= 6:
                slot = item_number - 3
        except (TypeError, ValueError):
            slot = None

    if slot is None:
        match_name = re.search(r"p10_line([2-5])", name_lower)
        if match_name:
            try:
                slot = int(match_name.group(1)) - 2
            except (TypeError, ValueError):
                slot = None

    if slot is None or slot < 0 or slot > 3:
        return None
    return slot, field_id


def _classify_i914_part9_header(
    field_name: str, label_lower: str
) -> tuple[str, str | None, str] | None:
    """Return (item_id, field_id, item_type) for an I-914 Part 9 header widget.

    Headers are pre-populated on page 12 from Part 2 applicant identity and
    A-Number. The PDF widget names use the suffix ``Part2_*[1]`` which we rely
    on to disambiguate from the paragraph widgets.
    """
    name_lower = (field_name or "").lower()
    if not (name_lower.startswith("form1[0].#subform[14].part2") or "part2_" in name_lower):
        return None
    if "alienregistrationnumber" in name_lower or "alien registration number" in label_lower:
        return ("p2_5", None, "text")
    if "familyname" in name_lower:
        return ("p2_1", "family_name", "group")
    if "givenname" in name_lower:
        return ("p2_1", "given_name", "group")
    if "middlename" in name_lower:
        return ("p2_1", "middle_name", "group")
    return None


def _force_i914_part9_target_mappings(targets: list[dict[str, Any]]) -> None:
    """Force deterministic mappings for I-914 Part 9 widgets (page 12).

    The scoring matcher leaves the Page/Part/Item number boxes (``A``, ``B``,
    ``C`` of each entry) and the identity header widgets (names + A-Number)
    unmapped because their labels share generic tokens with many other sections
    of the form. Without a mapping the textarea (``D``) ends up receiving the
    whole addendum text -- header and paragraph -- while the numbered boxes
    stay blank.

    The PDF labels consistently include ``"Part 9. Additional Information."``
    plus an item/letter position (``"3. A"`` .. ``"6. D"``), and the field
    names themselves encode the purpose (``PageNumber`` / ``PartNumber`` /
    ``ItemNumber`` / ``AdditionalInfo`` / ``Part2_*``). We use both signals to
    force deterministic mappings.
    """
    for target in targets:
        label = target.get("field_label") or ""
        field_name = target.get("field_name") or ""
        label_lower = label.lower()
        if "part 9" not in label_lower and "part9" not in label_lower:
            continue

        header = _classify_i914_part9_header(field_name, label_lower)
        if header is not None:
            item_id, field_id, item_type = header
            canonical = (
                f"{item_id}.{field_id}" if field_id else item_id
            )
            target["questionnaire_item_id"] = item_id
            target["question_id"] = item_id
            target["questionnaire_field_id"] = field_id or None
            target["answer_field_id"] = field_id or None
            target["canonical_questionnaire_id"] = canonical
            target["questionnaire_item_type"] = item_type
            target["mapping_confidence"] = "high"
            target["occurrence_index"] = 0
            target["repeatable_slot_index"] = None
            continue

        entry = _classify_i914_part9_entry_position(field_name, label_lower)
        if entry is None:
            continue
        slot, field_id = entry
        canonical = f"p9_entries.{field_id}"
        target["questionnaire_item_id"] = "p9_entries"
        target["question_id"] = "p9_entries"
        target["questionnaire_field_id"] = field_id
        target["answer_field_id"] = field_id
        target["canonical_questionnaire_id"] = canonical
        target["questionnaire_item_type"] = "repeatable_group"
        target["mapping_confidence"] = "high"
        target["occurrence_index"] = slot
        target["repeatable_slot_index"] = slot


def _build_extraction_targets(
    form_type: str,
    pdf_fields: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mappings_by_name = {
        _clean_text(mapping.get("field_name")): mapping
        for mapping in mappings
        if _clean_text(mapping.get("field_name"))
    }
    questionnaire_index = _build_questionnaire_index(form_type)
    normalized_form_type = _normalize_form_type(form_type)
    targets: list[dict[str, Any]] = []
    occurrence_by_repeatable_field: dict[tuple[str, str], int] = {}

    for pdf_field in pdf_fields:
        field_name = _clean_text(pdf_field.get("field_name"))
        mapping = dict(mappings_by_name.get(field_name, {}))
        canonical_id = _clean_text(mapping.get("canonical_questionnaire_id"))
        if not canonical_id:
            fallback_mapping = _fallback_yes_no_mapping(pdf_field, questionnaire_index)
            if not fallback_mapping and normalized_form_type == "i-914":
                fallback_mapping = _fallback_i914_entry_mapping(
                    pdf_field,
                    questionnaire_index,
                )
            if not fallback_mapping and normalized_form_type == "i-914":
                fallback_mapping = _fallback_i914_part3_reporting(
                    pdf_field,
                    questionnaire_index,
                )
            if fallback_mapping:
                mapping = {**mapping, **fallback_mapping}
                canonical_id = _clean_text(mapping.get("canonical_questionnaire_id"))
        bundle = questionnaire_index.get(canonical_id, {"base": {}, "options": [], "definitions": []})
        base = dict(bundle.get("base") or {})

        target = {
            "id": field_name,
            "field_name": field_name,
            "field_label": _clean_text(pdf_field.get("field_label")),
            "field_type": _clean_text(pdf_field.get("field_type") or base.get("item_type") or "text").lower(),
            "field_type_hint": _clean_text(pdf_field.get("field_type_hint")),
            "page_number": _safe_int(pdf_field.get("page_number")),
            "nearby_text": _clean_text(pdf_field.get("nearby_text")),
            "button_values": _as_clean_list(pdf_field.get("button_values")),
            "choice_values": _as_clean_list(pdf_field.get("choice_values")),
            "questionnaire_item_id": _clean_text(mapping.get("questionnaire_item_id") or base.get("item_id")) or None,
            "questionnaire_field_id": _clean_text(mapping.get("questionnaire_field_id") or base.get("field_id")) or None,
            "question_id": _clean_text(mapping.get("questionnaire_item_id") or base.get("item_id")) or None,
            "answer_field_id": _clean_text(mapping.get("questionnaire_field_id") or base.get("field_id")) or None,
            "questionnaire_option_value": _clean_text(mapping.get("questionnaire_option_value")) or None,
            "questionnaire_option_label": _resolve_option_label(
                bundle,
                _clean_text(mapping.get("questionnaire_option_value")),
            )
            or None,
            "canonical_questionnaire_id": canonical_id or None,
            "questionnaire_label": _clean_text(base.get("label") or mapping.get("matched_label")),
            "questionnaire_form_text": _clean_text(base.get("form_text")),
            "questionnaire_section": _clean_text(base.get("section") or mapping.get("matched_section")),
            "questionnaire_instruction": _clean_text(base.get("instruction")),
            "questionnaire_qc_description": _clean_text(base.get("qc_description")),
            "questionnaire_where_to_verify": _clean_text(base.get("qc_where_to_verify")),
            "questionnaire_responsible_party": _clean_text(
                base.get("responsible_party") or mapping.get("matched_responsible_party")
            ),
            "questionnaire_item_type": _clean_text(base.get("item_type")),
            "questionnaire_options": list(bundle.get("options", []) or []),
            "questionnaire_default_value": base.get("default_value"),
            "questionnaire_force_default": bool(base.get("force_default")),
            "mapping_confidence": _clean_text(mapping.get("confidence")),
            "match_score": float(mapping.get("match_score") or 0.0),
            "source_file": _clean_text(base.get("source_file") or mapping.get("source_file")),
            "occurrence_index": 0,
            "address_group_key": None,
            "is_address_group": False,
        }
        question_item_id = _clean_text(target.get("questionnaire_item_id"))
        question_field_id = _clean_text(target.get("questionnaire_field_id"))
        item_type = _clean_text(target.get("questionnaire_item_type")).lower()
        if item_type == "repeatable_group" and question_item_id and question_field_id:
            occurrence_key = (question_item_id, question_field_id)
            target["occurrence_index"] = occurrence_by_repeatable_field.get(occurrence_key, 0)
            occurrence_by_repeatable_field[occurrence_key] = int(target["occurrence_index"]) + 1
        elif question_item_id == "p3_8" and question_field_id.startswith("prior_entry_"):
            occurrence_key = (question_item_id, question_field_id)
            target["occurrence_index"] = occurrence_by_repeatable_field.get(occurrence_key, 0)
            occurrence_by_repeatable_field[occurrence_key] = int(target["occurrence_index"]) + 1
        if _logical_address_field_id(target) or _is_safe_mailing_target(target) or _is_current_physical_address_target(target):
            address_group_key = _address_target_group_key(target)
            target["address_group_key"] = address_group_key or None
            target["is_address_group"] = bool(address_group_key)
        target["search_query"] = _build_search_query(form_type, pdf_field, mapping, bundle)
        targets.append(target)

    _repair_yes_no_target_groups(form_type, targets, questionnaire_index)
    if normalized_form_type == "i-914":
        _force_i914_part5_target_mappings(targets)
        _force_i914_part9_target_mappings(targets)
    targets.sort(key=lambda item: (item.get("page_number") or 0, item.get("field_name") or ""))
    return targets


def _skip_reason(target: Mapping[str, Any]) -> str:
    if not _clean_text(target.get("canonical_questionnaire_id")):
        return "No questionnaire mapping found for this PDF field."
    if _is_pdf417_barcode_field(target):
        return "PDF417 barcode fields are generated artifacts and must not be auto-filled."
    if _is_manual_lea_unit_target(target):
        return "The Part 3.5 Number field is intentionally left blank and must be reviewed manually."
    if _clean_text(target.get("field_type")).lower() == "signature":
        return "Signature fields are not auto-filled by the AI form filling pipeline."
    return ""


def _load_field_rows(db: Session, job_id: str) -> list[FormFillingField]:
    return (
        db.query(FormFillingField)
        .filter(FormFillingField.job_id == job_id)
        .order_by(FormFillingField.created_at.asc())
        .all()
    )


def _replace_job_fields(db: Session, job: FormFillingJob, targets: list[dict[str, Any]]) -> list[FormFillingField]:
    db.query(FormFillingField).filter(FormFillingField.job_id == job.id).delete(synchronize_session=False)
    db.flush()

    for target in targets:
        reason = _skip_reason(target)
        db.add(
            FormFillingField(
                job_id=job.id,
                field_name=target["field_name"],
                field_label=_clean_text(target.get("field_label")),
                field_type=_clean_text(target.get("field_type") or "text") or "text",
                questionnaire_item_id=target.get("questionnaire_item_id"),
                questionnaire_field_id=target.get("questionnaire_field_id"),
                questionnaire_option_value=target.get("questionnaire_option_value"),
                page_number=_safe_int(target.get("page_number")),
                responsible_party=_clean_text(target.get("questionnaire_responsible_party") or "client"),
                extracted_value="",
                confidence="low" if reason else None,
                evidence_source=reason,
                manually_corrected=False,
            )
        )

    job.field_count = len(targets)
    job.filled_count = 0
    job.client_field_count = sum(1 for t in targets if _clean_text(t.get("questionnaire_responsible_party") or "client") == "client")
    job.client_filled_count = 0
    job.attorney_field_count = sum(1 for t in targets if _clean_text(t.get("questionnaire_responsible_party")) == "attorney")
    job.attorney_filled_count = 0
    db.add(job)
    db.commit()
    return _load_field_rows(db, job.id)


def _evidence_bundle_has_content(bundle: Mapping[str, Any]) -> bool:
    evidence = bundle.get("evidence")
    if isinstance(evidence, list) and evidence:
        return True
    text_context = _clean_text(bundle.get("text_context"))
    return bool(text_context)


def _collect_evidence_for_targets(
    targets: list[dict[str, Any]],
    *,
    case_id: str,
    job_id: str,
    tracker: Any,
    source_document_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    settings = get_rag_settings()
    evidence_by_id: dict[str, dict[str, Any]] = {}
    query_vectors: dict[str, list[float]] = {}

    queries = [
        _clean_text(target.get("search_query") or target.get("field_label") or target.get("field_name"))
        for target in targets
    ]
    try:
        if queries:
            embeddings = get_embedding_batch(
                queries,
                task_type=settings.embedding_task_type_query,
                tracker=tracker,
                step_label=f"form-fill-evidence-embeddings-{job_id[:8]}",
            )
            for target, embedding in zip(targets, embeddings, strict=False):
                field_id = _clean_text(target.get("id"))
                if field_id and embedding:
                    query_vectors[field_id] = embedding
    except Exception as exc:
        log.warning("Form filling %s query embedding batch fallback: %s", job_id[:8], exc)

    done_lock = Lock()
    processed_count = [0]

    def _collect_single(target: dict[str, Any]) -> None:
        field_id = _clean_text(target.get("id"))
        query_text = _clean_text(target.get("search_query") or target.get("field_label") or field_id)
        try:
            if not query_text:
                bundle = {
                    "evidence": [],
                    "text_context": "",
                    "source_pages": [],
                    "stage": "empty-query",
                    "matches": [],
                }
            else:
                bundle = collect_evidence_bundle_for_question(
                    query_text,
                    case_id=case_id,
                    where_to_verify=_clean_text(target.get("questionnaire_where_to_verify")),
                    source_document_ids=source_document_ids,
                    top_k=settings.autopilot_evidence_top_k,
                    query_vector=query_vectors.get(field_id),
                    max_context_chars=settings.autopilot_evidence_max_chars,
                    tracker=None,
                    document_fallback_enabled=False if source_document_ids is not None else None,
                )
        except Exception as exc:
            log.warning("Form filling evidence collection failed for %s: %s", field_id or "unknown", exc)
            bundle = {
                "evidence": [],
                "text_context": "",
                "source_pages": [],
                "stage": "error",
                "matches": [],
            }

        with done_lock:
            evidence_by_id[field_id] = bundle
            processed_count[0] += 1
            local_done = processed_count[0]
        form_filling_jobs.update_evidence_progress(
            job_id,
            processed_fields=local_done,
            phase="gathering_evidence",
        )

    with ThreadPoolExecutor(max_workers=max(1, settings.autopilot_evidence_workers)) as pool:
        futures = [pool.submit(_collect_single, target) for target in targets]
        for future in as_completed(futures):
            future.result()

    return evidence_by_id


def _extract_values_for_targets(
    targets: list[dict[str, Any]],
    *,
    evidence_by_id: dict[str, Any],
    form_type: str,
    job_id: str,
    tracker: Any,
) -> tuple[dict[str, dict[str, str]], int, int]:
    settings = get_rag_settings()
    results_by_id: dict[str, dict[str, str]] = {}
    extraction_error_count = 0
    skipped_or_unextractable_count = 0
    processed_extractable = 0

    all_targets = list(targets)
    skipped_targets = [target for target in all_targets if _skip_reason(target)]
    extractable_targets = [target for target in all_targets if not _skip_reason(target)]
    skipped_or_unextractable_count = len(skipped_targets)

    for target in skipped_targets:
        field_id = _clean_text(target.get("id"))
        results_by_id[field_id] = _default_extraction_result(field_id, _skip_reason(target))

    if not extractable_targets:
        form_filling_jobs.update_extraction_progress(
            job_id,
            extracted_fields=0,
            filled_count=0,
            failed_fields=skipped_or_unextractable_count,
            phase="extracting_values",
        )
        return results_by_id, 0, 0

    for batch_index, batch in enumerate(_chunked(extractable_targets, settings.autopilot_batch_size), start=1):
        batch_by_id, batch_error_count = _extract_target_batch_with_fallback(
            batch,
            evidence_by_id=evidence_by_id,
            form_type=form_type,
            tracker=tracker,
            batch_step_label=f"form-fill-batch-{job_id[:8]}-{batch_index}",
            single_step_label_prefix=f"form-fill-single-{job_id[:8]}-{batch_index}",
            warning_message=(
                "Form filling batch extraction failed for job %s batch %d. "
                "Falling back to single extraction: %s"
            ),
            warning_args=(job_id[:8], batch_index),
        )
        extraction_error_count += batch_error_count

        for target in batch:
            field_id = _clean_text(target.get("id"))
            results_by_id[field_id] = batch_by_id.get(
                field_id,
                _default_extraction_result(
                    field_id,
                    "No extraction result was returned for this field.",
                ),
            )

        processed_extractable += len(batch)
        filled_count = sum(
            1
            for result in results_by_id.values()
            if _clean_text(result.get("value"))
        )
        form_filling_jobs.update_extraction_progress(
            job_id,
            extracted_fields=processed_extractable,
            filled_count=filled_count,
            failed_fields=skipped_or_unextractable_count + extraction_error_count,
            phase="extracting_values",
        )

    _postprocess_autofill_results(all_targets, results_by_id, evidence_by_id)
    _postprocess_checkbox_widget_results(all_targets, results_by_id)
    _postprocess_compound_name_results(all_targets, results_by_id)
    if _normalize_form_type(form_type) == "i-914":
        _postprocess_i914_family_roster(all_targets, results_by_id, evidence_by_id)
    final_filled_count = sum(
        1 for result in results_by_id.values() if _clean_text(result.get("value"))
    )
    return results_by_id, final_filled_count, extraction_error_count


def _persist_extraction_results(
    db: Session,
    job: FormFillingJob,
    *,
    results_by_id: Mapping[str, Mapping[str, Any]],
) -> list[FormFillingField]:
    field_rows = _load_field_rows(db, job.id)
    by_field_name = {row.field_name: row for row in field_rows}

    for field_id, result in results_by_id.items():
        row = by_field_name.get(field_id)
        if not row:
            continue
        row.extracted_value = _clean_text(result.get("value"))
        row.confidence = _clean_text(result.get("confidence")) or row.confidence
        row.evidence_source = _clean_text(result.get("justification")) or row.evidence_source or ""
        db.add(row)

    _set_job_filled_counts(job, field_rows)
    db.add(job)
    db.commit()
    return _load_field_rows(db, job.id)


def _set_job_filled_counts(job: FormFillingJob, field_rows: list[FormFillingField]) -> None:
    job.filled_count = sum(1 for row in field_rows if _clean_text(row.extracted_value))
    job.client_filled_count = sum(
        1 for row in field_rows if _clean_text(row.extracted_value) and row.responsible_party == "client"
    )
    job.attorney_filled_count = sum(
        1 for row in field_rows if _clean_text(row.extracted_value) and row.responsible_party == "attorney"
    )


def _capture_manual_field_overrides(field_rows: Iterable[FormFillingField]) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    for row in field_rows:
        field_name = _clean_text(row.field_name)
        if not field_name or not row.manually_corrected:
            continue
        overrides[field_name] = {
            "extracted_value": row.extracted_value if row.extracted_value is not None else "",
            "confidence": row.confidence,
            "evidence_source": row.evidence_source or "",
            "manually_corrected": True,
        }
    return overrides


def _restore_manual_field_overrides(
    db: Session,
    job: FormFillingJob,
    field_rows: list[FormFillingField],
    overrides: Mapping[str, Mapping[str, Any]],
) -> list[FormFillingField]:
    if not overrides:
        return field_rows

    changed = False
    for row in field_rows:
        override = overrides.get(_clean_text(row.field_name))
        if not override:
            continue
        row.extracted_value = _clean_text(override.get("extracted_value"))
        row.confidence = _clean_text(override.get("confidence")) or row.confidence
        row.evidence_source = _clean_text(override.get("evidence_source")) or row.evidence_source or ""
        row.manually_corrected = bool(override.get("manually_corrected"))
        db.add(row)
        changed = True

    if not changed:
        return field_rows

    _set_job_filled_counts(job, field_rows)
    db.add(job)
    db.commit()
    return _load_field_rows(db, job.id)


def _rebuild_job_fields_from_answers(
    db: Session,
    job: FormFillingJob,
    *,
    resolved_form_type: str,
    pdf_fields: list[dict[str, Any]],
    precomputed_targets: list[dict[str, Any]] | None = None,
    precomputed_answers: Mapping[str, Any] | None = None,
    precomputed_results_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[FormFillingField]:
    previous_rows = _load_field_rows(db, job.id)
    manual_overrides = _capture_manual_field_overrides(previous_rows)

    targets = list(precomputed_targets or [])
    if not targets:
        mapping_result = map_pdf_fields_to_questionnaire_ids(resolved_form_type, pdf_fields)
        targets = _build_extraction_targets(
            resolved_form_type,
            pdf_fields,
            list(mapping_result.get("mappings", []) or []),
        )
    field_rows = _replace_job_fields(db, job, targets)
    answers = precomputed_answers
    if answers is None:
        answers = _get_questionnaire_answers_with_defaults(
            db,
            job.case_id,
            form_type=resolved_form_type,
        )
    answers = _propagate_shared_a_number_to_p2_5(answers)
    answers = _propagate_shared_name_to_p2_1(answers)
    results_by_id = dict(precomputed_results_by_id or {})
    if not results_by_id:
        results_by_id = _build_results_from_answers(targets, answers, pdf_fields=pdf_fields)
    field_rows = _persist_extraction_results(db, job, results_by_id=results_by_id)
    return _restore_manual_field_overrides(db, job, field_rows, manual_overrides)


def _is_template_backed_form_job(original_pdf_path: str, resolved_form_type: str) -> bool:
    cleaned_original_path = _clean_text(original_pdf_path)
    if not cleaned_original_path or not resolved_form_type:
        return False

    try:
        current_template_path = get_form_template_path(resolved_form_type)
    except (FileNotFoundError, ValueError):
        return False

    if cleaned_original_path == str(current_template_path):
        return True

    original_name = Path(cleaned_original_path).name.lower()
    template_name = current_template_path.name.lower()
    if original_name != template_name:
        return False

    normalized_original = cleaned_original_path.replace("\\", "/").lower()
    return "/seed_data/forms/" in normalized_original or normalized_original.endswith(f"/{template_name}")


def _target_looks_like_unit_type_button(target: Mapping[str, Any]) -> bool:
    field_type = _clean_text(target.get("field_type")).lower()
    if field_type not in {"checkbox", "radio", "button"}:
        return False

    combined = " | ".join(
        _normalize_hint_text(
            target.get(key)
        )
        for key in (
            "field_name",
            "field_label",
            "nearby_text",
            "questionnaire_field_id",
            "questionnaire_option_value",
            "questionnaire_option_label",
            "questionnaire_label",
            "questionnaire_form_text",
            "questionnaire_section",
        )
        if _clean_text(target.get(key))
    )
    if not combined:
        return False

    return any(
        phrase in combined
        for phrase in (
            "apt ste flr",
            "apartment suite floor",
            "apartment suite or floor",
            "check this box for apartment",
            "check this box for suite",
            "check this box for floor",
        )
    )


def _field_rows_need_unit_type_repair(
    field_rows: list[FormFillingField],
    *,
    resolved_form_type: str,
    pdf_fields: list[dict[str, Any]],
    answers: Mapping[str, Any],
    precomputed_targets: list[dict[str, Any]] | None = None,
    precomputed_results_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool:
    if not resolved_form_type or not pdf_fields or not answers:
        return False

    targets = list(precomputed_targets or [])
    if not targets:
        mapping_result = map_pdf_fields_to_questionnaire_ids(resolved_form_type, pdf_fields)
        targets = _build_extraction_targets(
            resolved_form_type,
            pdf_fields,
            list(mapping_result.get("mappings", []) or []),
        )
    results_by_id = dict(precomputed_results_by_id or {})
    if not results_by_id:
        results_by_id = _build_results_from_answers(targets, answers, pdf_fields=pdf_fields)
    rows_by_name = {_clean_text(row.field_name): row for row in field_rows if _clean_text(row.field_name)}

    for target in targets:
        if not _target_looks_like_unit_type_button(target):
            continue
        field_name = _clean_text(target.get("field_name"))
        row = rows_by_name.get(field_name)
        if row is None or row.manually_corrected:
            continue

        expected_value = _clean_text((results_by_id.get(field_name) or {}).get("value")).lower()
        if expected_value != "yes":
            continue

        current_value = _clean_text(row.extracted_value).lower()
        if current_value != "yes":
            return True

    return False


def _build_pdf_value_map(field_rows: list[FormFillingField]) -> dict[str, Any]:
    value_map: dict[str, Any] = {}
    for row in field_rows:
        if _clean_text(row.field_type).lower() == "signature" or _is_pdf417_barcode_field(row):
            continue
        value_map[row.field_name] = row.extracted_value if row.extracted_value is not None else ""
    return value_map


def _build_overlay_payload(
    pdf_fields: Iterable[Mapping[str, Any]],
    field_rows: list[FormFillingField],
) -> list[dict[str, Any]]:
    by_field_name = {row.field_name: row for row in field_rows}
    overlay_items: list[dict[str, Any]] = []
    for pdf_field in pdf_fields:
        field_name = _clean_text(pdf_field.get("field_name"))
        if not field_name:
            continue
        row = by_field_name.get(field_name)
        if row is None:
            continue
        if _clean_text(row.field_type).lower() == "signature" or _is_pdf417_barcode_field(row):
            continue

        rect = pdf_field.get("rect")
        if rect is None:
            rects = pdf_field.get("rects") or []
            rect = rects[0] if isinstance(rects, list) and rects else None
        if rect is None:
            continue

        overlay_items.append(
            {
                "field_name": field_name,
                "field_type": _clean_text(row.field_type or pdf_field.get("field_type") or "text") or "text",
                "page_number": _safe_int(pdf_field.get("page_number")) or row.page_number or 1,
                "rect": rect,
                "value": row.extracted_value if row.extracted_value is not None else "",
            }
        )
    return overlay_items


def _clone_answer_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _clone_answer_value(entry) for key, entry in value.items()}
    if isinstance(value, list):
        return [_clone_answer_value(entry) for entry in value]
    if isinstance(value, tuple):
        return [_clone_answer_value(entry) for entry in value]
    return value


def _has_meaningful_saved_answer(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(_clean_text(value))
    if isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, Mapping):
        return any(_has_meaningful_saved_answer(entry) for entry in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_meaningful_saved_answer(entry) for entry in value)
    return True


def _questionnaire_pages_for_form_defaults(form_type: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    pages.extend(get_shared_questions())
    pages.extend(get_form_client_questions(form_type))
    try:
        pages.extend(get_form_attorney_questions(form_type))
    except FileNotFoundError:
        pass
    return pages


def _apply_questionnaire_defaults_to_answers(
    pages: Iterable[Mapping[str, Any]],
    answers: Mapping[str, Any],
    *,
    include_optional_defaults: bool = True,
) -> dict[str, Any]:
    next_answers = {
        _clean_text(key): _clone_answer_value(value)
        for key, value in answers.items()
        if _clean_text(key)
    }

    for page in pages:
        for item in page.get("items", []) or []:
            item_id = _clean_text(item.get("id"))
            if not item_id:
                continue

            include_item_defaults = (
                include_optional_defaults
                or not bool(item.get("optional"))
                or _has_meaningful_saved_answer(next_answers.get(item_id))
            )
            fields = [field for field in (item.get("fields") or []) if isinstance(field, Mapping)]
            details_fields = [
                field for field in (item.get("details_fields") or []) if isinstance(field, Mapping)
            ]

            if (
                include_item_defaults
                and
                item.get("default_value") is not None
                and not fields
                and not _has_meaningful_saved_answer(next_answers.get(item_id))
            ):
                next_answers[item_id] = _clone_answer_value(item.get("default_value"))

            if fields:
                current_value = next_answers.get(item_id)
                group_value = dict(current_value) if isinstance(current_value, Mapping) else {}
                group_changed = False
                for field in fields:
                    field_id = _clean_text(field.get("id"))
                    if not field_id:
                        continue
                    if include_item_defaults and field.get("default_value") is not None and (
                        bool(field.get("force_default"))
                        or not _has_meaningful_saved_answer(group_value.get(field_id))
                    ):
                        group_value[field_id] = _clone_answer_value(field.get("default_value"))
                        group_changed = True
                if group_changed:
                    next_answers[item_id] = group_value

            for detail_field in details_fields:
                if (
                    detail_field.get("repeatable")
                    or detail_field.get("default_value") is None
                    or not include_item_defaults
                ):
                    continue
                detail_id = _clean_text(detail_field.get("id"))
                if not detail_id:
                    continue
                detail_key = f"{item_id}.{detail_id}"
                if (
                    bool(detail_field.get("force_default"))
                    or not _has_meaningful_saved_answer(next_answers.get(detail_key))
                ):
                    next_answers[detail_key] = _clone_answer_value(detail_field.get("default_value"))

    return next_answers


_I914_PART9_FIELD_IDS = (
    "page_number",
    "part_number",
    "item_number",
    "additional_information",
)
_I914_PART9_HEADER_PREFIX_RE = re.compile(
    r"^\s*Page\s+\S+\s*,\s*Part\s+\S+\s*,\s*Item\s+\S+\s*\.\s*",
    re.IGNORECASE,
)


def _strip_i914_part9_header(value: Any) -> str:
    return _i914_strip_part9_header(value, clean_text=_clean_text)
_I914_SPOUSE_REQUIRED_FIELDS = (
    "spouse_family_name",
    "spouse_given_name",
    "spouse_date_of_birth",
    "spouse_country_of_birth",
    "spouse_residence_city",
    "spouse_residence_country",
)
_I914_CHILD_REQUIRED_FIELDS = (
    "family_name",
    "given_name",
    "date_of_birth",
    "country_of_birth",
    "current_city",
    "current_country",
)
_I914_PART41_QUESTION_IDS = (
    "p4_1a",
    "p4_1b",
    "p4_1c",
    "p4_1d",
    "p4_1e",
    "p4_1f",
    "p4_1g",
    "p4_1h",
    "p4_1i",
)


def _normalize_i914_part9_row(value: Any) -> dict[str, str]:
    return _i914_normalize_part9_row(value, clean_text=_clean_text)


def _i914_part9_row_has_content(row: Mapping[str, Any]) -> bool:
    return _i914_helper_part9_row_has_content(row, clean_text=_clean_text)


def _i914_part9_row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return _i914_helper_part9_row_key(row, clean_text=_clean_text)


def _i914_mapping_has_any_value(value: Any) -> bool:
    return _i914_helper_mapping_has_any_value(value, clean_text=_clean_text)


def _i914_child_row_is_complete(row: Mapping[str, Any]) -> bool:
    return _i914_helper_child_row_is_complete(
        row,
        clean_text=_clean_text,
        normalize_country_value_for_pdf=_normalize_country_value_for_pdf,
        normalize_us_state_code=_normalize_us_state_code,
    )


def _apply_i914_family_answer_rules(answers: dict[str, Any]) -> dict[str, Any]:
    return _i914_apply_family_answer_rules(
        answers,
        clean_text=_clean_text,
        clone_answer_value=_clone_answer_value,
        normalize_country_value_for_pdf=_normalize_country_value_for_pdf,
        normalize_us_state_code=_normalize_us_state_code,
    )


def _apply_i914_forced_answer_rules(answers: dict[str, Any]) -> dict[str, Any]:
    return _i914_apply_forced_answer_rules(answers, clean_text=_clean_text)


def _make_form_generation_issue(
    *,
    code: str,
    message: str,
    question_id: str = "",
    field_id: str = "",
    label: str = "",
    row_label: str = "",
    section_code: str = "",
    source: str = "questionnaire",
) -> dict[str, str]:
    return {
        "code": _clean_text(code),
        "message": _clean_text(message),
        "question_id": _clean_text(question_id),
        "field_id": _clean_text(field_id),
        "label": _clean_text(label),
        "row_label": _clean_text(row_label),
        "section_code": _clean_text(section_code),
        "source": _clean_text(source) or "questionnaire",
    }


def _questionnaire_item_is_repeatable(item: Mapping[str, Any]) -> bool:
    return bool(item.get("fields")) and (
        _clean_text(item.get("type")).lower() == "repeatable_group"
        or bool(item.get("repeatable"))
    )


def _questionnaire_group_row(
    item: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> dict[str, str]:
    item_id = _clean_text(item.get("id"))
    fields = list(item.get("fields") or [])
    row = {
        _clean_text(field.get("id")): ""
        for field in fields
        if _clean_text(field.get("id"))
    }

    if not item_id:
        return row

    group_value = answers.get(item_id)
    if isinstance(group_value, Mapping):
        for field in fields:
            field_id = _clean_text(field.get("id"))
            if field_id:
                row[field_id] = _clean_text(group_value.get(field_id))

    for field in fields:
        field_id = _clean_text(field.get("id"))
        if not field_id or row.get(field_id):
            continue
        value, found = _lookup_saved_answer(answers, f"{item_id}.{field_id}")
        if found:
            row[field_id] = _clean_text(value)

    return row


def _questionnaire_repeatable_rows(
    item: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> list[dict[str, str]]:
    item_id = _clean_text(item.get("id"))
    fields = list(item.get("fields") or [])
    if not item_id or not fields:
        return []

    raw_rows = answers.get(item_id)
    if raw_rows is None:
        return []

    if isinstance(raw_rows, Mapping):
        iterable_rows: list[Any] = [raw_rows]
    elif isinstance(raw_rows, (list, tuple)):
        iterable_rows = list(raw_rows)
    else:
        return []

    rows: list[dict[str, str]] = []
    for raw_row in iterable_rows:
        if not isinstance(raw_row, Mapping):
            continue
        rows.append(
            {
                _clean_text(field.get("id")): _clean_text(raw_row.get(_clean_text(field.get("id"))))
                for field in fields
                if _clean_text(field.get("id"))
            }
        )
    return rows


def _questionnaire_detail_values(
    item: Mapping[str, Any],
    detail_field: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> list[str]:
    item_id = _clean_text(item.get("id"))
    detail_id = _clean_text(detail_field.get("id"))
    if not item_id or not detail_id:
        return []

    value, found = _lookup_saved_answer(answers, f"{item_id}.{detail_id}")
    if not found:
        return []
    if isinstance(value, (list, tuple)):
        return [_clean_text(entry) for entry in value]
    return [_clean_text(value)]


def _questionnaire_first_detail_value(
    item: Mapping[str, Any],
    detail_field_id: str,
    answers: Mapping[str, Any],
) -> str:
    values = _questionnaire_detail_values(item, {"id": detail_field_id}, answers)
    return values[0] if values else ""


def _questionnaire_value_matches_default(value: Any, default_value: Any) -> bool:
    if default_value is None:
        return False

    normalized_value = _normalize_option_answer(value)
    normalized_default = _normalize_option_answer(default_value)
    if normalized_value and normalized_default:
        return normalized_value == normalized_default

    return _clean_text(value) == _clean_text(default_value)


def _questionnaire_row_has_non_default_values(
    item: Mapping[str, Any],
    row: Mapping[str, Any],
) -> bool:
    for field in item.get("fields") or []:
        field_id = _clean_text(field.get("id"))
        if not field_id:
            continue
        value = row.get(field_id)
        if not _clean_text(value):
            continue
        if _questionnaire_value_matches_default(value, field.get("default_value")):
            continue
        return True
    return False


def _questionnaire_row_has_values(row: Mapping[str, Any]) -> bool:
    return any(_clean_text(value) for value in row.values())


def _questionnaire_optional_item_has_value(
    item: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> bool:
    if item.get("fields"):
        if _questionnaire_item_is_repeatable(item):
            return any(
                _questionnaire_row_has_non_default_values(item, row)
                for row in _questionnaire_repeatable_rows(item, answers)
            )
        return _questionnaire_row_has_non_default_values(item, _questionnaire_group_row(item, answers))

    item_id = _clean_text(item.get("id"))
    if item_id:
        value, found = _lookup_saved_answer(answers, item_id)
        if (
            found
            and _has_answer_value(value)
            and not _questionnaire_value_matches_default(value, item.get("default_value"))
        ):
            return True

    for detail_field in item.get("details_fields") or []:
        values = _questionnaire_detail_values(item, detail_field, answers)
        if any(
            _clean_text(value)
            and not _questionnaire_value_matches_default(value, detail_field.get("default_value"))
            for value in values
        ):
            return True

    return False


def _normalized_marital_status_from_answers(answers: Mapping[str, Any]) -> str:
    shared_biographics = answers.get("shared.biographics")
    if isinstance(shared_biographics, Mapping):
        marital_status = shared_biographics.get("marital_status")
        normalized = _normalize_option_answer(marital_status)
        if normalized:
            return normalized

    marital_status, found = _lookup_saved_answer(answers, "shared.biographics.marital_status")
    if not found:
        return ""
    return _normalize_option_answer(marital_status)


def _optional_item_requires_validation(
    item: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> bool:
    item_id = _clean_text(item.get("id"))
    if _questionnaire_optional_item_has_value(item, answers):
        return True
    if item_id == "p5_1":
        return _normalized_marital_status_from_answers(answers) == "married"
    if item_id == "p4_1_details":
        return _questionnaire_condition_applies(item, item.get("condition"), answers)
    return False


def _questionnaire_condition_applies(
    item: Mapping[str, Any],
    condition: Any,
    answers: Mapping[str, Any],
) -> bool:
    normalized_condition = _normalize_hint_text(condition)
    if not normalized_condition:
        return True

    item_id = _clean_text(item.get("id"))
    if item_id == "p4_1_details":
        return any(
            _normalize_option_answer(_lookup_saved_answer(answers, question_id)[0]) == "yes"
            for question_id in _I914_PART41_QUESTION_IDS
        )

    current_answer, found = _lookup_saved_answer(answers, item_id)
    normalized_answer = _normalize_option_answer(current_answer) if found else ""
    if "if yes" in normalized_condition:
        return normalized_answer == "yes"
    if "if no" in normalized_condition:
        return normalized_answer == "no"

    referenced_option_match = re.search(
        r"\bif\s+(\d+)\s+(\d+)\s+([a-z0-9]+)\s+is selected\b",
        normalized_condition,
    )
    if referenced_option_match:
        referenced_item_id = f"p{referenced_option_match.group(1)}_{referenced_option_match.group(2)}"
        referenced_answer, referenced_found = _lookup_saved_answer(answers, referenced_item_id)
        referenced_option = _normalize_option_answer(referenced_option_match.group(3))
        return referenced_found and _normalize_option_answer(referenced_answer) == referenced_option

    same_part_option_match = re.search(
        r"\bif option\s+([a-z0-9]+)\s+is selected in item\s+(\d+)\b",
        normalized_condition,
    )
    if same_part_option_match:
        part_match = re.match(r"p(\d+)_", item_id)
        if part_match:
            referenced_item_id = f"p{part_match.group(1)}_{same_part_option_match.group(2)}"
            referenced_answer, referenced_found = _lookup_saved_answer(answers, referenced_item_id)
            referenced_option = _normalize_option_answer(same_part_option_match.group(1))
            return referenced_found and _normalize_option_answer(referenced_answer) == referenced_option
        return False

    option_match = re.search(r"\bif(?: option)?\s+([a-z0-9]+)\s+is selected\b", normalized_condition)
    if option_match:
        return normalized_answer == _normalize_option_answer(option_match.group(1))

    if "checkbox is selected" in normalized_condition:
        checkbox_ids = [
            _clean_text(field.get("id"))
            for field in (item.get("fields") or [])
            if _clean_text(field.get("type")).lower() == "checkbox" and _clean_text(field.get("id"))
        ]
        if not checkbox_ids:
            return False
        row = _questionnaire_group_row(item, answers)
        return any(_normalize_option_answer(row.get(field_id)) == "yes" for field_id in checkbox_ids)

    return True


def _field_required_for_generation(
    item: Mapping[str, Any],
    field: Mapping[str, Any],
    row: Mapping[str, Any] | None = None,
) -> bool:
    if bool(field.get("optional")):
        return False

    normalized_type = _clean_text(field.get("type")).lower()
    if normalized_type == "signature":
        return False

    normalized_label = _normalize_hint_text(field.get("label") or item.get("form_text"))
    if "date of signature" in normalized_label:
        return False
    if any(token in normalized_label for token in ("if any", "if applicable")):
        return False

    item_id = _clean_text(item.get("id")).lower()
    field_id = _clean_text(field.get("id")).lower()
    normalized_city = _normalize_hint_text((row or {}).get("lea_city"))
    normalized_street = _normalize_hint_text((row or {}).get("lea_street_number_name"))
    uses_online_submission = "online submission" in normalized_city or "online submission" in normalized_street
    if item_id == "p3_5" and uses_online_submission and field_id in {"lea_agency_office", "lea_state", "lea_zip_code"}:
        return False

    return True


def _detail_required_for_generation(
    item: Mapping[str, Any],
    detail_field: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> bool:
    if not _field_required_for_generation(item, detail_field):
        return False

    item_id = _clean_text(item.get("id")).lower()
    field_id = _clean_text(detail_field.get("id")).lower()
    normalized_city = _normalize_hint_text(_questionnaire_first_detail_value(item, "lea_city", answers))
    normalized_street = _normalize_hint_text(
        _questionnaire_first_detail_value(item, "lea_street_number_name", answers)
    )
    uses_online_submission = "online submission" in normalized_city or "online submission" in normalized_street
    if item_id == "p3_5" and uses_online_submission and field_id in {"lea_agency_office", "lea_state", "lea_zip_code"}:
        return False

    return True


def _defer_item_validation(
    item: Mapping[str, Any],
) -> bool:
    item_id = _clean_text(item.get("id")).lower()
    return item_id in {"p3_8", "p4_1_details"}


def _defer_detail_validation(
    item: Mapping[str, Any],
    detail_field: Mapping[str, Any],
) -> bool:
    item_id = _clean_text(item.get("id")).lower()
    detail_id = _clean_text(detail_field.get("id")).lower()
    if item_id == "p3_8" and detail_id.startswith("prior_entry_"):
        return True
    if item_id == "p3_9" and detail_id == "arrival_circumstances":
        return True
    return False


def _questionnaire_row_label(item: Mapping[str, Any], index: int) -> str:
    visible_slots = item.get("visible_slots") or []
    if isinstance(visible_slots, list) and index < len(visible_slots):
        slot_label = _clean_text(visible_slots[index])
        if slot_label:
            return slot_label
    return f"Row {index + 1}"


def _questionnaire_validation_target(
    item: Mapping[str, Any],
    field: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    questionnaire_options = list(
        (field.get("options") if isinstance(field, Mapping) else None)
        or item.get("options")
        or []
    )
    return {
        "questionnaire_item_id": _clean_text(item.get("id")) or None,
        "questionnaire_field_id": _clean_text((field or {}).get("id")) or None,
        "questionnaire_label": _clean_text((field or {}).get("label") or item.get("form_text")) or None,
        "field_label": _clean_text((field or {}).get("label") or item.get("form_text")) or None,
        "field_name": _clean_text((field or {}).get("id") or item.get("id")) or None,
        "questionnaire_form_text": _clean_text(item.get("form_text")) or None,
        "questionnaire_section": _clean_text(item.get("section")) or None,
        "questionnaire_options": questionnaire_options,
        "field_type": _clean_text((field or {}).get("type") or item.get("type")),
        "questionnaire_item_type": _clean_text(item.get("type")),
    }


def _questionnaire_value_matches_options(
    target: Mapping[str, Any],
    value: Any,
) -> bool:
    normalized_value = _normalize_option_answer(value)
    if not normalized_value:
        return False
    option_sets = _iter_normalized_target_options(target)
    if not option_sets:
        return False
    return any(normalized_value in normalized_values for _, normalized_values in option_sets)


def _questionnaire_value_type_issue(
    item: Mapping[str, Any],
    field: Mapping[str, Any] | None,
    value: Any,
    *,
    row_label: str = "",
) -> dict[str, str] | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None

    target = _questionnaire_validation_target(item, field)
    field_type = _clean_text((field or {}).get("type") or item.get("type")).lower()
    label = _clean_text((field or {}).get("label") or item.get("form_text") or item.get("section"))
    issue_kwargs = {
        "question_id": _clean_text(item.get("id")),
        "field_id": _clean_text((field or {}).get("id")),
        "label": label,
        "row_label": row_label,
        "section_code": _clean_text(item.get("code")),
    }

    if _looks_like_date_target(target) and not _normalize_date_text(cleaned):
        return _make_form_generation_issue(
            code="invalid_date",
            message=(
                f"Enter a valid date in '{LONG_DATE_FORMAT_HUMAN}' format "
                f"(e.g., {LONG_DATE_EXAMPLE}) before generating the form."
            ),
            **issue_kwargs,
        )

    if _logical_address_field_id(target) == "state" and not _normalize_us_state_code(cleaned):
        return _make_form_generation_issue(
            code="invalid_state",
            message="Enter a valid U.S. state abbreviation before generating the form.",
            **issue_kwargs,
        )

    if _looks_like_country_target(target) and not _normalize_country_value_for_pdf(cleaned):
        return _make_form_generation_issue(
            code="invalid_country",
            message="Enter a recognized country before generating the form.",
            **issue_kwargs,
        )

    if _looks_like_nonimmigrant_status(target) and not _normalize_nonimmigrant_status(cleaned):
        return _make_form_generation_issue(
            code="invalid_immigration_status",
            message="Enter a valid immigration status before generating the form.",
            **issue_kwargs,
        )

    if field_type == "yes_no" and _normalize_option_answer(cleaned) not in {"yes", "no"}:
        return _make_form_generation_issue(
            code="invalid_yes_no",
            message="Select either Yes or No before generating the form.",
            **issue_kwargs,
        )

    if field_type in {"select", "single_choice"} and target.get("questionnaire_options"):
        if not _questionnaire_value_matches_options(target, cleaned):
            return _make_form_generation_issue(
                code="invalid_option",
                message="Select a valid option before generating the form.",
                **issue_kwargs,
            )

    return None


def _collect_generation_issues(
    item: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    item_id = _clean_text(item.get("id"))
    item_code = _clean_text(item.get("code"))
    item_label = _clean_text(item.get("form_text") or item.get("section") or item_id)
    optional_requires_validation = bool(item.get("optional")) and _optional_item_requires_validation(item, answers)

    if bool(item.get("optional")) and not optional_requires_validation:
        return issues

    item_condition_applies = _questionnaire_condition_applies(item, item.get("condition"), answers)

    if item.get("fields"):
        if _questionnaire_item_is_repeatable(item):
            rows = _questionnaire_repeatable_rows(item, answers)
            row_indexes = [index for index, row in enumerate(rows) if _questionnaire_row_has_values(row)]

            if not row_indexes and item_condition_applies and (not bool(item.get("optional")) or optional_requires_validation):
                if not _defer_item_validation(item):
                    issues.append(
                        _make_form_generation_issue(
                            code="missing_repeatable_entry",
                            message="Provide at least one complete entry before generating the form.",
                            question_id=item_id,
                            label=item_label,
                            section_code=item_code,
                        )
                    )

            for index in row_indexes:
                row = rows[index]
                row_label = _questionnaire_row_label(item, index)
                for field in item.get("fields") or []:
                    field_id = _clean_text(field.get("id"))
                    if not field_id:
                        continue
                    if (
                        not _field_required_for_generation(item, field, row)
                        or not _questionnaire_condition_applies(item, field.get("condition"), answers)
                    ):
                        continue

                    value = _clean_text(row.get(field_id))
                    if value:
                        type_issue = _questionnaire_value_type_issue(
                            item,
                            field,
                            value,
                            row_label=row_label,
                        )
                        if type_issue:
                            issues.append(type_issue)
                        continue

                    issues.append(
                        _make_form_generation_issue(
                            code="missing_required_field",
                            message="This required field must be completed before generating the form.",
                            question_id=item_id,
                            field_id=field_id,
                            label=_clean_text(field.get("label")) or item_label,
                            row_label=row_label,
                            section_code=item_code,
                        )
                    )
        else:
            row = _questionnaire_group_row(item, answers)
            for field in item.get("fields") or []:
                field_id = _clean_text(field.get("id"))
                if not field_id:
                    continue
                if (
                    not _field_required_for_generation(item, field, row)
                    or not _questionnaire_condition_applies(item, field.get("condition"), answers)
                ):
                    continue

                value = _clean_text(row.get(field_id))
                if value:
                    type_issue = _questionnaire_value_type_issue(item, field, value)
                    if type_issue:
                        issues.append(type_issue)
                    continue

                issues.append(
                    _make_form_generation_issue(
                        code="missing_required_field",
                        message="This required field must be completed before generating the form.",
                        question_id=item_id,
                        field_id=field_id,
                        label=_clean_text(field.get("label")) or item_label,
                        section_code=item_code,
                    )
                )
    else:
        value, found = _lookup_saved_answer(answers, item_id)
        cleaned_value = _clean_text(value) if found else ""
        if cleaned_value:
            type_issue = _questionnaire_value_type_issue(item, None, cleaned_value)
            if type_issue:
                issues.append(type_issue)
        elif item_condition_applies and (not bool(item.get("optional")) or optional_requires_validation):
            if not cleaned_value:
                issues.append(
                    _make_form_generation_issue(
                        code="missing_required_field",
                        message="This required field must be completed before generating the form.",
                        question_id=item_id,
                        label=item_label,
                        section_code=item_code,
                    )
                )

    repeatable_details = [
        detail_field
        for detail_field in item.get("details_fields") or []
        if bool(detail_field.get("repeatable"))
        and not bool(detail_field.get("optional"))
        and _questionnaire_condition_applies(item, detail_field.get("condition"), answers)
    ]
    detail_row_count = 0
    if repeatable_details:
        detail_row_count = max(
            (len(_questionnaire_detail_values(item, detail_field, answers)) for detail_field in repeatable_details),
            default=0,
        )
        if detail_row_count == 0 and (not bool(item.get("optional")) or optional_requires_validation):
            if not _defer_item_validation(item):
                issues.append(
                    _make_form_generation_issue(
                        code="missing_repeatable_entry",
                        message="Provide at least one complete entry before generating the form.",
                        question_id=item_id,
                        label=item_label,
                        section_code=item_code,
                    )
                )

    for detail_field in item.get("details_fields") or []:
        if bool(detail_field.get("optional")):
            continue
        if not _detail_required_for_generation(item, detail_field, answers):
            continue
        if not _questionnaire_condition_applies(item, detail_field.get("condition"), answers):
            continue
        if _defer_detail_validation(item, detail_field):
            continue

        detail_id = _clean_text(detail_field.get("id"))
        if not detail_id:
            continue

        values = _questionnaire_detail_values(item, detail_field, answers)
        if bool(detail_field.get("repeatable")):
            row_count = detail_row_count
            for index in range(row_count):
                row_label = _questionnaire_row_label(item, index)
                value = values[index] if index < len(values) else ""
                if value:
                    type_issue = _questionnaire_value_type_issue(
                        item,
                        detail_field,
                        value,
                        row_label=row_label,
                    )
                    if type_issue:
                        issues.append(type_issue)
                    continue
                issues.append(
                    _make_form_generation_issue(
                        code="missing_required_field",
                        message="This required field must be completed before generating the form.",
                        question_id=item_id,
                        field_id=detail_id,
                        label=_clean_text(detail_field.get("label")) or item_label,
                        row_label=row_label,
                        section_code=item_code,
                    )
                )
            continue

        value = values[0] if values else ""
        if value:
            type_issue = _questionnaire_value_type_issue(item, detail_field, value)
            if type_issue:
                issues.append(type_issue)
            continue
        issues.append(
            _make_form_generation_issue(
                code="missing_required_field",
                message="This required field must be completed before generating the form.",
                question_id=item_id,
                field_id=detail_id,
                label=_clean_text(detail_field.get("label")) or item_label,
                section_code=item_code,
            )
        )

    return issues


def _normalize_form_checklist_token(value: Any) -> str:
    return "".join(ch for ch in _clean_text(value).lower() if ch.isalnum())


def _form_codes_for_validation_pages(
    pages: Iterable[Mapping[str, Any]],
) -> set[str]:
    codes: set[str] = set()
    for page in pages:
        for item in page.get("items", []) or []:
            code = _clean_text(item.get("code"))
            if code:
                codes.add(code.upper())
    return codes


def _collect_qc_generation_validation_issues(
    db: Session,
    *,
    case_id: str,
    form_type: str,
    known_codes: set[str],
) -> list[dict[str, str]]:
    normalized_form_type = _normalize_form_type(form_type) or _clean_text(form_type).lower()
    if not normalized_form_type:
        return []

    checklist_rows = (
        db.query(QCChecklist, QCQuestion)
        .join(QCPart, QCPart.checklist_id == QCChecklist.id)
        .join(QCQuestion, QCQuestion.part_id == QCPart.id)
        .filter(QCChecklist.case_id == case_id, QCChecklist.is_template == False)
        .all()
    )

    normalized_form_token = _normalize_form_checklist_token(normalized_form_type)
    issues: list[dict[str, str]] = []
    for checklist, question in checklist_rows:
        checklist_haystack = _normalize_form_checklist_token(
            f"{checklist.name} {checklist.description}"
        )
        if normalized_form_token and normalized_form_token not in checklist_haystack:
            continue

        question_code = _clean_text(question.code).upper()
        if known_codes and question_code and question_code not in known_codes:
            continue

        correction = _clean_text(question.correction)
        answer = _clean_text(question.answer).lower()
        where_to_verify = _normalize_hint_text(question.where_to_verify)
        label = _clean_text(question.description) or question_code

        if correction:
            message = (
                "QC flagged an unresolved correction tied to FBI or record review."
                if "fbi" in where_to_verify
                else "QC flagged an unresolved correction that must be reviewed before generating the form."
            )
            if correction:
                message = f"{message} Correction: {correction}"
            issues.append(
                _make_form_generation_issue(
                    code="qc_correction_pending",
                    message=message,
                    question_id=question_code,
                    label=label,
                    section_code=question_code,
                    source="qc",
                )
            )
            continue

        if answer == "insufficient":
            issues.append(
                _make_form_generation_issue(
                    code="qc_insufficient",
                    message=(
                        "QC review marked this question as insufficient after FBI or record review."
                        if "fbi" in where_to_verify
                        else "QC review marked this question as insufficient. Resolve it before generating the form."
                    ),
                    question_id=question_code,
                    label=label,
                    section_code=question_code,
                    source="qc",
                )
            )

    return issues


def _validate_i914_part9_generation(
    pages: Iterable[Mapping[str, Any]],
    answers: Mapping[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    raw_entries = answers.get("p9_entries")
    entry_index: dict[tuple[str, str], dict[str, str]] = {}
    if isinstance(raw_entries, (list, tuple)):
        for raw_row in raw_entries:
            normalized_row = _normalize_i914_part9_row(raw_row)
            if not _i914_part9_row_has_content(normalized_row):
                continue
            entry_index[(normalized_row["part_number"], normalized_row["item_number"])] = normalized_row

    for page in pages:
        for item in page.get("items", []) or []:
            if _clean_text(item.get("responsible_party")).lower() != "client":
                continue
            if _clean_text(item.get("type")).lower() != "yes_no":
                continue

            item_id = _clean_text(item.get("id"))
            if not item_id:
                continue
            answer, found = _lookup_saved_answer(answers, item_id)
            normalized_answer = _normalize_option_answer(answer)
            if not found or normalized_answer not in {"yes", "no"}:
                continue

            part_number, item_number = _i914_question_part_and_item(item.get("code"), item.get("section"))
            if not part_number or not item_number:
                continue

            should_require_addendum = False
            if part_number == "4":
                should_require_addendum = normalized_answer == "yes"
            elif part_number == "3":
                should_require_addendum = _i914_part3_answer_requires_addendum(item, normalized_answer)
            if not should_require_addendum:
                continue

            entry = entry_index.get((part_number, item_number))
            if entry is None:
                issues.append(
                    _make_form_generation_issue(
                        code="missing_required_addendum",
                        message="A factual Part 9 addendum is required before generating the form.",
                        question_id=item_id,
                        label=_clean_text(item.get("form_text")) or item_id,
                        section_code=_clean_text(item.get("code")),
                    )
                )

    return issues


def _validate_i914_field_consistency(answers: Mapping[str, Any]) -> list[dict[str, str]]:
    _ = answers
    # Recent-arrival facts are derived and overridden later from consolidated evidence.
    # Keep preflight permissive here and let the post-generation review gate enforce
    # completion if the pipeline still cannot resolve the last-entry fields.
    return []


def _result_value_for_question_field(
    targets: Iterable[Mapping[str, Any]],
    results_by_id: Mapping[str, Mapping[str, Any]],
    *,
    question_id: str,
    field_id: str,
) -> str:
    normalized_question_id = _clean_text(question_id).lower()
    normalized_field_id = _clean_text(field_id).lower()
    for target in targets:
        if _clean_text(target.get("questionnaire_item_id")).lower() != normalized_question_id:
            continue
        target_field_id = _clean_text(target.get("questionnaire_field_id")).lower()
        if target_field_id != normalized_field_id:
            continue
        result_field_id = _clean_text(target.get("id"))
        if result_field_id:
            return _clean_text((results_by_id.get(result_field_id) or {}).get("value"))
    return ""


def _selected_yes_no_result_for_question(
    targets: Iterable[Mapping[str, Any]],
    results_by_id: Mapping[str, Mapping[str, Any]],
    *,
    question_id: str,
) -> str:
    normalized_question_id = _clean_text(question_id).lower()
    fallback_value = ""
    for target in targets:
        if _clean_text(target.get("questionnaire_item_id")).lower() != normalized_question_id:
            continue
        result_field_id = _clean_text(target.get("id"))
        if not result_field_id:
            continue
        result = results_by_id.get(result_field_id) or {}
        current_value = _normalize_option_answer(result.get("value"))
        option_value = _normalize_option_answer(target.get("questionnaire_option_value"))
        if option_value in {"yes", "no"}:
            if current_value == "yes":
                return option_value
            continue
        if current_value in {"yes", "no"}:
            fallback_value = current_value
    return fallback_value


def _collect_i914_result_review_issues(
    targets: list[dict[str, Any]],
    results_by_id: Mapping[str, Mapping[str, Any]],
    answers: Mapping[str, Any],
) -> list[str]:
    issues: list[str] = []
    critical_field_ids: set[str] = set()
    for target in targets:
        question_id = _clean_text(target.get("questionnaire_item_id")).lower()
        if question_id == "p2_last_entry" or question_id.startswith("p3_") or question_id.startswith("p4_") or question_id == "p9_entries":
            field_id = _clean_text(target.get("id"))
            if field_id:
                critical_field_ids.add(field_id)

    for field_id in critical_field_ids:
        result = results_by_id.get(field_id) or {}
        justification = _clean_text(result.get("justification"))
        value = _clean_text(result.get("value"))
        if _contains_i914_manual_review_marker(value) or _contains_i914_manual_review_marker(justification):
            issues.append("One or more I-914 fields still require manual review.")
            break

    recent_arrival_answer, found = _lookup_saved_answer(answers, "p3_9")
    if found and _normalize_option_answer(recent_arrival_answer) == "yes":
        missing_fields: list[str] = []
        if not _result_value_for_question_field(targets, results_by_id, question_id="p2_last_entry", field_id="last_entry_date"):
            missing_fields.append("the recent-arrival date")
        if not _result_value_for_question_field(targets, results_by_id, question_id="p2_last_entry", field_id="last_entry_city"):
            missing_fields.append("the last-entry city")
        if not _result_value_for_question_field(targets, results_by_id, question_id="p2_last_entry", field_id="last_entry_state"):
            missing_fields.append("the last-entry state")
        if missing_fields:
            issues.append(
                "Most recent arrival remains incomplete after evidence consolidation: "
                f"{_join_human_list(missing_fields)}."
            )

    prior_entry_answer, found = _lookup_saved_answer(answers, "p3_8")
    if found and _normalize_option_answer(prior_entry_answer) == "no":
        has_prior_entry_value = any(
            _clean_text((results_by_id.get(_clean_text(target.get("id"))) or {}).get("value"))
            for target in targets
            if _clean_text(target.get("questionnaire_item_id")).lower() == "p3_8"
            and _clean_text(target.get("questionnaire_field_id")).lower().startswith("prior_entry_")
        )
        if not has_prior_entry_value:
            issues.append(
                "Prior entries for the last five years remain incomplete and require manual review."
            )

    return list(dict.fromkeys(issues))


def validate_form_generation_requirements(
    db: Session,
    case_id: str,
    *,
    form_type: str,
) -> list[dict[str, str]]:
    normalized_form_type = _normalize_form_type(form_type)
    if not normalized_form_type:
        return [
            _make_form_generation_issue(
                code="invalid_form_type",
                message="A supported form type is required before generating the form.",
                question_id=_clean_text(form_type),
            )
        ]

    pages = _questionnaire_pages_for_form_defaults(normalized_form_type)
    raw_answers = get_questionnaire_answers(db, case_id, form_type=normalized_form_type)
    answers_for_validation = _apply_questionnaire_defaults_to_answers(
        pages,
        raw_answers,
        include_optional_defaults=False,
    )
    i914_validation_answers = answers_for_validation
    if normalized_form_type == "i-914":
        i914_validation_answers = _apply_i914_family_answer_rules(
            _clone_answer_value(answers_for_validation)
        )
        i914_validation_answers = _apply_i914_part9_addendum_answers(
            pages,
            i914_validation_answers,
        )

    issues: list[dict[str, str]] = []
    for page in pages:
        for item in page.get("items", []) or []:
            issues.extend(_collect_generation_issues(item, answers_for_validation))

    if normalized_form_type == "i-914":
        issues.extend(_validate_i914_part9_generation(pages, i914_validation_answers))
        issues.extend(_validate_i914_field_consistency(i914_validation_answers))

    known_codes = _form_codes_for_validation_pages(pages)
    issues.extend(
        _collect_qc_generation_validation_issues(
            db,
            case_id=case_id,
            form_type=normalized_form_type,
            known_codes=known_codes,
        )
    )

    deduped: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str, str, str]] = set()
    for issue in issues:
        key = (
            _clean_text(issue.get("source")),
            _clean_text(issue.get("question_id")),
            _clean_text(issue.get("field_id")),
            _clean_text(issue.get("row_label")),
            _clean_text(issue.get("message")),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(issue)

    if deduped and _i914_manual_review_bypass_enabled():
        log.warning(
            "validate_form_generation_requirements: I914_BYPASS_MANUAL_REVIEW is enabled. "
            "Ignoring %d validation issue(s) for case %s (form_type=%s): %s",
            len(deduped),
            case_id,
            normalized_form_type,
            [
                f"{_clean_text(issue.get('section_code'))}/{_clean_text(issue.get('question_id'))}/"
                f"{_clean_text(issue.get('field_id'))}"
                for issue in deduped
            ],
        )
        return []

    return deduped


def format_form_generation_validation_error(
    issues: Iterable[Mapping[str, Any]],
    *,
    max_items: int = 6,
) -> str:
    normalized_issues = [dict(issue) for issue in issues if isinstance(issue, Mapping)]
    if not normalized_issues:
        return "Form generation is blocked until the validation issues are resolved."

    lines = ["Form generation is blocked until the following issues are resolved:"]
    for issue in normalized_issues[:max_items]:
        section = _clean_text(issue.get("section_code"))
        label = _clean_text(issue.get("label"))
        row_label = _clean_text(issue.get("row_label"))
        message = _clean_text(issue.get("message")) or "Review this item."
        prefix_parts = [part for part in (section, label, row_label) if part]
        prefix = " - ".join(prefix_parts)
        lines.append(f"- {prefix}: {message}" if prefix else f"- {message}")

    remaining = len(normalized_issues) - max_items
    if remaining > 0:
        lines.append(f"- {remaining} additional validation issue(s) remain.")
    return "\n".join(lines)


def _i914_question_part_and_item(
    code: Any,
    section: Any,
) -> tuple[str, str]:
    cleaned_code = _clean_text(code)
    if cleaned_code:
        code_match = re.match(r"^(?P<part>\d+)\.(?P<item>.+)$", cleaned_code)
        if code_match:
            return (
                _clean_text(code_match.group("part")),
                _clean_text(code_match.group("item")).strip("."),
            )

    section_match = re.search(r"\bPart\s+(\d+)\b", _clean_text(section), re.IGNORECASE)
    if section_match and cleaned_code:
        return _clean_text(section_match.group(1)), cleaned_code
    return "", ""


def _i914_part3_explanation_clause_for_answer(
    instruction: str,
    normalized_answer: str,
) -> str:
    marker = f"if you selected {normalized_answer}"
    if marker not in instruction:
        return ""

    clause = instruction.split(marker, 1)[1]
    other_answer = "no" if normalized_answer == "yes" else "yes"
    other_marker = f"if you selected {other_answer}"
    if other_marker in clause:
        clause = clause.split(other_marker, 1)[0]
    return clause.strip()


def _i914_part3_answer_requires_addendum(
    item: Mapping[str, Any],
    normalized_answer: str,
) -> bool:
    if normalized_answer not in {"yes", "no"}:
        return False

    instruction = _normalize_hint_text(item.get("instruction"))
    if "explain" not in instruction:
        return False

    clause = _i914_part3_explanation_clause_for_answer(instruction, normalized_answer)
    if clause:
        return "explain" in clause

    if "if you selected yes" in instruction or "if you selected no" in instruction:
        return False

    return True


def _i914_saved_scalar_list(
    answers: Mapping[str, Any],
    question_id: str,
) -> list[str]:
    value, found = _lookup_saved_answer(answers, question_id)
    if not found:
        return []
    if isinstance(value, (list, tuple)):
        return [_clean_text(entry) for entry in value]
    return [_clean_text(value)]


def _i914_yes_no_display(normalized_answer: str) -> str:
    return "Yes" if normalized_answer == "yes" else "No"


def _format_i914_prior_entries_summary(
    answers: Mapping[str, Any],
    *,
    detention_facts: Mapping[str, Any] | None = None,
    classified_events: Sequence[_I914ClassifiedEvent] | None = None,
) -> str:
    dates = _i914_saved_scalar_list(answers, "p3_8.prior_entry_date")
    cities = _i914_saved_scalar_list(answers, "p3_8.prior_entry_city")
    states = _i914_saved_scalar_list(answers, "p3_8.prior_entry_state")
    statuses = _i914_saved_scalar_list(answers, "p3_8.prior_entry_status")
    row_count = max(len(dates), len(cities), len(states), len(statuses), 0)
    summaries: list[str] = []

    for index in range(row_count):
        raw_date = dates[index] if index < len(dates) else ""
        date = _normalize_date_text(raw_date) or _clean_text(raw_date)
        city = cities[index] if index < len(cities) else ""
        state = states[index] if index < len(states) else ""
        status = statuses[index] if index < len(statuses) else ""
        if not any((date, city, state, status)):
            continue

        parts: list[str] = []
        if date:
            parts.append(f"Date: {date}")
        place = ", ".join(part for part in (city, state) if part)
        if place:
            parts.append(f"Place: {place}")
        if status:
            parts.append(f"Status: {status}")
        summaries.append(f"Entry {index + 1} ({'; '.join(parts)})")

    if not summaries:
        summaries = _prior_entries_from_classified_events(classified_events)

    if not summaries:
        summaries = _prior_entries_from_last_entry_and_facts(answers, detention_facts)

    return "; ".join(summaries)


def _prior_entries_from_classified_events(
    classified_events: Sequence[_I914ClassifiedEvent] | None,
) -> list[str]:
    """Build prior-entry rows from immigration classified events in last 5 years."""
    if not classified_events:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * 5)
    rows: list[tuple[datetime, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for event in classified_events:
        authority_kind = _clean_text(getattr(event, "authority_kind", "")).lower()
        if authority_kind not in {"immigration", "unknown"}:
            continue

        normalized_date = _normalize_date_text(getattr(event, "date", ""))
        if not normalized_date:
            continue
        parsed_obj = parse_date_text(normalized_date)
        if parsed_obj is None:
            continue
        parsed_date = datetime(parsed_obj.year, parsed_obj.month, parsed_obj.day, tzinfo=timezone.utc)
        if parsed_date < cutoff:
            continue

        city = _clean_text(getattr(event, "location_city", ""))
        state = _normalize_us_state_code(getattr(event, "location_state", "")) or _clean_text(
            getattr(event, "location_state", "")
        )
        place = ", ".join(part for part in (city, state) if part)
        status = _clean_text(getattr(event, "outcome", "")) or _clean_text(getattr(event, "reason", ""))
        key = (normalized_date, place.lower(), status.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append((parsed_date, normalized_date, place, status))

    if not rows:
        return []

    rows.sort(key=lambda entry: entry[0], reverse=True)
    summaries: list[str] = []
    for index, (_, date, place, status) in enumerate(rows[:5], start=1):
        parts: list[str] = [f"Date: {date}"]
        if place:
            parts.append(f"Place: {place}")
        if status:
            parts.append(f"Status: {status[:120]}")
        summaries.append(f"Entry {index} ({'; '.join(parts)})")
    return summaries


def _prior_entries_from_last_entry_and_facts(
    answers: Mapping[str, Any],
    detention_facts: Mapping[str, Any] | None,
) -> list[str]:
    """Build a prior-entry summary row from p2_last_entry / detention_facts.

    When the user explicitly answered p3_8 = 'No' but the questionnaire's
    repeatable prior_entry_* fields are empty, the most-recent-entry data
    that the evidence pipeline already consolidated into ``p2_last_entry``
    (or ``detention_facts``) is the best available source. This helper
    synthesizes a single entry row from that data so the Part 9 addendum is
    compliant instead of producing a vague "to be confirmed" paragraph.
    """
    date = ""
    city = ""
    state = ""
    status = ""

    last_entry, found = _lookup_saved_answer(answers, "p2_last_entry")
    if found and isinstance(last_entry, Mapping):
        date = _normalize_date_text(last_entry.get("last_entry_date")) or _clean_text(
            last_entry.get("last_entry_date")
        )
        city = _clean_text(last_entry.get("last_entry_city"))
        status = _clean_text(last_entry.get("last_entry_status")) or _clean_text(last_entry.get("status"))
        state = (
            _normalize_us_state_code(last_entry.get("last_entry_state"))
            or _clean_text(last_entry.get("last_entry_state"))
        )

    if detention_facts:
        if not date:
            date = _normalize_date_text(detention_facts.get("date")) or _clean_text(
                detention_facts.get("date")
            )
        if not city:
            city = _clean_text(detention_facts.get("location_city"))
        if not state:
            state = (
                _normalize_us_state_code(detention_facts.get("location_state"))
                or _clean_text(detention_facts.get("location_state"))
            )
        if not status:
            status = _clean_text(detention_facts.get("status")) or _clean_text(detention_facts.get("outcome"))

    if not any((date, city, state, status)):
        return []

    parts: list[str] = []
    if date:
        parts.append(f"Date: {date}")
    place = ", ".join(p for p in (city, state) if p)
    if place:
        parts.append(f"Place: {place}")
    if status:
        parts.append(f"Status: {status}")
    return [f"Entry 1 ({'; '.join(parts)})"]


def _i914_saved_text_answer(
    answers: Mapping[str, Any],
    question_id: str,
) -> str:
    value, found = _lookup_saved_answer(answers, question_id)
    if not found:
        return ""
    return _clean_text(value)


def _format_i914_last_entry_summary(answers: Mapping[str, Any]) -> str:
    value, found = _lookup_saved_answer(answers, "p2_last_entry")
    if not found or not isinstance(value, Mapping):
        return ""

    city = _clean_text(value.get("last_entry_city"))
    state = _normalize_us_state_code(value.get("last_entry_state")) or _clean_text(
        value.get("last_entry_state")
    )
    raw_entry_date = value.get("last_entry_date")
    entry_date = _normalize_date_text(raw_entry_date) or _clean_text(raw_entry_date)
    i94_record_number = _clean_text(value.get("i94_record_number"))

    parts: list[str] = []
    if entry_date:
        parts.append(f"Date: {entry_date}")
    place = ", ".join(part for part in (city, state) if part)
    if place:
        parts.append(f"Place: {place}")
    if i94_record_number:
        parts.append(f"Form I-94: {i94_record_number}")
    return "; ".join(parts)


def _format_i914_recent_arrival_summary(answers: Mapping[str, Any]) -> str:
    parts: list[str] = []

    last_entry_summary = _format_i914_last_entry_summary(answers)
    if last_entry_summary:
        parts.append(last_entry_summary)

    arrival_circumstances = _i914_saved_text_answer(answers, "p3_9.arrival_circumstances")
    if arrival_circumstances:
        parts.append(f"Circumstances: {arrival_circumstances}")

    return "; ".join(parts)


def _format_i914_part4_incident_summary(answers: Mapping[str, Any]) -> str:
    value, found = _lookup_saved_answer(answers, "p4_1_details")
    if not found:
        return ""

    rows: list[Any]
    if isinstance(value, Mapping):
        rows = [value]
    elif isinstance(value, (list, tuple)):
        rows = list(value)
    else:
        return ""

    summaries: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue

        reason = _clean_text(row.get("incident_reason"))
        raw_incident_date = row.get("incident_date")
        incident_date = _normalize_date_text(raw_incident_date) or _clean_text(raw_incident_date)
        location = _clean_text(row.get("incident_location"))
        outcome = _clean_text(row.get("incident_outcome"))
        if not any((reason, incident_date, location, outcome)):
            continue

        parts: list[str] = []
        if reason:
            parts.append(f"Reason: {reason}")
        if incident_date:
            parts.append(f"Date: {incident_date}")
        if location:
            parts.append(f"Location: {location}")
        if outcome:
            parts.append(f"Outcome: {outcome}")
        summaries.append(f"Incident {index + 1} ({'; '.join(parts)})")

    return "; ".join(summaries)


_I914_PART9_PLACEHOLDER_TEXT = "Details to be provided upon review of supporting documentation."
_I914_MANUAL_REVIEW_PREFIX = "REQUIRES MANUAL COMPLETION:"


def _contains_i914_manual_review_marker(text: Any) -> bool:
    normalized = _normalize_hint_text(text)
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            _normalize_hint_text(_I914_PART9_PLACEHOLDER_TEXT),
            _normalize_hint_text(_I914_MANUAL_REVIEW_PREFIX),
            "manual review required",
        )
    )


def _join_human_list(values: Iterable[str]) -> str:
    cleaned_values = [_clean_text(value) for value in values if _clean_text(value)]
    if not cleaned_values:
        return ""
    if len(cleaned_values) == 1:
        return cleaned_values[0]
    if len(cleaned_values) == 2:
        return f"{cleaned_values[0]} and {cleaned_values[1]}"
    return f"{', '.join(cleaned_values[:-1])}, and {cleaned_values[-1]}"


def _split_location_city_state(value: Any) -> tuple[str, str]:
    cleaned = _clean_text(value)
    if not cleaned:
        return "", ""
    match = re.search(rf"^(?P<city>.+?)(?:,|\s+)(?P<state>{_US_STATE_PATTERN})$", cleaned, re.IGNORECASE)
    if match:
        city = _clean_text(match.group("city")).strip(" ,.")
        state = _normalize_us_state_code(match.group("state"))
        if city or state:
            return city, state
    inferred_state = _infer_state_from_city(cleaned)
    return cleaned, inferred_state


def _i914_detention_facts_from_answers(answers: Mapping[str, Any]) -> dict[str, str]:
    facts: dict[str, str] = {}
    rows: list[Any] = []
    value = answers.get("p4_1_details")
    if isinstance(value, Mapping):
        rows = [value]
    elif isinstance(value, (list, tuple)):
        rows = list(value)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        reason = _clean_text(row.get("incident_reason"))
        incident_date = _normalize_date_text(row.get("incident_date")) or _clean_text(row.get("incident_date"))
        location = _clean_text(row.get("incident_location"))
        outcome = _clean_text(row.get("incident_outcome"))
        if not any((reason, incident_date, location, outcome)):
            continue
        if reason:
            facts["reason"] = reason
        if incident_date:
            facts["date"] = incident_date
        if location:
            facts["location"] = location
            city, state = _split_location_city_state(location)
            if city:
                facts["location_city"] = city
            if state:
                facts["location_state"] = state
        if outcome:
            facts["outcome"] = outcome
        break

    last_entry_summary_value = answers.get("p2_last_entry")
    if isinstance(last_entry_summary_value, Mapping):
        last_entry_date = _normalize_date_text(last_entry_summary_value.get("last_entry_date")) or _clean_text(
            last_entry_summary_value.get("last_entry_date")
        )
        last_entry_city = _clean_text(last_entry_summary_value.get("last_entry_city"))
        last_entry_state = (
            _normalize_us_state_code(last_entry_summary_value.get("last_entry_state"))
            or _clean_text(last_entry_summary_value.get("last_entry_state"))
        )
        if last_entry_date and not facts.get("date"):
            facts["date"] = last_entry_date
        if (last_entry_city or last_entry_state) and not facts.get("location"):
            facts["location"] = ", ".join(part for part in (last_entry_city, last_entry_state) if part)
        if last_entry_city and not facts.get("location_city"):
            facts["location_city"] = last_entry_city
        if last_entry_state and not facts.get("location_state"):
            facts["location_state"] = last_entry_state

    arrival_circumstances = _i914_saved_text_answer(answers, "p3_9.arrival_circumstances")
    if arrival_circumstances and not facts.get("reason"):
        facts["reason"] = arrival_circumstances
    if arrival_circumstances and _OUTCOME_RE.search(arrival_circumstances) and not facts.get("outcome"):
        facts["outcome"] = arrival_circumstances
    return facts


def _i914_detention_fact_looks_noisy(value: Any) -> bool:
    normalized = _normalize_hint_text(value)
    if not normalized:
        return False

    if ("pregunta" in normalized and "respuesta" in normalized) or (
        "question" in normalized and "answer" in normalized
    ):
        return True

    return bool(re.search(r"\bitem\s+\d+\b", normalized) and ("pregunta" in normalized or "question" in normalized))


def _merge_i914_detention_facts(
    answers: Mapping[str, Any],
    detention_facts: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    merged = dict(_i914_detention_facts_from_answers(answers))
    if detention_facts:
        for key, value in detention_facts.items():
            cleaned_value = _clean_text(value)
            if not cleaned_value:
                continue
            if key in {"reason", "outcome"} and _i914_detention_fact_looks_noisy(cleaned_value):
                continue
            if key in {"date", "location", "location_city", "location_state"} and _clean_text(merged.get(key)):
                continue
            merged[key] = cleaned_value

    if not _clean_text(merged.get("location")):
        city = _clean_text(merged.get("location_city"))
        state = _normalize_us_state_code(merged.get("location_state")) or _clean_text(
            merged.get("location_state")
        )
        if city or state:
            merged["location"] = ", ".join(part for part in (city, state) if part)

    if _clean_text(merged.get("location")):
        city, state = _split_location_city_state(merged.get("location"))
        if city and not _clean_text(merged.get("location_city")):
            merged["location_city"] = city
        if state and not _clean_text(merged.get("location_state")):
            merged["location_state"] = state

    return merged


def _build_i914_recent_arrival_narrative(answers: Mapping[str, Any]) -> str:
    parts: list[str] = []
    recent_arrival_summary = _format_i914_recent_arrival_summary(answers)
    if recent_arrival_summary:
        parts.append(f"Most recent arrival: {recent_arrival_summary}.")
    return " ".join(part for part in parts if part).strip()


def _build_i914_recent_arrival_field_value(
    answers: Mapping[str, Any],
    *,
    detention_facts: Mapping[str, Any] | None = None,
    classified_events: Sequence[_I914ClassifiedEvent] | None = None,
) -> str:
    saved_value = _i914_saved_text_answer(answers, "p3_9.arrival_circumstances")
    if saved_value:
        return saved_value

    parts: list[str] = []
    last_entry_summary = _format_i914_last_entry_summary(answers)
    if last_entry_summary:
        parts.append(f"The most recent arrival is documented as {last_entry_summary}.")

    # Prefer the dedicated p3_9 template (which frames the arrival around the
    # trafficking nexus) rather than the legacy generic detention narrative.
    events_for_p3_9 = _events_for_part9_item("p3_9", classified_events, detention_facts)
    if events_for_p3_9:
        template_text = _i914_build_part9_text("p3_9", events_for_p3_9)
        if template_text:
            parts.append(template_text)

    if parts:
        return " ".join(part for part in parts if part).strip()
    return ""


# ---------------------------------------------------------------------------
# Source hierarchy: timeline consolidation for Part 3/4
# ---------------------------------------------------------------------------

_TIMELINE_EVENT_RE = re.compile(r"(?P<date>\d{1,2}/\d{1,2}/\d{4})")

_DETENTION_KEYWORDS_RE = re.compile(
    r"\b(?:detain|detained|detention|arrest|arrested|apprehend|apprehended|"
    r"custody|processed|fingerprint|charged|cited|inadmissibl)\w*\b"
    r"|\b(?:cbp|border\s*patrol|ice|lea)\b",
    re.IGNORECASE,
)

_LOCATION_RE = re.compile(
    r"\b(?:in|at|near|through|via)\s+([A-Z][a-z]+(?:\s*,\s*[A-Z]{2})?)",
)

_OUTCOME_RE = re.compile(
    r"\b(?:releas|process|fingerprint|photograph|court\s*date|nta|notice\s*to\s*appear|"
    r"removed|deport|bond|parole|asylum|dismiss|granted|denied|pending|"
    r"voluntary\s*departure|order\s*of\s*removal|hearing|adjudicat|"
    r"placed\s*in\s*(?:removal\s*)?proceedings|i-?94|"
    r"recognizance|supervision|transfer|referr|shelter|"
    r"sponsor|reunif|ORR|hhs)\w*\b",
    re.IGNORECASE,
)

_SOURCE_TIER_KEYWORDS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\bfbi\b|\bfoia\b|\blea\b|\bcourt\b|\bcriminal\b", re.IGNORECASE), 1),
    (re.compile(r"\bdeclaration\b|\baffidavit\b", re.IGNORECASE), 2),
    (re.compile(r"\bbiocall\b|\bbio\s*call\b|\bintake\b", re.IGNORECASE), 3),
]


def _source_tier_for_evidence(evidence_item: Mapping[str, Any]) -> int:
    """Return source tier (1=highest). Defaults to 4 for unknown sources."""
    haystack = " ".join(
        str(evidence_item.get(k, "") or "")
        for k in ("sectionName", "documentType", "sourceType", "originalFilename", "source")
    )
    for pattern, tier in _SOURCE_TIER_KEYWORDS:
        if pattern.search(haystack):
            return tier
    return 4


_TIMELINE_ITEM_KEYWORD_FILTERS: dict[str, re.Pattern[str]] = {
    "p4_1b": re.compile(
        r"\b(?:detain|detained|detention|arrest|arrested|apprehend|apprehended|"
        r"custody|cited|citation|processed|CBP|border\s*patrol|ICE)\b",
        re.IGNORECASE,
    ),
    "p4_1c": re.compile(
        r"\b(?:charge|charged|indictment|information|grand\s*jury|formal)\b",
        re.IGNORECASE,
    ),
    "p4_1d": re.compile(
        r"\b(?:convict|convicted|conviction|guilty|plea|sentence|sentenced)\b",
        re.IGNORECASE,
    ),
    "p4_1e": re.compile(
        r"\b(?:diversion|deferred|withheld|pre-?trial|PTI|adjudicat)\b",
        re.IGNORECASE,
    ),
    "p4_1f": re.compile(
        r"\b(?:probation|parole|suspended\s*sentence|community\s*service|supervision)\b",
        re.IGNORECASE,
    ),
    "p4_1g": re.compile(
        r"\b(?:jail|prison|incarcerat|penitentiary|correctional|sentence\s*served)\b",
        re.IGNORECASE,
    ),
    "p4_9a": re.compile(
        r"\b(?:pending|removal\s*proceedings|EOIR|immigration\s*court|hearing\s*date|"
        r"currently\s*in\s*proceedings)\b",
        re.IGNORECASE,
    ),
    "p4_9b": re.compile(
        r"\b(?:NTA|notice\s*to\s*appear|placed\s*in.*proceedings|proceedings?\s*initiated|"
        r"removal\s*proceedings|commenced)\b",
        re.IGNORECASE,
    ),
    "p4_9c": re.compile(
        r"\b(?:removed|excluded|deported|physically\s*removed|execution\s*of\s*removal)\b",
        re.IGNORECASE,
    ),
    "p4_9d": re.compile(
        r"\b(?:order\s*of\s*removal|removal\s*order|ordered\s*removed|ordered\s*deported|"
        r"final\s*order)\b",
        re.IGNORECASE,
    ),
    "p4_9e": re.compile(
        r"\b(?:denied|denial|inadmissib|refused\s*entry|visa\s*denied|"
        r"denied\s*admission)\b",
        re.IGNORECASE,
    ),
    "p4_9f": re.compile(
        r"\b(?:voluntary\s*departure|failed\s*to\s*depart|overstay)\b",
        re.IGNORECASE,
    ),
}


def _build_timeline_summary(events: list[dict[str, Any]]) -> str:
    lines = ["[CONSOLIDATED TIMELINE FROM ALL SOURCES]"]
    for event in events:
        tier_label = {1: "Tier1-Official", 2: "Tier2-Declaration", 3: "Tier3-Intake"}.get(
            event["tier"], "Tier4-Other"
        )
        source_info = f" ({event['source']})" if event["source"] else ""
        page_info = f" p.{event['page']}" if event.get("page") is not None else ""
        lines.append(f"[{tier_label}{source_info}{page_info}] {event['text']}")
    lines.append("[END CONSOLIDATED TIMELINE]")
    return "\n".join(lines)


def _consolidate_evidence_timeline(
    evidence_by_id: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    form_type: str,
) -> dict[str, Any]:
    """Consolidate timeline events from all Part 3/4 evidence and inject
    a category-filtered timeline summary into each field's evidence bundle.

    Each field receives only the timeline events whose text matches the
    keywords relevant to that field's questionnaire item (e.g. p4_1d only
    sees conviction-related events). Fields without a specific keyword
    filter receive the full unfiltered timeline.
    """
    if _normalize_form_type(form_type) != "i-914":
        return evidence_by_id

    part34_fields: list[tuple[str, str]] = []
    for target in targets:
        q_section = _clean_text(target.get("questionnaire_section")).lower()
        q_item_id = _clean_text(target.get("questionnaire_item_id")).lower()
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        is_part34 = (
            "part 3" in q_section
            or "part 4" in q_section
            or q_item_id.startswith("p3_")
            or q_item_id.startswith("p4_")
        )
        if is_part34:
            part34_fields.append((field_id, q_item_id))

    if not part34_fields:
        return evidence_by_id

    timeline_events: list[dict[str, Any]] = []
    seen_texts: set[str] = set()

    for field_id, _ in part34_fields:
        bundle = evidence_by_id.get(field_id)
        if not isinstance(bundle, dict):
            continue
        evidence_list = bundle.get("evidence")
        if not isinstance(evidence_list, list):
            continue
        for item in evidence_list:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            has_date = bool(_TIMELINE_EVENT_RE.search(text))
            has_detention_keyword = bool(_DETENTION_KEYWORDS_RE.search(text))
            if not (has_date or has_detention_keyword):
                continue
            text_key = text[:120].lower()
            if text_key in seen_texts:
                continue
            seen_texts.add(text_key)
            tier = _source_tier_for_evidence(item)
            timeline_events.append({
                "text": text,
                "tier": tier,
                "page": item.get("pageNumber"),
                "source": str(item.get("source", "") or item.get("sectionName", "") or ""),
            })

    if not timeline_events:
        return evidence_by_id

    timeline_events.sort(key=lambda e: (e["tier"], str(e.get("page") or "")))
    full_timeline_summary = _build_timeline_summary(timeline_events)

    for field_id, q_item_id in part34_fields:
        keyword_filter = _TIMELINE_ITEM_KEYWORD_FILTERS.get(q_item_id)
        if keyword_filter:
            filtered = [e for e in timeline_events if keyword_filter.search(e["text"])]
            timeline_summary = _build_timeline_summary(filtered) if filtered else full_timeline_summary
        else:
            timeline_summary = full_timeline_summary

        bundle = evidence_by_id.get(field_id)
        if not isinstance(bundle, dict):
            evidence_by_id[field_id] = {
                "evidence": [{"text": timeline_summary, "source": "consolidated-timeline"}],
                "text_context": timeline_summary,
                "source_pages": [],
                "stage": "timeline-injected",
                "matches": [],
            }
            continue

        existing_evidence = bundle.get("evidence")
        if isinstance(existing_evidence, list):
            existing_evidence.insert(0, {
                "text": timeline_summary,
                "source": "consolidated-timeline",
                "sourceType": "consolidated-timeline",
            })
        else:
            bundle["evidence"] = [{"text": timeline_summary, "source": "consolidated-timeline"}]

        existing_context = str(bundle.get("text_context", "") or "")
        bundle["text_context"] = f"{timeline_summary}\n\n{existing_context}".strip()

    return evidence_by_id


# ---------------------------------------------------------------------------
# Part 4 post-processing: consistency check and table autocompletion
# ---------------------------------------------------------------------------

_I914_PART4_1_YES_NO_IDS = (
    "p4_1a", "p4_1b", "p4_1c", "p4_1d", "p4_1e", "p4_1f", "p4_1g", "p4_1h", "p4_1i",
)

_I914_PART4_9_YES_NO_IDS = (
    "p4_9a", "p4_9b", "p4_9c", "p4_9d", "p4_9e", "p4_9f",
)

_I914_PART4_YES_NO_IDS = _I914_PART4_1_YES_NO_IDS + _I914_PART4_9_YES_NO_IDS

_I914_PART4_DETAIL_FIELD_IDS = (
    "incident_reason", "incident_date", "incident_location", "incident_outcome",
)


_I914_DEFAULT_OUTCOME_BY_CATEGORY: dict[str, str] = {
    "immigration_detention": "Processed and released",
    "nta_issued": "Notice to Appear issued; proceedings pending (confirm current status from case records)",
    "removal_proceedings_initiated": "Removal proceedings initiated (confirm current status from case records)",
    "removal_proceedings_pending": "Removal proceedings currently pending (confirm status from case records)",
    "removal_order": "Removal order entered (confirm date and outcome from EOIR record)",
    "deported_excluded": "Physically removed or deported (confirm date and port from immigration record)",
    "denial_of_admission": "Admission denied (confirm details from consular / inspection record)",
    "voluntary_departure_granted": "Voluntary departure granted (confirm compliance from immigration record)",
    "voluntary_departure_overstayed": "Voluntary departure granted but applicant did not depart in time",
    "criminal_arrest": "Outcome to be confirmed from arresting-agency and court records",
    "criminal_citation": "Outcome to be confirmed from citing-agency record",
    "criminal_detention": "Outcome to be confirmed from booking / court records",
    "formal_charge": "Outcome to be confirmed from court record",
    "diversion_deferred_withheld": "Outcome to be confirmed from court record (diversion / deferred / withheld adjudication)",
    "conviction": "Outcome to be confirmed from court record (sentence and disposition)",
    "probation_parole_suspended": "Outcome to be confirmed from sentencing / supervision record",
    "jail_prison": "Outcome to be confirmed from sentencing / incarceration record",
}


def _i914_default_outcome_for_category(category: Any) -> str:
    """Return a conservative default outcome string for Part 4 table rows.

    The PDF detail table must never carry an empty ``incident_outcome`` cell
    when a Yes answer is claimed; USCIS instructions require an explicit
    disposition. We fall back to a placeholder that makes it obvious the
    outcome still needs to be pulled from the underlying records rather than
    inventing a specific outcome.
    """
    key = _clean_text(category).lower()
    if not key:
        return "Outcome to be confirmed from case records"
    return _I914_DEFAULT_OUTCOME_BY_CATEGORY.get(
        key, "Outcome to be confirmed from case records"
    )


def _i914_row_slot_index_for_target(target: Mapping[str, Any]) -> int:
    """Return the 0-based row slot index for a Part 4 detail target."""
    explicit_slot = _infer_target_repeatable_slot_index(target)
    if explicit_slot is not None and explicit_slot >= 0:
        return explicit_slot
    row_index_raw = (
        target.get("questionnaire_row_index")
        or target.get("row_index")
        or 0
    )
    try:
        return max(0, int(row_index_raw))
    except (TypeError, ValueError):
        return 0


def _i914_infer_category_from_reason_text(reason: str) -> str:
    """Best-effort guess of a taxonomy category from a reason / outcome string.

    Used when saved answers describe an incident in plain language but no
    classified event is available. Falls back to an empty string (which makes
    :func:`_i914_default_outcome_for_category` return a generic placeholder).
    """
    normalized = _normalize_hint_text(reason)
    if not normalized:
        return ""
    if "immigration detention" in normalized or "cbp" in normalized or "ice" in normalized or "border" in normalized:
        return "immigration_detention"
    if "jail" in normalized or "prison" in normalized or "incarcerat" in normalized:
        return "jail_prison"
    if "convict" in normalized or "found guilty" in normalized or "pleaded guilty" in normalized:
        return "conviction"
    if "probation" in normalized or "parole" in normalized or "suspended sentence" in normalized:
        return "probation_parole_suspended"
    if "diversion" in normalized or "deferred" in normalized or "withheld" in normalized:
        return "diversion_deferred_withheld"
    if "charge" in normalized or "indict" in normalized:
        return "formal_charge"
    if "citation" in normalized or "cited" in normalized:
        return "criminal_citation"
    if "arrest" in normalized:
        return "criminal_arrest"
    return ""


def _i914_fill_missing_outcome_cell(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    saved_row: Mapping[str, Any],
) -> None:
    """Populate ``incident_outcome`` on the first Part 4 row if it is blank.

    Part 4 of the I-914 requires an outcome / disposition for each listed
    event. When the user provided reason / date / location but left outcome
    empty, we inject a category-aware placeholder instead of letting the PDF
    ship with a blank disposition cell.
    """
    reason = _clean_text(saved_row.get("incident_reason"))
    outcome_saved = _clean_text(saved_row.get("incident_outcome"))
    if outcome_saved:
        return
    category = _i914_infer_category_from_reason_text(reason)
    default_outcome = _i914_default_outcome_for_category(category)
    detail_targets = [
        t for t in targets
        if _clean_text(t.get("questionnaire_item_id")).lower() == "p4_1_details"
    ]
    first_slot = _i914_first_available_slot_index(detail_targets, results_by_id)
    for target in detail_targets:
        if _clean_text(target.get("questionnaire_field_id")).lower() != "incident_outcome":
            continue
        if _i914_row_slot_index_for_target(target) != first_slot:
            continue
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        if _clean_text((results_by_id.get(field_id) or {}).get("value")):
            continue
        _set_result_value(
            results_by_id,
            field_id,
            default_outcome,
            confidence="medium",
            justification=(
                "Auto-filled missing Part 4 disposition with a category-aware placeholder "
                f"({category or 'generic'}); confirm from case records before filing."
            ),
        )
        return


def _i914_first_available_slot_index(
    detail_targets: Iterable[Mapping[str, Any]],
    results_by_id: Mapping[str, Mapping[str, Any]],
) -> int:
    """Pick the lowest row index to populate in the Part 4 detail table.

    Prefers an empty slot so we never overwrite an existing row; if every slot
    already carries a value (typically during a regeneration), returns the
    lowest existing slot so the subsequent ``_dedupe`` pass can clear the rest.
    """
    slots_seen: set[int] = set()
    empty_slots: set[int] = set()
    for target in detail_targets:
        q_field_id = _clean_text(target.get("questionnaire_field_id")).lower()
        if q_field_id not in _I914_PART4_DETAIL_FIELD_IDS:
            continue
        slot_index = _i914_row_slot_index_for_target(target)
        slots_seen.add(slot_index)
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        existing = _clean_text((results_by_id.get(field_id) or {}).get("value"))
        if not existing:
            empty_slots.add(slot_index)
    if empty_slots:
        return min(empty_slots)
    if slots_seen:
        return min(slots_seen)
    return 0


def _collect_i914_classified_events(
    evidence_by_id: Mapping[str, Any],
    field_ids: Iterable[str],
) -> list[_I914ClassifiedEvent]:
    """Run the I-914 taxonomy classifier over a set of evidence bundles.

    Normalizes each evidence item into ``{text, tier, page, ...}`` before
    delegating to :func:`i914_event_taxonomy.classify_evidence_events`. Tier is
    pre-computed with :func:`_source_tier_for_evidence` so the pure taxonomy
    module does not need to re-inspect raw metadata.
    """
    normalized: list[dict[str, Any]] = []
    seen_text_keys: set[str] = set()
    for field_id in field_ids:
        bundle = evidence_by_id.get(field_id)
        if not isinstance(bundle, Mapping):
            continue
        evidence_list = bundle.get("evidence")
        if not isinstance(evidence_list, list):
            continue
        for item in evidence_list:
            if not isinstance(item, Mapping):
                continue
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            key = text[:160].lower()
            if key in seen_text_keys:
                continue
            seen_text_keys.add(key)
            tier = _source_tier_for_evidence(item)
            normalized.append(
                {
                    "text": text,
                    "tier": tier,
                    "page": item.get("pageNumber") or item.get("page"),
                    "source": item.get("source", ""),
                }
            )
    return _i914_classify_evidence_events(normalized)


def _extract_detention_facts_from_evidence(
    evidence_by_id: dict[str, Any],
    part4_field_ids: list[str],
) -> dict[str, str]:
    """Compatibility wrapper over the new I-914 event taxonomy classifier.

    Preserves the legacy signature/return shape expected by downstream callers:

        {date, location, location_city, location_state, reason, outcome, source_tier}

    Only the "best" classified event is surfaced as ``facts``, and only when
    its ``source_tier <= 2`` (i.e. backed by an official record or sworn
    declaration). For weaker tiers we intentionally return an empty dict so
    that post-processors fall back to conservative boilerplate instead of
    emitting hardcoded wildcard sentences.
    """
    events = _collect_i914_classified_events(evidence_by_id, part4_field_ids)
    if not events:
        return {}

    # Preferir un evento migratorio de deteccion o un arresto criminal, porque
    # la firma legacy de "detention_facts" es usada principalmente para poblar
    # p2_last_entry / p3_9 / tabla 4.1.
    preference: list[_I914EventCategory] = [
        _I914EventCategory.IMMIGRATION_DETENTION,
        _I914EventCategory.CRIMINAL_ARREST,
        _I914EventCategory.CRIMINAL_DETENTION,
        _I914EventCategory.FORMAL_CHARGE,
        _I914EventCategory.CONVICTION,
        _I914EventCategory.NTA_ISSUED,
        _I914EventCategory.REMOVAL_PROCEEDINGS_INITIATED,
    ]

    best: _I914ClassifiedEvent | None = None
    for preferred in preference:
        for event in events:
            if event.category == preferred and event.source_tier <= 2:
                best = event
                break
        if best is not None:
            break
    if best is None:
        best = min(events, key=lambda e: e.source_tier)
    if best.source_tier > 2:
        return {}

    location_combined = ""
    if best.location_city and best.location_state:
        location_combined = f"{best.location_city}, {best.location_state}"
    elif best.location_city:
        location_combined = best.location_city
    elif best.location_state:
        location_combined = best.location_state

    result: dict[str, str] = {"source_tier": str(best.source_tier)}
    if best.date:
        result["date"] = best.date
    if location_combined:
        result["location"] = location_combined
    if best.location_city:
        result["location_city"] = best.location_city
    if best.location_state:
        result["location_state"] = best.location_state
    if best.reason:
        result["reason"] = best.reason
    if best.outcome:
        result["outcome"] = best.outcome
    return result


def _postprocess_i914_critical_field_override(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    *,
    detention_facts: Mapping[str, Any] | None = None,
) -> None:
    if not detention_facts:
        return
    source_tier = _safe_int(detention_facts.get("source_tier")) or 4
    if source_tier > 2:
        return

    field_overrides = {
        "last_entry_date": _normalize_date_text(detention_facts.get("date")) or _clean_text(detention_facts.get("date")),
        "last_entry_city": _clean_text(detention_facts.get("location_city")),
        "last_entry_state": _normalize_us_state_code(detention_facts.get("location_state")),
    }

    for target in targets:
        question_item_id = _clean_text(target.get("questionnaire_item_id")).lower()
        question_field_id = _clean_text(target.get("questionnaire_field_id")).lower()
        canonical_id = _clean_text(target.get("canonical_questionnaire_id")).lower()
        if question_item_id != "p2_last_entry" and not canonical_id.startswith("p2_last_entry."):
            continue
        if question_field_id not in field_overrides:
            question_field_id = canonical_id.rsplit(".", 1)[-1] if "." in canonical_id else ""
        override_value = _clean_text(field_overrides.get(question_field_id))
        field_id = _clean_text(target.get("id"))
        if not field_id or not override_value:
            continue

        current_result = results_by_id.get(field_id) or {}
        current_value = _clean_text(current_result.get("value"))
        current_confidence = _clean_text(current_result.get("confidence")).lower() or "low"
        if current_value.lower() == override_value.lower():
            continue
        if current_confidence == "high" and source_tier > 1:
            continue

        _set_result_value(
            results_by_id,
            field_id,
            override_value,
            confidence="high" if source_tier == 1 else "medium",
            justification=(
                "Overrode the last-entry field with higher-tier consolidated evidence "
                f"(tier {source_tier}): {override_value}."
            ),
        )


def _postprocess_i914_arrival_circumstances(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    answers: Mapping[str, Any],
    *,
    detention_facts: Mapping[str, Any] | None = None,
    classified_events: Sequence[_I914ClassifiedEvent] | None = None,
) -> None:
    recent_arrival_answer, found = _lookup_saved_answer(answers, "p3_9")
    if not found or _normalize_option_answer(recent_arrival_answer) != "yes":
        return

    fill_value = _build_i914_recent_arrival_field_value(
        answers,
        detention_facts=detention_facts,
        classified_events=classified_events,
    )
    if not fill_value:
        return

    is_manual_review_fill = _contains_i914_manual_review_marker(fill_value)
    for target in targets:
        if _clean_text(target.get("questionnaire_item_id")).lower() != "p3_9":
            continue
        if _clean_text(target.get("questionnaire_field_id")).lower() != "arrival_circumstances":
            continue
        field_id = _clean_text(target.get("id"))
        if not field_id or _clean_text(results_by_id.get(field_id, {}).get("value")):
            continue
        _set_result_value(
            results_by_id,
            field_id,
            fill_value,
            confidence="low" if is_manual_review_fill else "medium",
            justification=(
                "Marked recent-arrival circumstances for manual review because the case evidence "
                "did not provide a complete factual narrative."
                if is_manual_review_fill
                else "Auto-completed recent-arrival circumstances from consolidated evidence."
            ),
        )


def _postprocess_i914_part4_consistency(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: dict[str, Any],
    *,
    detention_facts: dict[str, str] | None = None,
    classified_events: Sequence[_I914ClassifiedEvent] | None = None,
) -> list[dict[str, Any]]:
    """Force Yes / flag inconsistencies when strong evidence (tier <= 2)
    contradicts a 'No' answer for Part 4 items.

    Unlike the previous soft implementation (which only appended a CONFLICT
    note), this version:

    - When tier <= 2 evidence of a category mapped to item X exists and X is
      answered "No", the answer is forced to "Yes" at ``low`` confidence and a
      detailed justification is injected so the downstream review collector
      surfaces the conflict.
    - Returns a list of ``review_issue`` dicts so the pipeline can escalate
      them (including raising ``ReviewRequiredError`` when appropriate).
    """
    del detention_facts  # kept in the signature for backward compatibility.

    part4_targets = [
        t for t in targets
        if _clean_text(t.get("questionnaire_item_id")).lower() in _I914_PART4_YES_NO_IDS
    ]
    if not part4_targets:
        return []

    if classified_events is None:
        all_part4_field_ids = [_clean_text(t.get("id")) for t in part4_targets if _clean_text(t.get("id"))]
        classified_events = _collect_i914_classified_events(evidence_by_id, all_part4_field_ids)

    if not classified_events:
        return []

    events_per_item = _i914_map_events_to_part4_items(classified_events)
    strong_events_per_item: dict[str, list[_I914ClassifiedEvent]] = {
        item_id: [e for e in bucket if e.source_tier <= 2]
        for item_id, bucket in events_per_item.items()
    }

    targets_by_question: dict[str, list[dict[str, Any]]] = {}
    for target in part4_targets:
        q_item_id = _clean_text(target.get("questionnaire_item_id")).lower()
        targets_by_question.setdefault(q_item_id, []).append(target)

    review_issues: list[dict[str, Any]] = []
    for question_id, bucket in strong_events_per_item.items():
        if not bucket or question_id not in targets_by_question:
            continue
        current_answer = _selected_yes_no_result_for_question(
            targets,
            results_by_id,
            question_id=question_id,
        )
        if current_answer == "yes":
            continue  # Nothing to force; evidence already matches the answer.

        best_event = bucket[0]
        justification = (
            f"Tier-{best_event.source_tier} evidence of {best_event.category.value} "
            f"contradicts the previous 'No' answer. Forced to 'Yes' pending manual review."
        )
        yes_override_applied = False
        for target in targets_by_question[question_id]:
            field_id = _clean_text(target.get("id"))
            if not field_id:
                continue
            result = results_by_id.get(field_id)
            if result is None:
                continue
            target_option = _clean_text(target.get("questionnaire_target_option")).lower()
            # For radio/checkbox style targets we only override the "Yes" row;
            # siblings ("No" row) must become unchecked.
            current_value = _clean_text(result.get("value")).lower()
            if target_option in {"yes", "y", "true", "1"}:
                _set_result_value(
                    results_by_id,
                    field_id,
                    "Yes",
                    confidence="low",
                    justification=justification,
                )
                yes_override_applied = True
            elif target_option in {"no", "n", "false", "0"}:
                if current_value in {"yes", "y", "true", "1", "x", "checked", "on"}:
                    continue  # leave it to the downstream answer-formatter
                _set_result_value(
                    results_by_id,
                    field_id,
                    "",
                    confidence="low",
                    justification=justification,
                )

        if yes_override_applied:
            review_issues.append(
                {
                    "item_id": question_id,
                    "category": best_event.category.value,
                    "tier": best_event.source_tier,
                    "message": (
                        f"Item {question_id} was previously answered 'No' but "
                        f"tier-{best_event.source_tier} evidence of "
                        f"{best_event.category.value} was found. Forced to 'Yes' "
                        "for manual review."
                    ),
                }
            )
    return review_issues


_I914_NTA_MARKERS_RE = re.compile(
    r"\b(?:notice\s+to\s+appear|\bnta\b|removal\s+proceedings|"
    r"exclusion\s+proceedings|deportation\s+proceedings)\b",
    re.IGNORECASE,
)


def _downgrade_yes_answer_to_no(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    *,
    question_id: str,
    justification: str,
) -> bool:
    """Force a Yes/No question back to 'No'. Returns True if anything changed."""
    normalized_qid = _clean_text(question_id).lower()
    changed = False
    for target in targets:
        if _clean_text(target.get("questionnaire_item_id")).lower() != normalized_qid:
            continue
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        target_option = _clean_text(target.get("questionnaire_target_option")).lower()
        if target_option in {"yes", "y", "true", "1"}:
            _set_result_value(
                results_by_id,
                field_id,
                "",
                confidence="low",
                justification=justification,
            )
            changed = True
        elif target_option in {"no", "n", "false", "0"}:
            _set_result_value(
                results_by_id,
                field_id,
                "Yes",
                confidence="low",
                justification=justification,
            )
            changed = True
    return changed


def _dedupe_part4_detail_rows(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
) -> int:
    """Remove duplicate rows in the ``p4_1_details`` table in-place.

    Two rows are considered duplicates when their (reason, date, location,
    outcome) tuples are identical after trimming and case-folding. Duplicates
    beyond the first occurrence get cleared (empty string) so the PDF renders
    one unique event per row.

    The algorithm uses two strategies:

    1. **Slot-based grouping** -- targets are grouped by their inferred row
       slot index. If the slot indices correctly distinguish rows, duplicates
       are detected and the later rows are cleared.
    2. **Field-ID grouping** -- when multiple targets share the same
       ``questionnaire_field_id`` (e.g. two ``incident_reason`` targets), each
       unique field_id is assigned to a *physical* row in encounter order.
       This handles the edge case where the slot-index inference maps both
       physical rows to the same index (0), which makes the slot-based pass
       see only one logical row while both field_ids retain their values.

    Returns the number of individual field cells that were cleared.
    """
    def _comparable_value(field_id: str, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if not cleaned:
            return ""
        if field_id == "incident_date":
            normalized = _normalize_date_text(value)
            if normalized:
                return normalized.lower()
        return cleaned

    # -- Pass 1: slot-based grouping (existing behaviour) --
    rows: dict[int, dict[str, tuple[str, str]]] = {}
    for target in targets:
        if _clean_text(target.get("questionnaire_item_id")).lower() != "p4_1_details":
            continue
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        q_field_id = _clean_text(target.get("questionnaire_field_id")).lower()
        if q_field_id not in _I914_PART4_DETAIL_FIELD_IDS:
            continue
        row_index = _i914_row_slot_index_for_target(target)
        current = rows.setdefault(row_index, {})
        value = _clean_text(results_by_id.get(field_id, {}).get("value"))
        current[q_field_id] = (field_id, value)

    seen_keys: set[tuple[str, str, str, str]] = set()
    cleared = 0
    for row_index in sorted(rows.keys()):
        entries = rows[row_index]
        values = tuple(
            _comparable_value(fid, entries.get(fid, ("", ""))[1])
            for fid in _I914_PART4_DETAIL_FIELD_IDS
        )
        if not any(values):
            continue
        if values in seen_keys:
            for _, (field_id, _value) in entries.items():
                _set_result_value(
                    results_by_id,
                    field_id,
                    "",
                    confidence="low",
                    justification="Removed duplicate Part 4 detail row during consistency validation.",
                )
                cleared += 1
            continue
        seen_keys.add(values)

    # -- Pass 2: field-ID grouping --
    # When slot inference collapses distinct physical rows into the same index
    # (both get row 0), Pass 1 only retains the *last* field_id per field and
    # never triggers the duplicate check. Pass 2 detects this by collecting
    # every (field_id, value) per questionnaire_field_id and building physical
    # rows from the encounter order.
    fields_per_column: dict[str, list[tuple[str, str]]] = {}
    for target in targets:
        if _clean_text(target.get("questionnaire_item_id")).lower() != "p4_1_details":
            continue
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        q_field_id = _clean_text(target.get("questionnaire_field_id")).lower()
        if q_field_id not in _I914_PART4_DETAIL_FIELD_IDS:
            continue
        value = _clean_text(results_by_id.get(field_id, {}).get("value"))
        fields_per_column.setdefault(q_field_id, []).append((field_id, value))

    max_physical_rows = max((len(v) for v in fields_per_column.values()), default=0)
    if max_physical_rows <= 1:
        return cleared

    seen_physical: set[tuple[str, str, str, str]] = set()
    for phys_idx in range(max_physical_rows):
        row_values: list[str] = []
        row_field_ids: list[str] = []
        for col_id in _I914_PART4_DETAIL_FIELD_IDS:
            entries_for_col = fields_per_column.get(col_id, [])
            if phys_idx < len(entries_for_col):
                fid, val = entries_for_col[phys_idx]
                row_values.append(_comparable_value(col_id, val))
                row_field_ids.append(fid)
            else:
                row_values.append("")
                row_field_ids.append("")
        values_tuple = tuple(row_values)
        if not any(values_tuple):
            continue
        if values_tuple in seen_physical:
            for fid in row_field_ids:
                if fid:
                    _set_result_value(
                        results_by_id,
                        fid,
                        "",
                        confidence="low",
                        justification="Removed duplicate Part 4 detail row (field-ID grouping pass).",
                    )
                    cleared += 1
            continue
        seen_physical.add(values_tuple)
    return cleared


def _validate_i914_category_consistency(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    answers: Mapping[str, Any],
    evidence_by_id: Mapping[str, Any],
    *,
    classified_events: Sequence[_I914ClassifiedEvent] | None = None,
) -> list[dict[str, Any]]:
    """Final I-914-specific consistency gate run before persisting results.

    Enforces the eight hard rules from the refactor plan:

    1. Part 4 table mentions NTA / removal proceedings but p4_9b='No' -> review.
    2. p4_1g='Yes' without tier<=2 JAIL_PRISON -> downgrade + issue.
    3. p4_1d='Yes' without tier<=2 CONVICTION -> downgrade + issue.
    4. p4_9c='Yes' without DEPORTED_EXCLUDED -> downgrade + issue.
    5. p4_9d='Yes' without REMOVAL_ORDER -> downgrade + issue.
    6. p4_9e='Yes' without DENIAL_OF_ADMISSION -> downgrade + issue.
    7. p4_9f='Yes' without VOLUNTARY_DEPARTURE_OVERSTAYED -> downgrade + issue.
    8. p3_8='No' without saved prior_entries -> review issue.

    Additionally: duplicate rows in ``p4_1_details`` are removed.

    Returns a list of ``{"item_id", "message", "severity"}`` dicts. Severity is
    ``"review"`` for rule 1 and 8 (caller should stop the job) and
    ``"downgrade"`` for the rest (the answer was silently corrected).
    """
    issues: list[dict[str, Any]] = []

    all_part4_field_ids = [
        _clean_text(t.get("id"))
        for t in targets
        if _clean_text(t.get("questionnaire_item_id")).lower() in _I914_PART4_YES_NO_IDS
        and _clean_text(t.get("id"))
    ]
    if classified_events is None:
        classified_events = _collect_i914_classified_events(evidence_by_id, all_part4_field_ids)

    strong_categories_present: set[_I914EventCategory] = {
        event.category for event in classified_events if event.source_tier <= 2
    }

    # --- Rule 1: NTA / removal proceedings in table vs p4_9b = No ---
    table_mentions_nta = False
    for target in targets:
        if _clean_text(target.get("questionnaire_item_id")).lower() != "p4_1_details":
            continue
        q_field_id = _clean_text(target.get("questionnaire_field_id")).lower()
        if q_field_id not in {"incident_reason", "incident_outcome"}:
            continue
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue
        cell_value = _clean_text(results_by_id.get(field_id, {}).get("value"))
        if cell_value and _I914_NTA_MARKERS_RE.search(cell_value):
            table_mentions_nta = True
            break

    if table_mentions_nta:
        answer_9b = _selected_yes_no_result_for_question(
            targets, results_by_id, question_id="p4_9b"
        )
        raw_saved_9b = answers.get("p4_9b") if isinstance(answers, Mapping) else None
        saved_9b, saved_9b_found = _lookup_saved_answer(answers, "p4_9b")
        manually_corrected_9b = (
            saved_9b_found
            and _normalize_option_answer(saved_9b) == "no"
            and isinstance(raw_saved_9b, Mapping)
            and bool(raw_saved_9b.get("manually_corrected"))
        )
        if answer_9b == "no" and not manually_corrected_9b:
            issues.append(
                {
                    "item_id": "p4_9b",
                    "severity": "review",
                    "message": (
                        "Part 4 detail table references an NTA or removal proceedings, "
                        "but p4_9b is answered 'No'. Manual review is required before "
                        "finalizing the I-914."
                    ),
                }
            )

    # --- Rules 2-7: Yes answers requiring specific categories ---
    category_required: dict[str, tuple[_I914EventCategory, ...]] = {
        "p4_1d": (_I914EventCategory.CONVICTION,),
        "p4_1e": (_I914EventCategory.DIVERSION_DEFERRED_WITHHELD,),
        "p4_1f": (_I914EventCategory.PROBATION_PAROLE_SUSPENDED,),
        "p4_1g": (_I914EventCategory.JAIL_PRISON,),
        "p4_9c": (_I914EventCategory.DEPORTED_EXCLUDED,),
        "p4_9d": (_I914EventCategory.REMOVAL_ORDER,),
        "p4_9e": (_I914EventCategory.DENIAL_OF_ADMISSION,),
        "p4_9f": (_I914EventCategory.VOLUNTARY_DEPARTURE_OVERSTAYED,),
    }
    for item_id, required in category_required.items():
        current_answer = _selected_yes_no_result_for_question(
            targets, results_by_id, question_id=item_id
        )
        if current_answer != "yes":
            continue
        saved_answer, _ = _lookup_saved_answer(answers, item_id)
        raw_saved_answer = answers.get(item_id) if isinstance(answers, Mapping) else None
        saved_option = _normalize_option_answer(
            saved_answer
            if saved_answer is not None
            else (raw_saved_answer.get("value") if isinstance(raw_saved_answer, Mapping) else raw_saved_answer)
        )
        if (
            isinstance(raw_saved_answer, Mapping)
            and bool(raw_saved_answer.get("manually_corrected"))
            and saved_option == "yes"
        ):
            # The user manually confirmed this answer; keep it but record an
            # informational issue.
            if not any(cat in strong_categories_present for cat in required):
                issues.append(
                    {
                        "item_id": item_id,
                        "severity": "info",
                        "message": (
                            f"Item {item_id} is answered 'Yes' but no tier-1/2 evidence of "
                            f"{required[0].value} was found. Manually confirmed by the user."
                        ),
                    }
                )
            continue
        if not any(cat in strong_categories_present for cat in required):
            justification = (
                f"Downgraded {item_id} to 'No' because no tier-1/2 evidence of "
                f"{required[0].value} was found."
            )
            if _downgrade_yes_answer_to_no(
                targets,
                results_by_id,
                question_id=item_id,
                justification=justification,
            ):
                issues.append(
                    {
                        "item_id": item_id,
                        "severity": "downgrade",
                        "message": justification,
                    }
                )

    # --- Rule 8: p3_8 = No without prior entries listed ---
    prior_entry_answer, p3_8_found = _lookup_saved_answer(answers, "p3_8")
    if p3_8_found and _normalize_option_answer(prior_entry_answer) == "no":
        has_prior_entry_value = any(
            _clean_text((results_by_id.get(_clean_text(t.get("id"))) or {}).get("value"))
            for t in targets
            if _clean_text(t.get("questionnaire_item_id")).lower() == "p3_8"
            and _clean_text(t.get("questionnaire_field_id")).lower().startswith("prior_entry_")
        )
        if not has_prior_entry_value:
            issues.append(
                {
                    "item_id": "p3_8",
                    "severity": "review",
                    "message": (
                        "p3_8 is answered 'No' but no prior entries were recorded. Manual "
                        "review is required before finalizing the I-914."
                    ),
                }
            )

    # --- Dedupe Part 4 detail rows ---
    cleared = _dedupe_part4_detail_rows(targets, results_by_id)
    if cleared:
        issues.append(
            {
                "item_id": "p4_1_details",
                "severity": "info",
                "message": f"Removed {cleared} duplicate Part 4 detail cell(s).",
            }
        )

    return issues


_I914_LEA_AGENCY_LABEL = "Law Enforcement Agency and Office"


def _apply_i914_lea_agency_label_overlay(
    filled_pdf_path: str,
    answers: Mapping[str, Any],
    form_type: str | None,
) -> None:
    """Draw the Law Enforcement Agency name in the I-914 Part 3.5 blank
    space (there is no AcroForm widget for this label in the USCIS PDF).

    This operates on the already-filled PDF file referenced by
    ``filled_pdf_path`` and replaces its bytes in place when an overlay
    is drawn. Failures are logged and never re-raised so the rest of the
    pipeline continues working if, for example, PyMuPDF cannot locate
    the label.
    """
    if _normalize_form_type(form_type) != "i-914":
        return

    cleaned_path = _clean_text(filled_pdf_path)
    if not cleaned_path:
        return

    agency_value, _ = _lookup_saved_answer(answers, "p3_5.lea_agency_office")
    agency_text = _clean_text(agency_value)
    if not agency_text:
        return

    p3_5_value, p3_5_found = _lookup_saved_answer(answers, "p3_5")
    if p3_5_found and _normalize_option_answer(p3_5_value) == "no":
        return

    try:
        from .pdf_form_service import _read_pdf_bytes, _resolve_pdf_path

        overlay_suffix_path = f"{cleaned_path}.__lea_overlay__.pdf"
        result = draw_label_adjacent_text(
            cleaned_path,
            [{
                "page_number": 3,
                "label_text": _I914_LEA_AGENCY_LABEL,
                "value": agency_text,
                "anchor_y": 196.0,
                "offset_x": 155.0,
                "offset_y": 1.3,
                "width": 340.0,
                "height": 15.0,
                "font_size": 8.5,
                "font_name": "helv",
            }],
            output_path=overlay_suffix_path,
        )

        if int(result.get("written_count") or 0) <= 0:
            log.info(
                "I-914 LEA agency overlay skipped (label not found or empty value)"
            )

        overlay_output = _clean_text(result.get("output_path"))
        if not overlay_output:
            return

        overlay_bytes, overlay_from_s3 = _read_pdf_bytes(overlay_output)

        target = _resolve_pdf_path(cleaned_path)
        if target.exists():
            target.write_bytes(overlay_bytes)
            overlay_local = _resolve_pdf_path(overlay_output)
            if overlay_local != target and overlay_local.exists():
                overlay_local.unlink()
            return

        s3 = None
        try:
            s3 = get_s3_service()
        except Exception as exc:
            log.warning(
                "Could not initialize S3 while applying I-914 LEA agency overlay for %s: %s",
                cleaned_path,
                exc,
                exc_info=True,
            )
            s3 = None

        if s3 is not None:
            s3.upload_bytes(overlay_bytes, cleaned_path, "application/pdf")
            if overlay_from_s3:
                try:
                    s3.delete(overlay_output)
                except Exception as exc:
                    log.warning(
                        "Could not delete temporary overlay file %s after upload: %s",
                        overlay_output,
                        exc,
                        exc_info=True,
                    )
    except Exception as exc:
        log.warning(
            "Failed to draw I-914 LEA agency label text: %s",
            exc,
            exc_info=True,
        )


def _postprocess_i914_part4_table_completion(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: dict[str, Any],
    answers: Mapping[str, Any],
    *,
    detention_facts: dict[str, str] | None = None,
) -> None:
    """Auto-complete the Part 4 detail table when any 4.1.A-I is 'Yes'
    but the table fields are empty."""
    has_yes = False
    part4_field_ids: list[str] = []

    for target in targets:
        q_item_id = _clean_text(target.get("questionnaire_item_id")).lower()
        field_id = _clean_text(target.get("id"))
        if q_item_id in _I914_PART4_1_YES_NO_IDS:
            if field_id:
                part4_field_ids.append(field_id)
            result = results_by_id.get(field_id, {})
            if _normalize_option_answer(result.get("value")) == "yes":
                has_yes = True

    if not has_yes:
        for q_id in _I914_PART4_1_YES_NO_IDS:
            saved, found = _lookup_saved_answer(answers, q_id)
            if found and _normalize_option_answer(saved) == "yes":
                has_yes = True
                break

    if not has_yes:
        return

    existing_details, found = _lookup_saved_answer(answers, "p4_1_details")
    if found and existing_details:
        first_row: Mapping[str, Any] = {}
        if isinstance(existing_details, (list, tuple)) and existing_details and isinstance(existing_details[0], Mapping):
            first_row = existing_details[0]
        elif isinstance(existing_details, Mapping):
            first_row = existing_details
        if any(_clean_text(first_row.get(k)) for k in _I914_PART4_DETAIL_FIELD_IDS):
            _i914_fill_missing_outcome_cell(targets, results_by_id, first_row)
            _dedupe_part4_detail_rows(targets, results_by_id)
            return

    classified_events = _collect_i914_classified_events(evidence_by_id, part4_field_ids)
    if not classified_events:
        fallback_ids = [
            _clean_text(field_id)
            for field_id in evidence_by_id.keys()
            if _clean_text(field_id)
        ]
        classified_events = _collect_i914_classified_events(evidence_by_id, fallback_ids)

    # Only events backed by tier <= 2 evidence (official records or sworn
    # declarations) are strong enough to auto-populate the Part 4 table. Tier 3
    # (intake/BioCall) or tier 4 sources are allowed to flag the applicant for
    # manual review but never to synthesize specific incident details.
    strong_events = [e for e in classified_events if e.source_tier <= 2]
    table_rows = _i914_build_part4_table_rows(strong_events)

    if not table_rows:
        # Legacy fallback #1: derive a single row from the saved answers and any
        # ``detention_facts`` provided by the caller. This preserves the prior
        # behaviour for cases whose evidence does not mention an explicit
        # immigration / criminal authority yet the questionnaire already has a
        # structured "last entry" entry. The synthetic event stays at tier 2
        # (declaration-equivalent) which is conservative enough to populate the
        # table without triggering hard categories.
        merged_facts = _merge_i914_detention_facts(answers, detention_facts)
        synthetic = _synthesize_classified_event_from_facts(merged_facts)
        if synthetic is not None:
            synthetic.source_tier = min(synthetic.source_tier, 2)
            table_rows = _i914_build_part4_table_rows([synthetic])

    if not table_rows:
        # Legacy fallback #2: scan tier<=2 evidence text for a detention
        # mention + date + location. This never activates hard categories
        # (NTA, removal order, conviction, jail) because it relies solely on
        # the generic ``detained/arrested`` keyword; it only synthesises an
        # IMMIGRATION_DETENTION row good enough for the 4.1.B-style table.
        raw_synthetic = _synthesize_event_from_raw_evidence(evidence_by_id, part4_field_ids)
        if raw_synthetic is not None:
            table_rows = _i914_build_part4_table_rows([raw_synthetic])

    if not table_rows:
        log.info(
            "Part 4 has Yes answers but no tier<=2 classified events available to "
            "auto-complete the detail table; deferring to manual review."
        )
        return

    best_row = table_rows[0]
    detail_targets = [
        t for t in targets
        if _clean_text(t.get("questionnaire_item_id")).lower() == "p4_1_details"
    ]

    # Only populate ONE row slot so we never emit two identical rows into the
    # Part 4 detail table. Multiple classified events become distinct rows only
    # when the table has enough distinct row slots and distinct ``best_row``
    # entries are available (see future multi-row support below).
    first_slot_index = _i914_first_available_slot_index(detail_targets, results_by_id)

    raw_incident_date = _clean_text(best_row.get("incident_date"))
    normalized_incident_date = (
        _normalize_date_text(raw_incident_date) or raw_incident_date
    )
    field_mapping = {
        "incident_reason": _clean_text(best_row.get("incident_reason")),
        "incident_date": normalized_incident_date,
        "incident_location": _clean_text(best_row.get("incident_location")),
        "incident_outcome": _clean_text(best_row.get("incident_outcome")) or (
            _i914_default_outcome_for_category(best_row.get("_category"))
        ),
    }

    for target in detail_targets:
        field_id = _clean_text(target.get("id"))
        q_field_id = _clean_text(target.get("questionnaire_field_id")).lower()
        if not field_id or not q_field_id:
            continue
        slot_index = _i914_row_slot_index_for_target(target)
        if slot_index != first_slot_index:
            continue
        fill_value = field_mapping.get(q_field_id, "")
        if fill_value and not _clean_text(results_by_id.get(field_id, {}).get("value")):
            _set_result_value(
                results_by_id,
                field_id,
                fill_value,
                confidence="medium",
                justification=(
                    f"Auto-completed from classified tier-{best_row.get('_tier')} event "
                    f"({best_row.get('_category')}): {fill_value[:80]}"
                ),
            )

    _dedupe_part4_detail_rows(targets, results_by_id)

    log.info(
        "Part 4 table auto-completed with classified event (category=%s, tier=%s): %s",
        best_row.get("_category"),
        best_row.get("_tier"),
        {k: (v[:60] if isinstance(v, str) else v) for k, v in best_row.items() if v and not k.startswith("_")},
    )


_RAW_DETENTION_RE = re.compile(
    r"\b(?:detain(?:ed|ing)|arrest(?:ed)?|apprehend(?:ed)?|processed|in\s+custody|"
    r"held\s+(?:by|at|in)|cited|charged)\b",
    re.IGNORECASE,
)
_RAW_DATE_RE = re.compile(
    r"\b(?:(?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])[/\-](?:\d{4}|\d{2})|"
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_RAW_CITY_STATE_RE = re.compile(
    r"\b(?:in|at|near|from)\s+([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){0,3})\s*,\s*([A-Z]{2})\b"
)


def _synthesize_event_from_raw_evidence(
    evidence_by_id: Mapping[str, Any],
    field_ids: Iterable[str],
) -> _I914ClassifiedEvent | None:
    """Legacy raw-text fallback for ``_postprocess_i914_part4_table_completion``.

    When the strict taxonomy classifier yields no events (e.g. because the
    evidence text mentions an authority outside the IMMIGRATION / CRIMINAL
    vocabulary - FBI rap sheets, generic court printouts, etc.) this helper
    attempts a much narrower extraction: it requires a tier <= 2 evidence item
    whose text contains a generic ``detained/arrested`` keyword plus at least a
    date or a city/state location, and returns a single synthetic
    ``IMMIGRATION_DETENTION`` event carrying those slots.

    Returns ``None`` when no eligible evidence snippet is found.
    """
    best_text: str = ""
    best_tier = 5
    for field_id in field_ids:
        bundle = evidence_by_id.get(field_id)
        if not isinstance(bundle, Mapping):
            continue
        evidence_list = bundle.get("evidence")
        if not isinstance(evidence_list, list):
            continue
        for item in evidence_list:
            if not isinstance(item, Mapping):
                continue
            text = str(item.get("text", "") or "").strip()
            if not text or not _RAW_DETENTION_RE.search(text):
                continue
            tier = _source_tier_for_evidence(item)
            if tier > 2:
                continue
            if tier < best_tier:
                best_tier = tier
                best_text = text

    if not best_text:
        return None

    date_match = _RAW_DATE_RE.search(best_text)
    loc_match = _RAW_CITY_STATE_RE.search(best_text)
    city = loc_match.group(1).strip() if loc_match else ""
    state = loc_match.group(2).strip().upper() if loc_match else ""
    if not (date_match or city or state):
        return None

    return _I914ClassifiedEvent(
        category=_I914EventCategory.IMMIGRATION_DETENTION,
        date=date_match.group(0) if date_match else "",
        authority="",
        authority_kind="immigration",
        location_city=city,
        location_state=state,
        outcome="",
        reason="",
        raw_text=best_text,
        source_tier=max(1, min(best_tier, 2)),
    )


def _synthesize_classified_event_from_facts(
    detention_facts: Mapping[str, Any] | None,
) -> _I914ClassifiedEvent | None:
    """Legacy bridge: when only a dict of detention facts is available, wrap it
    into a single synthetic ``ClassifiedEvent`` of category
    ``IMMIGRATION_DETENTION`` so downstream template builders always receive a
    uniform input shape.

    This is intentionally conservative: no criminal category, no NTA, no
    removal order can be synthesized from facts alone. Stronger categories
    must be produced by the real classifier.
    """
    if not detention_facts:
        return None
    city = _clean_text(detention_facts.get("location_city"))
    state = _clean_text(detention_facts.get("location_state"))
    if not (city or state) and _clean_text(detention_facts.get("location")):
        city_part, state_part = _split_location_city_state(detention_facts.get("location"))
        city = city or city_part
        state = state or state_part
    tier_raw = _clean_text(detention_facts.get("source_tier"))
    try:
        tier = int(tier_raw) if tier_raw else 3
    except ValueError:
        tier = 3
    return _I914ClassifiedEvent(
        category=_I914EventCategory.IMMIGRATION_DETENTION,
        date=_clean_text(detention_facts.get("date")),
        authority="",
        authority_kind="immigration",
        location_city=city,
        location_state=(state or "").upper(),
        outcome=_clean_text(detention_facts.get("outcome")),
        reason=_clean_text(detention_facts.get("reason")),
        raw_text=_clean_text(detention_facts.get("reason")),
        source_tier=max(1, min(4, tier)),
        needs_paraphrase=not _clean_text(detention_facts.get("reason")),
    )


def _events_for_part9_item(
    item_id: str,
    classified_events: Sequence[_I914ClassifiedEvent] | None,
    detention_facts: Mapping[str, Any] | None,
) -> list[_I914ClassifiedEvent]:
    """Return the subset of classified events relevant to a single Part 9 item.

    If a real classifier result is available, only the events whose category
    maps to this item (via ``CATEGORY_TO_PART4_ITEMS``) are returned. When no
    classifier output exists but legacy ``detention_facts`` are provided, a
    single synthetic immigration-detention event is returned for items that
    legitimately accept one (``p4_1b`` and ``p3_9``) so the caller can emit a
    conservative factual paragraph.
    """
    normalized = _clean_text(item_id).lower()
    if classified_events:
        bucket = _i914_map_events_to_part4_items(classified_events).get(normalized, [])
        if bucket:
            return list(bucket)
        if normalized == "p3_9":
            immigration_events = [
                e for e in classified_events
                if e.category == _I914EventCategory.IMMIGRATION_DETENTION
            ]
            if immigration_events:
                return immigration_events
        return []

    synthetic = _synthesize_classified_event_from_facts(detention_facts)
    if synthetic is None:
        return []
    if normalized in {"p3_9", "p4_1b"}:
        return [synthetic]
    return []


def _paraphrase_events_if_needed(
    events: list[_I914ClassifiedEvent],
    *,
    tracker: Any = None,
) -> list[_I914ClassifiedEvent]:
    """Attempt LLM paraphrase for events whose reason slot is generic/empty.

    Mutates events in place (sets ``event.reason`` and clears
    ``event.needs_paraphrase``) for any event that has ``raw_text`` but
    ``needs_paraphrase == True``.
    """
    for event in events:
        if not event.needs_paraphrase or not _clean_text(event.raw_text):
            continue
        try:
            paraphrased = paraphrase_reason_slot(
                event.raw_text,
                authority_kind=event.authority_kind,
                category=event.category.value if hasattr(event.category, "value") else str(event.category),
                tracker=tracker,
            )
            if paraphrased:
                event.reason = paraphrased
                event.needs_paraphrase = False
        except Exception:
            log.debug(
                "Paraphrase failed for event category=%s, falling back to template reason.",
                event.category,
                exc_info=True,
            )
    return events


def _build_i914_part9_additional_information(
    item: Mapping[str, Any],
    normalized_answer: str,
    answers: Mapping[str, Any],
    *,
    page_number: str = "",
    part_number: str = "",
    item_number: str = "",
    detention_facts: Mapping[str, Any] | None = None,
    classified_events: Sequence[_I914ClassifiedEvent] | None = None,
) -> str:
    """Build a factual Part 9 addendum paragraph from case data.

    The Page/Part/Item number boxes (A/B/C) are filled separately via the
    dedicated PDF widgets (see ``_force_i914_part9_target_mappings``); the
    paragraph stored in ``additional_information`` (box D) must contain only
    the factual ``Question: ... Answer: ...`` narrative, otherwise the header
    is duplicated on the generated PDF.

    Branching logic lives per ``item_id`` so we never reuse the same narrative
    across distinct Part 4 items. The hybrid generation strategy is:

    - Deterministic skeleton from :func:`i914_event_taxonomy.build_part9_text`.
    - Slot-filled fallbacks (``on or about``, ``in or near``, ``if known``)
      when the classifier lacks high-confidence facts.
    - The LLM ``reason``-slot paraphrase is engaged for events that have
      ``needs_paraphrase=True`` and non-empty ``raw_text``.
    """
    del page_number, part_number, item_number

    item_id = _clean_text(item.get("id")).lower()
    parts: list[str] = []
    form_text = _clean_text(item.get("form_text"))

    if form_text:
        parts.append(f"Question: {form_text.rstrip('.')}.")
    if normalized_answer in {"yes", "no"}:
        parts.append(f"Answer: {_i914_yes_no_display(normalized_answer)}.")

    if item_id == "p3_5" and normalized_answer == "no":
        circumstances, found = _lookup_saved_answer(answers, "p3_5.lea_circumstances")
        cleaned_circumstances = _clean_text(circumstances)
        if found and cleaned_circumstances:
            parts.append(f"Circumstances: {cleaned_circumstances}.")
    elif item_id == "p3_7" and normalized_answer == "no":
        explanation = _i914_saved_text_answer(answers, "p3_7.explanation")
        if explanation:
            parts.append(f"Explanation: {explanation}.")
    elif item_id == "p3_8" and normalized_answer == "no":
        # Form instruction: when the applicant answers No to "This is the first
        # time I have entered the U.S.", list every prior entry in the last
        # five years.  A bare "Answer: No." is non-compliant.
        prior_entries = _format_i914_prior_entries_summary(
            answers,
            detention_facts=detention_facts,
            classified_events=classified_events,
        )
        if prior_entries:
            parts.append(
                "Within the past five years, the applicant entered the United States "
                f"as follows: {prior_entries}."
            )
        else:
            parts.append(
                "No specific prior entries within the past five years could be "
                "determined from the available records. Applicant's immigration "
                "history (I-94, passport stamps, CBP records) must be reviewed "
                "before filing to verify whether 'No' is the correct answer to "
                "this question."
            )
        recent_arrival_narrative = _build_i914_recent_arrival_narrative(answers)
        if recent_arrival_narrative:
            parts.append(recent_arrival_narrative)
    elif item_id == "p3_9":
        # Form instruction: explain the circumstances of the most recent
        # arrival and the nexus with the trafficking scheme. Never leave a
        # bare "Answer: Yes." here.
        recent_arrival_narrative = _build_i914_recent_arrival_narrative(answers)
        if recent_arrival_narrative:
            parts.append(recent_arrival_narrative)
        events = _events_for_part9_item("p3_9", classified_events, detention_facts)
        if not events and normalized_answer == "yes":
            placeholder = _i914_placeholder_event_for_item("p3_9")
            if placeholder is not None:
                events = [placeholder]
        if events:
            template_text = _i914_build_part9_text("p3_9", events)
            if template_text:
                parts.append(template_text)
    elif item_id.startswith("p4_1") and normalized_answer == "yes":
        incident_summary = _format_i914_part4_incident_summary(answers)
        if incident_summary:
            parts.append(incident_summary.rstrip(".") + ".")
        merged_facts = _merge_i914_detention_facts(answers, detention_facts)
        events = _events_for_part9_item(item_id, classified_events, merged_facts)
        if not events:
            placeholder = _i914_placeholder_event_for_item(item_id)
            if placeholder is not None:
                events = [placeholder]
        if events:
            template_text = _i914_build_part9_text(item_id, events)
            if template_text:
                parts.append(template_text)
    elif item_id.startswith("p4_9") and normalized_answer == "yes":
        merged_facts = _merge_i914_detention_facts(answers, detention_facts)
        events = _events_for_part9_item(item_id, classified_events, merged_facts)
        if not events:
            placeholder = _i914_placeholder_event_for_item(item_id)
            if placeholder is not None:
                events = [placeholder]
        if events:
            template_text = _i914_build_part9_text(item_id, events)
            if template_text:
                parts.append(template_text)

    return " ".join(part for part in parts if part).strip()


def _derive_i914_part9_entries(
    pages: Iterable[Mapping[str, Any]],
    answers: Mapping[str, Any],
) -> list[dict[str, str]]:
    derived_rows: list[dict[str, str]] = []

    for page in pages:
        page_number = str(_safe_int(page.get("page")) or "")
        for item in page.get("items", []) or []:
            if _clean_text(item.get("responsible_party") or "").lower() != "client":
                continue
            if _clean_text(item.get("type") or "").lower() != "yes_no":
                continue

            item_id = _clean_text(item.get("id"))
            if not item_id:
                continue

            answer, found = _lookup_saved_answer(answers, item_id)
            normalized_answer = _normalize_option_answer(answer)
            if not found or normalized_answer not in {"yes", "no"}:
                continue

            part_number, item_number = _i914_question_part_and_item(
                item.get("code"),
                item.get("section"),
            )
            if not part_number or not item_number:
                continue

            should_generate = False
            if part_number == "4":
                should_generate = normalized_answer == "yes"
            elif part_number == "3":
                should_generate = _i914_part3_answer_requires_addendum(
                    item,
                    normalized_answer,
                )
            if not should_generate:
                continue

            derived_rows.append(
                {
                    "page_number": page_number,
                    "part_number": part_number,
                    "item_number": item_number,
                    "additional_information": _build_i914_part9_additional_information(
                        item,
                        normalized_answer,
                        answers,
                        page_number=page_number,
                        part_number=part_number,
                        item_number=item_number,
                    ),
                }
            )

    return derived_rows


def _i914_part9_entry_is_no_answer_for_part4(row: Mapping[str, str]) -> bool:
    """Detect Part 9 entries that only state 'Answer: No' for a Part 4 item.

    Part 4 addendum entries should only exist for 'Yes' answers.  Entries
    that got saved with 'No' (from AI extraction or stale data) are
    unnecessary and should be filtered out.
    """
    part_number = _clean_text(row.get("part_number"))
    if part_number != "4":
        return False
    info = _clean_text(row.get("additional_information")).lower()
    return "answer: no" in info and "answer: yes" not in info


_I914_PART9_STALE_AUTO_TEXT_RE = re.compile(
    r"\b(?:"
    r"detained\s*/\s*arrested\s+by\s+law\s+enforcement|"
    r"detained\s+or\s+arrested\s+by\s+law\s+enforcement|"
    r"detained\s+by\s+law\s+enforcement|"
    r"arrested\s+by\s+law\s+enforcement"
    r")\b",
    re.IGNORECASE,
)


def _i914_part9_text_is_stale_autogen(text: Any) -> bool:
    """Return True if ``text`` uses forbidden generic wording from prior jobs.

    The previous builder emitted phrases such as "was detained/arrested by law
    enforcement" that conflated immigration and criminal events. Such text
    persists in ``p9_entries`` across re-runs and must be replaced by freshly
    derived narrative that complies with the I-914 taxonomy. Any other text
    (including user-authored narrative) is kept as-is.
    """
    cleaned = _clean_text(text)
    if not cleaned:
        return False
    return bool(_I914_PART9_STALE_AUTO_TEXT_RE.search(cleaned))


def _merge_i914_part9_entries(
    existing_rows: Iterable[Any],
    derived_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge Part 9 addendum rows while scrubbing forbidden legacy wording.

    Rules:

    1. Existing rows keyed by (page, part, item) are kept first and win by
       default so user-authored narrative survives regenerations.
    2. If an existing row has an empty ``additional_information`` or its text
       matches a forbidden stale pattern (e.g. "detained/arrested by law
       enforcement" from the legacy builder), it is overwritten with the
       freshly derived text.
    3. Rows flagged with ``manually_edited=True`` are never overwritten.
    4. Derived rows whose key does not match any existing row are appended.
    """
    merged: list[dict[str, Any]] = []
    existing_index_by_key: dict[tuple[str, str, str], int] = {}

    for raw_row in existing_rows:
        row = _normalize_i914_part9_row(raw_row)
        if not _i914_part9_row_has_content(row):
            continue
        if _i914_part9_entry_is_no_answer_for_part4(row):
            continue
        key = _i914_part9_row_key(row)
        if key in existing_index_by_key:
            continue
        existing_index_by_key[key] = len(merged)
        merged.append(row)

    for raw_row in derived_rows:
        row = _normalize_i914_part9_row(raw_row)
        if not _i914_part9_row_has_content(row):
            continue
        if _i914_part9_entry_is_no_answer_for_part4(row):
            continue

        key = _i914_part9_row_key(row)
        existing_index = existing_index_by_key.get(key)
        if existing_index is None:
            existing_index_by_key[key] = len(merged)
            merged.append(row)
            continue

        existing_row = merged[existing_index]
        derived_text = _clean_text(row.get("additional_information"))
        if not derived_text:
            continue
        if existing_row.get("manually_edited"):
            continue
        existing_text = _clean_text(existing_row.get("additional_information"))
        if existing_text and not _i914_part9_text_is_stale_autogen(existing_text):
            continue
        existing_row["additional_information"] = row["additional_information"]

    return merged


def _apply_i914_part9_addendum_answers(
    pages: Iterable[Mapping[str, Any]],
    answers: dict[str, Any],
) -> dict[str, Any]:
    raw_existing_rows = answers.get("p9_entries")
    existing_rows = (
        list(raw_existing_rows)
        if isinstance(raw_existing_rows, (list, tuple))
        else []
    )
    derived_rows = _derive_i914_part9_entries(pages, answers)
    merged_rows = _merge_i914_part9_entries(existing_rows, derived_rows)
    if merged_rows:
        answers["p9_entries"] = merged_rows
    return answers


# ---------------------------------------------------------------------------
# Part 9 validation and auto-generation
# ---------------------------------------------------------------------------

def _validate_part9_completeness(
    targets: list[dict[str, Any]],
    results_by_id: Mapping[str, Mapping[str, str]],
    answers: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Return a list of Part 4 (and relevant Part 3) items that answered 'Yes'
    (or require an addendum) but have no corresponding entry in Part 9.

    Each entry has keys: item_id, part_number, item_number, reason.
    """
    missing: list[dict[str, str]] = []

    p9_entries = answers.get("p9_entries")
    if not isinstance(p9_entries, (list, tuple)):
        p9_entries = []
    existing_keys: set[tuple[str, str]] = set()
    for row in p9_entries:
        if isinstance(row, Mapping):
            existing_keys.add((
                _clean_text(row.get("part_number")),
                _clean_text(row.get("item_number")),
            ))

    seen_item_ids: set[str] = set()
    for target in targets:
        q_item_id = _clean_text(target.get("questionnaire_item_id")).lower()
        if not q_item_id or q_item_id in seen_item_ids:
            continue
        seen_item_ids.add(q_item_id)

        if not q_item_id.startswith("p4_") and not q_item_id.startswith("p3_"):
            continue

        result = results_by_id.get(_clean_text(target.get("id")), {})
        current_value = _normalize_option_answer(result.get("value"))
        if not current_value:
            saved, found = _lookup_saved_answer(answers, q_item_id)
            if found:
                current_value = _normalize_option_answer(saved)

        should_require_addendum = False
        if q_item_id.startswith("p4_"):
            should_require_addendum = current_value == "yes"
        elif q_item_id.startswith("p3_"):
            should_require_addendum = _i914_part3_answer_requires_addendum(
                {
                    "id": q_item_id,
                    "instruction": _clean_text(target.get("questionnaire_instruction")),
                },
                current_value,
            )

        if not should_require_addendum:
            continue

        part_number, item_number = "", ""
        if q_item_id.startswith("p4_"):
            part_number = "4"
            item_number = q_item_id.replace("p4_", "").upper()
        elif q_item_id.startswith("p3_"):
            part_number = "3"
            item_number = q_item_id.replace("p3_", "").upper()

        if not part_number or not item_number:
            continue

        if (part_number, item_number) not in existing_keys:
            missing.append({
                "item_id": q_item_id,
                "part_number": part_number,
                "item_number": item_number,
                "reason": f"Part {part_number} Item {item_number} requires a Part 9 addendum entry.",
            })

    return missing


def _find_i914_item_context_from_targets(
    targets: Iterable[Mapping[str, Any]],
    item_id: str,
) -> dict[str, str]:
    normalized_item_id = _clean_text(item_id).lower()
    for target in targets:
        if _clean_text(target.get("questionnaire_item_id")).lower() != normalized_item_id:
            continue
        return {
            "id": normalized_item_id,
            "form_text": _clean_text(target.get("questionnaire_form_text")),
            "instruction": _clean_text(target.get("questionnaire_instruction")),
            "page_number": str(_safe_int(target.get("page_number")) or ""),
        }
    return {
        "id": normalized_item_id,
        "form_text": "",
        "instruction": "",
        "page_number": "",
    }


def _auto_generate_missing_part9_entries(
    missing_items: list[dict[str, str]],
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: dict[str, Any],
    answers: dict[str, Any],
    *,
    detention_facts: dict[str, str] | None = None,
    classified_events: Sequence[_I914ClassifiedEvent] | None = None,
) -> list[dict[str, str]]:
    """Auto-generate Part 9 addendum entries for Part 4 'Yes' items that
    are missing from the current Part 9 entries.

    Uses the classified I-914 events (taxonomy module) as the primary source
    of facts; legacy ``detention_facts`` are used only as a secondary bridge
    for callers that have not migrated yet.
    """
    if not missing_items:
        return []

    part4_field_ids = [
        _clean_text(t.get("id"))
        for t in targets
        if _clean_text(t.get("questionnaire_item_id")).lower() in _I914_PART4_YES_NO_IDS
        and _clean_text(t.get("id"))
    ]
    if classified_events is None:
        classified_events = _collect_i914_classified_events(evidence_by_id, part4_field_ids)
    if detention_facts is None:
        detention_facts = _extract_detention_facts_from_evidence(evidence_by_id, part4_field_ids)

    mutable_events = list(classified_events) if classified_events else []
    _paraphrase_events_if_needed(mutable_events)
    classified_events = mutable_events

    generated: list[dict[str, str]] = []
    for item_info in missing_items:
        part_number = item_info["part_number"]
        item_number = item_info["item_number"]
        item_id = item_info["item_id"]
        item_context = _find_i914_item_context_from_targets(targets, item_id)
        saved_value, found = _lookup_saved_answer(answers, item_id)
        normalized_answer = _normalize_option_answer(saved_value) if found else "yes"
        additional_info = _build_i914_part9_additional_information(
            item_context,
            normalized_answer or "yes",
            answers,
            page_number=_clean_text(item_context.get("page_number")) or ("4" if part_number == "4" else ""),
            part_number=part_number,
            item_number=item_number,
            detention_facts=detention_facts,
            classified_events=classified_events,
        )

        generated.append({
            "page_number": _clean_text(item_context.get("page_number")) or ("4" if part_number == "4" else ""),
            "part_number": part_number,
            "item_number": item_number,
            "additional_information": additional_info,
        })

        result_field_id = None
        for t in targets:
            if _clean_text(t.get("questionnaire_item_id")).lower() == item_id:
                result_field_id = _clean_text(t.get("id"))
                break
        if result_field_id and result_field_id in results_by_id:
            result = results_by_id[result_field_id]
            if _clean_text(result.get("confidence")) != "low":
                result["confidence"] = "low"
            existing_just = _clean_text(result.get("justification"))
            result["justification"] = (
                f"{existing_just} Auto-generated Part 9 addendum for this item."
            ).strip()

    if generated:
        existing_p9 = answers.get("p9_entries")
        if not isinstance(existing_p9, list):
            existing_p9 = []
        answers["p9_entries"] = _merge_i914_part9_entries(existing_p9, generated)
        log.info(
            "Auto-generated %d Part 9 addendum entries for missing items: %s",
            len(generated),
            [g["item_number"] for g in generated],
        )

    return generated


def _get_questionnaire_answers_with_defaults(
    db: Session,
    case_id: str,
    *,
    form_type: str,
) -> dict[str, Any]:
    answers = get_questionnaire_answers(db, case_id, form_type=form_type)
    pages = _questionnaire_pages_for_form_defaults(form_type)
    answers_with_defaults = _apply_questionnaire_defaults_to_answers(pages, answers)
    if _normalize_form_type(form_type) == "i-914":
        answers_with_defaults = _apply_i914_forced_answer_rules(answers_with_defaults)
        answers_with_defaults = _apply_i914_family_answer_rules(answers_with_defaults)
        return _apply_i914_part9_addendum_answers(pages, answers_with_defaults)
    return answers_with_defaults


def _has_answer_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(_clean_text(value))
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _coerce_scalar_answer(value: Any) -> tuple[Any | None, bool]:
    if isinstance(value, str):
        cleaned = _clean_text(value)
        return cleaned, bool(cleaned)
    if value is None:
        return None, False
    if isinstance(value, (bool, int, float)):
        return value, True
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return _coerce_scalar_answer(value[0])
    return None, False


def _extract_answer_from_saved_value(
    saved_value: Any,
    *,
    field_id: str | None = None,
    index: int | None = None,
) -> tuple[Any | None, bool]:
    slot_index = max(0, int(index or 0))
    normalized_field_id = _clean_text(field_id).lower()

    if not normalized_field_id:
        scalar_value, is_scalar = _coerce_scalar_answer(saved_value)
        if is_scalar:
            return scalar_value, True
        if isinstance(saved_value, (list, tuple)) and saved_value:
            chosen = saved_value[slot_index] if slot_index < len(saved_value) else None
            scalar_value, is_scalar = _coerce_scalar_answer(chosen)
            if is_scalar:
                return scalar_value, True
        return None, False

    if isinstance(saved_value, Mapping):
        for key, value in saved_value.items():
            if _clean_text(key).lower() == normalized_field_id:
                scalar_value, is_scalar = _coerce_scalar_answer(value)
                if is_scalar:
                    return scalar_value, True
                return None, False
        return None, False

    if isinstance(saved_value, (list, tuple)):
        if not saved_value:
            return None, False
        if slot_index >= len(saved_value):
            return None, False
        chosen = saved_value[slot_index]
        if isinstance(chosen, Mapping):
            return _extract_answer_from_saved_value(chosen, field_id=normalized_field_id)
        scalar_value, is_scalar = _coerce_scalar_answer(chosen)
        if is_scalar:
            return scalar_value, True

    return None, False


def _lookup_saved_answer(
    answers: Mapping[str, Any],
    question_id: str | None,
    *,
    field_id: str | None = None,
    index: int | None = None,
) -> tuple[Any | None, bool]:
    normalized_question_id = _clean_text(question_id)
    if not normalized_question_id:
        return None, False

    if normalized_question_id in answers:
        value, found = _extract_answer_from_saved_value(
            answers[normalized_question_id],
            field_id=field_id,
            index=index,
        )
        if found:
            return value, True

    if field_id is None and "." in normalized_question_id:
        parent_question_id, nested_field_id = normalized_question_id.rsplit(".", 1)
        return _lookup_saved_answer(
            answers,
            parent_question_id,
            field_id=nested_field_id,
            index=index,
        )

    return None, False


def _normalize_address_field_id(field_id: str | None) -> str:
    normalized = _clean_text(field_id).lower()
    if not normalized:
        return ""
    if normalized.startswith("safe_"):
        normalized = normalized[5:]
    if normalized.startswith("mailing_"):
        normalized = normalized[8:]
    if normalized.startswith("physical_"):
        normalized = normalized[9:]
    if normalized.startswith("current_"):
        normalized = normalized[8:]
    if normalized.startswith("last_entry_"):
        normalized = normalized[11:]
    if normalized.startswith("prior_entry_"):
        normalized = normalized[12:]
    if normalized.startswith("lea_"):
        normalized = normalized[4:]
    return normalized


def _resolve_shared_candidate_answer(
    target: Mapping[str, Any],
    answers: Mapping[str, Any],
    *,
    occurrence_index: int,
) -> tuple[Any, str | None]:
    for candidate_question_id, candidate_field_id, candidate_index in _shared_answer_candidates(
        target,
        occurrence_index,
    ):
        value, found = _lookup_saved_answer(
            answers,
            candidate_question_id,
            field_id=candidate_field_id,
            index=candidate_index,
        )
        if found and _has_answer_value(value):
            if candidate_field_id and "." not in candidate_question_id:
                source_key = f"{candidate_question_id}.{candidate_field_id}"
            else:
                source_key = candidate_question_id
            return value, source_key
    return "", None


def _shared_answer_candidates(
    target: Mapping[str, Any],
    occurrence_index: int,
) -> list[tuple[str, str | None, int | None]]:
    item_id = _clean_text(target.get("questionnaire_item_id")).lower()
    field_id = _clean_text(target.get("questionnaire_field_id")).lower()
    field_name = _normalize_hint_text(target.get("field_name"))
    label = _normalize_hint_text(target.get("questionnaire_label") or target.get("field_label"))
    form_text = _normalize_hint_text(target.get("questionnaire_form_text"))
    section = _normalize_hint_text(target.get("questionnaire_section"))
    option_label = _normalize_hint_text(target.get("questionnaire_option_label"))
    combined = " | ".join(part for part in [item_id, field_id, field_name, label, form_text, section, option_label] if part)
    candidates: list[tuple[str, str | None, int | None]] = []

    def add(question_id: str, field_name: str | None = None, index: int | None = None) -> None:
        candidate = (question_id, field_name, index)
        if candidate not in candidates:
            candidates.append(candidate)

    def mentions_any(*terms: str) -> bool:
        return any(term in combined for term in terms)

    mentions_uscis_boilerplate = mentions_any(
        "citizenship and immigration services",
        "uscis",
    )

    if not field_id:
        if mentions_any("family name", "last name"):
            field_id = "family_name"
        elif mentions_any("given name", "first name"):
            field_id = "given_name"
        elif mentions_any("middle name"):
            field_id = "middle_name"

    related_person_context_exclusions = ("spouse", "child", "parent", "family member")
    name_context_exclusions = (
        *related_person_context_exclusions,
        "interpreter",
        "preparer",
        "attorney",
    )
    normalized_name_field_id = field_id[6:] if field_id.startswith("other_") else field_id
    if normalized_name_field_id in {"family_name", "given_name", "middle_name"}:
        if mentions_any("other name", "alias", "nickname", "maiden"):
            add("shared.other_names_used", normalized_name_field_id, occurrence_index)
        elif not mentions_any(*name_context_exclusions):
            add(f"shared.name.{normalized_name_field_id}")

    if mentions_any("alien registration", "a-number"):
        add("shared.identifiers.a_number")
    if mentions_any("social security", "ssn"):
        add("shared.identifiers.ssn")
    if mentions_any("uscis online account"):
        add("shared.identifiers.uscis_online_account_number")
    if mentions_any("i-94", "arrival-departure record"):
        add("shared.identifiers.i94_record_number")
    if mentions_any("passport or travel document number") and not mentions_any(
        "issue date",
        "expiration",
        "issuing country",
    ):
        add("shared.identifiers.passport_number")
        add("shared.identifiers.travel_document_number")
    elif mentions_any("passport number") and not mentions_any(
        "issue date",
        "expiration",
        "issuing country",
    ):
        add("shared.identifiers.passport_number")
    if mentions_any("travel document number"):
        add("shared.identifiers.travel_document_number")
    if mentions_any("sevis"):
        add("shared.identifiers.sevis_number")

    if not mentions_any(*related_person_context_exclusions):
        if mentions_any("date of birth"):
            add("shared.biographics.date_of_birth")
        if field_id in {"birth_city", "birth_city_town_village"} or mentions_any(
            "city or town of birth",
            "birth city",
        ) or ("birth" in combined and "city" in field_id and "marriage" not in combined):
            add("shared.biographics.birth_city")
        if field_id in {"birth_state_province", "birth_state_or_province"} or mentions_any(
            "province of birth",
            "state or province of birth",
        ) or ("birth" in combined and "state" in field_id and "marriage" not in combined):
            add("shared.biographics.birth_state_or_province")
        if field_id == "birth_country" or mentions_any("country of birth"):
            add("shared.biographics.birth_country")
        if mentions_any("sex"):
            add("shared.biographics.sex")
        if mentions_any("marital status"):
            add("shared.biographics.marital_status")
        if mentions_any("number of times married", "times married"):
            add("shared.biographics.times_married")

        if mentions_any("citizenship", "nationality") and not mentions_uscis_boilerplate:
            if field_id.startswith("country_"):
                try:
                    slot_index = max(0, int(field_id.rsplit("_", 1)[1]) - 1)
                except (TypeError, ValueError):
                    slot_index = occurrence_index
                add("shared.country_of_citizenship", "country", slot_index)
            else:
                add("shared.country_of_citizenship", "country", occurrence_index)

    if not mentions_any("interpreter", "preparer", "employer", "law enforcement"):
        if mentions_any("safe daytime telephone"):
            add("shared.contact.safe_daytime_telephone_number")
        elif mentions_any("daytime telephone"):
            add("shared.contact.daytime_telephone_number")
        elif mentions_any("mobile telephone"):
            add("shared.contact.mobile_telephone_number")
        elif mentions_any("email address", "email"):
            add("shared.contact.email_address")

    normalized_address_field_id = _normalize_address_field_id(field_id)
    if not normalized_address_field_id:
        if mentions_any("in care of name"):
            normalized_address_field_id = "in_care_of_name"
        elif mentions_any("street number and name"):
            normalized_address_field_id = "street_number_name"
        elif mentions_any("apt ste flr", "apartment suite floor", "apartment suite or floor") and not mentions_any("number"):
            normalized_address_field_id = "unit_type"
        elif mentions_any("apartment suite or floor number", "apt ste flr number"):
            normalized_address_field_id = "unit_number"
        elif mentions_any("city or town", "city town"):
            normalized_address_field_id = "city"
        elif mentions_any("state"):
            normalized_address_field_id = "state"
        elif mentions_any("zip code"):
            normalized_address_field_id = "zip_code"
        elif mentions_any("postal code"):
            normalized_address_field_id = "postal_code"
        elif mentions_any("province"):
            normalized_address_field_id = "province"
        elif mentions_any("country") and mentions_any("address", "mailing", "physical"):
            normalized_address_field_id = "country"
    if (
        normalized_address_field_id
        and not mentions_any("interpreter", "preparer", "employer", "law enforcement")
    ):
        if mentions_any("address history", "last five years"):
            add("shared.address_history_last_five_years", normalized_address_field_id, occurrence_index)
        elif mentions_any("safe mailing address", "u.s. mailing address", "mailing address"):
            add(f"shared.safe_mailing_address.{normalized_address_field_id}")
        elif mentions_any("physical address", "current physical address", "current address"):
            add(f"shared.current_physical_address.{normalized_address_field_id}")

    return candidates


def _normalized_address_component_for_compare(field_id: str, value: Any) -> str:
    cleaned = _clean_text(value)
    if field_id == "unit_type":
        return _normalize_address_unit_type(cleaned) or cleaned
    if field_id == "state":
        return _normalize_us_state_code(cleaned) or cleaned
    return cleaned


def _saved_address_bucket(
    answers: Mapping[str, Any],
    question_id: str,
) -> dict[str, str]:
    bucket: dict[str, str] = {}
    for field_id in _ADDRESS_COMPONENT_FIELDS:
        candidate_field_ids = [
            field_id,
            f"safe_{field_id}",
            f"mailing_{field_id}",
            f"physical_{field_id}",
            f"current_{field_id}",
        ]
        for candidate_field_id in candidate_field_ids:
            value, found = _lookup_saved_answer(answers, question_id, field_id=candidate_field_id)
            if found and _has_answer_value(value):
                bucket[field_id] = _normalized_address_component_for_compare(field_id, value)
                break
    return bucket


def _should_blank_safe_mailing_value(
    target: Mapping[str, Any],
    answers: Mapping[str, Any],
    value: Any,
) -> bool:
    if not _is_safe_mailing_target(target) or not _has_answer_value(value):
        return False

    safe_question_id = _clean_text(target.get("questionnaire_item_id") or "shared.safe_mailing_address")
    safe_bucket = _saved_address_bucket(answers, safe_question_id)
    physical_bucket = _saved_address_bucket(answers, "shared.current_physical_address")
    if not safe_bucket or not physical_bucket:
        return False

    return _safe_mailing_duplicates_physical(safe_bucket, physical_bucket)


def _saved_address_component_value(
    answers: Mapping[str, Any],
    question_id: str,
    logical_field_id: str,
) -> str:
    if not question_id or not logical_field_id:
        return ""

    value, found = _lookup_saved_answer(answers, question_id)
    if not found or not isinstance(value, Mapping):
        return ""

    for raw_field_id, raw_field_value in value.items():
        if _normalize_address_field_id(str(raw_field_id)) != logical_field_id:
            continue
        cleaned = _clean_text(raw_field_value)
        if cleaned:
            return cleaned
    return ""


def _normalized_saved_state_value_for_target(
    target: Mapping[str, Any],
    answers: Mapping[str, Any],
    value: Any,
) -> str:
    normalized_state = _normalize_us_state_code(value)
    if normalized_state:
        return normalized_state

    question_id = _clean_text(target.get("questionnaire_item_id") or target.get("question_id"))
    if not question_id:
        return ""

    city_value = _saved_address_component_value(answers, question_id, "city")
    return _infer_state_from_city(city_value)


def _validate_resolved_target_value(
    target: Mapping[str, Any],
    answers: Mapping[str, Any],
    value: Any,
) -> Any:
    if _looks_like_a_number_target(target):
        normalized_value = _normalize_a_number_value(value)
    elif _logical_address_field_id(target) == "state":
        normalized_value = _normalized_saved_state_value_for_target(target, answers, value)
    elif _looks_like_country_target(target):
        normalized_value = _normalize_country_value_for_pdf(value)
    elif _looks_like_nonimmigrant_status(target):
        normalized_value = _normalize_nonimmigrant_status(value)
    else:
        normalized_value = value

    if _should_blank_safe_mailing_value(target, answers, normalized_value):
        return ""
    return normalized_value


def _resolve_questionnaire_answer(
    target: Mapping[str, Any],
    answers: Mapping[str, Any],
    *,
    occurrence_index: int,
) -> tuple[Any, str | None]:
    canonical_questionnaire_id = _clean_text(target.get("canonical_questionnaire_id"))
    field_type = _clean_text(target.get("field_type")).lower()
    prefer_shared_first = (
        field_type == "text"
        and bool(_clean_text(target.get("questionnaire_option_value")))
    )
    if prefer_shared_first:
        shared_value, shared_source_key = _resolve_shared_candidate_answer(
            target,
            answers,
            occurrence_index=occurrence_index,
        )
        normalized_shared_value = _validate_resolved_target_value(target, answers, shared_value)
        if shared_source_key and _has_answer_value(normalized_shared_value):
            return normalized_shared_value, shared_source_key

    if canonical_questionnaire_id:
        value, found = _lookup_saved_answer(
            answers,
            canonical_questionnaire_id,
            index=occurrence_index,
        )
        normalized_value = _validate_resolved_target_value(target, answers, value)
        if found and _has_answer_value(normalized_value):
            return normalized_value, canonical_questionnaire_id

    question_item_id = _clean_text(target.get("questionnaire_item_id"))
    question_field_id = _clean_text(target.get("questionnaire_field_id"))
    if question_item_id:
        value, found = _lookup_saved_answer(
            answers,
            question_item_id,
            field_id=question_field_id or None,
            index=occurrence_index,
        )
        normalized_value = _validate_resolved_target_value(target, answers, value)
        if found and _has_answer_value(normalized_value):
            source_key = (
                f"{question_item_id}.{question_field_id}"
                if question_field_id
                else question_item_id
            )
            return normalized_value, source_key

    shared_value, shared_source_key = _resolve_shared_candidate_answer(
        target,
        answers,
        occurrence_index=occurrence_index,
    )
    normalized_shared_value = _validate_resolved_target_value(target, answers, shared_value)
    if shared_source_key and _has_answer_value(normalized_shared_value):
        return normalized_shared_value, shared_source_key

    return "", None


def _normalize_option_answer(value: Any) -> str:
    normalized = _normalize_value_token(value)
    if normalized in {"true", "yes", "y", "1", "checked", "on"}:
        return "yes"
    if normalized in {"false", "no", "n", "0", "unchecked", "off"}:
        return "no"
    return _CANONICAL_VALUE_ALIASES.get(normalized, normalized)


def _normalize_country_value_for_pdf(value: Any) -> str:
    normalized = _normalize_option_answer(value)
    if not normalized:
        return ""
    return _COUNTRY_NAME_DISPLAY.get(normalized, "")


def _normalize_scalar_value_for_pdf_target(target: Mapping[str, Any], value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value

    cleaned = _clean_text(value)
    if not cleaned:
        return ""

    normalized_value = _normalize_option_answer(cleaned)
    for preferred, normalized_values in _iter_normalized_target_options(target):
        if normalized_value in normalized_values:
            return preferred

    context = _normalized_target_context(target)
    if any(term in context for term in ("social security", "ssn")):
        digits_only = re.sub(r"[^0-9]", "", cleaned)
        if len(digits_only) == 9:
            return digits_only

    if _looks_like_country_target(target):
        country_value = _normalize_country_value_for_pdf(cleaned)
        if country_value:
            return country_value
        return ""

    if _looks_like_nonimmigrant_status(target):
        return _normalize_nonimmigrant_status(cleaned)

    if any(term in context for term in ("sex", "marital status")):
        display_value = _CANONICAL_VALUE_DISPLAY.get(normalized_value)
        if display_value:
            return display_value

    return cleaned


def _iter_normalized_target_options(
    target: Mapping[str, Any],
) -> list[tuple[str, set[str]]]:
    normalized_options: list[tuple[str, set[str]]] = []
    for option in target.get("questionnaire_options", []) or []:
        if isinstance(option, Mapping):
            raw_value = _clean_text(option.get("value"))
            raw_label = _clean_text(option.get("label"))
            preferred = raw_value or raw_label
            if not preferred:
                continue
            normalized_values = {
                _normalize_option_answer(raw_value),
                _normalize_option_answer(raw_label),
            } - {""}
        else:
            preferred = _clean_text(option)
            if not preferred:
                continue
            normalized_values = {_normalize_option_answer(preferred)} - {""}
        if normalized_values:
            normalized_options.append((preferred, normalized_values))
    return normalized_options


def _match_target_options_from_hint(
    target: Mapping[str, Any],
    hint_text: Any,
) -> list[str]:
    hint_tokens = set(_normalize_hint_text(hint_text).split())
    if not hint_tokens:
        return []

    matched_options: list[str] = []
    for preferred, normalized_values in _iter_normalized_target_options(target):
        if any(set(candidate.split()).issubset(hint_tokens) for candidate in normalized_values):
            if preferred not in matched_options:
                matched_options.append(preferred)
    return matched_options


def _match_target_options_from_select_phrase(
    target: Mapping[str, Any],
    hint_text: Any,
) -> list[str]:
    normalized_hint = _normalize_hint_text(hint_text)
    if not normalized_hint:
        return []

    matched_options: list[str] = []
    for preferred, normalized_values in _iter_normalized_target_options(target):
        if any(f"select {candidate}" in normalized_hint for candidate in normalized_values):
            if preferred not in matched_options:
                matched_options.append(preferred)
    return matched_options


def _resolve_explicit_target_option(target: Mapping[str, Any]) -> str:
    raw_target_option = _clean_text(
        target.get("questionnaire_option_value") or target.get("questionnaire_option_label")
    )
    normalized_target_option = _normalize_option_answer(raw_target_option)
    if not normalized_target_option:
        return ""

    for preferred, normalized_values in _iter_normalized_target_options(target):
        if normalized_target_option in normalized_values:
            return preferred
    return ""


def _infer_target_option_value(target: Mapping[str, Any]) -> str:
    field_name_matches = _match_target_options_from_hint(target, target.get("field_name"))
    if len(field_name_matches) == 1:
        return field_name_matches[0]

    select_phrase_matches = _match_target_options_from_select_phrase(target, target.get("field_label"))
    if len(select_phrase_matches) == 1:
        return select_phrase_matches[0]

    explicit_target_option = _resolve_explicit_target_option(target)
    if explicit_target_option:
        return explicit_target_option

    label_matches = _match_target_options_from_hint(target, target.get("field_label"))
    if len(label_matches) == 1:
        return label_matches[0]

    return ""


def _normalize_checkbox_widget_value(target: Mapping[str, Any], value: Any) -> tuple[str, str]:
    cleaned = _clean_text(value)
    if not cleaned:
        return "", ""

    field_type = _clean_text(target.get("field_type")).lower()
    if field_type not in {"checkbox", "radio", "button"}:
        return cleaned, ""

    normalized_value = _normalize_option_answer(cleaned)
    item_type = _clean_text(target.get("questionnaire_item_type")).lower()
    option_matches = [
        preferred
        for preferred, normalized_values in _iter_normalized_target_options(target)
        if normalized_value in normalized_values
    ]
    target_option = _infer_target_option_value(target)
    if target_option:
        normalized_target_option = _normalize_option_answer(target_option)
        if normalized_value in {"yes", "no"}:
            return ("yes" if normalized_value == "yes" else "off"), ""
        if option_matches:
            matched_target_option = any(
                _normalize_option_answer(match) == normalized_target_option
                for match in option_matches
            )
            return ("yes" if matched_target_option else "off"), ""
        return (
            "",
            "Discarded checkbox value because it looked like a nearby mark or unsupported "
            "artifact instead of an explicit checked/unchecked answer.",
        )

    if target.get("questionnaire_options") or item_type in {"yes_no", "single_choice", "select"}:
        if normalized_value == "no":
            return "off", ""
        if normalized_value == "yes" or option_matches:
            return (
                "",
                "Discarded checkbox value because the widget option could not be resolved "
                "safely from the field metadata.",
            )
        return (
            "",
            "Discarded checkbox value because it looked like a nearby mark or unsupported "
            "artifact instead of an explicit answer.",
        )

    if normalized_value in {"yes", "no"}:
        return ("yes" if normalized_value == "yes" else "off"), ""

    return (
        "",
        "Discarded checkbox value because it looked like a nearby mark or unsupported "
        "artifact instead of an explicit checked/unchecked answer.",
    )


def _postprocess_checkbox_widget_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
) -> None:
    for target in targets:
        field_id = _clean_text(target.get("id"))
        if not field_id:
            continue

        current_value = _clean_text((results_by_id.get(field_id) or {}).get("value"))
        if not current_value:
            continue

        normalized_value, review_reason = _normalize_checkbox_widget_value(target, current_value)
        if review_reason:
            _flag_result_for_review(
                results_by_id,
                field_id,
                value=normalized_value,
                justification=review_reason,
            )
            continue

        if normalized_value != current_value:
            _set_result_value(
                results_by_id,
                field_id,
                normalized_value,
                justification="Normalized checkbox widget to an explicit PDF yes/off value.",
            )


def _format_resolved_value_for_pdf(target: Mapping[str, Any], value: Any) -> Any:
    normalized_value = _normalize_scalar_value_for_pdf_target(target, value)
    field_type = _clean_text(target.get("field_type")).lower()
    if field_type not in {"checkbox", "radio", "button"}:
        return normalized_value

    target_option = _infer_target_option_value(target)
    if target_option:
        return (
            "yes"
            if _normalize_option_answer(normalized_value) == _normalize_option_answer(target_option)
            else "off"
        )

    item_type = _clean_text(target.get("questionnaire_item_type")).lower()
    if (target.get("questionnaire_options") or []) and item_type in {"yes_no", "single_choice", "select"}:
        return "off"

    normalized_option_value = _normalize_option_answer(normalized_value)
    if normalized_option_value in {"yes", "no"}:
        return "yes" if normalized_option_value == "yes" else "off"
    return "yes" if _has_answer_value(normalized_value) else "off"


def _g28_answer_text(
    answers: Mapping[str, Any],
    question_id: str,
    field_id: str | None = None,
) -> str:
    value, found = _lookup_saved_answer(answers, question_id, field_id=field_id)
    return _clean_text(value) if found else ""


def _set_g28_pdf_result(
    results_by_id: dict[str, dict[str, str]],
    field_name_suffix: str,
    value: str,
    *,
    confidence: str = "high",
) -> set[str]:
    touched_field_names: set[str] = set()
    for field_name in list(results_by_id):
        if f".{field_name_suffix}[" not in field_name and not field_name.endswith(field_name_suffix):
            continue
        results_by_id[field_name] = {
            "id": field_name,
            "value": value,
            "confidence": confidence if value else "low",
            "justification": "Applied G-28 questionnaire default or saved answer to the exact PDF field.",
        }
        touched_field_names.add(field_name)
    return touched_field_names


def _g28_checkbox_value(
    answers: Mapping[str, Any],
    question_id: str,
    field_id: str | None = None,
) -> str:
    return "yes" if _normalize_option_answer(_g28_answer_text(answers, question_id, field_id)) == "yes" else "off"


def _g28_choice_matches(value: str, expected: str) -> bool:
    normalized = _normalize_option_answer(value).replace(" ", "_")
    return normalized == expected or _clean_text(value).lower() == expected.lower()


def _postprocess_g28_default_pdf_values(
    results_by_id: dict[str, dict[str, str]],
    answers: Mapping[str, Any],
) -> set[str]:
    if not any("Pt2Line1d_NameofFirmOrOrganization" in field_name for field_name in results_by_id):
        return set()

    touched_field_names: set[str] = set()

    text_mappings = {
        "Pt1Line1_USCISOnlineAcctNumber": ("p1_attorney_contact", "attorney_uscis_online_account_number"),
        "Pt1Line2a_FamilyName": ("p1_attorney_name", "attorney_family_name"),
        "Pt1Line2b_GivenName": ("p1_attorney_name", "attorney_given_name"),
        "Pt1Line2c_MiddleName": ("p1_attorney_name", "attorney_middle_name"),
        "Line3a_StreetNumber": ("p1_attorney_address", "attorney_street_number_name"),
        "Line3c_CityOrTown": ("p1_attorney_address", "attorney_city"),
        "Line3d_State": ("p1_attorney_address", "attorney_state"),
        "Line3e_ZipCode": ("p1_attorney_address", "attorney_zip_code"),
        "Line3h_Country": ("p1_attorney_address", "attorney_country"),
        "Line4_DaytimeTelephoneNumber": ("p1_attorney_contact", "attorney_daytime_telephone_number"),
        # The G-28 template has these two internal field names swapped:
        # Line6_EMail is rendered under "Mobile Telephone Number", and
        # Line7_MobileTelephoneNumber is rendered under "Email Address".
        "Line6_EMail": ("p1_attorney_contact", "attorney_mobile_telephone_number"),
        "Line7_MobileTelephoneNumber": ("p1_attorney_contact", "attorney_email_address"),
        "Pt2Line1a_LicensingAuthority": ("p2_eligibility", "attorney_licensing_authority"),
        "Pt2Line1b_BarNumber": ("p2_eligibility", "attorney_bar_number"),
        "Pt2Line1d_NameofFirmOrOrganization": ("p2_other", None),
        "Line1b_ListFormNumber": ("p3_appearance_matter", "uscis_form_numbers"),
        "Line12a_StreetNumberName": ("p3_client_mailing_address", "mailing_street_number_name"),
        "Line12c_CityOrTown": ("p3_client_mailing_address", "mailing_city"),
        "Line12d_State": ("p3_client_mailing_address", "mailing_state"),
        "Line12e_ZipCode": ("p3_client_mailing_address", "mailing_zip_code"),
        "Line12h_Country": ("p3_client_mailing_address", "mailing_country"),
    }
    for suffix, (question_id, field_id) in text_mappings.items():
        touched_field_names.update(
            _set_g28_pdf_result(
                results_by_id,
                suffix,
                _g28_answer_text(answers, question_id, field_id),
            )
        )

    touched_field_names.update(
        _set_g28_pdf_result(
            results_by_id,
            "CheckBox1",
            _g28_checkbox_value(answers, "p2_eligibility", "is_attorney_in_good_standing"),
        )
    )
    not_subject_to_discipline = _g28_checkbox_value(
        answers,
        "p2_eligibility",
        "is_not_subject_to_discipline",
    )
    touched_field_names.update(
        _set_g28_pdf_result(results_by_id, "Checkbox1dAmNot", not_subject_to_discipline)
    )
    touched_field_names.update(
        _set_g28_pdf_result(
            results_by_id,
            "Checkbox1dAm",
            "off" if not_subject_to_discipline == "yes" else "yes",
        )
    )
    touched_field_names.update(
        _set_g28_pdf_result(
            results_by_id,
            "Line1a_USCIS",
            _g28_checkbox_value(answers, "p3_appearance_matter", "appearance_before_uscis"),
        )
    )

    notice_preference = _normalize_option_answer(
        _g28_answer_text(answers, "p4_notification_preference")
    )
    secure_documents = _normalize_option_answer(
        _g28_answer_text(answers, "p4_secure_documents")
    )
    touched_field_names.update(
        _set_g28_pdf_result(
            results_by_id,
            "Pt4Line2a_CheckBox2a",
            "yes" if _g28_choice_matches(notice_preference, "notices_to_attorney") else "off",
        )
    )
    touched_field_names.update(
        _set_g28_pdf_result(
            results_by_id,
            "Pt4Line2b_CheckBox2b",
            "yes" if _g28_choice_matches(secure_documents, "secure_to_attorney") else "off",
        )
    )
    touched_field_names.update(_set_g28_pdf_result(results_by_id, "Pt4Line2c_CheckBox2c", "off"))
    return touched_field_names


def _fix_unit_type_checkbox_results(
    targets: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    answers: Mapping[str, Any],
    pdf_fields: list[dict[str, Any]],
) -> None:
    """Correct unit-type checkbox values using positional mapping.

    USCIS forms use three adjacent checkboxes (Apt./Ste./Flr.) for the
    address unit type, always laid out left-to-right.  When the matcher
    cannot assign a distinct ``questionnaire_option_value`` to each
    checkbox the generic select-type fallback marks them all ``"off"``.
    This function detects that scenario, resolves the saved unit-type
    answer, and uses each widget's x-position to assign ``"yes"`` to the
    correct checkbox.
    """
    _ORDERED_UNIT_OPTIONS: tuple[str, ...] = ("Apt.", "Ste.", "Flr.")

    pdf_rect_by_name: dict[str, dict[str, float]] = {}
    for field in pdf_fields:
        name = _clean_text(field.get("field_name"))
        rect = field.get("rect")
        if name and isinstance(rect, dict):
            pdf_rect_by_name[name] = rect

    groups: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        if not _target_looks_like_unit_type_button(target):
            continue
        canonical = _clean_text(target.get("canonical_questionnaire_id") or "")
        if "[" in canonical:
            canonical = canonical[: canonical.index("[")]
        group_key = canonical or f"_page_{target.get('page_number', 0)}"
        groups.setdefault(group_key, []).append(target)

    for group_key, group_targets in groups.items():
        if not all(
            _clean_text(
                (results_by_id.get(_clean_text(t.get("field_name"))) or {}).get("value")
            ).lower()
            in {"off", ""}
            for t in group_targets
        ):
            continue

        saved_unit_type = ""
        value, found = _lookup_saved_answer(answers, group_key)
        if found and _has_answer_value(value):
            saved_unit_type = _normalize_address_unit_type(value)
        if not saved_unit_type:
            for t in group_targets:
                item_id = _clean_text(t.get("questionnaire_item_id"))
                field_id = _clean_text(t.get("questionnaire_field_id"))
                if item_id:
                    v, f = _lookup_saved_answer(
                        answers, item_id, field_id=field_id or "unit_type"
                    )
                    if f and _has_answer_value(v):
                        saved_unit_type = _normalize_address_unit_type(v)
                        break

        if not saved_unit_type or saved_unit_type not in _ORDERED_UNIT_OPTIONS:
            continue

        def _x_pos(t: dict[str, Any]) -> float:
            rect = pdf_rect_by_name.get(_clean_text(t.get("field_name")), {})
            return float(rect.get("x0", 0))

        sorted_targets = sorted(group_targets, key=_x_pos)

        for idx, target in enumerate(sorted_targets):
            field_name = _clean_text(target.get("field_name"))
            positional_option = (
                _ORDERED_UNIT_OPTIONS[idx] if idx < len(_ORDERED_UNIT_OPTIONS) else ""
            )
            checked = positional_option == saved_unit_type
            results_by_id[field_name] = {
                "id": field_name,
                "value": "yes" if checked else "off",
                "confidence": "high" if checked else "low",
                "justification": (
                    f"Address unit type checkbox ({positional_option}) "
                    + ("matches" if checked else "does not match")
                    + f" saved answer: {saved_unit_type}."
                ),
            }


def _build_results_from_answers(
    targets: list[dict[str, Any]],
    answers: Mapping[str, Any],
    *,
    pdf_fields: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, str]]:
    results_by_id: dict[str, dict[str, str]] = {}
    occurrence_by_question_id: dict[str, int] = {}

    for target in targets:
        field_name = _clean_text(target.get("field_name"))
        if not field_name:
            continue
        if _is_pdf417_barcode_field(target):
            results_by_id[field_name] = {
                "id": field_name,
                "value": "",
                "confidence": "low",
                "justification": "Skipped PDF417 barcode field because it is a generated page artifact, not a user-entered form value.",
            }
            continue
        if _is_manual_lea_unit_target(target):
            results_by_id[field_name] = {
                "id": field_name,
                "value": "",
                "confidence": "low",
                "justification": "The Part 3.5 Number field is intentionally left blank and must be reviewed manually.",
            }
            continue

        canonical_questionnaire_id = _clean_text(
            target.get("canonical_questionnaire_id")
            or target.get("questionnaire_item_id")
            or field_name
        )
        item_type = _clean_text(target.get("questionnaire_item_type")).lower()
        precomputed_occurrence = _safe_int(target.get("occurrence_index"))
        if item_type == "repeatable_group" and precomputed_occurrence is not None:
            occurrence_index = precomputed_occurrence
            occurrence_by_question_id[canonical_questionnaire_id] = max(
                occurrence_by_question_id.get(canonical_questionnaire_id, 0),
                occurrence_index + 1,
            )
        elif item_type == "group":
            occurrence_index = 0
        else:
            occurrence_index = occurrence_by_question_id.get(canonical_questionnaire_id, 0)
            occurrence_by_question_id[canonical_questionnaire_id] = occurrence_index + 1

        effective_occurrence = 0 if _looks_like_a_number_target(target) else occurrence_index

        resolved_value, source_key = _resolve_questionnaire_answer(
            target,
            answers,
            occurrence_index=effective_occurrence,
        )
        pdf_value = _format_resolved_value_for_pdf(target, resolved_value)
        final_value = "" if pdf_value is None else str(pdf_value)
        results_by_id[field_name] = {
            "id": field_name,
            "value": final_value,
            "confidence": "high" if source_key else "low",
            "justification": (
                f"Saved questionnaire answer from {source_key}."
                if source_key
                else "No saved questionnaire answer found for this PDF field."
            ),
        }

        if not final_value and _looks_like_a_number_target(target):
            raw_p2_5 = answers.get("p2_5")
            raw_shared = (answers.get("shared.identifiers") or {}).get("a_number") if isinstance(answers.get("shared.identifiers"), dict) else None
            log.warning(
                "A-Number field %r (canonical=%s, occ_idx=%d->%d) resolved to empty. "
                "p2_5=%r, shared.identifiers.a_number=%r, resolved_value=%r, source=%r",
                field_name,
                canonical_questionnaire_id,
                occurrence_index,
                effective_occurrence,
                raw_p2_5,
                raw_shared,
                resolved_value,
                source_key,
            )

    if pdf_fields is not None:
        _fix_unit_type_checkbox_results(targets, results_by_id, answers, pdf_fields)

    _postprocess_address_results(targets, results_by_id, {})
    _postprocess_us_address_foreign_fields(targets, results_by_id)
    _postprocess_compound_name_results(targets, results_by_id)
    _postprocess_g28_default_pdf_values(results_by_id, answers)
    return results_by_id


def regenerate_filled_pdf(
    db: Session,
    job_id: str,
) -> FormFillingJob:
    """Rebuild the filled PDF from the persisted field values."""
    job = db.query(FormFillingJob).filter(FormFillingJob.id == job_id).first()
    if not job:
        raise ValueError("Form filling job not found.")

    validation_issues = validate_form_generation_requirements(
        db,
        job.case_id,
        form_type=job.form_type or "",
    )
    if validation_issues:
        raise ValueError(format_form_generation_validation_error(validation_issues))

    detection = detect_form_fields(job.original_pdf_path)
    pdf_fields = list(detection.get("fields", []) or [])
    source_pdf_path = job.original_pdf_path
    should_refresh_from_saved_answers = False
    field_rows = _load_field_rows(db, job.id)
    resolved_form_type = _normalize_form_type(job.form_type)
    answers: dict[str, Any] = {}
    targets: list[dict[str, Any]] = []
    results_by_id: dict[str, dict[str, str]] = {}
    if resolved_form_type and detection.get("field_count"):
        mappings = map_pdf_fields_to_questionnaire_ids(
            resolved_form_type,
            pdf_fields,
        )
        targets = _build_extraction_targets(
            resolved_form_type,
            pdf_fields,
            list(mappings.get("mappings", []) or []),
        )
        answers = _get_questionnaire_answers_with_defaults(
            db,
            job.case_id,
            form_type=resolved_form_type,
        )
        answers = _propagate_shared_a_number_to_p2_5(answers)
        answers = _propagate_shared_name_to_p2_1(answers)
        results_by_id = _build_results_from_answers(
            targets,
            answers,
            pdf_fields=pdf_fields,
        )
        forced_field_ids: set[str] = set()
        if _normalize_form_type(resolved_form_type) == "i-914":
            forced_field_ids = _postprocess_i914_forced_pdf_values(targets, results_by_id)
        if _normalize_form_type(resolved_form_type) == "g-28":
            forced_field_ids.update(_postprocess_g28_default_pdf_values(results_by_id, answers))
        rows_by_field_name = {row.field_name: row for row in field_rows}
        for field_name, result in results_by_id.items():
            row = rows_by_field_name.get(field_name)
            is_forced = field_name in forced_field_ids
            if row is None or (not is_forced and (row.manually_corrected or _clean_text(row.extracted_value))):
                continue
            next_value = _clean_text(result.get("value"))
            if not next_value:
                continue
            row.extracted_value = next_value
            row.confidence = _clean_text(result.get("confidence")) or row.confidence
            row.evidence_source = _clean_text(result.get("justification")) or row.evidence_source
            db.add(row)
    mode = _clean_text(detection.get("mode"))
    existing_field_rows = field_rows
    needs_unit_type_repair = _field_rows_need_unit_type_repair(
        existing_field_rows,
        resolved_form_type=resolved_form_type,
        pdf_fields=pdf_fields,
        answers=answers,
        precomputed_targets=targets,
        precomputed_results_by_id=results_by_id,
    )

    if should_refresh_from_saved_answers or needs_unit_type_repair:
        field_rows = _rebuild_job_fields_from_answers(
            db,
            job,
            resolved_form_type=resolved_form_type,
            pdf_fields=pdf_fields,
            precomputed_targets=targets,
            precomputed_answers=answers,
            precomputed_results_by_id=results_by_id,
        )
    else:
        field_rows = existing_field_rows

    if _field_rows_need_unit_type_repair(
        field_rows,
        resolved_form_type=resolved_form_type,
        pdf_fields=pdf_fields,
        answers=answers,
        precomputed_targets=targets,
        precomputed_results_by_id=results_by_id,
    ):
        raise RuntimeError(
            "The saved address unit type could not be mapped to the PDF unit checkboxes during regeneration."
        )

    if mode == "acroform":
        write_result = fill_acroform_fields(
            source_pdf_path,
            _build_pdf_value_map(field_rows),
            output_path=build_generated_form_output_path(db, job),
        )
    elif detection.get("field_count"):
        write_result = fill_overlay_fields(
            source_pdf_path,
            _build_overlay_payload(pdf_fields, field_rows),
            output_path=build_generated_form_output_path(db, job),
        )
    else:
        raise NotImplementedError(
            "The uploaded PDF does not contain AcroForm fields and no Document AI layout is available."
        )

    job.filled_pdf_path = _clean_text(write_result.get("output_path"))
    _apply_i914_lea_agency_label_overlay(
        job.filled_pdf_path,
        answers,
        resolved_form_type,
    )
    job.filled_count = sum(1 for row in field_rows if _clean_text(row.extracted_value))
    _persist_job_state(
        db,
        job,
        form_filling_jobs.update_writing_progress(
            job.id,
            written_fields=job.field_count,
            filled_pdf_path=job.filled_pdf_path,
            filled_count=job.filled_count,
            phase="regenerating_pdf",
        ),
    )
    completed_payload = form_filling_jobs.mark_completed(job.id, phase="completed")
    if completed_payload is None:
        now = datetime.now(timezone.utc)
        job.status = "completed"
        job.phase = "completed"
        job.completed_at = now
        job.updated_at = now
        _persist_job_state(db, job, None)
    else:
        _persist_job_state(db, job, completed_payload)
    db.refresh(job)
    return overlay_runtime_status(job) or job


def _audit_job(
    db: Session,
    *,
    case_id: str,
    action: str,
    job_id: str,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            case_id=case_id,
            action=action,
            entity_type="form_filling_job",
            entity_id=job_id,
            details=details,
        )
    )
    db.commit()


def _record_form_filling_job_failure(
    db: Session,
    *,
    job_id: str,
    exc: Exception,
    state: FormFillingExecutionState,
) -> None:
    db.rollback()
    review_required = isinstance(exc, ReviewRequiredError)
    if review_required:
        log.warning("Form filling job %s requires manual review: %s", job_id[:8], exc)
    else:
        log.exception("Form filling job %s failed", job_id[:8])

    try:
        failed_job = db.query(FormFillingJob).filter(FormFillingJob.id == job_id).first()
        if not failed_job:
            return

        runtime_payload = (
            form_filling_jobs.mark_needs_review(job_id, str(exc), phase="needs_review")
            if review_required
            else form_filling_jobs.mark_failed(job_id, str(exc), phase="failed")
        )
        if runtime_payload:
            _apply_runtime_payload(failed_job, runtime_payload)
        else:
            failed_job.status = "needs_review" if review_required else "failed"
            failed_job.phase = "needs_review" if review_required else "failed"
            failed_job.error_message = _clean_text(str(exc))[:1000]

        db.add(failed_job)
        db.commit()

        audit_details = {
            "error": _clean_text(str(exc))[:1000],
            "form_type": failed_job.form_type,
            "field_count": int(failed_job.field_count or 0),
            "matched_count": int(state.mapping_result.get("matched_count") or 0),
            "pdf_mode": state.pdf_fields_result.get("mode"),
        }
        if state.preparation_result:
            audit_details["case_preparation"] = state.preparation_result
        if state.detection_result:
            audit_details["detection"] = state.detection_result

        _audit_job(
            db,
            case_id=failed_job.case_id,
            action="form_filling_needs_review" if review_required else "form_filling_failed",
            job_id=failed_job.id,
            details=audit_details,
        )
    except Exception:
        db.rollback()
        log.exception("Could not persist failure details for form filling job %s", job_id[:8])


def generate_form_from_answers(job_id: str) -> None:
    """Generate a filled PDF from saved questionnaire answers."""
    db = SessionLocal()
    tracker = create_token_tracker(label=f"form-generate-{job_id[:8]}")
    mapping_result: dict[str, Any] = {}
    pdf_fields_result: dict[str, Any] = {}
    write_result: dict[str, Any] = {}
    evidence_by_id: dict[str, Any] = {}
    imported_page_count = 0

    try:
        job = db.query(FormFillingJob).filter(FormFillingJob.id == job_id).first()
        if not job:
            return

        _persist_job_state(db, job, _ensure_runtime_job(job))

        resolved_form_type = _normalize_form_type(job.form_type)
        if not resolved_form_type:
            raise ValueError("A supported form type is required to generate a filled PDF.")

        validation_issues = validate_form_generation_requirements(
            db,
            job.case_id,
            form_type=resolved_form_type,
        )
        if validation_issues:
            raise ValueError(format_form_generation_validation_error(validation_issues))

        template_path = get_form_template_path(resolved_form_type)
        if _clean_text(job.original_pdf_path) != str(template_path):
            job.original_pdf_path = str(template_path)
            _persist_job_state(
                db,
                job,
                form_filling_jobs.set_pdf_paths(
                    job_id,
                    original_pdf_path=str(template_path),
                ),
            )

        _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="detecting_fields"))
        pdf_fields_result = detect_form_fields(str(template_path))
        _persist_job_state(
            db,
            job,
            form_filling_jobs.set_field_total(
                job_id,
                int(pdf_fields_result.get("field_count") or 0),
                phase="detecting_fields",
            ),
        )

        if not pdf_fields_result.get("field_count"):
            raise NotImplementedError(
                "The blank PDF template does not contain AcroForm fields and no Document AI field layout was detected."
            )

        _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="matching_form"))
        mapping_result = map_pdf_fields_to_questionnaire_ids(
            resolved_form_type,
            list(pdf_fields_result.get("fields", []) or []),
        )
        _persist_job_state(
            db,
            job,
            form_filling_jobs.update_matching_progress(
                job_id,
                matched_fields=int(mapping_result.get("matched_count") or 0),
                phase="matching_form",
            ),
        )

        targets = _build_extraction_targets(
            resolved_form_type,
            list(pdf_fields_result.get("fields", []) or []),
            list(mapping_result.get("mappings", []) or []),
        )
        field_rows = _replace_job_fields(db, job, targets)

        answers = _get_questionnaire_answers_with_defaults(
            db,
            job.case_id,
            form_type=resolved_form_type,
        )
        answers = _propagate_shared_a_number_to_p2_5(answers)
        answers = _propagate_shared_name_to_p2_1(answers)
        results_by_id = _build_results_from_answers(
            targets,
            answers,
            pdf_fields=list(pdf_fields_result.get("fields", []) or []),
        )

        _diag_filled = sum(1 for r in results_by_id.values() if _clean_text(r.get("value")))
        _diag_empty = len(results_by_id) - _diag_filled
        _diag_conf = {}
        for t in targets:
            c = _clean_text(t.get("mapping_confidence")) or "unmapped"
            _diag_conf[c] = _diag_conf.get(c, 0) + 1
        log.info(
            "DIAG job %s form=%s: pdf_fields=%d, matched=%d, unmatched=%d, "
            "saved_answers=%d, resolved=%d, empty=%d, confidence=%s, "
            "answer_keys_sample=%s",
            job_id[:8],
            resolved_form_type,
            int(pdf_fields_result.get("field_count") or 0),
            int(mapping_result.get("matched_count") or 0),
            int(mapping_result.get("unmatched_count") or 0),
            len(answers),
            _diag_filled,
            _diag_empty,
            _diag_conf,
            list(answers.keys())[:15],
        )
        _diag_empty_samples = [
            (r["id"], _clean_text(r.get("justification"))[:80])
            for r in results_by_id.values()
            if not _clean_text(r.get("value"))
        ][:10]
        if _diag_empty_samples:
            log.info("DIAG job %s empty field samples: %s", job_id[:8], _diag_empty_samples)

        if _normalize_form_type(resolved_form_type) == "i-914":
            source_document_ids = _get_source_document_ids(db, job.case_id)
            evidence_targets = [
                target
                for target in targets
                if not _skip_reason(target)
                and (
                    _clean_text(target.get("questionnaire_item_id")).lower() == "p2_last_entry"
                    or _clean_text(target.get("questionnaire_item_id")).lower().startswith("p3_")
                    or _clean_text(target.get("questionnaire_item_id")).lower().startswith("p4_")
                    or _clean_text(target.get("questionnaire_item_id")).lower().startswith("p5_")
                )
            ]
            if evidence_targets:
                evidence_by_id = _collect_evidence_for_targets(
                    evidence_targets,
                    case_id=job.case_id,
                    job_id=job_id,
                    tracker=tracker,
                    source_document_ids=source_document_ids,
                )
                evidence_by_id = _consolidate_evidence_timeline(
                    evidence_by_id,
                    targets,
                    form_type=resolved_form_type,
                )

            missing_p9 = _validate_part9_completeness(targets, results_by_id, answers)
            if missing_p9:
                log.warning(
                    "Questionnaire generation job %s: %d Part 4/3 items have 'Yes' without Part 9 entries: %s",
                    job_id[:8],
                    len(missing_p9),
                    [m["item_id"] for m in missing_p9],
                )
                _auto_generate_missing_part9_entries(
                    missing_p9, targets, results_by_id, evidence_by_id, answers,
                )
                results_by_id = _build_results_from_answers(
                    targets,
                    answers,
                    pdf_fields=list(pdf_fields_result.get("fields", []) or []),
                )

            i914_relevant_field_ids = [
                _clean_text(target.get("id"))
                for target in targets
                if _clean_text(target.get("id"))
                and (
                    _clean_text(target.get("questionnaire_item_id")).lower() == "p2_last_entry"
                    or _clean_text(target.get("questionnaire_item_id")).lower().startswith("p3_")
                    or _clean_text(target.get("questionnaire_item_id")).lower().startswith("p4_")
                )
            ]
            shared_classified_events = _collect_i914_classified_events(
                evidence_by_id, i914_relevant_field_ids
            )
            shared_detention_facts = _extract_detention_facts_from_evidence(
                evidence_by_id, i914_relevant_field_ids
            )
            _postprocess_i914_critical_field_override(
                targets,
                results_by_id,
                detention_facts=shared_detention_facts,
            )
            _postprocess_i914_arrival_circumstances(
                targets,
                results_by_id,
                answers,
                detention_facts=shared_detention_facts,
                classified_events=shared_classified_events,
            )
            consistency_issues = _postprocess_i914_part4_consistency(
                targets,
                results_by_id,
                evidence_by_id,
                detention_facts=shared_detention_facts,
                classified_events=shared_classified_events,
            )
            _postprocess_i914_part4_table_completion(
                targets,
                results_by_id,
                evidence_by_id,
                answers,
                detention_facts=shared_detention_facts,
            )
            _postprocess_i914_forced_pdf_values(targets, results_by_id)
            _postprocess_i914_family_roster(targets, results_by_id, evidence_by_id)
            category_issues = _validate_i914_category_consistency(
                targets,
                results_by_id,
                answers,
                evidence_by_id,
                classified_events=shared_classified_events,
            )
            review_issues = _collect_i914_result_review_issues(targets, results_by_id, answers)
            for issue in consistency_issues:
                review_issues.append(issue["message"])
            for issue in category_issues:
                if issue.get("severity") in {"review", "downgrade"}:
                    review_issues.append(issue["message"])
            review_issues = list(dict.fromkeys(review_issues))
            if review_issues:
                if _i914_manual_review_bypass_enabled():
                    log.warning(
                        "Form filling job %s: I914_BYPASS_MANUAL_REVIEW is enabled. "
                        "Proceeding despite manual review issues: %s",
                        job_id[:8],
                        review_issues,
                    )
                else:
                    raise ReviewRequiredError(
                        "Manual review required before finalizing the I-914:\n"
                        + "\n".join(f"- {issue}" for issue in review_issues)
                    )

        field_rows = _persist_extraction_results(
            db,
            job,
            results_by_id=results_by_id,
        )

        filled_count = sum(1 for row in field_rows if _clean_text(row.extracted_value))
        _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="writing_pdf"))
        if _clean_text(pdf_fields_result.get("mode")) == "acroform":
            write_result = fill_acroform_fields(
                str(template_path),
                _build_pdf_value_map(field_rows),
                output_path=build_generated_form_output_path(db, job),
            )
        else:
            write_result = fill_overlay_fields(
                str(template_path),
                _build_overlay_payload(
                    list(pdf_fields_result.get("fields", []) or []),
                    field_rows,
                ),
                output_path=build_generated_form_output_path(db, job),
            )

        written_count = int(write_result.get("written_count") or 0)
        skipped_write_fields = list(write_result.get("skipped_fields") or [])
        job.filled_pdf_path = _clean_text(write_result.get("output_path"))
        _apply_i914_lea_agency_label_overlay(
            job.filled_pdf_path,
            answers,
            resolved_form_type,
        )
        job.filled_count = filled_count
        _persist_job_state(
            db,
            job,
            form_filling_jobs.update_writing_progress(
                job_id,
                written_fields=written_count,
                filled_pdf_path=job.filled_pdf_path,
                filled_count=filled_count,
                phase="writing_pdf",
            ),
        )

        if skipped_write_fields:
            log.warning(
                "Questionnaire generation job %s skipped malformed choice fields: %s",
                job_id[:8],
                ", ".join(skipped_write_fields),
            )

        try:
            imported_page_count = _import_generated_pdf_pages(db, job)
        except Exception:
            log.exception(
                "Could not import generated PDF pages for questionnaire job %s",
                job_id[:8],
            )

        _persist_job_state(db, job, form_filling_jobs.mark_completed(job_id, phase="completed"))

        _audit_job(
            db,
            case_id=job.case_id,
            action="form_filling_generated_from_answers",
            job_id=job.id,
            details={
                "form_type": job.form_type,
                "field_count": job.field_count,
                "matched_count": int(mapping_result.get("matched_count") or 0),
                "unmatched_count": int(mapping_result.get("unmatched_count") or 0),
                "saved_answer_count": len(answers),
                "filled_count": filled_count,
                "pdf_mode": pdf_fields_result.get("mode"),
                "written_count": written_count,
                "imported_page_count": imported_page_count,
                "missing_fields": list(write_result.get("missing_fields") or []),
                "skipped_fields": skipped_write_fields,
            },
        )
    except Exception as exc:
        db.rollback()
        review_required = isinstance(exc, ReviewRequiredError)
        if review_required:
            log.warning("Questionnaire generation job %s requires manual review: %s", job_id[:8], exc)
        else:
            log.exception("Questionnaire generation job %s failed", job_id[:8])
        try:
            failed_job = db.query(FormFillingJob).filter(FormFillingJob.id == job_id).first()
            if failed_job:
                runtime_payload = (
                    form_filling_jobs.mark_needs_review(job_id, str(exc), phase="needs_review")
                    if review_required
                    else form_filling_jobs.mark_failed(job_id, str(exc), phase="failed")
                )
                if runtime_payload:
                    _apply_runtime_payload(failed_job, runtime_payload)
                else:
                    failed_job.status = "needs_review" if review_required else "failed"
                    failed_job.phase = "needs_review" if review_required else "failed"
                    failed_job.error_message = _clean_text(str(exc))[:1000]
                db.add(failed_job)
                db.commit()
                _audit_job(
                    db,
                    case_id=failed_job.case_id,
                    action="form_filling_needs_review" if review_required else "form_filling_failed",
                    job_id=failed_job.id,
                    details={
                        "error": _clean_text(str(exc))[:1000],
                        "form_type": failed_job.form_type,
                        "field_count": int(failed_job.field_count or 0),
                        "matched_count": int(mapping_result.get("matched_count") or 0),
                        "pdf_mode": pdf_fields_result.get("mode"),
                        "generation_source": "questionnaire_answers",
                    },
                )
        except Exception:
            db.rollback()
            log.exception("Could not persist failure details for questionnaire generation job %s", job_id[:8])
    finally:
        db.close()


def _run_form_filling_job_pipeline(
    db: Session,
    job: FormFillingJob,
    *,
    job_id: str,
    tracker: Any,
    state: FormFillingExecutionState,
) -> None:
    filled_count = 0
    answers_for_pp: dict[str, Any] = {}

    _persist_job_state(db, job, _ensure_runtime_job(job))
    form_scope_source_document_ids = _get_source_document_ids(db, job.case_id)
    state.preparation_result = _prepare_case_documents_for_form_filling(
        db,
        job,
        job_id=job_id,
        tracker=tracker,
        source_document_ids=form_scope_source_document_ids,
    )
    _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="detecting_fields"))

    state.pdf_fields_result = detect_form_fields(job.original_pdf_path)
    _persist_job_state(
        db,
        job,
        form_filling_jobs.set_field_total(
            job_id,
            int(state.pdf_fields_result.get("field_count") or 0),
            phase="detecting_fields",
        ),
    )

    if not state.pdf_fields_result.get("field_count"):
        raise NotImplementedError(
            "The uploaded PDF does not contain AcroForm fields and no Document AI field layout was detected."
        )

    _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="matching_form"))

    if job.form_type:
        state.detection_result = {
            "form_type": _normalize_form_type(job.form_type),
            "detection_source": "provided",
            "score": 1.0,
            "reason": "Form type was provided explicitly.",
        }
    else:
        state.detection_result = identify_form_type_from_pdf(job.original_pdf_path)

    resolved_form_type = _normalize_form_type(state.detection_result.get("form_type") or job.form_type)
    if not resolved_form_type:
        raise ValueError(
            _clean_text(state.detection_result.get("reason"))
            or "Could not identify a supported questionnaire for the uploaded PDF."
        )

    job.form_type = resolved_form_type
    _persist_job_state(db, job, form_filling_jobs.set_form_type(job_id, resolved_form_type))

    state.mapping_result = map_pdf_fields_to_questionnaire_ids(
        resolved_form_type,
        list(state.pdf_fields_result.get("fields", []) or []),
    )
    _record_low_coverage_warning_if_needed(db, job, state.mapping_result)
    _persist_job_state(
        db,
        job,
        form_filling_jobs.update_matching_progress(
            job_id,
            matched_fields=int(state.mapping_result.get("matched_count") or 0),
            phase="matching_form",
        ),
    )

    targets = _build_extraction_targets(
        resolved_form_type,
        list(state.pdf_fields_result.get("fields", []) or []),
        list(state.mapping_result.get("mappings", []) or []),
    )
    field_rows = _replace_job_fields(db, job, targets)

    extractable_targets = [target for target in targets if not _skip_reason(target)]
    if extractable_targets:
        _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="gathering_evidence"))
        _persist_job_state(
            db,
            job,
            form_filling_jobs.set_evidence_total(
                job_id,
                len(extractable_targets),
                phase="gathering_evidence",
            ),
        )
        state.evidence_by_id = _collect_evidence_for_targets(
            extractable_targets,
            case_id=job.case_id,
            job_id=job_id,
            tracker=tracker,
            source_document_ids=form_scope_source_document_ids,
        )
    else:
        state.evidence_by_id = {}

    state.evidence_by_id = _consolidate_evidence_timeline(
        state.evidence_by_id,
        targets,
        form_type=resolved_form_type,
    )

    _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="extracting_values"))
    results_by_id, filled_count, state.extraction_error_count = _extract_values_for_targets(
        targets,
        evidence_by_id=state.evidence_by_id,
        form_type=resolved_form_type,
        job_id=job_id,
        tracker=tracker,
    )

    if _normalize_form_type(resolved_form_type) == "g-28":
        answers_for_pp = _get_questionnaire_answers_with_defaults(
            db,
            job.case_id,
            form_type=resolved_form_type,
        )
        _postprocess_g28_default_pdf_values(results_by_id, answers_for_pp)

    if _normalize_form_type(resolved_form_type) == "i-914":
        answers_for_pp = _get_questionnaire_answers_with_defaults(
            db, job.case_id, form_type=resolved_form_type,
        )
        detention_fact_field_ids = [
            _clean_text(t.get("id"))
            for t in targets
            if _clean_text(t.get("id"))
            and (
                _clean_text(t.get("questionnaire_item_id")).lower() == "p2_last_entry"
                or _clean_text(t.get("questionnaire_item_id")).lower().startswith("p3_")
                or _clean_text(t.get("questionnaire_item_id")).lower().startswith("p4_")
            )
        ]
        shared_classified_events = _collect_i914_classified_events(
            state.evidence_by_id, detention_fact_field_ids
        )
        shared_detention_facts = _extract_detention_facts_from_evidence(
            state.evidence_by_id,
            detention_fact_field_ids,
        )
        _postprocess_i914_critical_field_override(
            targets,
            results_by_id,
            detention_facts=shared_detention_facts,
        )
        _postprocess_i914_arrival_circumstances(
            targets,
            results_by_id,
            answers_for_pp,
            detention_facts=shared_detention_facts,
            classified_events=shared_classified_events,
        )
        consistency_issues = _postprocess_i914_part4_consistency(
            targets, results_by_id, state.evidence_by_id,
            detention_facts=shared_detention_facts,
            classified_events=shared_classified_events,
        )
        _postprocess_i914_part4_table_completion(
            targets, results_by_id, state.evidence_by_id, answers_for_pp,
            detention_facts=shared_detention_facts,
        )
        missing_p9 = _validate_part9_completeness(
            targets, results_by_id, answers_for_pp,
        )
        if missing_p9:
            generated_p9 = _auto_generate_missing_part9_entries(
                missing_p9, targets, results_by_id, state.evidence_by_id, answers_for_pp,
                detention_facts=shared_detention_facts,
                classified_events=shared_classified_events,
            )
            if generated_p9:
                generated_results = _build_results_from_answers(
                    targets,
                    answers_for_pp,
                    pdf_fields=list(state.pdf_fields_result.get("fields", []) or []),
                )
                for target in targets:
                    if _clean_text(target.get("questionnaire_item_id")).lower() != "p9_entries":
                        continue
                    field_id = _clean_text(target.get("id"))
                    if field_id and field_id in generated_results:
                        results_by_id[field_id] = dict(generated_results[field_id])
                log.warning(
                    "Form filling job %s: auto-generated %d missing Part 9 entries",
                    job_id[:8], len(generated_p9),
                )
        _postprocess_i914_forced_pdf_values(targets, results_by_id)
        category_issues = _validate_i914_category_consistency(
            targets,
            results_by_id,
            answers_for_pp,
            state.evidence_by_id,
            classified_events=shared_classified_events,
        )
        review_issues = _collect_i914_result_review_issues(targets, results_by_id, answers_for_pp)
        for issue in consistency_issues:
            review_issues.append(issue["message"])
        for issue in category_issues:
            if issue.get("severity") in {"review", "downgrade"}:
                review_issues.append(issue["message"])
        review_issues = list(dict.fromkeys(review_issues))
        if review_issues:
            if _i914_manual_review_bypass_enabled():
                log.warning(
                    "Form filling job %s: I914_BYPASS_MANUAL_REVIEW is enabled. "
                    "Proceeding despite manual review issues: %s",
                    job_id[:8],
                    review_issues,
                )
            else:
                raise ReviewRequiredError(
                    "Manual review required before finalizing the I-914:\n"
                    + "\n".join(f"- {issue}" for issue in review_issues)
                )

    field_rows = _persist_extraction_results(
        db,
        job,
        results_by_id=results_by_id,
    )

    _persist_job_state(db, job, form_filling_jobs.mark_running(job_id, phase="writing_pdf"))
    if _clean_text(state.pdf_fields_result.get("mode")) == "acroform":
        field_value_map = _build_pdf_value_map(field_rows)
        state.write_result = fill_acroform_fields(
            job.original_pdf_path,
            field_value_map,
            output_path=build_generated_form_output_path(db, job),
        )
    else:
        overlay_payload = _build_overlay_payload(
            list(state.pdf_fields_result.get("fields", []) or []),
            field_rows,
        )
        state.write_result = fill_overlay_fields(
            job.original_pdf_path,
            overlay_payload,
            output_path=build_generated_form_output_path(db, job),
        )

    written_count = int(state.write_result.get("written_count") or 0)
    skipped_write_fields = list(state.write_result.get("skipped_fields") or [])
    job.filled_pdf_path = _clean_text(state.write_result.get("output_path"))
    _apply_i914_lea_agency_label_overlay(
        job.filled_pdf_path,
        answers_for_pp,
        resolved_form_type,
    )
    job.filled_count = filled_count
    _persist_job_state(
        db,
        job,
        form_filling_jobs.update_writing_progress(
            job_id,
            written_fields=written_count,
            filled_pdf_path=job.filled_pdf_path,
            filled_count=filled_count,
            phase="writing_pdf",
        ),
    )

    if skipped_write_fields:
        log.warning(
            "Form filling job %s skipped malformed choice fields: %s",
            job_id[:8],
            ", ".join(skipped_write_fields),
        )

    try:
        state.imported_page_count = _import_generated_pdf_pages(db, job)
    except Exception:
        log.exception(
            "Could not import generated PDF pages for form filling job %s",
            job_id[:8],
        )

    _persist_job_state(db, job, form_filling_jobs.mark_completed(job_id, phase="completed"))

    tracker_summary = compact_token_summary(tracker.get_summary())
    evidence_hit_count = sum(
        1
        for bundle in state.evidence_by_id.values()
        if isinstance(bundle, Mapping) and _evidence_bundle_has_content(bundle)
    )
    _audit_job(
        db,
        case_id=job.case_id,
        action="form_filling_completed",
        job_id=job.id,
        details={
            "form_type": job.form_type,
            "case_preparation": state.preparation_result,
            "field_count": job.field_count,
            "matched_count": int(state.mapping_result.get("matched_count") or 0),
            "unmatched_count": int(state.mapping_result.get("unmatched_count") or 0),
            "filled_count": filled_count,
            "evidence_fields_with_hits": evidence_hit_count,
            "detection": state.detection_result,
            "pdf_mode": state.pdf_fields_result.get("mode"),
            "written_count": written_count,
            "imported_page_count": state.imported_page_count,
            "missing_fields": list(state.write_result.get("missing_fields") or []),
            "skipped_fields": skipped_write_fields,
            "token_summary": tracker_summary,
            "extraction_error_count": state.extraction_error_count,
        },
    )
    log_token_summary(tracker, label=f"Form filling {job_id[:8]}", logger=log)


def run_form_filling_job(job_id: str) -> None:
    """Run the end-to-end form filling pipeline in the background."""
    db = SessionLocal()
    tracker = create_token_tracker(label=f"form-fill-{job_id[:8]}")
    state = FormFillingExecutionState()

    try:
        job = db.query(FormFillingJob).filter(FormFillingJob.id == job_id).first()
        if not job:
            return

        _run_form_filling_job_pipeline(
            db,
            job,
            job_id=job_id,
            tracker=tracker,
            state=state,
        )
    except Exception as exc:
        _record_form_filling_job_failure(db, job_id=job_id, exc=exc, state=state)
    finally:
        db.close()