from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Callable

from ..database import SessionLocal
from ..models import DocumentType, ExtractionStatus, Page
from .gemini_runtime_service import ZERO_TOKEN_SUMMARY, sum_token_summaries
from .indexing_service import process_page_extraction
from .json_export_service import save_extraction_json

log = logging.getLogger("extraction")

MAX_EXTRACTION_WORKERS = int(os.getenv("MAX_EXTRACTION_WORKERS"))
EXTRACTION_BATCH_SIZE = int(os.getenv("EXTRACTION_BATCH_SIZE"))
PARALLEL_BATCHES = int(os.getenv("CASE_EXTRACTION_PARALLEL_BATCHES"))


def _determine_has_tables(page: Page, db) -> bool:
    if page.document_type_id:
        dt = db.query(DocumentType).filter(DocumentType.id == page.document_type_id).first()
        if dt:
            return dt.has_tables or False
    return False


def _page_has_usable_ocr(page: Page) -> bool:
    return (
        (page.extraction_status or "") == ExtractionStatus.DONE.value
        and bool((page.ocr_text or "").strip())
        and not str(page.ocr_text or "").strip().startswith("[Error]")
    )


def _extract_single_page(page_id: str, has_tables: bool) -> tuple[str, bool, str, dict | None]:
    try:
        result = process_page_extraction(page_id, has_tables)
        if result is None:
            return page_id, False, "OCR extraction did not produce a result", None
        return page_id, True, "", result
    except Exception as exc:
        return page_id, False, str(exc), None


def _chunked(items: list[dict[str, object]], size: int) -> list[list[dict[str, object]]]:
    if size <= 0:
        return [items]
    return [items[idx:idx + size] for idx in range(0, len(items), size)]


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
            if only_missing and _page_has_usable_ocr(page):
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

    log.info(
        "Case extraction [%s]: queued=%d already_done=%d workers=%d",
        case_id[:8],
        total,
        already_done,
        MAX_EXTRACTION_WORKERS,
    )
    if total:
        counter_lock = Lock()

        def _record_page_result(
            page_id: str,
            success: bool,
            err: str,
            result: dict | None,
        ) -> None:
            nonlocal done, failed
            with counter_lock:
                done += 1
                if not success:
                    failed += 1
                if result:
                    page_results.append(result)
                local_done = done
                local_failed = failed

            if not success:
                log.error("Case extraction [%s]: page %s failed: %s", case_id[:8], page_id[:8], err)
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "extracting_document",
                        "ocr_total_pages": total_case_pages,
                        "ocr_processed_pages": already_done + local_done,
                        "ocr_error_pages": local_failed,
                    }
                )
            if local_done % 20 == 0 or local_done == total:
                log.info("Case extraction [%s]: %d/%d done (%d errors)", case_id[:8], local_done, total, local_failed)

        def _run_batch(batch: list[dict[str, object]]) -> None:
            for cfg in batch:
                page_id, success, err, result = _extract_single_page(
                    str(cfg["page_id"]),
                    bool(cfg["has_tables"]),
                )
                _record_page_result(page_id, success, err, result)

        use_batch_mode = EXTRACTION_BATCH_SIZE > 0 and total > EXTRACTION_BATCH_SIZE
        if use_batch_mode:
            batches = _chunked(page_configs, EXTRACTION_BATCH_SIZE)
            batch_workers = min(PARALLEL_BATCHES, len(batches))
            log.info(
                "Case extraction [%s]: batch mode enabled (%d batches, size=%d, parallel=%d)",
                case_id[:8],
                len(batches),
                EXTRACTION_BATCH_SIZE,
                batch_workers,
            )
            with ThreadPoolExecutor(max_workers=batch_workers) as pool:
                futures = [pool.submit(_run_batch, batch) for batch in batches]
                for future in as_completed(futures):
                    future.result()
        else:
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
                    _record_page_result(page_id, success, err, result)

    page_results.sort(key=lambda row: row.get("page_number", 0))

    if progress_callback is not None:
        progress_callback({"phase": "writing_json"})

    extraction_pages = _build_extraction_pages(case_id)
    save_extraction_json(case_id, extraction_pages)

    ocr_token_totals = dict(ZERO_TOKEN_SUMMARY)
    for row in page_results:
        ts = row.get("token_summary", {}) or {}
        ocr_token_totals = sum_token_summaries(ocr_token_totals, ts)

    return {
        "queued": total,
        "processed": done,
        "errors": failed,
        "written_pages": len(extraction_pages),
        "total_case_pages": total_case_pages,
        "already_done": already_done,
        "ocr_token_summary": ocr_token_totals,
    }
