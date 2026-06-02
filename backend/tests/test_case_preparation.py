"""Tests for case preparation, OCR batch parallelism, and autofill cache sharing."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.services.autofill_case_cache import (
    clear_case_cache,
    get_autofill_context,
    get_cached_evidence,
    store_autofill_context,
    store_cached_evidence,
)
from app.services.case_preparation_service import is_organization_complete, maybe_start_case_preparation


class AutofillCaseCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_case_cache("case-1")

    def tearDown(self) -> None:
        clear_case_cache("case-1")

    def test_context_cache_reused_between_questionnaire_runs(self) -> None:
        store_autofill_context(
            "case-1",
            None,
            form_type="I-360",
            detected_name="Jane Doe",
            applicant_context="Applicant: Jane Doe",
        )
        cached = get_autofill_context("case-1", None)
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.form_type, "I-360")
        self.assertEqual(cached.detected_name, "Jane Doe")

    def test_evidence_cache_reuses_bundle_for_same_query(self) -> None:
        bundle = {
            "evidence": [{"page_id": "p1"}],
            "text_context": "snippet",
            "source_pages": ["p1"],
            "stage": "ok",
            "matches": [],
        }
        store_cached_evidence("case-1", None, "full legal name", bundle)
        cached = get_cached_evidence("case-1", None, "full legal name")
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached["text_context"], "snippet")


class CasePreparationTriggerTests(unittest.TestCase):
    @patch("app.services.case_preparation_service.start_job")
    @patch("app.services.case_preparation_service.find_active_job", return_value=None)
    @patch("app.services.case_preparation_service.case_needs_preparation", return_value=True)
    @patch("app.services.case_preparation_service.is_organization_complete", return_value=True)
    @patch("app.services.case_preparation_service.SessionLocal")
    def test_maybe_start_when_organization_complete(
        self,
        mock_session_local,
        _mock_org_complete,
        _mock_needs_prep,
        _mock_find_active,
        mock_start_job,
    ) -> None:
        db = MagicMock()
        mock_session_local.return_value = db
        maybe_start_case_preparation("case-abc")
        mock_start_job.assert_called_once()
        db.close.assert_called_once()

    @patch("app.services.case_preparation_service.start_job")
    @patch("app.services.case_preparation_service.SessionLocal")
    def test_maybe_start_skips_when_organization_incomplete(
        self,
        mock_session_local,
        mock_start_job,
    ) -> None:
        db = MagicMock()
        mock_session_local.return_value = db
        db.query.return_value.filter.return_value.count.side_effect = [3, 1]
        maybe_start_case_preparation("case-abc")
        mock_start_job.assert_not_called()
        db.close.assert_called_once()

    def test_is_organization_complete_requires_zero_unclassified(self) -> None:
        db = MagicMock()
        db.query.return_value.filter.return_value.count.side_effect = [5, 0]
        self.assertTrue(is_organization_complete(db, "case-1"))

        db.query.return_value.filter.return_value.count.side_effect = [5, 2]
        self.assertFalse(is_organization_complete(db, "case-1"))


class CaseExtractionBatchParallelismTests(unittest.TestCase):
    @patch("app.services.case_extraction_service.save_extraction_json")
    @patch("app.services.case_extraction_service._build_extraction_pages", return_value=[])
    @patch("app.services.case_extraction_service._extract_single_page")
    @patch("app.services.case_extraction_service.get_rag_settings")
    @patch("app.services.case_extraction_service.SessionLocal")
    def test_run_batch_extracts_pages_concurrently(
        self,
        mock_session_local,
        mock_get_rag_settings,
        mock_extract_single,
        _mock_build_pages,
        _mock_save_json,
    ) -> None:
        from app.services.case_extraction_service import extract_case_pages

        settings = MagicMock()
        settings.extraction_batch_size = 2
        settings.case_extraction_parallel_batches = 1
        settings.max_extraction_workers = 4
        mock_get_rag_settings.return_value = settings

        db = MagicMock()
        mock_session_local.return_value = db

        pages = []
        for index in range(4):
            page = MagicMock()
            page.id = f"page-{index}"
            page.case_id = "case-1"
            page.deleted_at = None
            page.extraction_status = "pending"
            page.ocr_text = ""
            page.has_tables = False
            page.document_type_id = None
            page.original_page_number = index + 1
            page.created_at = MagicMock()
            pages.append(page)

        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = pages

        tracker = {"active": 0, "peak": 0}
        lock = threading.Lock()

        def _slow_extract(page_id: str, _has_tables: bool):
            with lock:
                tracker["active"] += 1
                tracker["peak"] = max(tracker["peak"], tracker["active"])
            time.sleep(0.05)
            with lock:
                tracker["active"] -= 1
            return page_id, True, "", {"page_id": page_id, "page_number": 1, "token_summary": {}}

        mock_extract_single.side_effect = _slow_extract

        extract_case_pages("case-1", only_missing=True)

        self.assertEqual(mock_extract_single.call_count, 4)
        self.assertGreaterEqual(tracker["peak"], 2)


if __name__ == "__main__":
    unittest.main()
