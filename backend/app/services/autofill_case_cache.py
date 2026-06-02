"""Shared in-memory cache for questionnaire autofill preparation and evidence.

The cache is process-local and keyed by case plus document scope so client and
attorney autofill runs can reuse OCR readiness, detected context, and evidence
bundles without repeating expensive work.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

_CACHE_TTL_SECONDS = 6 * 60 * 60

_lock = threading.Lock()
_context_by_key: dict[str, dict[str, Any]] = {}
_readiness_by_case: dict[str, dict[str, Any]] = {}
_evidence_by_key: dict[str, dict[str, Any]] = {}


def scope_cache_key(case_id: str, source_document_ids: list[str] | None) -> str:
    normalized_case = str(case_id or "").strip()
    if not source_document_ids:
        return normalized_case
    scope = ",".join(sorted(str(doc_id) for doc_id in source_document_ids if str(doc_id)))
    return f"{normalized_case}:{scope}"


def _is_fresh(created_at: float) -> bool:
    return (time.time() - created_at) <= _CACHE_TTL_SECONDS


@dataclass(frozen=True)
class AutofillCaseContext:
    form_type: str
    detected_name: str
    applicant_context: str


def store_autofill_context(
    case_id: str,
    source_document_ids: list[str] | None,
    *,
    form_type: str,
    detected_name: str,
    applicant_context: str,
) -> None:
    key = scope_cache_key(case_id, source_document_ids)
    with _lock:
        _context_by_key[key] = {
            "form_type": form_type,
            "detected_name": detected_name,
            "applicant_context": applicant_context,
            "created_at": time.time(),
        }


def get_autofill_context(
    case_id: str,
    source_document_ids: list[str] | None,
) -> AutofillCaseContext | None:
    key = scope_cache_key(case_id, source_document_ids)
    with _lock:
        payload = _context_by_key.get(key)
        if payload is None or not _is_fresh(float(payload.get("created_at") or 0.0)):
            return None
        return AutofillCaseContext(
            form_type=str(payload.get("form_type") or ""),
            detected_name=str(payload.get("detected_name") or ""),
            applicant_context=str(payload.get("applicant_context") or ""),
        )


def store_case_readiness_snapshot(case_id: str, snapshot: Mapping[str, Any]) -> None:
    normalized_case = str(case_id or "").strip()
    if not normalized_case:
        return
    with _lock:
        _readiness_by_case[normalized_case] = {
            **dict(snapshot),
            "created_at": time.time(),
        }


def get_case_readiness_snapshot(case_id: str) -> dict[str, Any] | None:
    normalized_case = str(case_id or "").strip()
    with _lock:
        payload = _readiness_by_case.get(normalized_case)
        if payload is None or not _is_fresh(float(payload.get("created_at") or 0.0)):
            return None
        return dict(payload)


def get_cached_evidence(
    case_id: str,
    source_document_ids: list[str] | None,
    query_text: str,
) -> dict[str, Any] | None:
    key = f"{scope_cache_key(case_id, source_document_ids)}::{query_text}"
    with _lock:
        payload = _evidence_by_key.get(key)
        if payload is None or not _is_fresh(float(payload.get("created_at") or 0.0)):
            return None
        bundle = payload.get("bundle")
        return dict(bundle) if isinstance(bundle, dict) else None


def store_cached_evidence(
    case_id: str,
    source_document_ids: list[str] | None,
    query_text: str,
    bundle: Mapping[str, Any],
) -> None:
    key = f"{scope_cache_key(case_id, source_document_ids)}::{query_text}"
    with _lock:
        _evidence_by_key[key] = {
            "bundle": dict(bundle),
            "created_at": time.time(),
        }


def clear_case_cache(case_id: str) -> None:
    normalized_case = str(case_id or "").strip()
    with _lock:
        _readiness_by_case.pop(normalized_case, None)
        stale_context = [
            key for key in _context_by_key if key == normalized_case or key.startswith(f"{normalized_case}:")
        ]
        for key in stale_context:
            _context_by_key.pop(key, None)
        stale_evidence = [
            key for key in _evidence_by_key if key.startswith(f"{normalized_case}::") or key.startswith(f"{normalized_case}:")
        ]
        for key in stale_evidence:
            _evidence_by_key.pop(key, None)
