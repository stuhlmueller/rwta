"""Extended tests for formatting utilities."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.formatting import (  # noqa: E402
    ANSI_BOLD,
    ANSI_ITALIC,
    ANSI_RESET,
    _tokenize_markdown_line,
    wrap_text,
)


class TestWrapText(unittest.TestCase):
    def test_short_text_unchanged(self) -> None:
        text = "A short sentence."
        result = wrap_text(text, width=80)
        self.assertEqual(result, text)

    def test_long_text_wraps(self) -> None:
        text = "word " * 30  # ~150 chars
        result = wrap_text(text, width=40)
        for line in result.split("\n"):
            self.assertLessEqual(len(line), 40)

    def test_preserves_paragraph_breaks(self) -> None:
        text = "First paragraph.\n\nSecond paragraph."
        result = wrap_text(text, width=80)
        self.assertIn("\n\n", result)

    def test_preserves_list_items(self) -> None:
        text = "Intro:\n\n- Item one\n- Item two\n- Item three"
        result = wrap_text(text, width=80)
        self.assertIn("- Item one", result)
        self.assertIn("- Item two", result)

    def test_preserves_numbered_list(self) -> None:
        text = "1. First item\n2. Second item\n3. Third item"
        result = wrap_text(text, width=80)
        self.assertIn("1.", result)
        self.assertIn("2.", result)
        self.assertIn("3.", result)


class TestTokenizeMarkdownLine(unittest.TestCase):
    def test_plain_text(self) -> None:
        tokens = _tokenize_markdown_line("hello world")
        self.assertEqual(tokens, ["hello", " ", "world"])

    def test_bold_text(self) -> None:
        tokens = _tokenize_markdown_line("**bold**")
        self.assertIn(ANSI_BOLD, tokens)
        self.assertIn("bold", tokens)
        # Should have a reset
        self.assertTrue(any(ANSI_RESET in t for t in tokens))

    def test_italic_text(self) -> None:
        tokens = _tokenize_markdown_line("*italic*")
        self.assertIn(ANSI_ITALIC, tokens)
        self.assertIn("italic", tokens)

    def test_bold_and_italic(self) -> None:
        tokens = _tokenize_markdown_line("**bold** and *italic*")
        self.assertIn(ANSI_BOLD, tokens)
        self.assertIn(ANSI_ITALIC, tokens)
        self.assertIn("bold", tokens)
        self.assertIn("italic", tokens)

    def test_unclosed_bold(self) -> None:
        tokens = _tokenize_markdown_line("**unclosed bold")
        # Should still produce a reset at the end
        self.assertEqual(tokens[-1], ANSI_RESET)

    def test_empty_line(self) -> None:
        tokens = _tokenize_markdown_line("")
        self.assertEqual(tokens, [])


if __name__ == "__main__":
    unittest.main()
