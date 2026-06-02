import { createElement, type ReactNode } from "react";

const STOPWORDS = new Set([
  "a",
  "al",
  "and",
  "appear",
  "aparece",
  "aparecen",
  "buscar",
  "busca",
  "con",
  "de",
  "del",
  "donde",
  "dónde",
  "el",
  "en",
  "find",
  "for",
  "la",
  "las",
  "los",
  "nombre",
  "of",
  "para",
  "por",
  "que",
  "qué",
  "the",
  "un",
  "una",
  "where",
]);

interface NormalizedText {
  value: string;
  indexMap: number[];
}

export interface RagSnippet {
  text: string;
  hasLiteralMatch: boolean;
}

function normalizeForSearch(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function normalizeWithIndexMap(value: string): NormalizedText {
  let normalized = "";
  const indexMap: number[] = [];

  for (let index = 0; index < value.length; index += 1) {
    const normalizedChar = normalizeForSearch(value[index]);
    for (const char of normalizedChar) {
      normalized += char;
      indexMap.push(index);
    }
  }

  return { value: normalized, indexMap };
}

export function tokenizeQuery(query: string): string[] {
  const normalized = normalizeForSearch(query);
  const tokens = normalized.match(/[a-z0-9]+/g) ?? [];
  return Array.from(new Set(tokens.filter((token) => token.length > 1 && !STOPWORDS.has(token))));
}

function findFirstLiteralMatch(text: string, query: string): { start: number; end: number } | null {
  const tokens = tokenizeQuery(query);
  if (tokens.length === 0) return null;

  const normalizedText = normalizeWithIndexMap(text);
  let bestMatch: { start: number; end: number } | null = null;

  for (const token of tokens) {
    const normalizedIndex = normalizedText.value.indexOf(token);
    if (normalizedIndex === -1) continue;

    const start = normalizedText.indexMap[normalizedIndex] ?? 0;
    const end = (normalizedText.indexMap[normalizedIndex + token.length - 1] ?? start) + 1;
    if (!bestMatch || start < bestMatch.start) {
      bestMatch = { start, end };
    }
  }

  return bestMatch;
}

export function extractSnippet(text: string, query: string, maxLength = 420): RagSnippet {
  const normalizedText = text.trim();
  if (!normalizedText) {
    return { text: "", hasLiteralMatch: false };
  }

  if (normalizedText.length <= maxLength) {
    return { text: normalizedText, hasLiteralMatch: findFirstLiteralMatch(normalizedText, query) !== null };
  }

  const match = findFirstLiteralMatch(normalizedText, query);
  if (!match) {
    return {
      text: `${normalizedText.slice(0, maxLength).trimEnd()}...`,
      hasLiteralMatch: false,
    };
  }

  const halfWindow = Math.floor(maxLength / 2);
  const rawStart = Math.max(0, match.start - halfWindow);
  const rawEnd = Math.min(normalizedText.length, rawStart + maxLength);
  const start = Math.max(0, rawEnd - maxLength);
  const prefix = start > 0 ? "... " : "";
  const suffix = rawEnd < normalizedText.length ? " ..." : "";

  return {
    text: `${prefix}${normalizedText.slice(start, rawEnd).trim()}${suffix}`,
    hasLiteralMatch: true,
  };
}

export function highlightTerms(text: string, query: string): ReactNode[] {
  const tokens = tokenizeQuery(query);
  if (tokens.length === 0) return [text];

  const normalizedText = normalizeWithIndexMap(text);
  const ranges: Array<{ start: number; end: number }> = [];

  for (const token of tokens) {
    let searchFrom = 0;
    while (searchFrom < normalizedText.value.length) {
      const normalizedIndex = normalizedText.value.indexOf(token, searchFrom);
      if (normalizedIndex === -1) break;

      const start = normalizedText.indexMap[normalizedIndex] ?? 0;
      const end = (normalizedText.indexMap[normalizedIndex + token.length - 1] ?? start) + 1;
      ranges.push({ start, end });
      searchFrom = normalizedIndex + token.length;
    }
  }

  if (ranges.length === 0) return [text];

  const mergedRanges = ranges
    .sort((a, b) => a.start - b.start || b.end - a.end)
    .reduce<Array<{ start: number; end: number }>>((merged, range) => {
      const previous = merged[merged.length - 1];
      if (!previous || range.start > previous.end) {
        merged.push({ ...range });
      } else {
        previous.end = Math.max(previous.end, range.end);
      }
      return merged;
    }, []);

  const parts: ReactNode[] = [];
  let cursor = 0;

  mergedRanges.forEach((range, index) => {
    if (range.start > cursor) {
      parts.push(text.slice(cursor, range.start));
    }
    parts.push(
      createElement(
        "mark",
        { className: "rag-search-highlight", key: `${range.start}-${range.end}-${index}` },
        text.slice(range.start, range.end),
      ),
    );
    cursor = range.end;
  });

  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts;
}
