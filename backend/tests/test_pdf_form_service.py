import unittest

import fitz

from app.services import pdf_form_service as service


class _ButtonWidgetStub:
    def __init__(self, states: dict[str, list[str]]) -> None:
        self._states = states

    def button_states(self) -> dict[str, list[str]]:
        return self._states


class PdfFormServiceTests(unittest.TestCase):
    def test_collect_nearby_snippets_includes_left_label_and_heading(self) -> None:
        page_rect = fitz.Rect(0, 0, 612, 792)
        widget_rect = fitz.Rect(300, 200, 380, 220)
        lines = [
            {"text": "Date of Birth", "rect": fitz.Rect(82, 203, 292, 217)},
            {"text": "Part 2. General Information About You", "rect": fitz.Rect(72, 160, 420, 176)},
            {"text": "Page 2 of 12", "rect": fitz.Rect(500, 760, 575, 772)},
        ]

        snippets = service._collect_nearby_snippets_from_lines(lines, widget_rect, page_rect)

        self.assertIn("Date of Birth", snippets)
        self.assertIn("Part 2. General Information About You", snippets)
        self.assertNotIn("Page 2 of 12", snippets)

    def test_collect_nearby_snippets_includes_right_side_checkbox_label(self) -> None:
        page_rect = fitz.Rect(0, 0, 612, 792)
        widget_rect = fitz.Rect(100, 100, 112, 112)
        lines = [
            {"text": "Male", "rect": fitz.Rect(120, 98, 165, 114)},
            {"text": "Female", "rect": fitz.Rect(175, 98, 235, 114)},
        ]

        snippets = service._collect_nearby_snippets_from_lines(lines, widget_rect, page_rect)

        self.assertIn("Male", snippets)

    def test_button_target_value_matches_pdf_export_value_using_normalized_label(self) -> None:
        widget = _ButtonWidgetStub({"normal": ["#20APT#20"], "down": ["#20APT#20", "Off"]})

        self.assertEqual(service._button_target_value(widget, "Apt."), "Yes")

    def test_button_target_value_uses_widget_on_state_for_truthy_values(self) -> None:
        widget = _ButtonWidgetStub({"normal": ["#20STE#20"], "down": ["#20STE#20", "Off"]})

        self.assertEqual(service._button_target_value(widget, "yes"), "Yes")


if __name__ == "__main__":
    unittest.main()
