import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import verification_service


def _settings(model="gpt-4o-mini", **overrides):
    base = dict(
        verification_provider="openai",
        verification_model=model,
        verification_temperature=0,
        verification_max_tokens=4096,
        verification_enabled=True,
        verification_batch_size=20,
        openai_api_key="test-key",
        anthropic_api_key="",
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-2.0-flash",
        gemini_thinking_level="",
        gemini_ocr_thinking_level="",
        gemini_extraction_thinking_level="",
        gemini_form_detection_thinking_level="",
        gemini_verification_thinking_level="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _build_response(payload_dict):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8),
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(payload_dict)),
            )
        ],
    )


def _build_field_payload_minimal(field_id="field_1", snippet="Jane Doe"):
    return {
        "field_id": field_id,
        "field_label": "Name",
        "question_text": "What is the applicant's full name?",
        "field_type": "name",
        "where_to_verify": "passport",
        "section": "Part 1",
        "extracted_value": "Jane Doe",
        "evidence_snippet": snippet,
        "evidence_truncated": False,
    }


class BuildFieldPayloadTests(unittest.TestCase):
    def test_payload_includes_question_type_and_where(self):
        target = {
            "id": "p1_first_name",
            "field_label": "First name",
            "field_name": "p1.first_name",
            "questionnaire_form_text": "What is your first name?",
            "field_type_hint": "first_name",
            "questionnaire_where_to_verify": "passport",
            "questionnaire_section": "Part 1",
            "questionnaire_options": [
                {"value": "MR", "label": "Mr."},
                {"value": "MRS", "label": "Mrs."},
            ],
        }
        evidence = {"text_context": "Given names: MARIA"}
        result = {"value": "Maria", "confidence": "high", "justification": "ignored"}

        payload = verification_service._build_field_payload(
            "p1_first_name", target, result, evidence
        )

        self.assertEqual(payload["question_text"], "What is your first name?")
        self.assertEqual(payload["field_type"], "first_name")
        self.assertEqual(payload["where_to_verify"], "passport")
        self.assertEqual(payload["section"], "Part 1")
        self.assertEqual(
            payload["allowed_options"],
            [{"value": "MR", "label": "Mr."}, {"value": "MRS", "label": "Mrs."}],
        )
        self.assertEqual(payload["extracted_value"], "Maria")
        self.assertIn("MARIA", payload["evidence_snippet"])
        self.assertFalse(payload["evidence_truncated"])

    def test_payload_omits_gemini_confidence_and_justification(self):
        target = {"id": "f1", "questionnaire_form_text": "q?"}
        evidence = {"text_context": "x"}
        result = {"value": "v", "confidence": "high", "justification": "anchor me"}

        payload = verification_service._build_field_payload("f1", target, result, evidence)

        self.assertNotIn("gemini_confidence", payload)
        self.assertNotIn("gemini_justification", payload)

    def test_payload_marks_truncated_evidence(self):
        target = {"id": "f1"}
        long_text = "x" * (verification_service.EVIDENCE_SNIPPET_MAX_CHARS + 100)
        evidence = {"text_context": long_text}

        payload = verification_service._build_field_payload(
            "f1", target, {"value": "v"}, evidence
        )

        self.assertTrue(payload["evidence_truncated"])
        self.assertEqual(
            len(payload["evidence_snippet"]),
            verification_service.EVIDENCE_SNIPPET_MAX_CHARS,
        )

    def test_payload_omits_allowed_options_when_empty(self):
        target = {"id": "f1", "questionnaire_options": []}
        payload = verification_service._build_field_payload(
            "f1", target, {"value": "v"}, {"text_context": "x"}
        )
        self.assertNotIn("allowed_options", payload)


class CallOpenAIBatchTests(unittest.TestCase):
    def _run(self, settings, response, fields_payload):
        create = Mock(return_value=response)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(verification_service, "_get_openai_client", return_value=client),
        ):
            result = verification_service._call_openai_batch(fields_payload)
        return result, create

    def test_uses_strict_json_schema_response_format(self):
        settings = _settings()
        response = _build_response({
            "results": [
                {
                    "id": "field_1",
                    "status": "approved",
                    "evidence_quote": "Jane Doe",
                    "reason": "Quote matches extracted value.",
                }
            ]
        })

        result, create = self._run(settings, response, [_build_field_payload_minimal()])

        self.assertEqual(result["field_1"].status, "approved")
        self.assertEqual(result["field_1"].evidence_quote, "Jane Doe")
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")
        self.assertEqual(kwargs["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(kwargs["response_format"]["json_schema"]["name"], "verification_batch")

    def test_reasoning_model_uses_low_effort_and_higher_token_floor(self):
        settings = _settings(model="gpt-5.4-mini")
        response = _build_response({
            "results": [
                {
                    "id": "field_1",
                    "status": "approved",
                    "evidence_quote": "Jane Doe",
                    "reason": "ok",
                }
            ]
        })

        _, create = self._run(settings, response, [_build_field_payload_minimal()])

        kwargs = create.call_args.kwargs
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["max_completion_tokens"], 16384)

    def test_non_reasoning_model_keeps_temperature(self):
        settings = _settings(model="gpt-4o-mini", verification_temperature=0)
        response = _build_response({
            "results": [
                {
                    "id": "field_1",
                    "status": "approved",
                    "evidence_quote": "Jane Doe",
                    "reason": "ok",
                }
            ]
        })

        _, create = self._run(settings, response, [_build_field_payload_minimal()])

        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0)
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertEqual(kwargs["max_completion_tokens"], 4096)

    def test_falls_back_to_json_object_when_schema_rejected(self):
        settings = _settings(model="gpt-4o-mini")
        success_response = _build_response({
            "results": [
                {
                    "id": "field_1",
                    "status": "approved",
                    "evidence_quote": "Jane Doe",
                    "reason": "ok",
                }
            ]
        })
        create = Mock(side_effect=[Exception("invalid response_format"), success_response])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(verification_service, "_get_openai_client", return_value=client),
        ):
            result = verification_service._call_openai_batch([_build_field_payload_minimal()])

        self.assertEqual(result["field_1"].status, "approved")
        self.assertEqual(create.call_count, 2)
        first_kwargs = create.call_args_list[0].kwargs
        retry_kwargs = create.call_args_list[1].kwargs
        self.assertEqual(first_kwargs["response_format"]["type"], "json_schema")
        self.assertEqual(retry_kwargs["response_format"], {"type": "json_object"})

    def test_returns_empty_map_for_empty_content(self):
        settings = _settings(model="gpt-5.4-mini")
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4096),
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content=""),
                )
            ],
        )

        result, _ = self._run(settings, response, [_build_field_payload_minimal()])

        self.assertEqual(result, {})


class CallGeminiBatchTests(unittest.TestCase):
    def test_parses_gemini_json_response(self):
        settings = _settings(
            verification_provider="gemini",
            verification_model="gemini-3.1-flash-lite-preview",
        )
        response = SimpleNamespace(
            text=json.dumps({
                "results": [
                    {
                        "id": "field_1",
                        "status": "approved",
                        "evidence_quote": "Jane Doe",
                        "reason": "Quote matches extracted value.",
                    }
                ]
            }),
            usage_metadata=SimpleNamespace(
                prompt_token_count=12,
                candidates_token_count=8,
            ),
        )
        generate_content = Mock(return_value=response)
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(verification_service, "_get_client", return_value=client),
        ):
            result = verification_service._call_gemini_batch(
                [_build_field_payload_minimal()]
            )

        self.assertEqual(result["field_1"].status, "approved")
        self.assertEqual(result["field_1"].reason, "Quote matches extracted value.")
        self.assertEqual(result["field_1"].evidence_quote, "Jane Doe")
        kwargs = generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-3.1-flash-lite-preview")
        self.assertIn("Jane Doe", kwargs["contents"][0])


class ParseVerificationResponseTests(unittest.TestCase):
    def test_parses_well_formed_response(self):
        raw = json.dumps({
            "results": [
                {
                    "id": "f1",
                    "status": "approved",
                    "evidence_quote": "Jane Doe",
                    "reason": "matches",
                }
            ]
        })
        snippets = {"f1": "Applicant: Jane Doe"}

        result = verification_service._parse_verification_response(raw, snippets)

        self.assertEqual(result["f1"].status, "approved")
        self.assertEqual(result["f1"].evidence_quote, "Jane Doe")

    def test_empty_response_returns_empty_map(self):
        result = verification_service._parse_verification_response("", {"f1": "anything"})

        self.assertEqual(result, {})

    def test_skips_non_schema_json_before_valid_payload(self):
        raw = (
            '{"note":"analysis"}\n'
            + json.dumps({
                "results": [
                    {
                        "id": "f1",
                        "status": "approved",
                        "evidence_quote": "Jane Doe",
                        "reason": "matches",
                    }
                ]
            })
        )

        result = verification_service._parse_verification_response(
            raw,
            {"f1": "Applicant: Jane Doe"},
        )

        self.assertEqual(result["f1"].status, "approved")

    def test_non_json_response_returns_empty_map(self):
        result = verification_service._parse_verification_response(
            "I cannot verify this request.",
            {"f1": "anything"},
        )

        self.assertEqual(result, {})

    def test_unknown_status_degrades_to_needs_review(self):
        raw = json.dumps({
            "results": [
                {
                    "id": "f1",
                    "status": "maybe",
                    "evidence_quote": "anything",
                    "reason": "x",
                }
            ]
        })

        result = verification_service._parse_verification_response(raw, {"f1": "anything"})

        self.assertEqual(result["f1"].status, "needs_review")
        self.assertEqual(result["f1"].reason, "judge returned invalid status")

    def test_empty_quote_for_approved_degrades_to_needs_review(self):
        raw = json.dumps({
            "results": [
                {
                    "id": "f1",
                    "status": "approved",
                    "evidence_quote": "   ",
                    "reason": "looks good",
                }
            ]
        })

        result = verification_service._parse_verification_response(raw, {"f1": "anything"})

        self.assertEqual(result["f1"].status, "needs_review")
        self.assertEqual(result["f1"].reason, "judge could not cite supporting evidence")

    def test_empty_quote_for_rejected_degrades_to_needs_review(self):
        raw = json.dumps({
            "results": [
                {
                    "id": "f1",
                    "status": "rejected",
                    "evidence_quote": "",
                    "reason": "no support",
                }
            ]
        })

        result = verification_service._parse_verification_response(raw, {"f1": "snippet"})

        self.assertEqual(result["f1"].status, "needs_review")
        self.assertEqual(result["f1"].reason, "judge could not cite supporting evidence")

    def test_quote_not_in_snippet_degrades_to_needs_review(self):
        raw = json.dumps({
            "results": [
                {
                    "id": "f1",
                    "status": "approved",
                    "evidence_quote": "fabricated text",
                    "reason": "trust me",
                }
            ]
        })

        result = verification_service._parse_verification_response(
            raw, {"f1": "actual evidence text from document"}
        )

        self.assertEqual(result["f1"].status, "needs_review")
        self.assertEqual(result["f1"].reason, "judge cited text not present in evidence")

    def test_quote_match_is_case_and_whitespace_insensitive(self):
        raw = json.dumps({
            "results": [
                {
                    "id": "f1",
                    "status": "approved",
                    "evidence_quote": "JANE  DOE",
                    "reason": "ok",
                }
            ]
        })

        result = verification_service._parse_verification_response(
            raw, {"f1": "Applicant name: jane doe (verified)"}
        )

        self.assertEqual(result["f1"].status, "approved")

    def test_needs_review_with_empty_quote_is_kept(self):
        raw = json.dumps({
            "results": [
                {
                    "id": "f1",
                    "status": "needs_review",
                    "evidence_quote": "",
                    "reason": "ambiguous evidence",
                }
            ]
        })

        result = verification_service._parse_verification_response(raw, {"f1": "anything"})

        self.assertEqual(result["f1"].status, "needs_review")
        self.assertEqual(result["f1"].reason, "ambiguous evidence")

    def test_malformed_result_degrades_matching_field_to_needs_review(self):
        raw = json.dumps({"results": [1]})

        result = verification_service._parse_verification_response(
            raw, {"f1": "Applicant: Jane Doe"}
        )

        self.assertEqual(result["f1"].status, "needs_review")
        self.assertEqual(
            result["f1"].reason,
            "judge returned malformed verification result",
        )


class VerifyAutofillBatchMappingTests(unittest.TestCase):
    def _run(self, fake_result, evidence_by_id):
        settings = _settings()
        targets = [{"id": "f1", "questionnaire_form_text": "q?", "field_type": "name"}]
        results_by_id = {"f1": {"value": "Jane"}}
        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(
                verification_service,
                "_call_verification_batch",
                return_value={"f1": fake_result},
            ),
        ):
            return verification_service.verify_autofill_batch(
                results_by_id=results_by_id,
                evidence_by_id=evidence_by_id,
                targets=targets,
            ), settings

    def test_evidence_combines_judge_quote_and_rag_snippet(self):
        fake_result = verification_service.FieldVerificationResult(
            status="approved",
            reason="ok",
            evidence_quote="Jane Doe",
        )
        verification_map, settings = self._run(
            fake_result,
            {"f1": {"text_context": "Applicant name: Jane Doe (verified)."}},
        )

        entry = verification_map["f1"]
        self.assertEqual(entry["status"], "approved")
        self.assertEqual(entry["evidence_quote"], "Jane Doe")
        self.assertIn('Judge cited: "Jane Doe"', entry["evidence"])
        self.assertIn("Document context", entry["evidence"])
        self.assertIn("Applicant name: Jane Doe", entry["evidence"])
        self.assertEqual(entry["model"], settings.verification_model)

    def test_evidence_falls_back_to_rag_snippet_when_quote_empty(self):
        fake_result = verification_service.FieldVerificationResult(
            status="needs_review",
            reason="ambiguous",
            evidence_quote="",
        )
        verification_map, _ = self._run(
            fake_result,
            {"f1": {"text_context": "Original retrieved snippet from doc."}},
        )

        entry = verification_map["f1"]
        self.assertNotIn("Judge cited", entry["evidence"])
        self.assertEqual(entry["evidence"], "Original retrieved snippet from doc.")
        self.assertEqual(entry["evidence_quote"], "")

    def test_evidence_truncated_to_display_limit(self):
        long_text = "x" * (verification_service.EVIDENCE_DISPLAY_MAX_CHARS + 500)
        fake_result = verification_service.FieldVerificationResult(
            status="needs_review",
            reason="x",
            evidence_quote="",
        )
        verification_map, _ = self._run(fake_result, {"f1": {"text_context": long_text}})

        self.assertEqual(
            len(verification_map["f1"]["evidence"]),
            verification_service.EVIDENCE_DISPLAY_MAX_CHARS,
        )

    def test_skips_default_filled_field_before_calling_judge(self):
        settings = _settings()
        targets = [
            {
                "id": "f1",
                "questionnaire_form_text": "q?",
                "questionnaire_default_value": "no",
            }
        ]
        results_by_id = {"f1": {"value": "No"}}
        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(verification_service, "_call_verification_batch") as call_batch,
        ):
            verification_map = verification_service.verify_autofill_batch(
                results_by_id=results_by_id,
                evidence_by_id={"f1": {"text_context": "No"}},
                targets=targets,
            )

        self.assertEqual(verification_map, {})
        call_batch.assert_not_called()

    def test_skips_default_filled_country_alias_before_calling_judge(self):
        settings = _settings()
        targets = [
            {
                "id": "f1",
                "questionnaire_form_text": "q?",
                "questionnaire_default_value": "EE. UU.",
            }
        ]
        results_by_id = {"f1": {"value": "United States"}}
        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(verification_service, "_call_verification_batch") as call_batch,
        ):
            verification_map = verification_service.verify_autofill_batch(
                results_by_id=results_by_id,
                evidence_by_id={"f1": {"text_context": "United States"}},
                targets=targets,
            )

        self.assertEqual(verification_map, {})
        call_batch.assert_not_called()

    def test_skips_force_default_field_even_when_extractor_returns_other_value(self):
        settings = _settings()
        targets = [
            {
                "id": "f1",
                "questionnaire_form_text": "q?",
                "questionnaire_default_value": "Law Offices of Manuel E. Solis",
                "questionnaire_force_default": True,
            }
        ]
        results_by_id = {"f1": {"value": "Different value"}}
        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(verification_service, "_call_verification_batch") as call_batch,
        ):
            verification_map = verification_service.verify_autofill_batch(
                results_by_id=results_by_id,
                evidence_by_id={"f1": {"text_context": "Different value"}},
                targets=targets,
            )

        self.assertEqual(verification_map, {})
        call_batch.assert_not_called()

    def test_verifies_non_default_value_when_field_has_default(self):
        fake_result = verification_service.FieldVerificationResult(
            status="approved",
            reason="ok",
            evidence_quote="Yes",
        )
        settings = _settings()
        targets = [
            {
                "id": "f1",
                "questionnaire_form_text": "q?",
                "questionnaire_default_value": "no",
            }
        ]
        results_by_id = {"f1": {"value": "yes"}}
        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(
                verification_service,
                "_call_verification_batch",
                return_value={"f1": fake_result},
            ) as call_batch,
        ):
            verification_map = verification_service.verify_autofill_batch(
                results_by_id=results_by_id,
                evidence_by_id={"f1": {"text_context": "Yes"}},
                targets=targets,
            )

        self.assertEqual(verification_map["f1"]["status"], "approved")
        call_batch.assert_called_once()

    def test_retries_missing_batch_results_individually(self):
        settings = _settings(verification_batch_size=20)
        targets = [
            {"id": "f1", "questionnaire_form_text": "First?"},
            {"id": "f2", "questionnaire_form_text": "Second?"},
        ]
        results_by_id = {"f1": {"value": "Jane"}, "f2": {"value": "Doe"}}
        fake_first = verification_service.FieldVerificationResult(
            status="approved",
            reason="ok",
            evidence_quote="Jane",
        )
        fake_second = verification_service.FieldVerificationResult(
            status="approved",
            reason="ok",
            evidence_quote="Doe",
        )
        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(
                verification_service,
                "_call_verification_batch",
                side_effect=[
                    {"f1": fake_first},
                    {"f2": fake_second},
                ],
            ) as call_batch,
        ):
            verification_map = verification_service.verify_autofill_batch(
                results_by_id=results_by_id,
                evidence_by_id={
                    "f1": {"text_context": "Jane"},
                    "f2": {"text_context": "Doe"},
                },
                targets=targets,
            )

        self.assertEqual(verification_map["f1"]["status"], "approved")
        self.assertEqual(verification_map["f2"]["status"], "approved")
        self.assertEqual(call_batch.call_count, 2)
        self.assertEqual(len(call_batch.call_args_list[0].args[0]), 2)
        self.assertEqual(len(call_batch.call_args_list[1].args[0]), 1)

    def test_missing_single_retry_degrades_to_needs_review(self):
        settings = _settings(verification_batch_size=20)
        targets = [
            {"id": "f1", "questionnaire_form_text": "First?"},
            {"id": "f2", "questionnaire_form_text": "Second?"},
        ]
        results_by_id = {"f1": {"value": "Jane"}, "f2": {"value": "Doe"}}
        fake_first = verification_service.FieldVerificationResult(
            status="approved",
            reason="ok",
            evidence_quote="Jane",
        )
        with (
            patch.object(verification_service, "get_rag_settings", return_value=settings),
            patch.object(
                verification_service,
                "_call_verification_batch",
                side_effect=[
                    {"f1": fake_first},
                    {},
                ],
            ),
        ):
            verification_map = verification_service.verify_autofill_batch(
                results_by_id=results_by_id,
                evidence_by_id={
                    "f1": {"text_context": "Jane"},
                    "f2": {"text_context": "Doe"},
                },
                targets=targets,
            )

        self.assertEqual(verification_map["f1"]["status"], "approved")
        self.assertEqual(verification_map["f2"]["status"], "needs_review")
        self.assertEqual(
            verification_map["f2"]["reason"],
            "judge returned no usable verification response",
        )


class MissingProviderKeyTests(unittest.TestCase):
    def test_missing_openai_key_message(self):
        with patch.object(
            verification_service,
            "get_rag_settings",
            return_value=_settings(openai_api_key=""),
        ):
            self.assertEqual(
                verification_service._missing_provider_api_key_message(),
                "OPENAI_API_KEY not configured",
            )

    def test_missing_gemini_key_message(self):
        with patch.object(
            verification_service,
            "get_rag_settings",
            return_value=_settings(
                verification_provider="gemini",
                gemini_api_key="",
            ),
        ):
            self.assertEqual(
                verification_service._missing_provider_api_key_message(),
                "GEMINI_API_KEY not configured",
            )


if __name__ == "__main__":
    unittest.main()
