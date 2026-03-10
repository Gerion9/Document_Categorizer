"""
Persists extraction results and token usage as JSON files under /storage/exports/.

Two files per case extraction run:
  1. extraction_<case_id>.json  -- full OCR text extracted from every page
  2. token_usage_<case_id>.json -- concise global + per-phase token summary
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .gemini_runtime_service import ZERO_TOKEN_SUMMARY, sum_token_summaries
from .paths import EXPORTS_DIR, STORAGE_DIR

log = logging.getLogger("json_export")

_write_lock = threading.Lock()

_ZERO_TOKENS = ZERO_TOKEN_SUMMARY


def _ensure_exports_dir() -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORTS_DIR


def _write_json(path: Path, data: Any) -> None:
    with _write_lock:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Wrote %s (%d bytes)", path.name, path.stat().st_size)


_sum_tokens = sum_token_summaries


# ---------------------------------------------------------------------------
# 1) Extraction result JSON
# ---------------------------------------------------------------------------

def save_extraction_json(case_id: str, pages: list[dict]) -> Path:
    out_dir = _ensure_exports_dir()
    path = out_dir / f"extraction_{case_id}.json"

    payload = {
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(pages),
        "pages": pages,
    }
    _write_json(path, payload)
    return path


# ---------------------------------------------------------------------------
# 2) Token usage JSON -- concise, written ONCE at end of pipeline
# ---------------------------------------------------------------------------

def save_final_token_summary(
    case_id: str,
    *,
    phases: dict[str, dict],
    total_pages: int = 0,
) -> Path:
    """Write a concise token summary with global totals and per-phase breakdown.

    phases: {"ocr": {"token_summary": {...}, ...}, "indexing": {...}, "autopilot": {...}}
    No per-page detail is stored -- just phases and a single global roll-up.
    """
    out_dir = _ensure_exports_dir()
    path = out_dir / f"token_usage_{case_id}.json"

    global_totals = dict(_ZERO_TOKENS)
    for phase_data in phases.values():
        if not isinstance(phase_data, dict):
            continue
        ts = phase_data.get("token_summary")
        if isinstance(ts, dict):
            global_totals = _sum_tokens(global_totals, ts)

    payload = {
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": total_pages,
        "global_totals": global_totals,
        "phases": phases,
    }
    _write_json(path, payload)
    return path


# ---------------------------------------------------------------------------
# Legacy helpers kept for backward compat (extraction router, etc.)
# ---------------------------------------------------------------------------

def save_token_usage_json(
    case_id: str,
    *,
    page_summaries: list[dict],
    global_totals: dict,
) -> Path:
    out_dir = _ensure_exports_dir()
    path = out_dir / f"token_usage_{case_id}.json"
    payload = {
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(page_summaries),
        "global_totals": global_totals,
        "phases": {"ocr": {"token_summary": global_totals}},
    }
    _write_json(path, payload)
    return path


def merge_token_usage_json(
    case_id: str,
    *,
    phase_name: str,
    token_summary: dict,
    extra_payload: dict | None = None,
) -> Path:
    out_dir = _ensure_exports_dir()
    path = out_dir / f"token_usage_{case_id}.json"
    payload = read_token_usage_json(case_id) or {
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": 0,
        "global_totals": dict(_ZERO_TOKENS),
        "phases": {},
    }
    payload.pop("pages", None)
    payload.setdefault("phases", {})
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["phases"][phase_name] = {
        "token_summary": token_summary,
        **(extra_payload or {}),
    }
    global_totals = dict(_ZERO_TOKENS)
    for phase_data in payload["phases"].values():
        if not isinstance(phase_data, dict):
            continue
        ts = phase_data.get("token_summary")
        if isinstance(ts, dict):
            global_totals = _sum_tokens(global_totals, ts)
    payload["global_totals"] = global_totals
    _write_json(path, payload)
    return path


def merge_ocr_token_usage_json(
    case_id: str,
    *,
    page_summaries: list[dict],
    global_totals: dict,
) -> Path:
    return merge_token_usage_json(
        case_id,
        phase_name="ocr",
        token_summary=global_totals,
        extra_payload={"ocr_pages_extracted": len(page_summaries)},
    )


# ---------------------------------------------------------------------------
# Read helpers (for API endpoints)
# ---------------------------------------------------------------------------

def read_extraction_json(case_id: str) -> dict | None:
    path = EXPORTS_DIR / f"extraction_{case_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_token_usage_json(case_id: str) -> dict | None:
    path = EXPORTS_DIR / f"token_usage_{case_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
