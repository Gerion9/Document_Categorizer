"""Deterministic USPS state normalization and inference helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import json
import re
import unicodedata
from typing import Any, Iterable

from ..utils.text import clean_text as _clean_text

_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "seed_data" / "reference" / "us_state_resolution.json"
_US_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_STATE_TRAILING_WORD_COUNTS = (4, 3, 2, 1)
_CITY_PREFIXES = (
    "city or town",
    "city",
    "entered via",
    "entry at",
    "entry through",
    "place of entry",
    "port of entry",
    "town",
    "via",
)
_CITY_SUFFIXES = (
    "airport",
    "border crossing",
    "entry point",
    "international airport",
    "land port of entry",
    "port of entry",
)
_COUNTRY_SUFFIXES = (
    "ee uu",
    "eeuu",
    "estados unidos",
    "mexico",
    "u s",
    "u s a",
    "united states",
    "usa",
)


def _normalize_lookup_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return " ".join(text.lower().split())


@lru_cache(maxsize=1)
def _reference_data() -> dict[str, Any]:
    return json.loads(_REFERENCE_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _state_code_to_name() -> dict[str, str]:
    data = _reference_data()
    return {
        str(code).upper(): _normalize_lookup_text(name)
        for code, name in (data.get("state_codes") or {}).items()
        if _clean_text(code) and _clean_text(name)
    }


@lru_cache(maxsize=1)
def _state_name_to_code() -> dict[str, str]:
    mapping = {name: code for code, name in _state_code_to_name().items()}
    for alias, code in (_reference_data().get("state_name_aliases") or {}).items():
        normalized_alias = _normalize_lookup_text(alias)
        normalized_code = _clean_text(code).upper()
        if normalized_alias and normalized_code:
            mapping[normalized_alias] = normalized_code
    return mapping


@lru_cache(maxsize=1)
def _city_aliases() -> dict[str, str]:
    return {
        _normalize_lookup_text(alias): _clean_text(code).upper()
        for alias, code in (_reference_data().get("city_aliases") or {}).items()
        if _clean_text(alias) and _clean_text(code)
    }


@lru_cache(maxsize=1)
def _ambiguous_city_aliases() -> set[str]:
    return {
        _normalize_lookup_text(alias)
        for alias in (_reference_data().get("ambiguous_city_aliases") or [])
        if _clean_text(alias)
    }


@lru_cache(maxsize=1)
def _exact_zip_to_state() -> dict[str, str]:
    return {
        re.sub(r"[^0-9]", "", str(zip_code))[:5]: _clean_text(code).upper()
        for zip_code, code in (_reference_data().get("exact_zip_to_state") or {}).items()
        if re.sub(r"[^0-9]", "", str(zip_code))[:5] and _clean_text(code)
    }


@lru_cache(maxsize=1)
def _zip_prefix_ranges() -> tuple[tuple[int, int, str], ...]:
    ranges: list[tuple[int, int, str]] = []
    for entry in _reference_data().get("zip_prefix_ranges") or []:
        if not isinstance(entry, dict):
            continue
        start = _clean_text(entry.get("start"))
        end = _clean_text(entry.get("end"))
        state = _clean_text(entry.get("state")).upper()
        if not (start.isdigit() and end.isdigit() and state):
            continue
        ranges.append((int(start), int(end), state))
    return tuple(ranges)


def _build_state_pattern() -> str:
    tokens = list(_state_code_to_name()) + list(_state_name_to_code())
    unique_tokens = []
    seen: set[str] = set()
    for token in tokens:
        normalized = _clean_text(token)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_tokens.append(re.escape(normalized))
    return "|".join(sorted(unique_tokens, key=len, reverse=True))


US_STATE_PATTERN = _build_state_pattern()


@dataclass(frozen=True)
class StateResolution:
    code: str = ""
    source: str = ""
    matched_value: str = ""


def normalize_us_state_code(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    compact = re.sub(r"[^A-Za-z]", "", text).upper()
    if compact in _state_code_to_name():
        return compact
    return _state_name_to_code().get(_normalize_lookup_text(text), "")


def extract_us_zip_code(value: Any) -> str:
    match = _US_ZIP_RE.search(_clean_text(value))
    if not match:
        return ""
    return re.sub(r"[^0-9]", "", match.group(0))[:5]


def infer_state_from_zip_code(value: Any) -> str:
    zip_code = extract_us_zip_code(value)
    if not zip_code:
        return ""
    exact_state = _exact_zip_to_state().get(zip_code)
    if exact_state:
        return exact_state
    prefix = int(zip_code[:3])
    for start, end, state_code in _zip_prefix_ranges():
        if start <= prefix <= end:
            return state_code
    return ""


def _strip_country_suffix(text: str) -> str:
    normalized = text
    for suffix in _COUNTRY_SUFFIXES:
        if normalized.endswith(f" {suffix}"):
            return normalized[: -len(suffix) - 1].strip()
        if normalized == suffix:
            return ""
    return normalized


def _strip_city_prefix(text: str) -> str:
    normalized = text
    for prefix in _CITY_PREFIXES:
        if normalized.startswith(f"{prefix} "):
            return normalized[len(prefix) + 1 :].strip()
    return normalized


def _strip_city_suffix(text: str) -> str:
    normalized = text
    for suffix in _CITY_SUFFIXES:
        if normalized.endswith(f" {suffix}"):
            return normalized[: -len(suffix) - 1].strip()
        if normalized == suffix:
            return ""
    return normalized


def _extract_trailing_state_token(text: str) -> tuple[str, str]:
    tokens = text.split()
    if not tokens:
        return "", text
    for word_count in _STATE_TRAILING_WORD_COUNTS:
        if len(tokens) < word_count:
            continue
        candidate = " ".join(tokens[-word_count:])
        normalized_code = normalize_us_state_code(candidate)
        if normalized_code:
            remainder = " ".join(tokens[:-word_count]).strip()
            return normalized_code, remainder
    return "", text


def _city_lookup_candidates(value: Any) -> list[str]:
    raw = _clean_text(value)
    if not raw:
        return []

    segments: list[str] = []
    for piece in re.split(r"[|\n;]+", raw):
        cleaned_piece = _clean_text(piece)
        if cleaned_piece:
            segments.append(cleaned_piece)
        if ":" in cleaned_piece:
            after_colon = _clean_text(cleaned_piece.split(":", 1)[1])
            if after_colon:
                segments.append(after_colon)
        if "," in cleaned_piece:
            first_comma = _clean_text(cleaned_piece.split(",", 1)[0])
            if first_comma:
                segments.append(first_comma)

    candidates: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        normalized = _normalize_lookup_text(segment)
        if not normalized:
            continue
        normalized = _clean_text(_US_ZIP_RE.sub(" ", normalized))
        normalized = _strip_country_suffix(normalized)
        normalized = _strip_city_prefix(normalized)
        normalized = _strip_city_suffix(normalized)
        _, normalized = _extract_trailing_state_token(normalized)
        normalized = _strip_country_suffix(normalized)
        normalized = _strip_city_prefix(normalized)
        normalized = _strip_city_suffix(normalized)
        normalized = " ".join(normalized.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    return candidates


def infer_state_from_city(city: Any) -> str:
    for candidate in _city_lookup_candidates(city):
        city_state = _city_aliases().get(candidate)
        if city_state:
            return city_state
        if candidate in _ambiguous_city_aliases():
            return ""
    return ""


def extract_explicit_state_from_text(value: Any) -> str:
    normalized = _normalize_lookup_text(value)
    if not normalized:
        return ""
    normalized = _clean_text(_US_ZIP_RE.sub(" ", normalized))
    normalized = _strip_country_suffix(normalized)
    state_code, _ = _extract_trailing_state_token(normalized)
    return state_code


def resolve_us_state(
    *,
    state_value: Any = None,
    city_value: Any = None,
    zip_value: Any = None,
    text_candidates: Iterable[Any] = (),
) -> StateResolution:
    normalized_state = normalize_us_state_code(state_value)
    if normalized_state:
        return StateResolution(code=normalized_state, source="explicit_state", matched_value=_clean_text(state_value))

    candidate_values = [_clean_text(candidate) for candidate in text_candidates if _clean_text(candidate)]
    for candidate in candidate_values:
        explicit_state = extract_explicit_state_from_text(candidate)
        if explicit_state:
            return StateResolution(code=explicit_state, source="explicit_text", matched_value=candidate)

    normalized_zip = extract_us_zip_code(zip_value)
    if not normalized_zip:
        for candidate in candidate_values:
            normalized_zip = extract_us_zip_code(candidate)
            if normalized_zip:
                break
    if normalized_zip:
        inferred_from_zip = infer_state_from_zip_code(normalized_zip)
        if inferred_from_zip:
            return StateResolution(code=inferred_from_zip, source="zip", matched_value=normalized_zip)

    inferred_from_city = infer_state_from_city(city_value)
    if inferred_from_city:
        return StateResolution(code=inferred_from_city, source="city", matched_value=_clean_text(city_value))

    for candidate in candidate_values:
        inferred_from_candidate_city = infer_state_from_city(candidate)
        if inferred_from_candidate_city:
            return StateResolution(code=inferred_from_candidate_city, source="city", matched_value=candidate)

    return StateResolution()
