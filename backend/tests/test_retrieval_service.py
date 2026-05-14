import unittest

from app.services import retrieval_service


class RetrievalServiceTests(unittest.TestCase):
    def test_rank_matches_prefers_external_record_sources_over_form_checkbox_echo(self) -> None:
        matches = [
            {
                "id": "form-page",
                "score": 0.95,
                "metadata": {
                    "page_id": "24",
                    "chunk_order": 1,
                    "source_type": "gemini_ocr",
                    "text": (
                        "Pregunta: Part 4 Item 10.B - Has participated in killing any person?\n"
                        "Respuesta: [ ] Yes [X] No"
                    ),
                    "original_filename": "DRAFT.pdf",
                },
            },
            {
                "id": "fbi-page",
                "score": 0.80,
                "metadata": {
                    "page_id": "110",
                    "chunk_order": 1,
                    "source_type": "gemini_ocr",
                    "text": (
                        "Question: Document Type\n"
                        "Answer: CRIMINAL HISTORY RECORD\n"
                        "Question: Agency\n"
                        "Answer: UNITED STATES DEPARTMENT OF JUSTICE FEDERAL BUREAU OF INVESTIGATION"
                    ),
                    "original_filename": "DRAFT.pdf",
                },
            },
        ]

        ranked = retrieval_service._rank_matches(
            matches,
            top_k=1,
            where_to_verify="Personal history; Intake, FBI; Bio Call",
            retrieval_profile="qc_checklist",
        )

        self.assertEqual([match["id"] for match in ranked], ["fbi-page"])

    def test_rank_matches_generic_profile_preserves_base_similarity_order(self) -> None:
        matches = [
            {
                "id": "form-page",
                "score": 0.95,
                "metadata": {
                    "page_id": "24",
                    "chunk_order": 1,
                    "source_type": "gemini_ocr",
                    "text": (
                        "Pregunta: Part 4 Item 10.B - Has participated in killing any person?\n"
                        "Respuesta: [ ] Yes [X] No"
                    ),
                    "original_filename": "DRAFT.pdf",
                },
            },
            {
                "id": "fbi-page",
                "score": 0.80,
                "metadata": {
                    "page_id": "110",
                    "chunk_order": 1,
                    "source_type": "gemini_ocr",
                    "text": (
                        "Question: Document Type\n"
                        "Answer: CRIMINAL HISTORY RECORD\n"
                        "Question: Agency\n"
                        "Answer: UNITED STATES DEPARTMENT OF JUSTICE FEDERAL BUREAU OF INVESTIGATION"
                    ),
                    "original_filename": "DRAFT.pdf",
                },
            },
        ]

        ranked = retrieval_service._rank_matches(
            matches,
            top_k=1,
            where_to_verify="Personal history; Intake, FBI; Bio Call",
            retrieval_profile="generic",
        )

        self.assertEqual([match["id"] for match in ranked], ["form-page"])

    def test_candidate_query_pool_is_larger_than_requested_top_k(self) -> None:
        self.assertGreater(
            retrieval_service._candidate_query_k(10, retrieval_profile="qc_checklist"),
            10,
        )
        self.assertEqual(
            retrieval_service._candidate_query_k(10, retrieval_profile="generic"),
            10,
        )

    def test_build_retrieval_stages_prefers_targeted_documents_before_scope(self) -> None:
        stages = retrieval_service._build_retrieval_stages(
            preferred_source_document_ids=["doc-fbi", "doc-bio"],
            source_document_ids=["doc-fbi", "doc-bio", "doc-decl"],
            document_fallback_enabled=True,
        )

        self.assertEqual(
            [stage_name for stage_name, _ in stages],
            ["preferred_source_document", "source_document", "case_wide"],
        )


if __name__ == "__main__":
    unittest.main()
