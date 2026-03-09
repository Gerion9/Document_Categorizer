"""
Persists extraction results and token usage as JSON files under /storage/exports/.

Two files per case extraction run:
  1. extraction_<case_id>.json  -- full OCR text extracted from every page
  2. token_usage_<case_id>.json -- per-page token breakdown + global totals
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("json_export")

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"
EXPORTS_DIR = STORAGE_DIR / "exports"

_write_lock = threading.Lock()


def _ensure_exports_dir() -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORTS_DIR


def _write_json(path: Path, data: Any) -> None:
    with _write_lock:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Wrote %s (%d bytes)", path.name, path.stat().st_size)


# ---------------------------------------------------------------------------
# 1) Extraction result JSON
# ---------------------------------------------------------------------------

def save_extraction_json(case_id: str, pages: list[dict]) -> Path:
    """
    Write a JSON with all extracted text for a case.

    Expected page dict keys: page_id, page_number, original_filename,
    extraction_method, extraction_status, ocr_text, chars.
    """
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
# 2) Token usage JSON
# ---------------------------------------------------------------------------

def save_token_usage_json(
    case_id: str,
    *,
    page_summaries: list[dict],
    global_totals: dict,
) -> Path:
    """
    Write a JSON with per-page token usage and global totals.

    page_summaries: list of {page_id, page_number, tokens: {input, output, cached, ...}}
    global_totals:  {input, output, cached, thoughts, embedding, grand_total}
    """
    out_dir = _ensure_exports_dir()
    path = out_dir / f"token_usage_{case_id}.json"

    payload = {
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(page_summaries),
        "global_totals": global_totals,
        "pages": page_summaries,
        "phases": {
            "ocr": {
                "token_summary": global_totals,
            }
        },
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
        "global_totals": {
            "input": 0,
            "output": 0,
            "cached": 0,
            "thoughts": 0,
            "embedding": 0,
            "grand_total": 0,
        },
        "pages": [],
        "phases": {},
    }

    payload.setdefault("phases", {})
    previous_token_summary = (
        payload["phases"].get(phase_name, {}).get("token_summary", {})
        if isinstance(payload["phases"].get(phase_name), dict)
        else {}
    )
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["phases"][phase_name] = {
        "token_summary": token_summary,
        **(extra_payload or {}),
    }
    global_totals = payload.setdefault("global_totals", {})
    for key in ("input", "output", "cached", "thoughts", "embedding", "grand_total"):
        global_totals[key] = (
            int(global_totals.get(key, 0) or 0)
            - int(previous_token_summary.get(key, 0) or 0)
            + int(token_summary.get(key, 0) or 0)
        )

    _write_json(path, payload)
    return path


def merge_ocr_token_usage_json(
    case_id: str,
    *,
    page_summaries: list[dict],
    global_totals: dict,
) -> Path:
    out_dir = _ensure_exports_dir()
    path = out_dir / f"token_usage_{case_id}.json"
    payload = read_token_usage_json(case_id) or {
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": 0,
        "global_totals": {
            "input": 0,
            "output": 0,
            "cached": 0,
            "thoughts": 0,
            "embedding": 0,
            "grand_total": 0,
        },
        "pages": [],
        "phases": {},
    }

    existing_pages = {
        str(page.get("page_id", "") or ""): page
        for page in payload.get("pages", [])
        if isinstance(page, dict)
    }
    for page_summary in page_summaries:
        page_id = str(page_summary.get("page_id", "") or "")
        if page_id:
            existing_pages[page_id] = page_summary

    payload["pages"] = sorted(
        existing_pages.values(),
        key=lambda page: int(page.get("page_number", 0) or 0),
    )
    payload["total_pages"] = len(payload["pages"])
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()

    ocr_totals = (
        payload.get("phases", {})
        .get("ocr", {})
        .get("token_summary", {})
    )
    merged_ocr_totals = {}
    for key in ("input", "output", "cached", "thoughts", "embedding", "grand_total"):
        merged_ocr_totals[key] = int(ocr_totals.get(key, 0) or 0) + int(global_totals.get(key, 0) or 0)

    phases = payload.setdefault("phases", {})
    phases["ocr"] = {"token_summary": merged_ocr_totals}

    payload["global_totals"] = merged_ocr_totals
    for phase_name, phase_payload in phases.items():
        if phase_name == "ocr" or not isinstance(phase_payload, dict):
            continue
        token_summary = phase_payload.get("token_summary", {})
        if not isinstance(token_summary, dict):
            continue
        for key in ("input", "output", "cached", "thoughts", "embedding", "grand_total"):
            payload["global_totals"][key] = int(payload["global_totals"].get(key, 0) or 0) + int(token_summary.get(key, 0) or 0)

    _write_json(path, payload)
    return path


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
