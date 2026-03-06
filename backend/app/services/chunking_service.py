from __future__ import annotations

import re


SECTION_RE = re.compile(r"^(?:Form\s+\S+|Part\s+\d+\b|Tipo de documento\s*:)", re.IGNORECASE)
FOOTER_RE = re.compile(
    r"^(?:form\s+[\w-]+\s+\d{2}/\d{2}/\d{2,4}\s+page\s+\d+\s+of\s+\d+|page\s+\d+\s+of\s+\d+|page\s+\d+|\d+)$",
    re.IGNORECASE,
)
MIN_USEFUL_LENGTH = 50


def sanitize_identifier(value: str, max_length: int = 40) -> str:
    clean = re.sub(r"[^a-z0-9-]", "-", str(value or "").lower())
    clean = re.sub(r"-+", "-", clean).strip("-")
    return clean[:max_length]


def is_section_header(line: str) -> bool:
    return bool(SECTION_RE.match(line.strip()))


def split_into_sections(text: str) -> list[str]:
    lines = text.splitlines()
    sections: list[str] = []
    buffer: list[str] = []

    for line in lines:
        if is_section_header(line) and buffer:
            sections.append("\n".join(buffer))
            buffer = []
        buffer.append(line)

    if buffer:
        sections.append("\n".join(buffer))
    return sections


def sliding_window(text: str, size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    cursor = 0

    while cursor < len(text):
        end = min(cursor + size, len(text))
        chunk = text[cursor:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        cursor = max(0, end - overlap)

    return chunks


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    if not isinstance(text, str):
        return []

    trimmed = text.strip()
    if not trimmed:
        return []

    sections = split_into_sections(trimmed)
    chunks: list[str] = []

    for section in sections:
        if len(section) <= chunk_size:
            candidate = section.strip()
            if candidate:
                chunks.append(candidate)
            continue

        first_newline = section.find("\n")
        first_line = section[:first_newline].strip() if first_newline >= 0 else section.strip()
        section_header = first_line if is_section_header(first_line) else ""
        header_prefix = f"{section_header}\n\n" if section_header else ""
        effective_size = max(chunk_size - len(header_prefix), chunk_size // 2)

        paragraphs = [p for p in re.split(r"\n\s*\n", section) if p.strip()]
        current = ""

        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else f"{header_prefix}{paragraph}"

            if len(candidate) <= chunk_size:
                current = candidate
                continue

            if current.strip():
                chunks.append(current.strip())

            if len(header_prefix) + len(paragraph) <= chunk_size:
                current = f"{header_prefix}{paragraph}"
                continue

            for subchunk in sliding_window(paragraph, effective_size, overlap):
                candidate_subchunk = f"{header_prefix}{subchunk}".strip()
                if candidate_subchunk:
                    chunks.append(candidate_subchunk)
            current = ""

        if current.strip():
            chunks.append(current.strip())

    return [chunk for chunk in chunks if chunk]


def is_garbage_chunk(text: str) -> bool:
    trimmed = text.strip()
    if len(trimmed) < MIN_USEFUL_LENGTH:
        return True
    if FOOTER_RE.match(trimmed):
        return True
    alnum_count = len(re.findall(r"[a-zA-Z0-9]", trimmed))
    return alnum_count < len(trimmed) * 0.3


def extract_section_label(text: str) -> str:
    first_line = text.splitlines()[0].strip() if text.strip() else ""
    if is_section_header(first_line):
        return first_line[:120]
    return ""
