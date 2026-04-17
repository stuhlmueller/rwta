import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.formatting import parse_suggestions  # noqa: E402


class TestFormatting(unittest.TestCase):
    def test_parse_suggestions_extracts_actions(self) -> None:
        text = """The sun sets over the harbor.

---
1. Walk toward the lighthouse
2. Talk to the fisherman
3. Check your pockets"""

        narrative, suggestions = parse_suggestions(text)
        self.assertEqual(narrative, "The sun sets over the harbor.")
        self.assertEqual(
            suggestions,
            ["Walk toward the lighthouse", "Talk to the fisherman", "Check your pockets"],
        )

    def test_parse_suggestions_no_suggestions(self) -> None:
        text = "Just a regular narrative without any suggestions."
        narrative, suggestions = parse_suggestions(text)
        self.assertEqual(narrative, text)
        self.assertEqual(suggestions, [])

    def test_parse_suggestions_handles_extra_whitespace(self) -> None:
        text = """Narrative here.

---

1.   Action one
2. Action two
3.   Action three
"""
        narrative, suggestions = parse_suggestions(text)
        self.assertEqual(narrative, "Narrative here.")
        self.assertEqual(suggestions, ["Action one", "Action two", "Action three"])

    def test_parse_suggestions_ignores_horizontal_rule_in_narrative(self) -> None:
        # A markdown horizontal rule mid-narrative must not be confused with the
        # suggestions delimiter. Only a trailing `---` followed by a numbered
        # list counts as the suggestions block.
        text = (
            "Part one of the scene.\n"
            "\n---\n\n"  # mid-narrative horizontal rule
            "Part two of the scene.\n"
            "\n---\n"
            "1. Walk to the harbor\n"
            "2. Look for a phone\n"
            "3. Sit on the bench\n"
        )
        narrative, suggestions = parse_suggestions(text)
        self.assertIn("Part one", narrative)
        self.assertIn("Part two", narrative)
        self.assertEqual(
            suggestions,
            ["Walk to the harbor", "Look for a phone", "Sit on the bench"],
        )

    def test_parse_suggestions_supports_paren_numbering(self) -> None:
        text = "Scene.\n\n---\n1) Run\n2) Hide\n3) Fight\n"
        narrative, suggestions = parse_suggestions(text)
        self.assertEqual(narrative, "Scene.")
        self.assertEqual(suggestions, ["Run", "Hide", "Fight"])

    def test_parse_suggestions_no_separator(self) -> None:
        text = "Just narrative, no suggestions block."
        narrative, suggestions = parse_suggestions(text)
        self.assertEqual(narrative, text.strip())
        self.assertEqual(suggestions, [])


if __name__ == "__main__":
    unittest.main()
