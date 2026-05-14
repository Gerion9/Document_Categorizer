import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import field_extraction_service as service


def _settings(provider: str, model: str = ""):
    return SimpleNamespace(
        extraction_provider=provider,
        extraction_model=model,
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
        gemini_model="gemini-2.0-flash",
        qc_batch_model="",
        qc_batch_use_prompt_cache=True,
        qc_batch_max_output_tokens=4096,
        verify_temperature=0.25,
        narrative_temperature=0.45,
        verify_max_retries=1,
    )


def _field():
    return {
        "id": "field_1",
        "field_type": "text",
        "field_label": "Applicant name",
        "questionnaire_form_text": "What is the applicant's full name?",
    }


def _batch_payload():
    return {
        "answers": [
            {
                "id": "field_1",
                "value": "Jane Doe",
                "confidence": "high",
                "justification": "The evidence states the applicant name.",
            }
        ]
    }


class _FakeAnthropicStream:
    def __init__(self, text: str):
        self.text_stream = [text]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FieldExtractionDispatcherTests(unittest.TestCase):
    def test_openai_batch_returns_normalized_shape_without_prompt_cache(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=json.dumps(_batch_payload())),
                )
            ]
        )
        create = Mock(return_value=response)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        with (
            patch.object(
                service,
                "get_rag_settings",
                return_value=_settings("openai", "gpt-5.4"),
            ),
            patch.object(service, "_get_openai_client", return_value=client),
            patch.object(service, "get_or_create_ocr_prompt_cache") as cache_mock,
        ):
            result = service.extract_field_values_batch(
                [_field()],
                {"field_1": "Applicant name: Jane Doe"},
                form_type="I-914",
            )

        self.assertEqual(
            result,
            [
                {
                    "id": "field_1",
                    "value": "Jane Doe",
                    "confidence": "high",
                    "justification": "The evidence states the applicant name.",
                }
            ],
        )
        cache_mock.assert_not_called()
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.4")
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertIn("Output JSON", kwargs["messages"][0]["content"])
        self.assertIn("INPUT:", kwargs["messages"][0]["content"])

    def test_anthropic_batch_returns_normalized_shape_without_prompt_cache(self):
        stream = Mock(
            return_value=_FakeAnthropicStream(
                "# Analyzing the request\n" + json.dumps(_batch_payload())
            )
        )
        client = SimpleNamespace(messages=SimpleNamespace(stream=stream))

        with (
            patch.object(
                service,
                "get_rag_settings",
                return_value=_settings("anthropic", "claude-sonnet-4-6"),
            ),
            patch.object(service, "_get_anthropic_client", return_value=client),
            patch.object(service, "get_or_create_ocr_prompt_cache") as cache_mock,
        ):
            result = service.extract_field_values_batch(
                [_field()],
                {"field_1": "Applicant name: Jane Doe"},
                form_type="I-914",
            )

        self.assertEqual(result[0]["id"], "field_1")
        self.assertEqual(result[0]["value"], "Jane Doe")
        self.assertEqual(result[0]["confidence"], "high")
        cache_mock.assert_not_called()
        kwargs = stream.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-sonnet-4-6")
        self.assertEqual(kwargs["max_tokens"], 2048)
        self.assertIn("Output JSON", kwargs["system"])
        self.assertIn("Return ONLY valid JSON", kwargs["system"])
        self.assertIn("INPUT:", kwargs["messages"][0]["content"])
        self.assertEqual(len(kwargs["messages"]), 1)
        self.assertEqual(kwargs["messages"][0]["role"], "user")

    def test_anthropic_parser_skips_non_schema_json_before_answer(self):
        stream = Mock(
            return_value=_FakeAnthropicStream(
                '{"note":"thinking"}\n' + json.dumps(_batch_payload())
            )
        )
        client = SimpleNamespace(messages=SimpleNamespace(stream=stream))

        with (
            patch.object(
                service,
                "get_rag_settings",
                return_value=_settings("anthropic", "claude-sonnet-4-6"),
            ),
            patch.object(service, "_get_anthropic_client", return_value=client),
            patch.object(service, "get_or_create_ocr_prompt_cache"),
        ):
            result = service.extract_field_values_batch(
                [_field()],
                {"field_1": "Applicant name: Jane Doe"},
                form_type="I-914",
            )

        self.assertEqual(result[0]["value"], "Jane Doe")

    def test_anthropic_low_batch_coverage_raises_for_single_fallback(self):
        payload = {
            "answers": [
                {"id": f"field_{idx}", "value": "", "confidence": "low", "justification": ""}
                for idx in range(1, 6)
            ]
        }
        stream = Mock(return_value=_FakeAnthropicStream(json.dumps(payload)))
        client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
        fields = [
            {
                "id": f"field_{idx}",
                "field_type": "text",
                "field_label": f"Field {idx}",
                "questionnaire_form_text": f"Question {idx}?",
            }
            for idx in range(1, 6)
        ]
        evidence_by_id = {
            f"field_{idx}": f"Evidence for field {idx}: value {idx}"
            for idx in range(1, 6)
        }

        with (
            patch.object(
                service,
                "get_rag_settings",
                return_value=_settings("anthropic", "claude-sonnet-4-6"),
            ),
            patch.object(service, "_get_anthropic_client", return_value=client),
            patch.object(service, "get_or_create_ocr_prompt_cache"),
        ):
            with self.assertRaisesRegex(RuntimeError, "too few usable values"):
                service.extract_field_values_batch(
                    fields,
                    evidence_by_id,
                    form_type="I-914",
                )


if __name__ == "__main__":
    unittest.main()
