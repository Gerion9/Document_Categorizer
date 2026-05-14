"""Unit tests for the centralized date parsing/formatting utility."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from app.utils.date_format import (
    LONG_DATE_EXAMPLE,
    LONG_DATE_FORMAT_HUMAN,
    MONTH_ABBR_EN,
    format_long_date,
    format_long_datetime,
    month_token_to_number,
    normalize_date_text_to_long,
    parse_date_text,
)


class FormatLongDateTests(unittest.TestCase):
    def test_returns_canonical_string_for_date(self) -> None:
        self.assertEqual(format_long_date(date(1979, 3, 21)), "Mar 21 1979")

    def test_returns_canonical_string_for_datetime(self) -> None:
        self.assertEqual(format_long_date(datetime(2024, 1, 5, 10, 30)), "Jan 05 2024")

    def test_returns_canonical_string_for_iso_string(self) -> None:
        self.assertEqual(format_long_date("2020-12-31"), "Dec 31 2020")

    def test_returns_empty_for_invalid_input(self) -> None:
        self.assertEqual(format_long_date("not a date"), "")
        self.assertEqual(format_long_date(""), "")
        self.assertEqual(format_long_date(None), "")

    def test_emits_zero_padded_day_and_year(self) -> None:
        self.assertEqual(format_long_date("1/5/24"), "Jan 05 2024")
        self.assertEqual(format_long_date("Mar 1 99"), "Mar 01 1999")

    def test_emits_english_abbreviation_for_every_month(self) -> None:
        for month_index in range(1, 13):
            with self.subTest(month=month_index):
                formatted = format_long_date(date(2024, month_index, 15))
                expected_prefix = MONTH_ABBR_EN[month_index - 1]
                self.assertTrue(
                    formatted.startswith(expected_prefix),
                    f"Expected {expected_prefix} prefix, got {formatted!r}",
                )


class FormatLongDateTimeTests(unittest.TestCase):
    def test_emits_long_date_with_time(self) -> None:
        self.assertEqual(
            format_long_datetime(datetime(1979, 3, 21, 14, 30)),
            "Mar 21 1979 14:30",
        )

    def test_supports_seconds_when_requested(self) -> None:
        self.assertEqual(
            format_long_datetime(datetime(1979, 3, 21, 14, 30, 5), include_seconds=True),
            "Mar 21 1979 14:30:05",
        )

    def test_handles_iso_string_with_timezone(self) -> None:
        formatted = format_long_datetime("2024-03-21T14:30:00Z")
        self.assertTrue(formatted.startswith("Mar"))
        self.assertIn("2024", formatted)

    def test_returns_empty_for_invalid_input(self) -> None:
        self.assertEqual(format_long_datetime(""), "")
        self.assertEqual(format_long_datetime(None), "")


class ParseDateTextTests(unittest.TestCase):
    def test_accepts_canonical_long_format(self) -> None:
        self.assertEqual(parse_date_text("Mar 21 1979"), date(1979, 3, 21))

    def test_accepts_legacy_us_slash(self) -> None:
        self.assertEqual(parse_date_text("03/21/1979"), date(1979, 3, 21))
        self.assertEqual(parse_date_text("3/21/79"), date(1979, 3, 21))

    def test_accepts_iso(self) -> None:
        self.assertEqual(parse_date_text("1979-03-21"), date(1979, 3, 21))
        self.assertEqual(parse_date_text("2024-03-21T14:30:00Z"), date(2024, 3, 21))

    def test_accepts_day_first_when_unambiguous(self) -> None:
        self.assertEqual(parse_date_text("21/03/1979"), date(1979, 3, 21))

    def test_accepts_textual_long_form(self) -> None:
        self.assertEqual(parse_date_text("March 21, 1979"), date(1979, 3, 21))
        self.assertEqual(parse_date_text("21 March 1979"), date(1979, 3, 21))

    def test_accepts_spanish_month_names(self) -> None:
        self.assertEqual(parse_date_text("21 de marzo de 1979"), date(1979, 3, 21))
        self.assertEqual(parse_date_text("septiembre 9 2020"), date(2020, 9, 9))

    def test_returns_none_for_invalid_input(self) -> None:
        self.assertIsNone(parse_date_text("foo"))
        self.assertIsNone(parse_date_text(""))
        self.assertIsNone(parse_date_text(None))


class RoundTripTests(unittest.TestCase):
    def test_round_trip_preserves_components(self) -> None:
        cases = [
            ("Mar 21 1979", "Mar 21 1979"),
            ("03/21/1979", "Mar 21 1979"),
            ("1979-03-21", "Mar 21 1979"),
            ("March 21, 1979", "Mar 21 1979"),
            ("21 de marzo de 1979", "Mar 21 1979"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                parsed = parse_date_text(raw)
                self.assertIsNotNone(parsed)
                self.assertEqual(format_long_date(parsed), expected)


class NormalizeDateTextTests(unittest.TestCase):
    def test_normalizes_to_canonical_format(self) -> None:
        self.assertEqual(normalize_date_text_to_long("03/21/1979"), "Mar 21 1979")

    def test_returns_empty_for_invalid_input(self) -> None:
        self.assertEqual(normalize_date_text_to_long("foo"), "")


class MonthTokenLookupTests(unittest.TestCase):
    def test_resolves_english_abbreviations(self) -> None:
        self.assertEqual(month_token_to_number("Mar"), 3)
        self.assertEqual(month_token_to_number("MARCH"), 3)
        self.assertEqual(month_token_to_number("sept."), 9)

    def test_resolves_spanish_full_names(self) -> None:
        self.assertEqual(month_token_to_number("marzo"), 3)
        self.assertEqual(month_token_to_number("febrero"), 2)
        self.assertEqual(month_token_to_number("septiembre"), 9)

    def test_returns_none_for_unknown_token(self) -> None:
        self.assertIsNone(month_token_to_number("xyz"))


class ConstantsTests(unittest.TestCase):
    def test_long_date_format_human_is_documented(self) -> None:
        self.assertEqual(LONG_DATE_FORMAT_HUMAN, "Mmm DD YYYY")

    def test_long_date_example_matches_format(self) -> None:
        self.assertEqual(LONG_DATE_EXAMPLE, "Mar 21 1979")
        parsed = parse_date_text(LONG_DATE_EXAMPLE)
        self.assertIsNotNone(parsed)
        self.assertEqual(format_long_date(parsed), LONG_DATE_EXAMPLE)


if __name__ == "__main__":
    unittest.main()
