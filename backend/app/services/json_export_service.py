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
from typing import Any

from .gemini_runtime_service import ZERO_TOKEN_SUMMARY, sum_token_summaries
from .paths import EXPORTS_PREFIX
from .storage_service import S3StorageService

log = logging.getLogger("json_export")

_write_lock = threading.Lock()

_ZERO_TOKENS = ZERO_TOKEN_SUMMARY


def _get_s3() -> S3StorageService:
    from ..dependencies import get_s3_service
    return get_s3_service()


def _write_json_s3(key: str, data: Any) -> str:
    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    with _write_lock:
        _get_s3().upload_bytes(content, key, "application/json")
    log.info("Wrote %s to S3 (%d bytes)", key, len(content))
    return key


def _read_json_s3(key: str) -> dict | None:
    try:
        raw = _get_s3().download_bytes(key)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


_sum_tokens = sum_token_summaries


# ---------------------------------------------------------------------------
# 1) Extraction result JSON
# ---------------------------------------------------------------------------

def save_extraction_json(case_id: str, pages: list[dict]) -> str:
    key = f"{EXPORTS_PREFIX}/extraction_{case_id}.json"
    payload = {
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(pages),
        "pages": pages,
    }
    return _write_json_s3(key, payload)


# ---------------------------------------------------------------------------
# 2) Token usage JSON -- concise, written ONCE at end of pipeline
# ---------------------------------------------------------------------------

def save_final_token_summary(
    case_id: str,
    *,
    phases: dict[str, dict],
    total_pages: int = 0,
) -> str:
    """Write a concise token summary with global totals and per-phase breakdown.

    phases: {"ocr": {"token_summary": {...}, ...}, "indexing": {...}, "autopilot": {...}}
    No per-page detail is stored -- just phases and a single global roll-up.
    """
    # --- DISABLED: token usage JSON generation ---
    # out_dir = _ensure_exports_dir()
    # path = out_dir / f"token_usage_{case_id}.json"
    #
    # global_totals = dict(_ZERO_TOKENS)
    # for phase_data in phases.values():
    #     if not isinstance(phase_data, dict):
    #         continue
    #     ts = phase_data.get("token_summary")
    #     if isinstance(ts, dict):
    #         global_totals = _sum_tokens(global_totals, ts)
    #
    # payload = {
    #     "case_id": case_id,
    #     "generated_at": datetime.now(timezone.utc).isoformat(),
    #     "total_pages": total_pages,
    #     "global_totals": global_totals,
    #     "phases": phases,
    # }
    # _write_json(path, payload)
    # return path
    return f"{EXPORTS_PREFIX}/token_usage_{case_id}.json"


# ---------------------------------------------------------------------------
# Legacy helpers kept for backward compat (extraction router, etc.)
# ---------------------------------------------------------------------------

def save_token_usage_json(
    case_id: str,
    *,
    page_summaries: list[dict],
    global_totals: dict,
) -> str:
    # --- DISABLED: token usage JSON generation ---
    # out_dir = _ensure_exports_dir()
    # path = out_dir / f"token_usage_{case_id}.json"
    # payload = {
    #     "case_id": case_id,
    #     "generated_at": datetime.now(timezone.utc).isoformat(),
    #     "total_pages": len(page_summaries),
    #     "global_totals": global_totals,
    #     "phases": {"ocr": {"token_summary": global_totals}},
    # }
    # _write_json(path, payload)
    # return path
    return f"{EXPORTS_PREFIX}/token_usage_{case_id}.json"


def merge_token_usage_json(
    case_id: str,
    *,
    phase_name: str,
    token_summary: dict,
    extra_payload: dict | None = None,
) -> str:
    # --- DISABLED: token usage JSON generation ---
    # out_dir = _ensure_exports_dir()
    # path = out_dir / f"token_usage_{case_id}.json"
    # payload = read_token_usage_json(case_id) or {
    #     "case_id": case_id,
    #     "generated_at": datetime.now(timezone.utc).isoformat(),
    #     "total_pages": 0,
    #     "global_totals": dict(_ZERO_TOKENS),
    #     "phases": {},
    # }
    # payload.pop("pages", None)
    # payload.setdefault("phases", {})
    # payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    # payload["phases"][phase_name] = {
    #     "token_summary": token_summary,
    #     **(extra_payload or {}),
    # }
    # global_totals = dict(_ZERO_TOKENS)
    # for phase_data in payload["phases"].values():
    #     if not isinstance(phase_data, dict):
    #         continue
    #     ts = phase_data.get("token_summary")
    #     if isinstance(ts, dict):
    #         global_totals = _sum_tokens(global_totals, ts)
    # payload["global_totals"] = global_totals
    # _write_json(path, payload)
    # return path
    return f"{EXPORTS_PREFIX}/token_usage_{case_id}.json"


def merge_ocr_token_usage_json(
    case_id: str,
    *,
    page_summaries: list[dict],
    global_totals: dict,
) -> str:
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
    return _read_json_s3(f"{EXPORTS_PREFIX}/extraction_{case_id}.json")


def read_token_usage_json(case_id: str) -> dict | None:
    return _read_json_s3(f"{EXPORTS_PREFIX}/token_usage_{case_id}.json")
