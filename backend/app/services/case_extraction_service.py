from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from ..database import SessionLocal
from ..models import DocumentType, Page
from .indexing_service import process_page_extraction
from .json_export_service import save_extraction_json

log = logging.getLogger("extraction")

MAX_EXTRACTION_WORKERS = int(os.getenv("MAX_EXTRACTION_WORKERS", "6"))


def _determine_has_tables(page: Page, db) -> bool:
    if page.document_type_id:
        dt = db.query(DocumentType).filter(DocumentType.id == page.document_type_id).first()
        if dt:
            return dt.has_tables or False
    return False


def _extract_single_page(page_id: str, has_tables: bool) -> tuple[str, bool, str, dict | None]:
    try:
        result = process_page_extraction(page_id, has_tables)
        return page_id, True, "", result
    except Exception as exc:
        return page_id, False, str(exc), None


def _build_extraction_pages(case_id: str) -> list[dict]:
    db = SessionLocal()
    try:
        pages = (
            db.query(Page)
            .filter(Page.case_id == case_id)
            .order_by(Page.original_page_number.asc(), Page.created_at.asc())
            .all()
        )
        return [
            {
                "page_id": page.id,
                "page_number": page.original_page_number or 0,
                "original_filename": page.original_filename or "",
                "extraction_method": page.extraction_method,
                "extraction_status": page.extraction_status or "pending",
                "chars": len(page.ocr_text or ""),
                "ocr_text": page.ocr_text or "",
            }
            for page in pages
        ]
    finally:
        db.close()


def extract_case_pages(
    case_id: str,
    *,
    page_ids: list[str] | None = None,
    only_missing: bool = False,
    progress_callback: Callable[[dict[str, int | str]], None] | None = None,
) -> dict[str, int]:
    db = SessionLocal()
    try:
        query = db.query(Page).filter(Page.case_id == case_id)
        if page_ids:
            query = query.filter(Page.id.in_([str(page_id) for page_id in page_ids]))
        pages = query.order_by(Page.original_page_number.asc(), Page.created_at.asc()).all()

        total_case_pages = len(pages)
        already_done = 0
        page_configs: list[dict[str, object]] = []
        for page in pages:
            if only_missing and (page.ocr_text or "").strip():
                already_done += 1
                continue
            page_configs.append(
                {
                    "page_id": page.id,
                    "has_tables": _determine_has_tables(page, db),
                }
            )
    finally:
        db.close()

    total = len(page_configs)
    done = 0
    failed = 0
    page_results: list[dict] = []

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "extracting_document",
                "ocr_total_pages": total_case_pages,
                "ocr_processed_pages": already_done,
                "ocr_error_pages": 0,
            }
        )

    if total:
        with ThreadPoolExecutor(max_workers=MAX_EXTRACTION_WORKERS) as pool:
            futures = [
                pool.submit(
                    _extract_single_page,
                    str(cfg["page_id"]),
                    bool(cfg["has_tables"]),
                )
                for cfg in page_configs
            ]
            for future in as_completed(futures):
                page_id, success, err, result = future.result()
                done += 1
                if not success:
                    failed += 1
                    log.error("Case extraction [%s]: page %s failed: %s", case_id[:8], page_id[:8], err)
                if result:
                    page_results.append(result)
                if progress_callback is not None:
                    progress_callback(
                        {
                            "phase": "extracting_document",
                            "ocr_total_pages": total_case_pages,
                            "ocr_processed_pages": already_done + done,
                            "ocr_error_pages": failed,
                        }
                    )
                if done % 20 == 0 or done == total:
                    log.info("Case extraction [%s]: %d/%d done (%d errors)", case_id[:8], done, total, failed)

    page_results.sort(key=lambda row: row.get("page_number", 0))

    if progress_callback is not None:
        progress_callback({"phase": "writing_json"})

    extraction_pages = _build_extraction_pages(case_id)
    save_extraction_json(case_id, extraction_pages)

    ocr_token_totals = {
        "input": 0, "output": 0, "cached": 0,
        "thoughts": 0, "embedding": 0, "grand_total": 0,
    }
    for row in page_results:
        ts = row.get("token_summary", {}) or {}
        for key in ocr_token_totals:
            ocr_token_totals[key] += int(ts.get(key, 0) or 0)

    result = {
        "queued": total,
        "processed": done,
        "errors": failed,
        "written_pages": len(extraction_pages),
        "total_case_pages": total_case_pages,
        "already_done": already_done,
        "ocr_token_summary": ocr_token_totals,
    }
    # region agent log
    import json as _json; open("debug-efc156.log", "a").write(_json.dumps({"sessionId":"efc156","hypothesisId":"H-B","runId":"post-fix","location":"case_extraction_service.py:result","message":"extraction result","data":{"total_case_pages":total_case_pages,"already_done":already_done,"queued":total,"processed":done},"timestamp":int(__import__("time").time()*1000)}) + "\n")
    # endregion
    return result
