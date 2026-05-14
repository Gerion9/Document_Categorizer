"""Centralized date parsing and formatting helpers.

The canonical project-wide output format is ``"Mmm DD YYYY"`` (e.g. ``"Mar 21 1979"``)
with English month abbreviations. Parsing is intentionally lenient so legacy values
(``"MM/DD/YYYY"``, ISO 8601, ``"DD/MM/YYYY"``, ``"Month D, YYYY"``, etc.) keep working
during the migration.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Optional

from .text import clean_text


LONG_DATE_FORMAT_HUMAN = "Mmm DD YYYY"
LONG_DATE_EXAMPLE = "Mar 21 1979"

MONTH_ABBR_EN: tuple[str, ...] = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


_MONTH_NAME_TO_NUMBER: dict[str, int] = {
    # English
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
    # Spanish (legacy/tolerant input)
    "ene": 1, "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abr": 4, "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "ago": 8, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "set": 9,
    "octubre": 10,
    "noviembre": 11,
    "dic": 12, "diciembre": 12,
}


LONG_DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{4})\b",
    re.IGNORECASE,
)


_NUMERIC_DATE_FORMATS: tuple[str, ...] = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d/%m/%y",
)


def _strip_accents(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_month_token(token: str) -> str:
    return _strip_accents(token or "").strip().lower().rstrip(".")


def month_token_to_number(token: str) -> Optional[int]:
    """Resolve a month token (``"Mar"``, ``"marzo"``, ``"sept."`` ...) to ``1..12``."""
    return _MONTH_NAME_TO_NUMBER.get(_normalize_month_token(token))


def _expand_two_digit_year(year: int) -> int:
    if year >= 100:
        return year
    return year + (2000 if year < 50 else 1900)


def parse_date_text(value: Any) -> Optional[date]:
    """Best-effort parse of arbitrary date-like text into a ``date`` object.

    Accepts (in priority order):

    * ``Mmm DD YYYY`` (canonical) and ``Mmm D, YYYY`` / ``Mmm-DD-YYYY`` variants.
    * ISO 8601 dates and datetimes (``2024-03-21``, ``2024-03-21T14:30:00Z``).
    * Numeric slash/dash/dot separated dates: ``MM/DD/YYYY``, ``M/D/YY``,
      ``YYYY/MM/DD``, ``DD/MM/YYYY`` (US-first interpretation when ambiguous).
    * Long textual forms: ``January 21, 1979``, ``21 de marzo de 1979`` (Spanish),
      ``21 March 1979``.

    Returns ``None`` when the value cannot be parsed.
    """
    raw = clean_text(value)
    if not raw:
        return None

    iso_attempt = raw.replace("T", " ").split()[0] if "T" in raw else None
    if iso_attempt:
        try:
            return datetime.fromisoformat(iso_attempt).date()
        except ValueError:
            pass

    long_match = LONG_DATE_RE.search(raw)
    if long_match:
        month = month_token_to_number(long_match.group(1))
        day = int(long_match.group(2))
        year = int(long_match.group(3))
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None

    numeric = (
        raw.replace(".", "/").replace("-", "/").replace(" ", "/")
    )
    while "//" in numeric:
        numeric = numeric.replace("//", "/")
    numeric = numeric.strip("/")
    for fmt in _NUMERIC_DATE_FORMATS:
        try:
            return datetime.strptime(numeric, fmt).date()
        except ValueError:
            continue

    textual = re.sub(r"[,/.\-]", " ", raw)
    textual = re.sub(r"\bde\b", " ", textual, flags=re.IGNORECASE)
    textual = " ".join(textual.split())

    day_first = re.fullmatch(
        r"(?i)(\d{1,2})\s+([A-Za-z\u00c0-\u017f]{3,12})\.?\s+(\d{2,4})",
        textual,
    )
    month_first = re.fullmatch(
        r"(?i)([A-Za-z\u00c0-\u017f]{3,12})\.?\s+(\d{1,2})\s+(\d{2,4})",
        textual,
    )
    for match, day_index, month_index, year_index in (
        (day_first, 1, 2, 3),
        (month_first, 2, 1, 3),
    ):
        if not match:
            continue
        day = int(match.group(day_index))
        month = month_token_to_number(match.group(month_index))
        if not month:
            continue
        year = _expand_two_digit_year(int(match.group(year_index)))
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None


def format_long_date(value: Any) -> str:
    """Format a date-like value as ``"Mmm DD YYYY"`` or return ``""``.

    Accepts ``date`` / ``datetime`` instances or any string parseable by
    :func:`parse_date_text`.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        d = parse_date_text(value)
        if d is None:
            return ""
    return f"{MONTH_ABBR_EN[d.month - 1]} {d.day:02d} {d.year:04d}"


def format_long_datetime(value: Any, *, include_seconds: bool = False) -> str:
    """Format a datetime-like value as ``"Mmm DD YYYY HH:MM"`` or ``""``.

    Strings without an explicit time component fall back to ``format_long_date``.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return format_long_date(value)
    else:
        text = clean_text(value)
        if not text:
            return ""
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return format_long_date(text)
    pattern = "%H:%M:%S" if include_seconds else "%H:%M"
    return f"{format_long_date(dt)} {dt.strftime(pattern)}"


def normalize_date_text_to_long(value: Any) -> str:
    """Parse a free-form date string and emit the canonical ``"Mmm DD YYYY"``.

    Returns ``""`` when the input cannot be interpreted as a date.
    """
    parsed = parse_date_text(value)
    if parsed is None:
        return ""
    return format_long_date(parsed)


__all__ = [
    "LONG_DATE_EXAMPLE",
    "LONG_DATE_FORMAT_HUMAN",
    "LONG_DATE_RE",
    "MONTH_ABBR_EN",
    "format_long_date",
    "format_long_datetime",
    "month_token_to_number",
    "normalize_date_text_to_long",
    "parse_date_text",
]
