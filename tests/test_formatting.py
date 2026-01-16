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


if __name__ == "__main__":
    unittest.main()
