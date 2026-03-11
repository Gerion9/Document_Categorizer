from __future__ import annotations

import json
from typing import Any


def _format_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    """Add a human-readable source label to a structured evidence item."""
    formatted = dict(item)
    parts: list[str] = []
    page = item.get("pageNumber")
    if page is not None:
        parts.append(f"p.{page}")
    section = item.get("sectionName", "")
    if section:
        parts.append(section)
    doc_type = item.get("documentType", "")
    if doc_type:
        parts.append(doc_type)
    filename = item.get("originalFilename", "")
    if filename and not parts:
        parts.append(filename)
    if parts:
        formatted["source"] = " | ".join(parts)
    return formatted


def build_rag_verify_json_payload(
    *,
    question_text: str,
    where_to_verify: str,
    text_evidence: str,
) -> str:
    payload = {
        "question": question_text,
        "where_to_verify": where_to_verify or "Not specified",
        "evidence": text_evidence or "(no evidence available)",
    }
    return json.dumps(payload, ensure_ascii=False)


def build_rag_batch_json_payload(
    questions: list[dict[str, Any]],
    evidence_by_id: dict[str, Any],
) -> str:
    """Build JSON payload for batch verification.

    ``evidence_by_id`` maps question id to either:
      - a list of structured evidence dicts (preferred), or
      - a plain text string (legacy fallback).
    """
    items: list[dict[str, Any]] = []
    evidence_section: dict[str, Any] = {}

    for question in questions:
        qid = str(question.get("id", "") or "")
        items.append(
            {
                "id": qid,
                "question": str(question.get("description", "") or ""),
                "whereToVerify": str(question.get("where_to_verify", "") or "Not specified"),
            }
        )
        raw_evidence = evidence_by_id.get(qid)
        if isinstance(raw_evidence, list):
            evidence_section[qid] = [_format_evidence_item(e) for e in raw_evidence]
        else:
            evidence_section[qid] = str(raw_evidence or "(no evidence available)")

    payload = {"questions": items, "evidence": evidence_section}
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Backward-compatible aliases
# ---------------------------------------------------------------------------
build_rag_verify_toon_payload = build_rag_verify_json_payload
build_rag_batch_toon_payload = build_rag_batch_json_payload
