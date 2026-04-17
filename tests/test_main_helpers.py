"""Tests for the small utility helpers in rwta.main and tools.LocationUpdate."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.main import _sanitize_slug, _strip_suggestions  # noqa: E402
from rwta.tools import LocationUpdate  # noqa: E402


class TestSanitizeSlug(unittest.TestCase):
    def test_lowercases_and_hyphenates(self) -> None:
        self.assertEqual(_sanitize_slug("San Francisco"), "san-francisco")

    def test_strips_punctuation(self) -> None:
        self.assertEqual(_sanitize_slug("Saint-Tropez!"), "saint-tropez")

    def test_keeps_digits(self) -> None:
        self.assertEqual(_sanitize_slug("District 9"), "district-9")

    def test_collapses_multiple_punctuation(self) -> None:
        # Punctuation other than hyphens is dropped, spaces become hyphens.
        self.assertEqual(_sanitize_slug("New York, NY (USA)"), "new-york-ny-usa")

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(_sanitize_slug(""), "")


class TestStripSuggestions(unittest.TestCase):
    def test_removes_trailing_section(self) -> None:
        text = "The harbor lies still.\n\n---\n1. Walk\n2. Wait\n3. Run"
        self.assertEqual(_strip_suggestions(text), "The harbor lies still.")

    def test_no_suggestions_returns_unchanged(self) -> None:
        text = "Just a narrative."
        self.assertEqual(_strip_suggestions(text), text)

    def test_preserves_horizontal_rule_inside_narrative(self) -> None:
        # A markdown horizontal rule used as a section break in the narrative
        # must NOT be confused with the suggestions delimiter. Only a trailing
        # `---` followed by a numbered list is the suggestions block.
        text = "Para one.\n\n---\n\nPara two.\n\n---\n1. Walk on\n2. Turn back\n3. Sit down\n"
        stripped = _strip_suggestions(text)
        self.assertIn("Para one", stripped)
        self.assertIn("Para two", stripped)
        self.assertNotIn("1. Walk on", stripped)


class TestLocationUpdate(unittest.TestCase):
    def test_to_location_round_trip(self) -> None:
        update = LocationUpdate(
            city="Paris",
            region="Ile-de-France",
            country="France",
            address="Eiffel Tower",
            latitude=48.8584,
            longitude=2.2945,
        )
        loc = update.to_location()
        self.assertEqual(loc.city, "Paris")
        self.assertEqual(loc.region, "Ile-de-France")
        self.assertEqual(loc.country, "France")
        self.assertEqual(loc.address, "Eiffel Tower")
        self.assertAlmostEqual(loc.latitude or 0.0, 48.8584)
        self.assertAlmostEqual(loc.longitude or 0.0, 2.2945)

    def test_to_location_without_optional_fields(self) -> None:
        update = LocationUpdate(city="Reno", region="NV", country="US")
        loc = update.to_location()
        self.assertIsNone(loc.address)
        self.assertIsNone(loc.latitude)
        self.assertIsNone(loc.longitude)


if __name__ == "__main__":
    unittest.main()
