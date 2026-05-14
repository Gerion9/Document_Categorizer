"""Taxonomia estricta de eventos migratorios y criminales para el formulario I-914.

Este modulo desacopla la deteccion, clasificacion y redaccion de eventos que el
resto del pipeline de I-914 (post-processors en ``form_filling_service``) usa
para poblar la tabla de Part 4 (p4_1_details) y el addendum de Part 9.

Principios de diseno (reforzados por el plan de refactor):

- Cada categoria de evento tiene un regex estricto con positive + negative
  lookaheads, y un ``min_tier`` que controla cuando puede activarse.
- "Detencion migratoria" no es equivalente a "arresto criminal".
- NTA issued, proceedings, removal order, deportation, denial of admission y
  voluntary departure son eventos distintos; nunca se reciclan entre si.
- Ningun template emite cadenas hardcoded como "Detained by immigration
  authorities (CBP) upon entry" cuando no hay evidencia que lo respalde; en su
  lugar se usan fallbacks explicitos ("on or about", "in or near", "if known").
- El modulo es puro: no tiene dependencias de DB, Gemini ni de otros servicios;
  recibe listas/diccionarios y devuelve dataclasses / strings. Esto facilita
  tests unitarios deterministas.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..utils.date_format import format_long_date, parse_date_text


# ---------------------------------------------------------------------------
# Enums / dataclasses
# ---------------------------------------------------------------------------


class EventCategory(str, Enum):
    """Categorias mutuamente distintas de eventos relevantes para I-914 Part 4/9."""

    # Categorias migratorias
    IMMIGRATION_DETENTION = "immigration_detention"
    NTA_ISSUED = "nta_issued"
    REMOVAL_PROCEEDINGS_INITIATED = "removal_proceedings_initiated"
    REMOVAL_PROCEEDINGS_PENDING = "removal_proceedings_pending"
    REMOVAL_ORDER = "removal_order"
    DEPORTED_EXCLUDED = "deported_excluded"
    DENIAL_OF_ADMISSION = "denial_of_admission"
    VOLUNTARY_DEPARTURE_GRANTED = "voluntary_departure_granted"
    VOLUNTARY_DEPARTURE_OVERSTAYED = "voluntary_departure_overstayed"

    # Categorias criminales
    CRIMINAL_ARREST = "criminal_arrest"
    CRIMINAL_CITATION = "criminal_citation"
    CRIMINAL_DETENTION = "criminal_detention"
    FORMAL_CHARGE = "formal_charge"
    DIVERSION_DEFERRED_WITHHELD = "diversion_deferred_withheld"
    CONVICTION = "conviction"
    PROBATION_PAROLE_SUSPENDED = "probation_parole_suspended"
    JAIL_PRISON = "jail_prison"


IMMIGRATION_CATEGORIES: frozenset[EventCategory] = frozenset({
    EventCategory.IMMIGRATION_DETENTION,
    EventCategory.NTA_ISSUED,
    EventCategory.REMOVAL_PROCEEDINGS_INITIATED,
    EventCategory.REMOVAL_PROCEEDINGS_PENDING,
    EventCategory.REMOVAL_ORDER,
    EventCategory.DEPORTED_EXCLUDED,
    EventCategory.DENIAL_OF_ADMISSION,
    EventCategory.VOLUNTARY_DEPARTURE_GRANTED,
    EventCategory.VOLUNTARY_DEPARTURE_OVERSTAYED,
})

CRIMINAL_CATEGORIES: frozenset[EventCategory] = frozenset({
    EventCategory.CRIMINAL_ARREST,
    EventCategory.CRIMINAL_CITATION,
    EventCategory.CRIMINAL_DETENTION,
    EventCategory.FORMAL_CHARGE,
    EventCategory.DIVERSION_DEFERRED_WITHHELD,
    EventCategory.CONVICTION,
    EventCategory.PROBATION_PAROLE_SUSPENDED,
    EventCategory.JAIL_PRISON,
})


@dataclass
class ClassifiedEvent:
    """Representacion estructurada de un evento extraido de la evidencia.

    - ``source_tier``: 1 = official record (FBI/court/FOIA), 2 = sworn
      declaration/affidavit, 3 = intake/BioCall, 4 = otros.
    - ``needs_paraphrase``: True si el campo ``reason`` viene vacio o demasiado
      generico y seria candidato a paraphrase LLM acotado.
    """

    category: EventCategory
    date: str = ""
    authority: str = ""
    authority_kind: str = "unknown"  # "immigration" | "criminal" | "unknown"
    location_city: str = ""
    location_state: str = ""
    outcome: str = ""
    reason: str = ""
    raw_text: str = ""
    source_tier: int = 4
    source_page: Any = None
    needs_paraphrase: bool = False
    dedupe_key: str = field(default="", repr=False)


# ---------------------------------------------------------------------------
# Min tier por categoria (regla dura)
# ---------------------------------------------------------------------------
#
# Tier 1 = official (FBI, court, FOIA, EOIR). Tier 2 = declaration / affidavit.
# Tier 3 = intake / BioCall. Tier 4 = desconocido.
#
# Las categorias "duras" (con consecuencias legales fuertes) exigen tier <= 2
# para poder activarse desde evidencia textual. Tier 4 nunca puede escalar mas
# alla de una deteccion migratoria o un arresto criminal generico.

MIN_TIER_BY_CATEGORY: dict[EventCategory, int] = {
    EventCategory.IMMIGRATION_DETENTION: 4,
    EventCategory.NTA_ISSUED: 2,
    EventCategory.REMOVAL_PROCEEDINGS_INITIATED: 2,
    EventCategory.REMOVAL_PROCEEDINGS_PENDING: 2,
    EventCategory.REMOVAL_ORDER: 2,
    EventCategory.DEPORTED_EXCLUDED: 2,
    EventCategory.DENIAL_OF_ADMISSION: 2,
    EventCategory.VOLUNTARY_DEPARTURE_GRANTED: 2,
    EventCategory.VOLUNTARY_DEPARTURE_OVERSTAYED: 2,
    EventCategory.CRIMINAL_ARREST: 4,
    EventCategory.CRIMINAL_CITATION: 3,
    EventCategory.CRIMINAL_DETENTION: 3,
    EventCategory.FORMAL_CHARGE: 2,
    EventCategory.DIVERSION_DEFERRED_WITHHELD: 2,
    EventCategory.CONVICTION: 2,
    EventCategory.PROBATION_PAROLE_SUSPENDED: 2,
    EventCategory.JAIL_PRISON: 2,
}


# ---------------------------------------------------------------------------
# Mapeo categoria -> items de Part 4 (uno-a-pocos, nunca uno-a-todos)
# ---------------------------------------------------------------------------
#
# IDs tomados de backend/app/seed_data/questions/i914_form_client.json
#
#   p4_1a .. p4_1i : "Have you EVER been ..." (arrestado, charged,
#                     convicted, diverted, probation/parole, jail/prison,
#                     testifying / restraining order / domestic violence).
#   p4_9a          : removal/exclusion/rescission/deportation PENDING
#   p4_9b          : proceedings EVER INITIATED (NTA, proceedings)
#   p4_9c          : EVER removed / excluded / deported
#   p4_9d          : EVER ordered to be removed / deported
#   p4_9e          : EVER denied visa / admission
#   p4_9f          : granted voluntary departure + failed to depart in time

CATEGORY_TO_PART4_ITEMS: dict[EventCategory, tuple[str, ...]] = {
    # Migratorias
    EventCategory.IMMIGRATION_DETENTION: ("p4_1b",),
    EventCategory.NTA_ISSUED: ("p4_9b",),
    EventCategory.REMOVAL_PROCEEDINGS_INITIATED: ("p4_9b",),
    EventCategory.REMOVAL_PROCEEDINGS_PENDING: ("p4_9a", "p4_9b"),
    EventCategory.REMOVAL_ORDER: ("p4_9d",),
    EventCategory.DEPORTED_EXCLUDED: ("p4_9c",),
    EventCategory.DENIAL_OF_ADMISSION: ("p4_9e",),
    EventCategory.VOLUNTARY_DEPARTURE_GRANTED: (),
    EventCategory.VOLUNTARY_DEPARTURE_OVERSTAYED: ("p4_9f",),
    # Criminales
    EventCategory.CRIMINAL_ARREST: ("p4_1b",),
    EventCategory.CRIMINAL_CITATION: ("p4_1b",),
    EventCategory.CRIMINAL_DETENTION: ("p4_1b",),
    EventCategory.FORMAL_CHARGE: ("p4_1c",),
    EventCategory.DIVERSION_DEFERRED_WITHHELD: ("p4_1e",),
    EventCategory.CONVICTION: ("p4_1d",),
    EventCategory.PROBATION_PAROLE_SUSPENDED: ("p4_1f",),
    EventCategory.JAIL_PRISON: ("p4_1g",),
}


# ---------------------------------------------------------------------------
# Regex de deteccion (positive + negative lookaheads por categoria)
# ---------------------------------------------------------------------------

# Rangos y indicadores claros de contexto migratorio vs criminal.
_IMMIGRATION_AUTHORITY_PATTERN = (
    r"\b(?:cbp|customs\s+and\s+border\s+protection|border\s*patrol|ice|"
    r"u\.?s\.?\s*immigration|immigration\s+and\s+customs\s+enforcement|"
    r"dhs|department\s+of\s+homeland\s+security|immigration\s+authorities|"
    r"immigration\s+officers?|immigration\s+judge|eoir|port\s+of\s+entry|"
    r"border\s+authorities|orr|office\s+of\s+refugee\s+resettlement|hhs)\b"
)

_CRIMINAL_AUTHORITY_PATTERN = (
    r"\b(?:police|pd\b|sheriff|state\s+trooper|county\s+jail|court|"
    r"district\s+attorney|da's\s+office|prosecutor|marshal|"
    r"local\s+law\s+enforcement|city\s+police)\b"
)

_IMMIGRATION_AUTHORITY_RE = re.compile(_IMMIGRATION_AUTHORITY_PATTERN, re.IGNORECASE)
_CRIMINAL_AUTHORITY_RE = re.compile(_CRIMINAL_AUTHORITY_PATTERN, re.IGNORECASE)

# Patron que indica "breve retencion" migratoria (no escala a jail/prison).
_BRIEF_IMMIGRATION_HOLD_RE = re.compile(
    r"\b(?:hielera|cbp\s+hold|cbp\s+custody|ice\s+hold|border\s+processing|"
    r"held\s+by\s+cbp|held\s+for\s+processing|short(?:\s|-)term\s+hold)\b",
    re.IGNORECASE,
)


@dataclass
class _CategoryRule:
    category: EventCategory
    positive: re.Pattern[str]
    negative: re.Pattern[str] | None = None
    requires_authority_kind: str | None = None  # "immigration" | "criminal" | None
    prefer_authority_kind: str | None = None


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


CATEGORY_RULES: tuple[_CategoryRule, ...] = (
    # ---- Migratorias ----
    _CategoryRule(
        category=EventCategory.NTA_ISSUED,
        positive=_rx(r"\b(?:notice\s+to\s+appear|nta\s+(?:issued|served)|nta\b)"),
        negative=_rx(r"\b(?:without\s+an?\s+nta|no\s+nta|nta\s+was\s+not)\b"),
        prefer_authority_kind="immigration",
    ),
    _CategoryRule(
        category=EventCategory.REMOVAL_PROCEEDINGS_PENDING,
        positive=_rx(
            r"\b(?:removal|exclusion|rescission|deportation)\s+proceedings\b"
            r"[^.]{0,80}\bpending\b|"
            r"\bproceedings\s+(?:are|remain)\s+pending\b|"
            r"\bcase\s+pending\s+(?:in|before)\s+(?:immigration\s+court|eoir)\b"
        ),
        prefer_authority_kind="immigration",
    ),
    _CategoryRule(
        category=EventCategory.REMOVAL_PROCEEDINGS_INITIATED,
        positive=_rx(
            r"\b(?:placed\s+in|initiated|commenced|began|started)\s+"
            r"(?:removal|exclusion|rescission|deportation)\s+proceedings\b|"
            r"\bremoval\s+proceedings\s+(?:were|have\s+been)\s+(?:initiated|commenced|begun)\b"
        ),
        prefer_authority_kind="immigration",
    ),
    _CategoryRule(
        category=EventCategory.REMOVAL_ORDER,
        positive=_rx(
            r"\b(?:ordered\s+(?:to\s+be\s+)?(?:removed|deported|excluded))\b|"
            r"\border\s+of\s+removal\b|"
            r"\bfinal\s+order\s+of\s+(?:removal|deportation|exclusion)\b|"
            r"\bremoval\s+order\s+(?:issued|entered)\b"
        ),
        negative=_rx(r"\b(?:no\s+order\s+of\s+removal|without\s+an?\s+order)\b"),
        prefer_authority_kind="immigration",
    ),
    _CategoryRule(
        category=EventCategory.DEPORTED_EXCLUDED,
        positive=_rx(
            r"\b(?:was|were)\s+(?:physically\s+)?(?:removed|deported|excluded)\b|"
            r"\b(?:deportation|removal|exclusion)\s+(?:was\s+)?executed\b|"
            r"\breturned\s+to\s+(?:mexico|honduras|guatemala|el\s+salvador|country\s+of\s+origin)\b"
            r"[^.]{0,60}\b(?:deport|removed|excluded|by\s+cbp|by\s+ice)\b"
        ),
        prefer_authority_kind="immigration",
    ),
    _CategoryRule(
        category=EventCategory.DENIAL_OF_ADMISSION,
        positive=_rx(
            r"\b(?:denied\s+(?:a\s+)?visa|visa\s+(?:was\s+)?denied|"
            r"denied\s+admission\s+to\s+the\s+united\s+states|"
            r"refused\s+(?:admission|entry)\s+(?:at|to|by))\b"
        ),
        prefer_authority_kind="immigration",
    ),
    _CategoryRule(
        category=EventCategory.VOLUNTARY_DEPARTURE_OVERSTAYED,
        positive=_rx(
            r"\b(?:granted\s+voluntary\s+departure)\b[^.]{0,120}"
            r"\b(?:failed\s+to\s+depart|did\s+not\s+depart|overstay(?:ed)?|"
            r"did\s+not\s+leave\s+(?:in|within)\s+time)\b"
        ),
        prefer_authority_kind="immigration",
    ),
    _CategoryRule(
        category=EventCategory.VOLUNTARY_DEPARTURE_GRANTED,
        positive=_rx(
            r"\b(?:granted\s+voluntary\s+departure|voluntary\s+departure\s+(?:was\s+)?granted)\b"
        ),
        negative=_rx(r"\bfailed\s+to\s+depart\b|\bdid\s+not\s+depart\b"),
        prefer_authority_kind="immigration",
    ),
    _CategoryRule(
        category=EventCategory.IMMIGRATION_DETENTION,
        positive=_rx(
            r"\b(?:detained|held|apprehended|processed|in\s+custody)\b"
            r"[^.]{0,120}"
            + _IMMIGRATION_AUTHORITY_PATTERN
            + r"|"
            + _IMMIGRATION_AUTHORITY_PATTERN
            + r"[^.]{0,120}\b(?:detained|held|apprehended|processed|custody)\b|"
            r"\b(?:hielera|ice\s+detention|cbp\s+custody|immigration\s+detention)\b"
        ),
        prefer_authority_kind="immigration",
    ),
    # ---- Criminales ----
    _CategoryRule(
        category=EventCategory.JAIL_PRISON,
        positive=_rx(
            r"\b(?:sentenced\s+to\s+\d+\s+(?:days?|months?|years?)\s+(?:in\s+)?(?:jail|prison)|"
            r"served\s+\d+\s+(?:days?|months?|years?)\s+in\s+(?:jail|prison)|"
            r"incarcerat(?:ed|ion)|"
            r"(?:county|state|federal)\s+(?:jail|prison)\s+(?:sentence|time)|"
            r"imprisoned\s+for)\b"
        ),
        negative=_rx(
            r"\b(?:cbp\s+hold|ice\s+hold|hielera|immigration\s+detention|"
            r"held\s+by\s+cbp|held\s+by\s+ice|border\s+processing)\b"
        ),
        prefer_authority_kind="criminal",
    ),
    _CategoryRule(
        category=EventCategory.CONVICTION,
        positive=_rx(
            r"\b(?:convicted\s+of|found\s+guilty\s+of|"
            r"pleaded\s+guilty\s+to|plea\s+of\s+guilty|"
            r"conviction\s+(?:for|of))\b"
        ),
        negative=_rx(r"\b(?:no\s+conviction|never\s+convicted|not\s+convicted)\b"),
        prefer_authority_kind="criminal",
    ),
    _CategoryRule(
        category=EventCategory.PROBATION_PAROLE_SUSPENDED,
        positive=_rx(
            r"\b(?:placed\s+on\s+probation|probation\s+sentence|"
            r"on\s+probation\s+for|placed\s+on\s+parole|"
            r"suspended\s+sentence|sentence\s+was\s+suspended|"
            r"supervised\s+release)\b"
        ),
        prefer_authority_kind="criminal",
    ),
    _CategoryRule(
        category=EventCategory.DIVERSION_DEFERRED_WITHHELD,
        positive=_rx(
            r"\b(?:diversion\s+program|pretrial\s+diversion|"
            r"deferred\s+adjudication|deferred\s+prosecution|"
            r"withheld\s+adjudication|adjudication\s+withheld)\b"
        ),
        prefer_authority_kind="criminal",
    ),
    _CategoryRule(
        category=EventCategory.FORMAL_CHARGE,
        positive=_rx(
            r"\b(?:formally\s+charged|formal\s+charges\s+(?:were\s+)?filed|"
            r"indicted\s+for|indictment\s+for|charged\s+with\s+a\s+(?:crime|felony|misdemeanor)|"
            r"charging\s+document|criminal\s+complaint\s+filed)\b"
        ),
        prefer_authority_kind="criminal",
    ),
    _CategoryRule(
        category=EventCategory.CRIMINAL_CITATION,
        positive=_rx(
            r"\b(?:cited\s+for|issued\s+a\s+citation|received\s+a\s+citation|"
            r"traffic\s+citation|municipal\s+citation)\b"
        ),
        prefer_authority_kind="criminal",
    ),
    _CategoryRule(
        category=EventCategory.CRIMINAL_DETENTION,
        positive=_rx(
            r"\b(?:booked\s+into\s+(?:jail|county\s+jail)|"
            r"held\s+(?:by|at)\s+(?:police|sheriff|county\s+jail)|"
            r"in\s+police\s+custody)\b"
        ),
        prefer_authority_kind="criminal",
    ),
    _CategoryRule(
        category=EventCategory.CRIMINAL_ARREST,
        positive=_rx(
            r"\b(?:arrested|taken\s+into\s+custody)\b"
            r"[^.]{0,120}"
            + _CRIMINAL_AUTHORITY_PATTERN
            + r"|"
            + _CRIMINAL_AUTHORITY_PATTERN
            + r"[^.]{0,120}\barrested\b|"
            r"\b(?:police\s+arrest|made\s+an\s+arrest)\b"
        ),
        negative=_rx(
            r"\b(?:cbp|ice|dhs|immigration\s+authorities|border\s+patrol)\b"
            r"[^.]{0,40}\barrested\b"
        ),
        prefer_authority_kind="criminal",
    ),
)


# ---------------------------------------------------------------------------
# Regex auxiliares (fechas, locacion, paraphrase trigger)
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(
    r"\b(?:"
    r"(?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])[/\-](?:\d{4}|\d{2})|"
    r"(?:\d{4})[/\-](?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])|"
    r"(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\.?\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

_LOCATION_CITY_STATE_RE = re.compile(
    r"\b(?:in|at|near)\s+([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){0,3})"
    r"\s*,\s*([A-Z]{2})\b"
)

_LOCATION_CITY_ONLY_RE = re.compile(
    r"\b(?:in|at|near)\s+([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){0,3})\b"
)

_GENERIC_REASON_RE = re.compile(
    r"^\s*(?:detained|arrested|held|in\s+custody|processed|"
    r"law\s+enforcement|officers?)\s*\.?\s*$",
    re.IGNORECASE,
)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(0) if match else ""


def _detect_authority(text: str) -> tuple[str, str]:
    """Return (authority_literal, authority_kind)."""
    imm = _IMMIGRATION_AUTHORITY_RE.search(text)
    crim = _CRIMINAL_AUTHORITY_RE.search(text)
    if imm and not crim:
        return imm.group(0), "immigration"
    if crim and not imm:
        return crim.group(0), "criminal"
    if imm and crim:
        # Ambos presentes: preferimos el que aparezca primero.
        if imm.start() <= crim.start():
            return imm.group(0), "immigration"
        return crim.group(0), "criminal"
    return "", "unknown"


def _extract_location(text: str) -> tuple[str, str]:
    """Return (city, state) best-effort."""
    m = _LOCATION_CITY_STATE_RE.search(text)
    if m:
        return _norm(m.group(1)), _norm(m.group(2)).upper()
    m2 = _LOCATION_CITY_ONLY_RE.search(text)
    if m2:
        return _norm(m2.group(1)), ""
    return "", ""


def _looks_like_brief_immigration_hold(text: str) -> bool:
    return bool(_BRIEF_IMMIGRATION_HOLD_RE.search(text))


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def _evidence_text(item: Mapping[str, Any]) -> str:
    text = item.get("text")
    if isinstance(text, str):
        return text
    return _norm(text)


def _evidence_tier(item: Mapping[str, Any]) -> int:
    """Accept a tier already computed by the caller, default to 4."""
    tier = item.get("tier")
    if isinstance(tier, int) and 1 <= tier <= 4:
        return tier
    if isinstance(tier, str) and tier.isdigit():
        value = int(tier)
        if 1 <= value <= 4:
            return value
    return 4


def _build_reason(text: str, category: EventCategory) -> tuple[str, bool]:
    """Extract a short reason sentence from the evidence snippet.

    Returns (reason_text, needs_paraphrase).
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.;!?])\s+", text) if s.strip()]
    if not sentences:
        return "", True
    reason = sentences[0]
    if len(reason) > 220:
        reason = reason[:217].rstrip() + "..."
    generic = bool(_GENERIC_REASON_RE.match(reason))
    return reason, generic


def classify_evidence_events(
    evidence_list: Iterable[Mapping[str, Any]],
) -> list[ClassifiedEvent]:
    """Classify raw evidence snippets into structured ``ClassifiedEvent``.

    ``evidence_list`` may be the flat list of evidence items collected for
    several Part 4 fields; callers are expected to dedupe across fields before
    invoking this function. Items without a usable text payload are ignored.

    Each evidence item is checked against every ``_CategoryRule``. A single
    snippet can produce multiple events (e.g. "arrested by CBP and NTA was
    issued" -> IMMIGRATION_DETENTION + NTA_ISSUED).
    """
    events: list[ClassifiedEvent] = []
    for item in evidence_list or []:
        if not isinstance(item, Mapping):
            continue
        text = _evidence_text(item)
        if not text:
            continue
        tier = _evidence_tier(item)
        authority, authority_kind = _detect_authority(text)
        date = _first_match(_DATE_RE, text)
        city, state = _extract_location(text)

        for rule in CATEGORY_RULES:
            if not rule.positive.search(text):
                continue
            if rule.negative and rule.negative.search(text):
                continue
            if rule.category == EventCategory.JAIL_PRISON and _looks_like_brief_immigration_hold(text):
                continue

            min_tier = MIN_TIER_BY_CATEGORY.get(rule.category, 4)
            if tier > min_tier:
                continue

            # Coherencia con el tipo de autoridad detectado.
            if rule.category in IMMIGRATION_CATEGORIES:
                if authority_kind == "criminal":
                    # Evento migratorio con autoridad puramente criminal: sospechoso,
                    # solo aceptamos si el texto menciona explicitamente una autoridad
                    # migratoria.
                    if not _IMMIGRATION_AUTHORITY_RE.search(text):
                        continue
                effective_kind = "immigration"
            elif rule.category in CRIMINAL_CATEGORIES:
                if authority_kind == "immigration" and not _CRIMINAL_AUTHORITY_RE.search(text):
                    continue
                effective_kind = "criminal"
            else:
                effective_kind = authority_kind or "unknown"

            reason, generic = _build_reason(text, rule.category)
            outcome_text = ""
            if rule.category in {
                EventCategory.REMOVAL_PROCEEDINGS_PENDING,
                EventCategory.REMOVAL_PROCEEDINGS_INITIATED,
            }:
                outcome_text = "Proceedings pending" if rule.category == EventCategory.REMOVAL_PROCEEDINGS_PENDING else "Proceedings initiated"

            dedupe_key = f"{rule.category.value}|{date}|{city.lower()}|{state.upper()}"

            events.append(
                ClassifiedEvent(
                    category=rule.category,
                    date=date,
                    authority=authority,
                    authority_kind=effective_kind,
                    location_city=city,
                    location_state=state,
                    outcome=outcome_text,
                    reason=reason,
                    raw_text=text,
                    source_tier=tier,
                    source_page=item.get("page") or item.get("pageNumber"),
                    needs_paraphrase=generic or not reason,
                    dedupe_key=dedupe_key,
                )
            )

    events.sort(key=lambda e: (e.source_tier, e.category.value, e.date))
    return _dedupe_events(events)


def _dedupe_events(events: Iterable[ClassifiedEvent]) -> list[ClassifiedEvent]:
    seen: dict[str, ClassifiedEvent] = {}
    for event in events:
        key = event.dedupe_key or f"{event.category.value}|{event.date}|{event.location_city}"
        incumbent = seen.get(key)
        if incumbent is None:
            seen[key] = event
            continue
        # Keep the event with the lowest (best) tier; break ties preferring the
        # one with more slots populated.
        incumbent_slots = sum(1 for v in (incumbent.date, incumbent.location_city, incumbent.reason) if v)
        new_slots = sum(1 for v in (event.date, event.location_city, event.reason) if v)
        if event.source_tier < incumbent.source_tier or (
            event.source_tier == incumbent.source_tier and new_slots > incumbent_slots
        ):
            seen[key] = event
    return list(seen.values())


# ---------------------------------------------------------------------------
# Mapping events -> Part 4 items
# ---------------------------------------------------------------------------


def map_events_to_part4_items(
    events: Iterable[ClassifiedEvent],
) -> dict[str, list[ClassifiedEvent]]:
    """Return ``{item_id: [events...]}`` for every Part 4 item activated.

    Uses the explicit ``CATEGORY_TO_PART4_ITEMS`` mapping. A single event can
    feed multiple items (e.g. REMOVAL_PROCEEDINGS_PENDING -> p4_9a and p4_9b).
    """
    mapping: dict[str, list[ClassifiedEvent]] = {}
    for event in events:
        for item_id in CATEGORY_TO_PART4_ITEMS.get(event.category, ()):
            mapping.setdefault(item_id, []).append(event)
    # Orden estable: tier asc, luego fecha.
    for item_id, bucket in mapping.items():
        bucket.sort(key=lambda e: (e.source_tier, e.date))
    return mapping


# ---------------------------------------------------------------------------
# Templates (Part 4 table + Part 9 addendum)
# ---------------------------------------------------------------------------


_FALLBACK_DATE = "on or about (date to be confirmed)"
_FALLBACK_PLACE = "in or near a location to be confirmed"
_FALLBACK_AUTHORITY_IMMIGRATION = "immigration authorities"
_FALLBACK_AUTHORITY_CRIMINAL = "local law enforcement"
_FALLBACK_REASON = "the reason remains to be confirmed (if known)"


def _format_date_slot(date: str) -> str:
    if not date:
        return _FALLBACK_DATE
    parsed = parse_date_text(date)
    if parsed is not None:
        return f"on {format_long_date(parsed)}"
    return f"on {date}"


def _format_place_slot(city: str, state: str) -> str:
    city = _norm(city)
    state = _norm(state).upper()
    if city and state:
        return f"in or near {city}, {state}"
    if city:
        return f"in or near {city}"
    if state:
        return f"in {state}"
    return _FALLBACK_PLACE


def _format_authority_slot(event: ClassifiedEvent) -> str:
    if event.authority:
        return event.authority
    if event.authority_kind == "immigration":
        return _FALLBACK_AUTHORITY_IMMIGRATION
    if event.authority_kind == "criminal":
        return _FALLBACK_AUTHORITY_CRIMINAL
    # Ante incertidumbre, escoger el fallback segun la categoria.
    if event.category in IMMIGRATION_CATEGORIES:
        return _FALLBACK_AUTHORITY_IMMIGRATION
    if event.category in CRIMINAL_CATEGORIES:
        return _FALLBACK_AUTHORITY_CRIMINAL
    return "the responsible authority"


def _format_reason_slot(event: ClassifiedEvent, reason_override: str | None) -> str:
    override = _norm(reason_override)
    if override:
        return override
    reason = _norm(event.reason)
    if reason and not _GENERIC_REASON_RE.match(reason):
        return reason
    return _FALLBACK_REASON


def build_part4_table_rows(
    events: Iterable[ClassifiedEvent],
) -> list[dict[str, str]]:
    """Return rows ready to populate the Part 4 table (p4_1_details)."""
    rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for event in events:
        # Solo eventos que mapeen a items 4.1.* aparecen en la tabla.
        item_ids = CATEGORY_TO_PART4_ITEMS.get(event.category, ())
        if not any(item_id.startswith("p4_1") for item_id in item_ids):
            continue
        reason = event.reason if event.reason and not _GENERIC_REASON_RE.match(event.reason) else ""
        if event.category == EventCategory.IMMIGRATION_DETENTION:
            reason = ""
        outcome = event.outcome or ""
        place = ", ".join(part for part in (event.location_city, event.location_state) if part)
        key = (event.date or "", place.lower(), event.category.value)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(
            {
                "incident_date": event.date or "",
                "incident_location": place,
                "incident_reason": reason or _category_default_reason(event.category),
                "incident_outcome": outcome,
                "_category": event.category.value,
                "_tier": str(event.source_tier),
            }
        )
    return rows


def _category_default_reason(category: EventCategory) -> str:
    mapping: dict[EventCategory, str] = {
        EventCategory.IMMIGRATION_DETENTION: "Immigration detention",
        EventCategory.CRIMINAL_ARREST: "Criminal arrest",
        EventCategory.CRIMINAL_CITATION: "Citation",
        EventCategory.CRIMINAL_DETENTION: "Held in criminal custody",
        EventCategory.FORMAL_CHARGE: "Formal criminal charge",
        EventCategory.DIVERSION_DEFERRED_WITHHELD: "Diversion / deferred adjudication program",
        EventCategory.CONVICTION: "Criminal conviction",
        EventCategory.PROBATION_PAROLE_SUSPENDED: "Probation / parole / suspended sentence",
        EventCategory.JAIL_PRISON: "Jail or prison sentence",
    }
    return mapping.get(category, "Event details to be confirmed")


def build_part9_text(
    item_id: str,
    events: list[ClassifiedEvent],
    *,
    reason_override: str | None = None,
) -> str:
    """Build the Part 9 addendum text for a single Part 4 item.

    - ``item_id`` is one of ``p4_1b..p4_1g`` or ``p4_9a..p4_9f`` (or ``p3_9``).
    - ``events`` must already be filtered to the subset relevant for this item.
    - If ``reason_override`` is provided, it replaces the ``{reason}`` slot.
    - If ``events`` is empty, returns an empty string (caller must decide
      whether to fall back to a conservative boilerplate or flag for review).
    """
    normalized_item = _norm(item_id).lower()
    if not events:
        return ""

    if normalized_item == "p3_9":
        return _build_p3_9_text(events, reason_override)
    if normalized_item == "p4_1b":
        return _build_p4_1b_text(events, reason_override)
    if normalized_item == "p4_1c":
        return _build_p4_1c_text(events, reason_override)
    if normalized_item == "p4_1d":
        return _build_p4_1d_text(events, reason_override)
    if normalized_item == "p4_1e":
        return _build_p4_1e_text(events, reason_override)
    if normalized_item == "p4_1f":
        return _build_p4_1f_text(events, reason_override)
    if normalized_item == "p4_1g":
        return _build_p4_1g_text(events, reason_override)
    if normalized_item == "p4_9a":
        return _build_p4_9a_text(events)
    if normalized_item == "p4_9b":
        return _build_p4_9b_text(events)
    if normalized_item == "p4_9c":
        return _build_p4_9c_text(events)
    if normalized_item == "p4_9d":
        return _build_p4_9d_text(events)
    if normalized_item == "p4_9e":
        return _build_p4_9e_text(events)
    if normalized_item == "p4_9f":
        return _build_p4_9f_text(events)
    return ""


# ---- Part 3 / Part 4 per-item templates ----


def _build_p3_9_text(
    events: list[ClassifiedEvent],
    reason_override: str | None,
) -> str:
    """Circumstances of most recent arrival, tied to the trafficking nexus.

    We intentionally avoid any generic "was detained by law enforcement"
    wording; Part 3 item 9 is about the applicant's own narrative of how they
    arrived and the nexus with the trafficking scheme, not a criminal history.
    """
    first = events[0]
    date_slot = _format_date_slot(first.date)
    place_slot = _format_place_slot(first.location_city, first.location_state)
    reason_slot = _format_reason_slot(first, reason_override)
    return (
        f"Most recent arrival: the applicant entered the United States {date_slot} "
        f"{place_slot}. The circumstances of this arrival are connected to the "
        f"applicant's victimization as a victim of a severe form of trafficking in persons: "
        f"{reason_slot}."
    )


def _build_p4_1b_text(
    events: list[ClassifiedEvent],
    reason_override: str | None,
) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    authority = _format_authority_slot(event)
    reason = _format_reason_slot(event, reason_override)
    if event.category in IMMIGRATION_CATEGORIES:
        verb_clause = f"was detained by {authority}"
    else:
        verb_clause = f"was arrested by {authority}"
    outcome_part = f" Outcome: {event.outcome}." if event.outcome else ""
    return (
        f"The applicant {verb_clause} {date_slot} {place_slot}. "
        f"Reason: {reason}.{outcome_part}"
    ).strip()


def _build_p4_1c_text(
    events: list[ClassifiedEvent],
    reason_override: str | None,
) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    charge = _format_reason_slot(event, reason_override)
    return (
        f"Formal criminal charges were filed against the applicant {date_slot} {place_slot}. "
        f"Charge: {charge}."
    )


def _build_p4_1d_text(
    events: list[ClassifiedEvent],
    reason_override: str | None,
) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    offense = _format_reason_slot(event, reason_override)
    outcome = event.outcome or "the sentence is documented in the court record (if known)"
    return (
        f"The applicant was convicted {date_slot} {place_slot}. "
        f"Offense: {offense}. Outcome: {outcome}."
    )


def _build_p4_1e_text(
    events: list[ClassifiedEvent],
    reason_override: str | None,
) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    offense = _format_reason_slot(event, reason_override)
    return (
        f"The applicant participated in a diversion, deferred adjudication, or withheld "
        f"adjudication program {date_slot} {place_slot}. Underlying offense: {offense}."
    )


def _build_p4_1f_text(
    events: list[ClassifiedEvent],
    reason_override: str | None,
) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    offense = _format_reason_slot(event, reason_override)
    return (
        f"The applicant was placed on probation, parole, or received a suspended sentence "
        f"{date_slot} {place_slot} in connection with: {offense}."
    )


def _build_p4_1g_text(
    events: list[ClassifiedEvent],
    reason_override: str | None,
) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    outcome = event.outcome or _format_reason_slot(event, reason_override)
    return (
        f"The applicant served time in jail or prison {date_slot} {place_slot}. "
        f"Details: {outcome}."
    )


# ---- Part 4 item 9 (migratorios) ----


def _build_p4_9a_text(events: list[ClassifiedEvent]) -> str:
    return (
        "Removal, exclusion, rescission, or deportation proceedings against the applicant "
        "remain pending as of the date of filing."
    )


def _build_p4_9b_text(events: list[ClassifiedEvent]) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    authority = _format_authority_slot(event)
    if event.category == EventCategory.NTA_ISSUED:
        return (
            f"Immigration authorities initiated removal proceedings by issuing a Notice to "
            f"Appear {date_slot} {place_slot} via {authority}."
        )
    return (
        f"Removal, exclusion, rescission, or deportation proceedings were initiated against "
        f"the applicant {date_slot} {place_slot} by {authority}."
    )


def _build_p4_9c_text(events: list[ClassifiedEvent]) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    return (
        f"The applicant was removed, excluded, or deported from the United States "
        f"{date_slot} {place_slot}."
    )


def _build_p4_9d_text(events: list[ClassifiedEvent]) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    authority = _format_authority_slot(event)
    return (
        f"The applicant was ordered to be removed, excluded, or deported from the United "
        f"States {date_slot} {place_slot} by {authority}."
    )


def _build_p4_9e_text(events: list[ClassifiedEvent]) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    place_slot = _format_place_slot(event.location_city, event.location_state)
    return (
        f"The applicant was denied a visa or denied admission to the United States "
        f"{date_slot} {place_slot}."
    )


def _build_p4_9f_text(events: list[ClassifiedEvent]) -> str:
    event = events[0]
    date_slot = _format_date_slot(event.date)
    return (
        f"The applicant was granted voluntary departure {date_slot} and failed to depart "
        f"within the allotted time."
    )


# ---------------------------------------------------------------------------
# Conflict detection (categoria vs answers)
# ---------------------------------------------------------------------------


# Respuestas que consideramos "afirmativas" y "negativas" al comparar eventos
# contra las answers almacenadas.
_YES_VALUES: frozenset[str] = frozenset({"yes", "y", "true", "1"})
_NO_VALUES: frozenset[str] = frozenset({"no", "n", "false", "0"})


def _normalize_answer(value: Any) -> str:
    return _norm(value).lower()


def detect_category_conflicts(
    events: Iterable[ClassifiedEvent],
    answers_by_item: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Detect conflicts between the classified events and the current answers.

    Returns a list of dicts:

        {
            "item_id": "p4_9b",
            "kind": "missing_yes" | "unsupported_yes",
            "category": EventCategory,
            "event": ClassifiedEvent | None,
            "message": str,
        }

    - ``missing_yes``: there is tier <= 2 evidence for the category but the
      answer remains ``No``.
    - ``unsupported_yes``: the answer is ``Yes`` but no event of the required
      category (and tier) was found.
    """
    conflicts: list[dict[str, Any]] = []
    events_list = list(events)
    per_item = map_events_to_part4_items(events_list)

    # 1) missing_yes: eventos solidos vs answers No.
    for item_id, bucket in per_item.items():
        strong_events = [e for e in bucket if e.source_tier <= 2]
        if not strong_events:
            continue
        answer = _normalize_answer(answers_by_item.get(item_id))
        if answer in _NO_VALUES:
            first = strong_events[0]
            conflicts.append(
                {
                    "item_id": item_id,
                    "kind": "missing_yes",
                    "category": first.category,
                    "event": first,
                    "message": (
                        f"Item {item_id} is answered 'No' but tier-{first.source_tier} evidence "
                        f"supports {first.category.value}."
                    ),
                }
            )

    # 2) unsupported_yes: answer Yes sin evento requerido.
    required_categories: dict[str, tuple[EventCategory, ...]] = {
        "p4_1d": (EventCategory.CONVICTION,),
        "p4_1e": (EventCategory.DIVERSION_DEFERRED_WITHHELD,),
        "p4_1f": (EventCategory.PROBATION_PAROLE_SUSPENDED,),
        "p4_1g": (EventCategory.JAIL_PRISON,),
        "p4_9c": (EventCategory.DEPORTED_EXCLUDED,),
        "p4_9d": (EventCategory.REMOVAL_ORDER,),
        "p4_9e": (EventCategory.DENIAL_OF_ADMISSION,),
        "p4_9f": (EventCategory.VOLUNTARY_DEPARTURE_OVERSTAYED,),
    }

    event_categories_tier2 = {e.category for e in events_list if e.source_tier <= 2}
    for item_id, required in required_categories.items():
        answer = _normalize_answer(answers_by_item.get(item_id))
        if answer not in _YES_VALUES:
            continue
        if not any(cat in event_categories_tier2 for cat in required):
            conflicts.append(
                {
                    "item_id": item_id,
                    "kind": "unsupported_yes",
                    "category": required[0],
                    "event": None,
                    "message": (
                        f"Item {item_id} is answered 'Yes' but no tier-1/2 evidence of "
                        f"{required[0].value} was found."
                    ),
                }
            )

    return conflicts


# ---------------------------------------------------------------------------
# Placeholder events (Yes answers without corroborating facts)
# ---------------------------------------------------------------------------
#
# When the applicant's answer for a Part 4 Yes/No item is "Yes" but we do not
# yet have a classified event (no date, no authority, no location), we must
# still emit a compliant Part 9 addendum. ``placeholder_event_for_item``
# returns an empty-slot event whose ``build_part9_text`` output uses the
# conservative fallbacks ("on or about (date to be confirmed)", etc.) so the
# generated PDF never leaves the narrative blank and never reuses generic
# wording like "was detained/arrested by law enforcement".

_ITEM_TO_PLACEHOLDER_CATEGORY: dict[str, EventCategory] = {
    "p3_9": EventCategory.IMMIGRATION_DETENTION,
    "p4_1b": EventCategory.IMMIGRATION_DETENTION,
    "p4_1c": EventCategory.FORMAL_CHARGE,
    "p4_1d": EventCategory.CONVICTION,
    "p4_1e": EventCategory.DIVERSION_DEFERRED_WITHHELD,
    "p4_1f": EventCategory.PROBATION_PAROLE_SUSPENDED,
    "p4_1g": EventCategory.JAIL_PRISON,
    "p4_9a": EventCategory.REMOVAL_PROCEEDINGS_PENDING,
    "p4_9b": EventCategory.REMOVAL_PROCEEDINGS_INITIATED,
    "p4_9c": EventCategory.DEPORTED_EXCLUDED,
    "p4_9d": EventCategory.REMOVAL_ORDER,
    "p4_9e": EventCategory.DENIAL_OF_ADMISSION,
    "p4_9f": EventCategory.VOLUNTARY_DEPARTURE_OVERSTAYED,
}


def placeholder_event_for_item(item_id: str) -> ClassifiedEvent | None:
    """Return a fact-less ``ClassifiedEvent`` for a Part 4 Yes answer.

    The returned event carries an empty ``date``, ``authority``, ``location``
    and ``reason`` so :func:`build_part9_text` emits the "to be confirmed"
    fallbacks. ``source_tier`` is set to 4 so the event never qualifies as
    strong evidence and never activates hard categories elsewhere.
    """
    normalized = (item_id or "").strip().lower()
    category = _ITEM_TO_PLACEHOLDER_CATEGORY.get(normalized)
    if category is None:
        return None
    authority_kind = "immigration" if category in IMMIGRATION_CATEGORIES else "criminal"
    return ClassifiedEvent(
        category=category,
        authority_kind=authority_kind,
        source_tier=4,
        needs_paraphrase=True,
    )


__all__ = [
    "CATEGORY_TO_PART4_ITEMS",
    "CRIMINAL_CATEGORIES",
    "ClassifiedEvent",
    "EventCategory",
    "IMMIGRATION_CATEGORIES",
    "MIN_TIER_BY_CATEGORY",
    "build_part4_table_rows",
    "build_part9_text",
    "classify_evidence_events",
    "detect_category_conflicts",
    "map_events_to_part4_items",
    "placeholder_event_for_item",
]
