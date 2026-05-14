"""Identify questionnaire form types and map PDF fields to questionnaire IDs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from ..utils.text import clean_text as _clean_text

SEED_DATA_DIR = Path(__file__).resolve().parent.parent / "seed_data"
QUESTIONNAIRES_DIR = SEED_DATA_DIR / "questions"
FORM_CODE_RE = re.compile(r"\b(?:form\s+)?(i[\s-]?\d{2,4}[a-z]?)\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "with",
}

DEFAULT_FIELD_MATCH_MIN_SCORE = 0.35
DEFAULT_FIELD_MATCH_CANDIDATE_MIN_SCORE = 0.18
LOW_COVERAGE_RATIO_THRESHOLD = 0.30
FIELD_MATCH_AMBIGUOUS_MARGIN = 0.08
FIELD_MATCH_SECOND_PASS_MARGIN = 0.12
FIELD_MATCH_SECOND_PASS_WINDOW = 0.12
FIELD_MATCH_SECOND_PASS_MAX_CANDIDATES = 8
QC_HINT_MIN_SCORE = 0.42
QC_HINT_AMBIGUOUS_MARGIN = 0.05
FIELD_MATCH_TOKEN_OVERLAP_STEP = 0.10
FIELD_MATCH_TOKEN_OVERLAP_MAX_BONUS = 0.45
FIELD_MATCH_TOKEN_COVERAGE_WEIGHT = 0.20
FIELD_MATCH_LABEL_PHRASE_BONUS = 0.20
SECOND_PASS_EXACT_LABEL_MATCH_BONUS = 0.10
SECOND_PASS_HIGH_LABEL_OVERLAP_THRESHOLD = 0.75
FIELD_MATCH_MEDIUM_CONFIDENCE_THRESHOLD = 0.60
PART_NUMBER_RE = re.compile(r"\bpart\s+([0-9]+[a-z]?)\b", re.IGNORECASE)
NUMERIC_CODE_RANGE_RE = re.compile(r"(?:(?P<prefix>\d+)\.)?(?P<start>\d+)-(?:(?P<prefix2>\d+)\.)?(?P<end>\d+)$")
PDF_FIELD_NAME_CODE_RE = re.compile(r"\b(?:dq|q)(\d+[a-z]?)\b", re.IGNORECASE)
PDF_INLINE_CODE_RE = re.compile(
    r"(?<![a-z0-9])(\d{1,2}(?:\.\d{1,2})?(?:\.[a-z]|[a-z])?)(?=[.)](?:\s|$))",
    re.IGNORECASE,
)
PDF_OPTION_ACTION_RE = re.compile(r"(?:select|check this box for)\s+([a-z0-9./ -]+?)(?:\.\s*$|$)", re.IGNORECASE)


@dataclass(frozen=True)
class QuestionnaireFieldDefinition:
    definition_id: str
    canonical_questionnaire_id: str
    form_type: str
    page_number: int
    responsible_party: str
    item_id: str
    item_code: str
    item_type: str
    section: str
    form_text: str
    label: str
    field_id: str | None
    option_value: str | None
    option_label: str | None
    source_file: str
    field_type_hint: str
    default_value: Any | None
    force_default: bool
    qc_description: str
    qc_where_to_verify: str
    search_text: str
    tokens: frozenset[str]


@dataclass(frozen=True)
class QCQuestionHint:
    form_type: str
    question_code: str
    top_part_numbers: frozenset[str]
    path_codes: tuple[str, ...]
    path_names: tuple[str, ...]
    description: str
    where_to_verify: str
    code_variants: frozenset[str]
    search_text: str
    tokens: frozenset[str]


from .form_registry import compact_form_type as _compact_form_code  # noqa: E402,F401
from .form_registry import normalize_form_type as _normalize_canonical_form_type  # noqa: E402


def _normalize_form_code(raw: str) -> str:
    """Thin str-returning wrapper around the canonical normalizer."""
    return _normalize_canonical_form_type(raw) or ""


def _normalize_text(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(text).lower()).strip()


def _tokenize(text: Any) -> set[str]:
    return {
        token
        for token in TOKEN_RE.findall(_normalize_text(text))
        if token and token not in STOPWORDS
    }


def _field_type_hint(question_type: str) -> str:
    lowered = _clean_text(question_type).lower()
    if lowered in {"checkbox", "yes_no", "single_choice", "radio", "button"}:
        return "button"
    if lowered in {"select", "choice", "combobox", "listbox"}:
        return "choice"
    if lowered == "signature":
        return "signature"
    return "text"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def available_form_types() -> list[str]:
    forms: set[str] = set()

    for path in SEED_DATA_DIR.glob("*_form.json"):
        match = re.fullmatch(r"([a-z0-9]+)_form\.json", path.name, re.IGNORECASE)
        if match:
            forms.add(_normalize_form_code(match.group(1)))

    for path in QUESTIONNAIRES_DIR.glob("*_form_*.json"):
        match = re.fullmatch(r"([a-z0-9]+)_form_[a-z0-9_]+\.json", path.name, re.IGNORECASE)
        if match:
            forms.add(_normalize_form_code(match.group(1)))

    return sorted(form_code for form_code in forms if form_code)


def _annotate_page(page_data: Mapping[str, Any], *, source_file: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in page_data.get("items", []) or []:
        annotated_item = dict(item)
        annotated_item["__source_file"] = source_file
        items.append(annotated_item)

    return {
        "page": page_data.get("page"),
        "items": items,
        "excluded_sections": list(page_data.get("excluded_sections", []) or []),
    }


def load_questionnaire_definition(form_type: str) -> dict[str, Any]:
    """
    Load the questionnaire definition for a form.

    Prefers a merged `seed_data/<form>_form.json` file when present. Otherwise
    it merges the split `questions/<form>_form_*.json` files.
    """
    canonical_form = _normalize_form_code(form_type)
    compact_form = canonical_form.replace("-", "")
    if not canonical_form:
        raise ValueError("Invalid form type.")

    merged_path = SEED_DATA_DIR / f"{compact_form}_form.json"
    if merged_path.exists():
        data = _read_json(merged_path)
        raw_pages = data if isinstance(data, list) else (data.get("pages", []) or [])
        pages = [
            _annotate_page(page, source_file=merged_path.name)
            for page in raw_pages
        ]
        return {
            "form": canonical_form.upper(),
            "pages": pages,
            "source_files": [merged_path.name],
        }

    split_paths = sorted(QUESTIONNAIRES_DIR.glob(f"{compact_form}_form_*.json"))
    if not split_paths:
        raise ValueError(f"No questionnaire JSON found for form type {canonical_form}.")

    page_map: dict[int, dict[str, Any]] = {}
    source_files: list[str] = []

    for path in split_paths:
        data = _read_json(path)
        source_files.append(path.name)
        raw_pages = data if isinstance(data, list) else (data.get("pages", []) or [])
        for page in raw_pages:
            page_number = int(page.get("page") or 0)
            merged_page = page_map.setdefault(
                page_number,
                {"page": page_number, "items": [], "excluded_sections": []},
            )
            annotated = _annotate_page(page, source_file=path.name)
            merged_page["items"].extend(annotated["items"])
            merged_page["excluded_sections"].extend(annotated["excluded_sections"])

    pages = [page_map[key] for key in sorted(page_map)]
    return {
        "form": canonical_form.upper(),
        "pages": pages,
        "source_files": source_files,
    }


def _normalize_options(item_type: str, raw_options: Any) -> list[dict[str, str]]:
    if item_type == "yes_no" and not raw_options:
        return [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]

    if not isinstance(raw_options, list):
        return []

    options: list[dict[str, str]] = []
    for option in raw_options:
        if isinstance(option, Mapping):
            value = _clean_text(option.get("value") or option.get("id") or option.get("label"))
            label = _clean_text(option.get("label") or option.get("value") or option.get("id"))
        else:
            value = _clean_text(option)
            label = value
        if value or label:
            options.append({"value": value or label, "label": label or value})
    return options


def _load_qc_template_bundle(form_type: str) -> dict[str, Any]:
    """Dispatch QC template loading via the central form registry.

    Replaces the previous chain of `if canonical_form == "i-XXX"` branches: the
    module to import and the symbol to read come from `FormSpec`. Returns an
    empty dict for unregistered forms (legacy callers expect this).
    """
    import importlib

    from .form_registry import get_form_spec_or_none

    spec = get_form_spec_or_none(form_type)
    if spec is None:
        return {}

    module = importlib.import_module(f"..seed_data.{spec.qc_template_module}", package=__package__)
    template = getattr(module, spec.qc_template_symbol, None)
    if template is None:
        return {}
    return dict(template)


def _extract_part_numbers(*values: Any) -> set[str]:
    numbers: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        for match in PART_NUMBER_RE.finditer(text):
            numbers.add(match.group(1).lower())
    return numbers


def _normalize_code_text(value: Any) -> str:
    normalized = _clean_text(value).lower()
    if not normalized:
        return ""
    normalized = normalized.replace("item number", "")
    normalized = normalized.replace("item", "")
    normalized = normalized.replace("number", "")
    normalized = normalized.replace(" ", "")
    normalized = normalized.replace("_", ".")
    normalized = re.sub(r"[^a-z0-9.\-]+", "", normalized)
    normalized = re.sub(r"\.+", ".", normalized).strip(".-")
    return normalized


def _expand_numeric_code_range_variants(
    normalized_code: str,
    top_part_numbers: set[str],
) -> set[str]:
    match = NUMERIC_CODE_RANGE_RE.fullmatch(normalized_code)
    if not match:
        return set()

    prefix = match.group("prefix") or match.group("prefix2") or next(iter(top_part_numbers), "")
    start = int(match.group("start"))
    end = int(match.group("end"))
    if end < start or end - start > 12:
        return set()

    variants: set[str] = set()
    for value in range(start, end + 1):
        variants.add(str(value))
        if prefix:
            variants.add(f"{prefix}.{value}")
    return variants


def _code_variants(value: Any, top_part_numbers: set[str] | None = None) -> set[str]:
    normalized = _normalize_code_text(value)
    if not normalized:
        return set()

    resolved_top_part_numbers = set(top_part_numbers or set())
    variants = {normalized}
    variants.update(_expand_numeric_code_range_variants(normalized, resolved_top_part_numbers))

    if "." in normalized:
        prefix, suffix = normalized.split(".", 1)
        if suffix:
            variants.add(suffix)
        if prefix:
            resolved_top_part_numbers.add(prefix)
    elif normalized and normalized != "-":
        for top_part_number in resolved_top_part_numbers:
            variants.add(f"{top_part_number}.{normalized}")

    dotted_variant = normalized.replace("-", ".")
    dashed_variant = normalized.replace(".", "-")
    if dotted_variant and dotted_variant != normalized:
        variants.add(dotted_variant)
    if dashed_variant and dashed_variant != normalized:
        variants.add(dashed_variant)

    return {variant.strip(".-") for variant in variants if variant.strip(".-")}


def _build_qc_question_hint(
    *,
    form_type: str,
    path_codes: tuple[str, ...],
    path_names: tuple[str, ...],
    question: Mapping[str, Any],
) -> QCQuestionHint | None:
    question_code = _clean_text(question.get("code"))
    description = _clean_text(question.get("description"))
    where_to_verify = _clean_text(question.get("where_to_verify"))
    if not question_code and not description and not where_to_verify:
        return None

    top_part_numbers = _extract_part_numbers(*path_codes, *path_names)
    search_text = " ".join(
        part
        for part in [
            " ".join(path_codes),
            " ".join(path_names),
            question_code,
            description,
            where_to_verify,
        ]
        if part
    )
    return QCQuestionHint(
        form_type=form_type,
        question_code=question_code,
        top_part_numbers=frozenset(top_part_numbers),
        path_codes=path_codes,
        path_names=path_names,
        description=description,
        where_to_verify=where_to_verify,
        code_variants=frozenset(_code_variants(question_code, top_part_numbers)),
        search_text=search_text,
        tokens=frozenset(_tokenize(search_text)),
    )


@lru_cache(maxsize=16)
def _qc_question_hints(form_type: str) -> tuple[QCQuestionHint, ...]:
    canonical_form = _normalize_form_code(form_type)
    bundle = _load_qc_template_bundle(canonical_form)
    if not bundle:
        return tuple()

    hints: list[QCQuestionHint] = []

    def walk(parts: Sequence[Mapping[str, Any]], *, path_codes: tuple[str, ...] = (), path_names: tuple[str, ...] = ()) -> None:
        for part in parts:
            current_codes = path_codes + ((_clean_text(part.get("code"))),)
            current_names = path_names + ((_clean_text(part.get("name"))),)
            for question in part.get("questions", []) or []:
                if not isinstance(question, Mapping):
                    continue
                hint = _build_qc_question_hint(
                    form_type=canonical_form,
                    path_codes=current_codes,
                    path_names=current_names,
                    question=question,
                )
                if hint is not None:
                    hints.append(hint)
            child_parts = part.get("subparts") or []
            if isinstance(child_parts, list):
                walk(child_parts, path_codes=current_codes, path_names=current_names)

    root_parts = bundle.get("parts") or []
    if isinstance(root_parts, list):
        walk(root_parts)
    return tuple(hints)


def _score_qc_hint_match(
    *,
    item_code: str,
    section: str,
    form_text: str,
    label: str,
    field_id: str | None,
    extra_text: str,
    hint: QCQuestionHint,
) -> float:
    context_text = " ".join(part for part in [section, form_text, label, field_id, extra_text] if part)
    context_tokens = _tokenize(context_text)
    if not context_tokens:
        return 0.0

    questionnaire_part_numbers = _extract_part_numbers(section)
    questionnaire_part_numbers.update({
        variant.split(".", 1)[0]
        for variant in _code_variants(item_code, questionnaire_part_numbers)
        if "." in variant and variant.split(".", 1)[0].isdigit()
    })
    questionnaire_code_variants = _code_variants(item_code, questionnaire_part_numbers)

    score = 0.0
    if questionnaire_part_numbers & set(hint.top_part_numbers):
        score += 0.14
    if questionnaire_code_variants & set(hint.code_variants):
        score += 0.34

    overlap = context_tokens & set(hint.tokens)
    score += min(0.30, 0.06 * len(overlap))
    score += (len(overlap) / max(1, len(context_tokens))) * 0.18

    normalized_form_text = _normalize_text(form_text)
    normalized_label = _normalize_text(label)
    normalized_hint_description = _normalize_text(hint.description)
    if normalized_form_text and normalized_hint_description:
        if normalized_form_text in normalized_hint_description or normalized_hint_description in normalized_form_text:
            score += 0.18
    if normalized_label and normalized_hint_description:
        if normalized_label in normalized_hint_description or normalized_hint_description in normalized_label:
            score += 0.12

    if field_id:
        field_tokens = _tokenize(field_id)
        if field_tokens and field_tokens.issubset(set(hint.tokens)):
            score += 0.08

    return round(min(1.0, score), 4)


def _resolve_qc_hint_for_questionnaire_field(
    *,
    form_type: str,
    item_code: str,
    section: str,
    form_text: str,
    label: str,
    field_id: str | None,
    extra_text: str,
) -> tuple[str, str]:
    scored_hints: list[tuple[QCQuestionHint, float]] = []
    for hint in _qc_question_hints(form_type):
        score = _score_qc_hint_match(
            item_code=item_code,
            section=section,
            form_text=form_text,
            label=label,
            field_id=field_id,
            extra_text=extra_text,
            hint=hint,
        )
        if score > 0:
            scored_hints.append((hint, score))

    if not scored_hints:
        return "", ""

    scored_hints.sort(key=lambda item: item[1], reverse=True)
    best_hint, best_score = scored_hints[0]
    runner_up_score = scored_hints[1][1] if len(scored_hints) > 1 else 0.0
    if best_score < QC_HINT_MIN_SCORE:
        return "", ""
    if runner_up_score > 0 and best_score - runner_up_score < QC_HINT_AMBIGUOUS_MARGIN and best_score < 0.70:
        return "", ""
    return best_hint.description, best_hint.where_to_verify


def _definition_from_parts(
    *,
    form_type: str,
    page_number: int,
    responsible_party: str,
    item_id: str,
    item_code: str,
    item_type: str,
    section: str,
    form_text: str,
    label: str,
    field_id: str | None,
    option_value: str | None,
    option_label: str | None,
    source_file: str,
    extra_text: str,
    default_value: Any | None = None,
    force_default: bool = False,
    qc_description: str = "",
    qc_where_to_verify: str = "",
) -> QuestionnaireFieldDefinition:
    canonical_questionnaire_id = f"{item_id}.{field_id}" if field_id else item_id
    definition_id = (
        f"{canonical_questionnaire_id}[{option_value}]"
        if option_value
        else canonical_questionnaire_id
    )
    search_text = " ".join(
        part
        for part in [
            section,
            form_text,
            label,
            item_id,
            field_id,
            item_code,
            responsible_party,
            option_label,
            option_value,
            extra_text,
            qc_description,
            qc_where_to_verify,
        ]
        if part
    )
    return QuestionnaireFieldDefinition(
        definition_id=definition_id,
        canonical_questionnaire_id=canonical_questionnaire_id,
        form_type=form_type,
        page_number=page_number,
        responsible_party=responsible_party,
        item_id=item_id,
        item_code=item_code,
        item_type=item_type,
        section=section,
        form_text=form_text,
        label=label,
        field_id=field_id,
        option_value=option_value,
        option_label=option_label,
        source_file=source_file,
        field_type_hint=_field_type_hint(item_type),
        default_value=default_value,
        force_default=force_default,
        qc_description=qc_description,
        qc_where_to_verify=qc_where_to_verify,
        search_text=search_text,
        tokens=frozenset(_tokenize(search_text)),
    )


@lru_cache(maxsize=16)
def _questionnaire_field_definitions(form_type: str) -> tuple[QuestionnaireFieldDefinition, ...]:
    canonical_form = _normalize_form_code(form_type)
    bundle = load_questionnaire_definition(canonical_form)
    definitions: list[QuestionnaireFieldDefinition] = []

    for page in bundle.get("pages", []) or []:
        page_number = int(page.get("page") or 0)
        for item in page.get("items", []) or []:
            item_id = _clean_text(item.get("id"))
            if not item_id:
                continue
            if bool(item.get("exclude_from_form_mapping")):
                continue

            item_code = _clean_text(item.get("code"))
            item_type = _clean_text(item.get("type")).lower()
            section = _clean_text(item.get("section"))
            form_text = _clean_text(item.get("form_text"))
            responsible_party = _clean_text(item.get("responsible_party"))
            source_file = _clean_text(item.get("__source_file"))
            extra_text = " ".join(
                _clean_text(value)
                for value in [
                    item.get("instruction"),
                    item.get("condition"),
                    " ".join(str(v) for v in item.get("visible_slots", []) or []),
                    " ".join(str(v) for v in item.get("also_validate_with", []) or []),
                ]
                if _clean_text(value)
            )

            fields = list(item.get("fields") or [])
            details_fields = list(item.get("details_fields") or [])
            field_entries = fields + details_fields
            if field_entries:
                for field in field_entries:
                    field_id = _clean_text(field.get("id"))
                    if not field_id:
                        continue
                    field_type = _clean_text(field.get("type") or item_type).lower()
                    label = _clean_text(field.get("label") or form_text)
                    field_extra_text = " ".join(
                        _clean_text(value)
                        for value in [
                            extra_text,
                            field.get("instruction"),
                            field.get("condition"),
                        ]
                        if _clean_text(value)
                    )
                    qc_description, qc_where_to_verify = _resolve_qc_hint_for_questionnaire_field(
                        form_type=canonical_form,
                        item_code=item_code,
                        section=section,
                        form_text=form_text,
                        label=label,
                        field_id=field_id,
                        extra_text=field_extra_text,
                    )

                    definitions.append(
                        _definition_from_parts(
                            form_type=canonical_form,
                            page_number=page_number,
                            responsible_party=responsible_party,
                            item_id=item_id,
                            item_code=item_code,
                            item_type=field_type,
                            section=section,
                            form_text=form_text,
                            label=label,
                            field_id=field_id,
                            option_value=None,
                            option_label=None,
                            source_file=source_file,
                            extra_text=field_extra_text,
                            default_value=field.get("default_value"),
                            force_default=bool(field.get("force_default")),
                            qc_description=qc_description,
                            qc_where_to_verify=qc_where_to_verify,
                        )
                    )

                    if field_type in {"yes_no", "single_choice", "select"}:
                        for option in _normalize_options(field_type, field.get("options")):
                            definitions.append(
                                _definition_from_parts(
                                    form_type=canonical_form,
                                    page_number=page_number,
                                    responsible_party=responsible_party,
                                    item_id=item_id,
                                    item_code=item_code,
                                    item_type=field_type,
                                    section=section,
                                    form_text=form_text,
                                    label=label,
                                    field_id=field_id,
                                    option_value=option["value"],
                                    option_label=option["label"],
                                    source_file=source_file,
                                    extra_text=field_extra_text,
                                    default_value=field.get("default_value"),
                                    force_default=bool(field.get("force_default")),
                                    qc_description=qc_description,
                                    qc_where_to_verify=qc_where_to_verify,
                                )
                            )
                if fields and item_type not in {"yes_no", "single_choice"}:
                    continue

            label = form_text or section or item_id
            qc_description, qc_where_to_verify = _resolve_qc_hint_for_questionnaire_field(
                form_type=canonical_form,
                item_code=item_code,
                section=section,
                form_text=form_text,
                label=label,
                field_id=None,
                extra_text=extra_text,
            )
            definitions.append(
                _definition_from_parts(
                    form_type=canonical_form,
                    page_number=page_number,
                    responsible_party=responsible_party,
                    item_id=item_id,
                    item_code=item_code,
                    item_type=item_type,
                    section=section,
                    form_text=form_text,
                    label=label,
                    field_id=None,
                    option_value=None,
                    option_label=None,
                    source_file=source_file,
                    extra_text=extra_text,
                    default_value=item.get("default_value"),
                    force_default=bool(item.get("force_default")),
                    qc_description=qc_description,
                    qc_where_to_verify=qc_where_to_verify,
                )
            )

            if item_type in {"yes_no", "single_choice"}:
                for option in _normalize_options(item_type, item.get("options")):
                    definitions.append(
                        _definition_from_parts(
                            form_type=canonical_form,
                            page_number=page_number,
                            responsible_party=responsible_party,
                            item_id=item_id,
                            item_code=item_code,
                            item_type=item_type,
                            section=section,
                            form_text=form_text,
                            label=label,
                            field_id=None,
                            option_value=option["value"],
                            option_label=option["label"],
                            source_file=source_file,
                            extra_text=extra_text,
                            default_value=item.get("default_value"),
                            force_default=bool(item.get("force_default")),
                            qc_description=qc_description,
                            qc_where_to_verify=qc_where_to_verify,
                        )
                    )

    return tuple(definitions)


def list_questionnaire_field_definitions(form_type: str) -> list[dict[str, Any]]:
    return [asdict(definition) for definition in _questionnaire_field_definitions(form_type)]


@lru_cache(maxsize=16)
def get_questionnaire_field_metadata_lookup(form_type: str) -> dict[str, dict[str, Any]]:
    canonical_form = _normalize_form_code(form_type)
    bundle = load_questionnaire_definition(canonical_form)
    metadata_by_id: dict[str, dict[str, Any]] = {}

    for page in bundle.get("pages", []) or []:
        page_number = int(page.get("page") or 0)
        for item in page.get("items", []) or []:
            item_id = _clean_text(item.get("id"))
            if not item_id:
                continue
            if bool(item.get("exclude_from_form_mapping")):
                continue

            item_type = _clean_text(item.get("type")).lower()
            section = _clean_text(item.get("section"))
            form_text = _clean_text(item.get("form_text"))
            responsible_party = _clean_text(item.get("responsible_party"))
            item_instruction = _clean_text(item.get("instruction"))
            item_condition = _clean_text(item.get("condition"))
            item_optional = bool(item.get("optional"))
            field_entries = list(item.get("fields") or []) + list(item.get("details_fields") or [])

            if field_entries:
                for field in field_entries:
                    field_id = _clean_text(field.get("id"))
                    if not field_id:
                        continue
                    field_type = _clean_text(field.get("type") or item_type).lower()
                    canonical_questionnaire_id = f"{item_id}.{field_id}"
                    metadata_by_id[canonical_questionnaire_id] = {
                        "canonical_questionnaire_id": canonical_questionnaire_id,
                        "item_id": item_id,
                        "field_id": field_id,
                        "page_number": page_number,
                        "section": section,
                        "form_text": form_text,
                        "label": _clean_text(field.get("label") or form_text or section or field_id),
                        "responsible_party": responsible_party,
                        "field_type": field_type,
                        "instruction": _clean_text(field.get("instruction") or item_instruction),
                        "condition": _clean_text(field.get("condition") or item_condition),
                        "optional": bool(field.get("optional", item_optional)),
                        "questionnaire_options": _normalize_options(field_type, field.get("options")),
                        "default_value": field.get("default_value"),
                        "force_default": bool(field.get("force_default")),
                        "qc_description": "",
                        "qc_where_to_verify": "",
                    }
                continue

            canonical_questionnaire_id = item_id
            metadata_by_id[canonical_questionnaire_id] = {
                "canonical_questionnaire_id": canonical_questionnaire_id,
                "item_id": item_id,
                "field_id": None,
                "page_number": page_number,
                "section": section,
                "form_text": form_text,
                "label": form_text or section or item_id,
                "responsible_party": responsible_party,
                "field_type": item_type,
                "instruction": item_instruction,
                "condition": item_condition,
                "optional": item_optional,
                "questionnaire_options": _normalize_options(item_type, item.get("options")),
                "default_value": item.get("default_value"),
                "force_default": bool(item.get("force_default")),
                "qc_description": "",
                "qc_where_to_verify": "",
            }

    definitions_by_id = {definition.canonical_questionnaire_id: definition for definition in _questionnaire_field_definitions(canonical_form)}
    for canonical_id, metadata in metadata_by_id.items():
        definition = definitions_by_id.get(canonical_id)
        if not definition:
            continue
        metadata["qc_description"] = definition.qc_description
        metadata["qc_where_to_verify"] = definition.qc_where_to_verify

    return metadata_by_id


@lru_cache(maxsize=16)
def _form_signature(form_type: str) -> dict[str, Any]:
    bundle = load_questionnaire_definition(form_type)
    page_one = next(
        (page for page in bundle.get("pages", []) or [] if int(page.get("page") or 0) == 1),
        None,
    )

    phrases: set[str] = {_normalize_text(bundle.get("form", form_type))}
    if page_one:
        for item in page_one.get("items", []) or []:
            section = _normalize_text(item.get("section"))
            form_text = _normalize_text(item.get("form_text"))
            if section:
                phrases.add(section)
            if form_text:
                phrases.add(form_text)

    tokens: set[str] = set()
    for phrase in phrases:
        tokens.update(_tokenize(phrase))

    return {"phrases": tuple(sorted(phrases)), "tokens": frozenset(tokens)}


def identify_form_type(
    first_page_text: str,
    *,
    candidate_form_types: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Identify the form type from the first page text.

    The heuristic first looks for explicit USCIS form codes, then falls back to
    page-one questionnaire signatures derived from the configured JSON files.
    """
    text = _clean_text(first_page_text)
    forms = [
        _normalize_form_code(form_type)
        for form_type in (candidate_form_types or available_form_types())
        if _normalize_form_code(form_type)
    ]
    if not text:
        return {
            "form_type": None,
            "detection_source": "insufficient-text",
            "score": 0.0,
            "reason": "No readable first-page text was available for form detection.",
        }

    explicit_counts: dict[str, int] = {}
    for raw_form_code in FORM_CODE_RE.findall(text):
        normalized = _normalize_form_code(raw_form_code)
        if normalized in forms:
            explicit_counts[normalized] = explicit_counts.get(normalized, 0) + 1

    if explicit_counts:
        best_form = max(explicit_counts.items(), key=lambda item: (item[1], item[0]))[0]
        return {
            "form_type": best_form,
            "detection_source": "explicit-form-code",
            "score": 1.0,
            "reason": f"Detected explicit USCIS form code {best_form.upper()} in the first page text.",
        }

    normalized_text = _normalize_text(text)
    text_tokens = _tokenize(text)
    best_result = {
        "form_type": None,
        "detection_source": "questionnaire-heuristic",
        "score": 0.0,
        "reason": "No questionnaire signature matched the first-page text.",
    }

    for form_type in forms:
        signature = _form_signature(form_type)
        phrase_hits = 0
        phrase_score = 0.0
        best_phrase = ""

        for phrase in signature["phrases"]:
            if not phrase or len(phrase.split()) < 2:
                continue
            if phrase in normalized_text:
                phrase_hits += 1
                hit_score = min(0.4, 0.06 * len(phrase.split()))
                phrase_score += hit_score
                if len(phrase) > len(best_phrase):
                    best_phrase = phrase

        overlap_count = len(text_tokens & set(signature["tokens"]))
        token_score = overlap_count / max(1, len(signature["tokens"]))
        total_score = round(min(1.0, phrase_score + token_score), 4)

        if total_score > best_result["score"]:
            reason = (
                f"Matched questionnaire signature phrase '{best_phrase}'."
                if best_phrase
                else "Matched questionnaire tokens from the configured JSON definition."
            )
            best_result = {
                "form_type": form_type,
                "detection_source": "questionnaire-heuristic",
                "score": total_score,
                "reason": reason,
            }

    if best_result["score"] < 0.15:
        return {
            "form_type": None,
            "detection_source": "questionnaire-heuristic",
            "score": round(float(best_result["score"]), 4),
            "reason": "The first-page text did not match any configured questionnaire strongly enough.",
        }

    return best_result


def identify_form_type_from_pdf(
    pdf_path: str | Path,
    *,
    max_pages: int = 1,
    candidate_form_types: Sequence[str] | None = None,
) -> dict[str, Any]:
    from .pdf_form_service import extract_pdf_text

    text = extract_pdf_text(pdf_path, max_pages=max_pages)
    result = identify_form_type(text, candidate_form_types=candidate_form_types)
    result["sample_text"] = text[:2000]
    return result


def _pdf_field_tokens(pdf_field: Mapping[str, Any]) -> tuple[str, set[str]]:
    context_parts = [
        pdf_field.get("field_name"),
        pdf_field.get("field_label"),
        pdf_field.get("nearby_text"),
        " ".join(str(v) for v in pdf_field.get("button_values", []) or []),
        " ".join(str(v) for v in pdf_field.get("choice_values", []) or []),
    ]
    normalized_context = _normalize_text(" ".join(_clean_text(part) for part in context_parts if _clean_text(part)))
    return normalized_context, _tokenize(normalized_context)


def _context_mentions(context: str, *phrases: str) -> bool:
    normalized_context = _normalize_text(context)
    return any(_normalize_text(phrase) in normalized_context for phrase in phrases if _normalize_text(phrase))


def _normalized_choice_values(values: Any) -> set[str]:
    if not isinstance(values, (list, tuple, set)):
        return set()
    normalized: set[str] = set()
    for value in values:
        cleaned = _normalize_text(value)
        if cleaned:
            normalized.add(cleaned)
    return normalized


_USCIS_ABBREVIATION_EXPANSIONS: dict[str, str] = {
    "apt": "apartment",
    "ste": "suite",
    "flr": "floor",
    "apartment": "apt",
    "suite": "ste",
    "floor": "flr",
}


def _label_phrase_variants(label: Any) -> set[str]:
    raw_label = _clean_text(label)
    if not raw_label:
        return set()

    variants = {
        _normalize_text(raw_label),
        _normalize_text(re.sub(r"\([^)]*\)", "", raw_label)),
    }
    if " - " in raw_label:
        for part in raw_label.split(" - "):
            variants.add(_normalize_text(part))
    expanded: set[str] = set()
    for variant in variants:
        if variant:
            expanded.add(variant)
            if variant in _USCIS_ABBREVIATION_EXPANSIONS:
                expanded.add(_USCIS_ABBREVIATION_EXPANSIONS[variant])
    return expanded


def _pdf_field_code_variants(pdf_field: Mapping[str, Any]) -> set[str]:
    raw_values = [
        pdf_field.get("field_name"),
        pdf_field.get("field_label"),
        pdf_field.get("nearby_text"),
    ]
    top_part_numbers = _extract_part_numbers(*raw_values)
    variants: set[str] = set()

    for value in raw_values:
        text = _clean_text(value)
        if not text:
            continue
        for match in PDF_FIELD_NAME_CODE_RE.finditer(text):
            variants.update(_code_variants(match.group(1), top_part_numbers))

        text_without_part_refs = PART_NUMBER_RE.sub(" ", text)
        for match in PDF_INLINE_CODE_RE.finditer(text_without_part_refs):
            candidate = _clean_text(match.group(1))
            if not candidate:
                continue
            if candidate.isdigit() and int(candidate) > 40:
                continue
            variants.update(_code_variants(candidate, top_part_numbers))

    return variants


def _definition_code_variants(definition: QuestionnaireFieldDefinition) -> set[str]:
    questionnaire_part_numbers = _extract_part_numbers(definition.section)
    questionnaire_part_numbers.update(
        {
            variant.split(".", 1)[0]
            for variant in _code_variants(definition.item_code, questionnaire_part_numbers)
            if "." in variant and variant.split(".", 1)[0].isdigit()
        }
    )
    return _code_variants(definition.item_code, questionnaire_part_numbers)


def _explicit_pdf_option_hint(pdf_field: Mapping[str, Any]) -> str:
    field_label = _clean_text(pdf_field.get("field_label"))
    hint = ""
    for match in PDF_OPTION_ACTION_RE.finditer(field_label):
        hint = _normalize_text(match.group(1))
    return hint


def _explicit_prompt_score(
    pdf_field: Mapping[str, Any],
    definition: QuestionnaireFieldDefinition,
) -> float:
    field_label = _normalize_text(pdf_field.get("field_label"))
    field_name_tokens = _tokenize(pdf_field.get("field_name"))
    score = 0.0

    label_variants = _label_phrase_variants(definition.label)
    label_tokens = _tokenize(definition.label)
    field_label_tokens = _tokenize(field_label)
    leading_label_token = next(
        (
            token
            for token in TOKEN_RE.findall(_normalize_text(definition.label))
            if token and token not in STOPWORDS
        ),
        "",
    )
    matched_label_variants = [
        variant
        for variant in label_variants
        if f"enter {variant}" in field_label or f"select {variant}" in field_label
    ]
    if matched_label_variants:
        longest_variant = max(matched_label_variants, key=lambda variant: len(variant.split()))
        score += 1.0 if len(longest_variant.split()) >= 3 else 0.45
    elif (
        "enter" in field_label_tokens
        and len(label_tokens) >= 3
        and _token_overlap_ratio(field_label_tokens, label_tokens) >= 0.8
        and (not leading_label_token or leading_label_token in field_label_tokens)
    ):
        score += 0.7
    elif label_variants and any(len(variant.split()) > 1 and variant in field_label for variant in label_variants):
        score += 0.4

    if definition.option_label:
        option_variants = _label_phrase_variants(definition.option_label or definition.option_value)
        explicit_option_hint = _explicit_pdf_option_hint(pdf_field)
        if explicit_option_hint and option_variants:
            if explicit_option_hint in option_variants:
                score += 1.0
            else:
                score -= 0.4
        elif option_variants and any(set(variant.split()).issubset(field_name_tokens) for variant in option_variants):
            score += 0.6

    return score


def _token_overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def _phrase_matches_context(phrase: str, text: str, values: set[str]) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    if normalized_phrase in text:
        return True
    return any(
        normalized_phrase == value
        or normalized_phrase in value
        or value in normalized_phrase
        for value in values
        if value
    )


def _score_context_specificity(context: str, definition: QuestionnaireFieldDefinition) -> float:
    score = 0.0
    normalized_form_text = _normalize_text(definition.form_text)
    normalized_section = _normalize_text(definition.section)
    combined_target_context = " ".join(part for part in [normalized_form_text, normalized_section] if part)

    if _context_mentions(context, "other names used", "other name", "alias", "maiden"):
        if _context_mentions(combined_target_context, "other names used", "other name", "alias", "maiden"):
            score += 0.18
        elif definition.field_id in {"family_name", "given_name", "middle_name"}:
            score -= 0.2

    if _context_mentions(context, "full legal name", "legal name"):
        if _context_mentions(combined_target_context, "full legal name", "legal name"):
            score += 0.14
        elif _context_mentions(combined_target_context, "other names used", "other name"):
            score -= 0.12

    return score


def _is_ambiguous_best_match(
    pdf_field: Mapping[str, Any],
    best_definition: QuestionnaireFieldDefinition,
    best_score: float,
    runner_up_definition: QuestionnaireFieldDefinition | None,
    runner_up_score: float,
    *,
    min_margin: float = 0.08,
) -> bool:
    if runner_up_definition is None or runner_up_score <= 0:
        return False
    if best_definition.canonical_questionnaire_id == runner_up_definition.canonical_questionnaire_id:
        return False
    if best_score - runner_up_score >= min_margin:
        return False

    context, _ = _pdf_field_tokens(pdf_field)
    field_label = _normalize_text(pdf_field.get("field_label"))
    best_label = _normalize_text(best_definition.label)
    runner_up_label = _normalize_text(runner_up_definition.label)
    best_form_text = _normalize_text(best_definition.form_text)
    runner_up_form_text = _normalize_text(runner_up_definition.form_text)
    competing_labels_present = bool(
        best_label
        and runner_up_label
        and best_label in context
        and runner_up_label in context
    )

    # When the PDF explicitly mentions one address block ("Physical Address"
    # vs "Safe Mailing Address"), prefer that context instead of treating the
    # two matches as equivalent only because they share a section.
    if best_form_text and runner_up_form_text and best_form_text != runner_up_form_text:
        best_form_present = best_form_text in context
        runner_up_form_present = runner_up_form_text in context
        if best_form_present and not runner_up_form_present:
            return False
        if runner_up_form_present and not best_form_present:
            return True

    if field_label and best_label and runner_up_label and best_label != runner_up_label:
        best_label_present = best_label in field_label
        runner_up_label_present = runner_up_label in field_label
        if best_label_present and not runner_up_label_present:
            return False
        if runner_up_label_present and not best_label_present:
            return True

    best_prompt_score = _explicit_prompt_score(pdf_field, best_definition)
    runner_up_prompt_score = _explicit_prompt_score(pdf_field, runner_up_definition)
    if best_prompt_score - runner_up_prompt_score >= 0.4:
        return False
    if runner_up_prompt_score - best_prompt_score >= 0.4:
        return True

    same_scope = bool(
        best_definition.item_id == runner_up_definition.item_id
        or (
            _normalize_text(best_definition.form_text)
            and _normalize_text(best_definition.form_text)
            == _normalize_text(runner_up_definition.form_text)
        )
        or (
            _normalize_text(best_definition.section)
            and _normalize_text(best_definition.section)
            == _normalize_text(runner_up_definition.section)
        )
    )
    conflicting_field_ids = bool(
        best_definition.field_id
        and runner_up_definition.field_id
        and best_definition.field_id != runner_up_definition.field_id
    )
    return (same_scope and conflicting_field_ids) or competing_labels_present


_DOC_AI_HINT_BONUS = 0.10


def _doc_ai_hint_phrases(definition: QuestionnaireFieldDefinition) -> tuple[str, ...]:
    """Return form-specific Document AI alias phrases for `definition.item_id`.

    Hints live in `FormSpec.doc_ai_hints` and capture the most common ways the
    PDF text or Document AI label refers to a canonical questionnaire item
    (e.g. "alien no" -> `p2_a_number`). When any hint phrase appears in the
    Document-AI-extracted context, the match score gets a small additive boost.
    """
    item_id = (getattr(definition, "item_id", "") or "").strip().lower()
    form_type = (getattr(definition, "form_type", "") or "").strip().lower()
    if not item_id or not form_type:
        return ()
    from .form_registry import get_form_spec_or_none

    spec = get_form_spec_or_none(form_type)
    if spec is None:
        return ()
    return tuple(phrase.lower() for phrase in spec.doc_ai_hints.get(item_id, ()))


def _score_field_match(
    pdf_field: Mapping[str, Any],
    definition: QuestionnaireFieldDefinition,
    *,
    context: str | None = None,
    pdf_tokens: set[str] | None = None,
) -> float:
    if context is None or pdf_tokens is None:
        context, pdf_tokens = _pdf_field_tokens(pdf_field)
    if not context and not pdf_tokens:
        return 0.0

    overlap = pdf_tokens & set(definition.tokens)
    score = 0.0
    score += min(FIELD_MATCH_TOKEN_OVERLAP_MAX_BONUS, FIELD_MATCH_TOKEN_OVERLAP_STEP * len(overlap))
    score += (len(overlap) / max(1, len(definition.tokens))) * FIELD_MATCH_TOKEN_COVERAGE_WEIGHT

    # Document AI alias boost (when configured for the form's item).
    for phrase in _doc_ai_hint_phrases(definition):
        if phrase and phrase in context:
            score += _DOC_AI_HINT_BONUS
            break

    label_phrase = _normalize_text(definition.label)
    label_variants = _label_phrase_variants(definition.label)
    if label_phrase and label_phrase in context:
        score += FIELD_MATCH_LABEL_PHRASE_BONUS
    elif label_variants and any(variant and variant in context for variant in label_variants):
        score += 0.12

    form_text_phrase = _normalize_text(definition.form_text)
    if form_text_phrase and len(form_text_phrase.split()) > 2 and form_text_phrase in context:
        score += 0.15

    section_phrase = _normalize_text(definition.section)
    if section_phrase and len(section_phrase.split()) > 2 and section_phrase in context:
        score += 0.08

    score += _score_context_specificity(context, definition)

    if definition.field_id:
        field_id_tokens = _tokenize(definition.field_id)
        if field_id_tokens and field_id_tokens.issubset(pdf_tokens):
            score += 0.12

    definition_code_variants = _definition_code_variants(definition)
    pdf_code_variants = _pdf_field_code_variants(pdf_field)
    if definition_code_variants and pdf_code_variants and definition_code_variants & pdf_code_variants:
        score += 0.18

    if definition.option_label:
        option_label_phrase = _normalize_text(definition.option_label)
        option_value_tokens = _tokenize(definition.option_value)
        if option_label_phrase and option_label_phrase in context:
            score += 0.22
        elif option_value_tokens and option_value_tokens.issubset(pdf_tokens):
            score += 0.14
        else:
            score -= 0.04

    pdf_page = pdf_field.get("page_number")
    if isinstance(pdf_page, int) and definition.page_number > 0:
        if pdf_page == definition.page_number:
            score += 0.12
        elif abs(pdf_page - definition.page_number) == 1:
            score += 0.05

    pdf_type_hint = _clean_text(pdf_field.get("field_type_hint") or pdf_field.get("field_type")).lower()
    if pdf_type_hint == definition.field_type_hint:
        score += 0.12
    elif pdf_type_hint in {"text", "choice"} and definition.field_type_hint in {"text", "choice"}:
        score += 0.04
    elif pdf_type_hint == "button" and definition.field_type_hint in {"button", "choice"}:
        score += 0.05
    else:
        score -= 0.05

    return round(max(0.0, min(1.0, score)), 4)


def _score_second_pass_specificity(
    pdf_field: Mapping[str, Any],
    definition: QuestionnaireFieldDefinition,
) -> float:
    field_label = _normalize_text(pdf_field.get("field_label"))
    field_name = _normalize_text(pdf_field.get("field_name"))
    nearby_text = _normalize_text(pdf_field.get("nearby_text"))
    _, pdf_tokens = _pdf_field_tokens(pdf_field)
    pdf_code_variants = _pdf_field_code_variants(pdf_field)
    field_label_tokens = _tokenize(field_label)
    field_name_tokens = _tokenize(field_name)
    nearby_tokens = _tokenize(nearby_text)
    context_tokens = set(pdf_tokens) | set(field_label_tokens) | set(field_name_tokens) | set(nearby_tokens)
    normalized_values = _normalized_choice_values(pdf_field.get("button_values")) | _normalized_choice_values(
        pdf_field.get("choice_values")
    )

    label_phrase = _normalize_text(definition.label)
    label_variants = _label_phrase_variants(definition.label)
    label_tokens = _tokenize(definition.label)
    form_text_phrase = _normalize_text(definition.form_text)
    section_phrase = _normalize_text(definition.section)

    score = 0.0

    if field_label and label_phrase:
        if field_label == label_phrase:
            score += SECOND_PASS_EXACT_LABEL_MATCH_BONUS
        elif len(field_label_tokens) > 1 and (label_phrase in field_label or field_label in label_phrase):
            score += 0.06

        label_overlap = _token_overlap_ratio(field_label_tokens, label_tokens)
        if label_overlap:
            score += min(0.06, label_overlap * 0.06)
            if len(label_tokens) >= 3 and label_overlap >= SECOND_PASS_HIGH_LABEL_OVERLAP_THRESHOLD:
                score += SECOND_PASS_EXACT_LABEL_MATCH_BONUS
        elif field_label_tokens:
            score -= 0.04

    if nearby_text and form_text_phrase:
        if nearby_text == form_text_phrase:
            score += 0.18
        elif form_text_phrase in nearby_text:
            score += 0.14

    if field_label and form_text_phrase and form_text_phrase in field_label:
        score += 0.12

    if nearby_text and section_phrase and len(section_phrase.split()) > 2 and section_phrase in nearby_text:
        score += 0.08

    definition_code_variants = _definition_code_variants(definition)
    if definition_code_variants and pdf_code_variants and definition_code_variants & pdf_code_variants:
        score += 0.30

    matched_prompt_variants = [
        variant
        for variant in label_variants
        if f"enter {variant}" in field_label or f"select {variant}" in field_label
    ]
    if matched_prompt_variants:
        longest_prompt_variant = max(matched_prompt_variants, key=lambda variant: len(variant.split()))
        score += 0.16 if len(longest_prompt_variant.split()) >= 3 else 0.06

    if field_label and "number" in field_label and _context_mentions(
        field_label,
        "apartment, suite or floor",
        "apartment suite or floor",
    ):
        if definition.field_id in {"unit_number", "safe_unit_number", "preparer_unit_number", "interpreter_unit_number", "lea_unit_number"}:
            score += 0.08
        elif definition.field_id in {"street_number_name", "safe_street_number_name", "lea_street_number_name"}:
            score -= 0.06

    _unit_type_field_ids = {
        "unit_type",
        "safe_unit_type",
        "preparer_unit_type",
        "interpreter_unit_type",
        "lea_unit_type",
    }
    if (
        _context_mentions(
            field_label,
            "check this box for apartment",
            "check this box for suite",
            "check this box for floor",
        )
        or _context_mentions(
            nearby_text,
            "apt. ste. flr.",
            "apt ste flr",
        )
        or _context_mentions(
            field_label,
            "apt. ste. flr.",
            "apt ste flr",
        )
    ) and definition.field_id in _unit_type_field_ids:
        score += 0.12

    if definition.field_id:
        field_id_overlap = _token_overlap_ratio(_tokenize(definition.field_id), context_tokens)
        if field_id_overlap:
            score += min(0.05, field_id_overlap * 0.05)

    if definition.option_label:
        option_variants = _label_phrase_variants(definition.option_label or definition.option_value)
        explicit_option_hint = _explicit_pdf_option_hint(pdf_field)
        if explicit_option_hint and option_variants:
            if explicit_option_hint in option_variants:
                score += 0.32
            else:
                score -= 0.14
        if option_variants and any(
            f"select {variant}" in field_label or f"check this box for {variant}" in field_label
            for variant in option_variants
        ):
            score += 0.24
        elif option_variants and any(set(variant.split()).issubset(field_name_tokens) for variant in option_variants):
            score += 0.16
        if _phrase_matches_context(definition.option_label, f"{field_label} {nearby_text}".strip(), normalized_values):
            score += 0.20
        elif _phrase_matches_context(definition.option_value or "", f"{field_label} {nearby_text}".strip(), normalized_values):
            score += 0.14
        elif normalized_values:
            score -= 0.06

    pdf_page = pdf_field.get("page_number")
    if isinstance(pdf_page, int) and definition.page_number > 0:
        if pdf_page == definition.page_number:
            score += 0.06
        elif abs(pdf_page - definition.page_number) == 1:
            score += 0.02

    pdf_type_hint = _clean_text(pdf_field.get("field_type_hint") or pdf_field.get("field_type")).lower()
    if pdf_type_hint and pdf_type_hint == definition.field_type_hint:
        score += 0.03
    elif pdf_type_hint and definition.field_type_hint:
        score -= 0.01

    if pdf_type_hint in {"text", "choice"} and definition.field_id is None and definition.item_type in {"yes_no", "single_choice"}:
        score -= 0.22

    return round(max(-0.30, min(1.50, score)), 4)


def _resolve_field_match(
    pdf_field: Mapping[str, Any],
    scored_candidates: Sequence[tuple[QuestionnaireFieldDefinition, float]],
    *,
    min_score: float,
    candidate_min_score: float = DEFAULT_FIELD_MATCH_CANDIDATE_MIN_SCORE,
) -> tuple[QuestionnaireFieldDefinition | None, float]:
    if not scored_candidates:
        return None, 0.0

    best_definition, best_score = scored_candidates[0]
    runner_up_definition, runner_up_score = (
        scored_candidates[1] if len(scored_candidates) > 1 else (None, 0.0)
    )

    resolved_candidate_min_score = max(0.0, min(candidate_min_score, min_score))
    if best_score < resolved_candidate_min_score:
        return None, best_score

    ambiguous_match = (
        best_definition is not None
        and _is_ambiguous_best_match(
            pdf_field,
            best_definition,
            best_score,
            runner_up_definition,
            runner_up_score,
            min_margin=FIELD_MATCH_AMBIGUOUS_MARGIN,
        )
    )
    close_score_competition = runner_up_definition is not None and best_score - runner_up_score < FIELD_MATCH_SECOND_PASS_MARGIN
    should_run_second_pass = ambiguous_match or best_score < min_score or close_score_competition
    if not should_run_second_pass:
        return best_definition, best_score

    shortlist = [
        (definition, score)
        for definition, score in scored_candidates
        if best_score - score <= FIELD_MATCH_SECOND_PASS_WINDOW
    ]
    if not shortlist:
        shortlist = [scored_candidates[0]]
    elif len(shortlist) > FIELD_MATCH_SECOND_PASS_MAX_CANDIDATES:
        cutoff_score = shortlist[FIELD_MATCH_SECOND_PASS_MAX_CANDIDATES - 1][1]
        shortlist = [
            (definition, score)
            for definition, score in shortlist
            if score >= cutoff_score
        ]

    pdf_page = pdf_field.get("page_number")
    reranked: list[tuple[QuestionnaireFieldDefinition, float, float, float]] = []
    for definition, base_score in shortlist:
        specificity_bonus = _score_second_pass_specificity(pdf_field, definition)
        raw_refined_score = round(base_score + specificity_bonus, 4)
        refined_score = round(max(0.0, min(1.0, raw_refined_score)), 4)
        reranked.append((definition, refined_score, base_score, raw_refined_score))

    reranked.sort(
        key=lambda item: (
            item[3],
            item[1],
            item[2],
            1 if isinstance(pdf_page, int) and pdf_page == item[0].page_number else 0,
        ),
        reverse=True,
    )

    resolved_definition, resolved_score, _, resolved_raw_score = reranked[0]
    next_definition, next_raw_score = (
        (reranked[1][0], reranked[1][3]) if len(reranked) > 1 else (None, 0.0)
    )

    still_ambiguous = resolved_score < min_score
    if not still_ambiguous and next_definition is not None:
        score_gap = round(resolved_raw_score - next_raw_score, 4)
        resolved_prompt_score = _explicit_prompt_score(pdf_field, resolved_definition)
        next_prompt_score = _explicit_prompt_score(pdf_field, next_definition)
        clear_prompt_winner = resolved_prompt_score - next_prompt_score >= 0.4
        still_ambiguous = (score_gap < FIELD_MATCH_SECOND_PASS_MARGIN and not clear_prompt_winner) or _is_ambiguous_best_match(
            pdf_field,
            resolved_definition,
            resolved_raw_score,
            next_definition,
            next_raw_score,
            min_margin=FIELD_MATCH_SECOND_PASS_MARGIN,
        )

    if still_ambiguous:
        return None, resolved_score
    return resolved_definition, resolved_score


def _score_confidence(score: float) -> str:
    if score >= 0.82:
        return "high"
    if score >= FIELD_MATCH_MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def map_pdf_fields_to_questionnaire_ids(
    form_type: str,
    pdf_fields: Sequence[Mapping[str, Any]],
    *,
    min_score: float = DEFAULT_FIELD_MATCH_MIN_SCORE,
    candidate_min_score: float = DEFAULT_FIELD_MATCH_CANDIDATE_MIN_SCORE,
) -> dict[str, Any]:
    canonical_form = _normalize_form_code(form_type)
    if not canonical_form:
        raise ValueError("Invalid form type for questionnaire mapping.")

    bundle = load_questionnaire_definition(canonical_form)
    definitions = _questionnaire_field_definitions(canonical_form)
    mappings: list[dict[str, Any]] = []
    matched_count = 0

    for pdf_field in pdf_fields:
        context, pdf_tokens = _pdf_field_tokens(pdf_field)
        scored_candidates: list[tuple[QuestionnaireFieldDefinition, float]] = []
        for definition in definitions:
            score = _score_field_match(pdf_field, definition, context=context, pdf_tokens=pdf_tokens)
            if score > 0:
                scored_candidates.append((definition, score))
        scored_candidates.sort(key=lambda item: item[1], reverse=True)

        best_definition, best_score = _resolve_field_match(
            pdf_field,
            scored_candidates,
            min_score=min_score,
            candidate_min_score=candidate_min_score,
        )

        if best_definition is None:
            mappings.append(
                {
                    "field_name": _clean_text(pdf_field.get("field_name")),
                    "field_label": _clean_text(pdf_field.get("field_label")),
                    "page_number": pdf_field.get("page_number"),
                    "field_type": _clean_text(pdf_field.get("field_type")),
                    "questionnaire_item_id": None,
                    "questionnaire_field_id": None,
                    "questionnaire_option_value": None,
                    "canonical_questionnaire_id": None,
                    "match_score": round(best_score, 4),
                    "confidence": "low",
                    "matched_label": None,
                    "matched_section": None,
                    "matched_responsible_party": None,
                    "source_file": None,
                }
            )
            continue

        matched_count += 1
        mappings.append(
            {
                "field_name": _clean_text(pdf_field.get("field_name")),
                "field_label": _clean_text(pdf_field.get("field_label")),
                "page_number": pdf_field.get("page_number"),
                "field_type": _clean_text(pdf_field.get("field_type")),
                "questionnaire_item_id": best_definition.item_id,
                "questionnaire_field_id": best_definition.field_id,
                "questionnaire_option_value": best_definition.option_value,
                "canonical_questionnaire_id": best_definition.canonical_questionnaire_id,
                "match_score": round(best_score, 4),
                "confidence": _score_confidence(best_score),
                "matched_label": best_definition.label or best_definition.form_text,
                "matched_section": best_definition.section,
                "matched_responsible_party": best_definition.responsible_party,
                "source_file": best_definition.source_file,
            }
        )

    expected_item_count = len({
        definition.item_id
        for definition in definitions
        if definition.item_id and not definition.option_value
    })
    matched_item_ids: set[str] = {
        mapping.get("questionnaire_item_id")
        for mapping in mappings
        if mapping.get("questionnaire_item_id")
    }
    matched_item_count = len(matched_item_ids)
    coverage_ratio = (
        matched_item_count / expected_item_count if expected_item_count else 0.0
    )
    low_coverage_warning = (
        expected_item_count > 0
        and coverage_ratio < LOW_COVERAGE_RATIO_THRESHOLD
    )

    return {
        "form_type": canonical_form,
        "source_files": bundle.get("source_files", []),
        "field_count": len(pdf_fields),
        "matched_count": matched_count,
        "unmatched_count": len(pdf_fields) - matched_count,
        "expected_item_count": expected_item_count,
        "matched_item_count": matched_item_count,
        "coverage_ratio": round(coverage_ratio, 4),
        "low_coverage_warning": low_coverage_warning,
        "mappings": mappings,
    }

