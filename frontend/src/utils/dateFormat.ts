/**
 * Centralized date parsing and formatting helpers.
 *
 * The canonical project-wide output format is `"Mmm DD YYYY"` (e.g. `"Mar 21 1979"`)
 * with English month abbreviations. Parsing is intentionally lenient so legacy
 * values (`"MM/DD/YYYY"`, ISO 8601, `"DD/MM/YYYY"`, `"Month D, YYYY"`, etc.) keep
 * working during the migration.
 *
 * Always go through these helpers when displaying or storing dates so the
 * canonical format stays consistent across the UI, backend payloads, and PDF
 * outputs.
 */

export const MONTH_ABBR_EN = [
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
] as const;

export const LONG_DATE_FORMAT_HUMAN = "Mmm DD, YYYY";
export const LONG_DATE_EXAMPLE = "Mar 21, 1979";
export const LONG_DATE_PLACEHOLDER = LONG_DATE_FORMAT_HUMAN;

const MONTH_ABBR_LOOKUP: Record<string, number> = (() => {
  const entries: Array<[string, number]> = [
    ["jan", 1], ["january", 1], ["ene", 1], ["enero", 1],
    ["feb", 2], ["february", 2], ["febrero", 2],
    ["mar", 3], ["march", 3], ["marzo", 3],
    ["apr", 4], ["april", 4], ["abr", 4], ["abril", 4],
    ["may", 5], ["mayo", 5],
    ["jun", 6], ["june", 6], ["junio", 6],
    ["jul", 7], ["july", 7], ["julio", 7],
    ["aug", 8], ["august", 8], ["ago", 8], ["agosto", 8],
    ["sep", 9], ["sept", 9], ["september", 9], ["septiembre", 9], ["setiembre", 9],
    ["oct", 10], ["october", 10], ["octubre", 10],
    ["nov", 11], ["november", 11], ["noviembre", 11],
    ["dec", 12], ["december", 12], ["dic", 12], ["diciembre", 12],
  ];
  return Object.fromEntries(entries) as Record<string, number>;
})();

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_DATETIME_RE = /^(\d{4})-(\d{2})-(\d{2})T/;
const NUMERIC_DATE_RE = /^(\d{1,4})[\/\-.](\d{1,2})[\/\-.](\d{1,4})$/;
const LONG_DATE_RE = /\b([A-Za-z\u00C0-\u017F]{3,12})\.?\s+(\d{1,2})\s*,?\s*(\d{2,4})\b/;
const DAY_FIRST_LONG_RE = /\b(\d{1,2})\s+([A-Za-z\u00C0-\u017F]{3,12})\.?\s+(\d{2,4})\b/;
const TIMESTAMP_TZ_RE = /(?:Z|[+-]\d{2}:\d{2})$/i;

function stripAccents(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function normalizeMonthToken(token: string): string {
  return stripAccents((token || "").trim().toLowerCase()).replace(/\.$/, "");
}

function expandTwoDigitYear(year: number): number {
  if (year >= 100) return year;
  return year + (year < 50 ? 2000 : 1900);
}

function buildDate(year: number, month: number, day: number): Date | null {
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return null;
  }
  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;
  const dt = new Date(year, month - 1, day);
  if (
    dt.getFullYear() !== year ||
    dt.getMonth() !== month - 1 ||
    dt.getDate() !== day
  ) {
    return null;
  }
  return dt;
}

/**
 * Parse a free-form date string into a `Date` (local time, midnight).
 *
 * Returns `null` when the value cannot be interpreted.
 */
export function parseFlexibleDate(input: unknown): Date | null {
  if (input == null) return null;
  if (input instanceof Date) {
    return Number.isNaN(input.getTime()) ? null : input;
  }
  const raw = String(input).trim();
  if (!raw) return null;

  const isoDateOnly = raw.match(ISO_DATE_RE);
  if (isoDateOnly) {
    const [, y, m, d] = isoDateOnly;
    return buildDate(Number(y), Number(m), Number(d));
  }

  const isoDateTime = raw.match(ISO_DATETIME_RE);
  if (isoDateTime) {
    const [, y, m, d] = isoDateTime;
    return buildDate(Number(y), Number(m), Number(d));
  }

  const cleanedTextual = raw
    .replace(/\bde\b/gi, " ")
    .replace(/[,/.\-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  for (const candidate of [raw, cleanedTextual]) {
    const dayFirstLong = candidate.match(DAY_FIRST_LONG_RE);
    if (dayFirstLong) {
      const month = MONTH_ABBR_LOOKUP[normalizeMonthToken(dayFirstLong[2])];
      if (month) {
        const day = Number(dayFirstLong[1]);
        const year = expandTwoDigitYear(Number(dayFirstLong[3]));
        const built = buildDate(year, month, day);
        if (built) return built;
      }
    }

    const longMatch = candidate.match(LONG_DATE_RE);
    if (longMatch) {
      const month = MONTH_ABBR_LOOKUP[normalizeMonthToken(longMatch[1])];
      if (month) {
        const day = Number(longMatch[2]);
        const year = expandTwoDigitYear(Number(longMatch[3]));
        const built = buildDate(year, month, day);
        if (built) return built;
      }
    }
  }

  const numericMatch = raw.match(NUMERIC_DATE_RE);
  if (numericMatch) {
    const [, a, b, c] = numericMatch;
    const aNum = Number(a);
    const bNum = Number(b);
    const cNum = Number(c);
    if (a.length === 4) {
      const built = buildDate(aNum, bNum, cNum);
      if (built) return built;
    }
    if (c.length === 4 || c.length === 2) {
      const year = expandTwoDigitYear(cNum);
      const usFirst = buildDate(year, aNum, bNum);
      if (usFirst) return usFirst;
      const dayFirst = buildDate(year, bNum, aNum);
      if (dayFirst) return dayFirst;
    }
  }

  const fallback = new Date(raw);
  if (!Number.isNaN(fallback.getTime())) {
    return fallback;
  }
  return null;
}

function pad2(value: number): string {
  return value.toString().padStart(2, "0");
}

function pad4(value: number): string {
  return value.toString().padStart(4, "0");
}

/**
 * Format a date-like value as `"Mmm DD, YYYY"` (e.g. `"Mar 21, 1979"`).
 *
 * Returns `""` for empty/invalid inputs.
 */
export function formatLongDate(input: unknown): string {
  const dt =
    input instanceof Date ? (Number.isNaN(input.getTime()) ? null : input) : parseFlexibleDate(input);
  if (!dt) return "";
  return `${MONTH_ABBR_EN[dt.getMonth()]} ${pad2(dt.getDate())}, ${pad4(dt.getFullYear())}`;
}

/**
 * Format a datetime-like value as `"Mmm DD, YYYY HH:MM"`.
 *
 * Returns `""` for empty/invalid inputs.
 */
export function formatLongDateTime(input: unknown): string {
  let dt: Date | null = null;
  if (input instanceof Date) {
    dt = Number.isNaN(input.getTime()) ? null : input;
  } else if (typeof input === "string") {
    const trimmed = input.trim();
    if (!trimmed) return "";
    const normalized = TIMESTAMP_TZ_RE.test(trimmed) ? trimmed : `${trimmed}Z`;
    const parsed = new Date(normalized);
    dt = Number.isNaN(parsed.getTime()) ? parseFlexibleDate(trimmed) : parsed;
  } else {
    dt = parseFlexibleDate(input);
  }
  if (!dt) return "";
  const hasTimeComponent = dt.getHours() !== 0 || dt.getMinutes() !== 0 || dt.getSeconds() !== 0;
  if (!hasTimeComponent) {
    return formatLongDate(dt);
  }
  return `${formatLongDate(dt)} ${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
}

/**
 * Convert a stored date string into the `yyyy-mm-dd` representation expected by
 * native `<input type="date">` controls.
 */
export function toDateInputValue(stored: string | null | undefined): string {
  if (!stored) return "";
  const dt = parseFlexibleDate(stored);
  if (!dt) return "";
  return `${pad4(dt.getFullYear())}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}`;
}

/**
 * Convert the `yyyy-mm-dd` value emitted by `<input type="date">` into the
 * canonical project-wide stored format `"Mmm DD, YYYY"`.
 */
export function fromDateInputValue(picker: string | null | undefined): string {
  if (!picker) return "";
  const trimmed = picker.trim();
  if (!trimmed) return "";
  const match = trimmed.match(ISO_DATE_RE);
  if (!match) {
    return formatLongDate(trimmed);
  }
  const [, y, m, d] = match;
  const built = buildDate(Number(y), Number(m), Number(d));
  if (!built) return "";
  return formatLongDate(built);
}
