"""Tests for skipping verification on questionnaire default answers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.verification_service import (
    _target_should_skip_verification,
    verify_autofill_batch,
)


class VerificationDefaultSkipTests(unittest.TestCase):
    def test_skip_force_default_targets(self) -> None:
        target = {"questionnaire_force_default": True}
        self.assertTrue(_target_should_skip_verification(target))

    def test_skip_targets_with_configured_default_value(self) -> None:
        target = {
            "id": "attorney.office_name",
            "questionnaire_default_value": "Law Offices of Manuel E. Solis",
        }
        self.assertTrue(_target_should_skip_verification(target))

    def test_skip_default_even_when_extracted_value_differs(self) -> None:
        target = {
            "id": "attorney.office_city",
            "questionnaire_default_value": "Houston",
        }
        self.assertTrue(_target_should_skip_verification(target))

    def test_do_not_skip_without_default_metadata(self) -> None:
        target = {"id": "client.full_name"}
        self.assertFalse(_target_should_skip_verification(target))

    @patch("app.services.verification_service._call_verification_batch_with_missing_retries")
    @patch("app.services.verification_service.get_rag_settings")
    def test_verify_autofill_batch_excludes_default_targets(
        self,
        mock_get_settings,
        mock_call_batch,
    ) -> None:
        settings = mock_get_settings.return_value
        settings.verification_enabled = True
        settings.verification_batch_size = 10
        settings.verification_provider = "openai"
        settings.openai_api_key = "test-key"

        targets = [
            {
                "id": "default.field",
                "questionnaire_default_value": "Preset",
            },
            {
                "id": "extracted.field",
            },
        ]
        results_by_id = {
            "default.field": {"value": "Preset"},
            "extracted.field": {"value": "From documents"},
        }
        evidence_by_id = {
            "extracted.field": {"text_context": "Evidence snippet"},
        }

        verify_autofill_batch(
            results_by_id=results_by_id,
            evidence_by_id=evidence_by_id,
            targets=targets,
        )

        mock_call_batch.assert_called_once()
        payload = mock_call_batch.call_args.args[0]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["field_id"], "extracted.field")


if __name__ == "__main__":
    unittest.main()
