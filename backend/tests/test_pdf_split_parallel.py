"""Tests for parallel PDF page splitting on upload."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.services import pdf_service


class PdfSplitParallelismTests(unittest.TestCase):
    @patch("app.services.pdf_service._save_page_and_thumbnail")
    @patch("app.services.pdf_service._render_page_image")
    @patch("app.services.pdf_service.fitz")
    @patch("app.services.pdf_service.get_rag_settings")
    def test_split_pdf_processes_pages_concurrently(
        self,
        mock_get_settings,
        mock_fitz,
        mock_render,
        mock_save_paths,
    ) -> None:
        settings = MagicMock()
        settings.pdf_split_workers = 4
        mock_get_settings.return_value = settings

        page_count = 6

        def _make_doc(*_args, **_kwargs):
            doc = MagicMock()
            doc.__len__.return_value = page_count
            doc.__enter__.return_value = doc
            doc.__exit__.return_value = None
            return doc

        mock_fitz.open.side_effect = _make_doc

        tracker = {"active": 0, "peak": 0}
        lock = threading.Lock()

        def _slow_render(_page):
            with lock:
                tracker["active"] += 1
                tracker["peak"] = max(tracker["peak"], tracker["active"])
            time.sleep(0.03)
            with lock:
                tracker["active"] -= 1
            return MagicMock()

        mock_render.side_effect = _slow_render
        mock_save_paths.return_value = {
            "file_path": "pages/test.jpg",
            "thumbnail_path": "thumbnails/thumb_test.jpg",
        }

        s3 = MagicMock()
        s3.download_bytes.return_value = b"%PDF-1.4 mock"

        results = pdf_service.split_pdf("uploads/sample.pdf", s3)

        self.assertEqual(len(results), page_count)
        self.assertEqual([row["page_number"] for row in results], list(range(1, page_count + 1)))
        self.assertGreaterEqual(tracker["peak"], 2)
        self.assertEqual(mock_render.call_count, page_count)


if __name__ == "__main__":
    unittest.main()
