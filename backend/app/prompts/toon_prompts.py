from __future__ import annotations

import math
import re
from typing import Any

_VALID_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_NUMERIC_LIKE_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$", re.IGNORECASE)
_LEADING_ZERO_RE = re.compile(r"^-?0\d+$")
_INDENT = "  "
_DELIMITER = ","


def _escape_toon_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _encode_key(value: str) -> str:
    text = str(value or "")
    if _VALID_KEY_RE.match(text):
        return text
    return f'"{_escape_toon_string(text)}"'


def _encode_string(value: str, *, delimiter: str = _DELIMITER) -> str:
    text = str(value or "")
    needs_quotes = (
        not text
        or text != text.strip()
        or text in {"true", "false", "null"}
        or bool(_NUMERIC_LIKE_RE.match(text))
        or bool(_LEADING_ZERO_RE.match(text))
        or any(ch in text for ch in (":", '"', "\\", "[", "]", "{", "}", "\n", "\r", "\t", delimiter))
        or text.startswith("-")
    )
    return f'"{_escape_toon_string(text)}"' if needs_quotes else text


def _encode_number(value: int | float) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return _encode_string(str(value))
    if value == 0:
        return "0"
    text = f"{value:.15f}".rstrip("0").rstrip(".")
    return text or "0"


def _encode_primitive(value: Any, *, delimiter: str = _DELIMITER) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _encode_number(value)
    return _encode_string(str(value), delimiter=delimiter)


def _render_object(fields: dict[str, Any], *, depth: int = 0) -> str:
    lines: list[str] = []
    prefix = _INDENT * depth
    for key, value in fields.items():
        encoded_key = _encode_key(key)
        if isinstance(value, dict):
            lines.append(f"{prefix}{encoded_key}:")
            lines.append(_render_object(value, depth=depth + 1))
        else:
            lines.append(f"{prefix}{encoded_key}: {_encode_primitive(value)}")
    return "\n".join(lines)


def _render_uniform_array(name: str, rows: list[dict[str, Any]], fields: list[str]) -> str:
    encoded_fields = _DELIMITER.join(_encode_key(field) for field in fields)
    lines = [f"{_encode_key(name)}[{len(rows)}]{{{encoded_fields}}}:"]
    for row in rows:
        encoded_cells = _DELIMITER.join(
            _encode_primitive(row.get(field, ""), delimiter=_DELIMITER)
            for field in fields
        )
        lines.append(f"{_INDENT}{encoded_cells}")
    return "\n".join(lines)


def build_rag_verify_toon_payload(
    *,
    question_text: str,
    where_to_verify: str,
    text_evidence: str,
) -> str:
    return _render_object(
        {
            "request": {
                "question": question_text,
                "where_to_verify": where_to_verify or "Not specified",
                "evidence": text_evidence or "(no evidence available)",
            }
        }
    )


def build_rag_batch_toon_payload(
    questions: list[dict[str, Any]],
    evidence_by_id: dict[str, str],
) -> str:
    rows: list[dict[str, Any]] = []
    for question in questions:
        qid = str(question.get("id", "") or "")
        rows.append(
            {
                "id": qid,
                "question": str(question.get("description", "") or ""),
                "where_to_verify": str(question.get("where_to_verify", "") or "Not specified"),
                "evidence": str(evidence_by_id.get(qid, "") or "(no evidence available)"),
            }
        )
    return _render_uniform_array(
        "questions",
        rows,
        fields=["id", "question", "where_to_verify", "evidence"],
    )
