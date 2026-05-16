"""Tests for adaptive thinking configuration in GameNarrator."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Need an API key set so the Anthropic client constructor doesn't error.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-only-fake")


class TestThinkingKwargs(unittest.TestCase):
    """Patch ``THINKING_MODE`` for the duration of each test.

    ``_thinking_kwargs`` reads the module-level constant at call time, so the
    patch must be active when the method is invoked, not just when the
    narrator is constructed.
    """

    def _kwargs(self, fast: bool = False, mode: str = "adaptive") -> dict[str, object]:
        import rwta.llm

        with patch.object(rwta.llm, "THINKING_MODE", mode):
            return rwta.llm.GameNarrator(fast=fast)._thinking_kwargs()

    def test_default_enables_adaptive(self) -> None:
        kwargs = self._kwargs()
        self.assertIn("extra_body", kwargs)
        body = kwargs["extra_body"]
        assert isinstance(body, dict)
        self.assertEqual(body["thinking"], {"type": "adaptive", "display": "omitted"})
        self.assertIn("output_config", body)

    def test_fast_mode_disables_thinking(self) -> None:
        self.assertEqual(self._kwargs(fast=True), {})

    def test_mode_off_disables_thinking(self) -> None:
        self.assertEqual(self._kwargs(mode="off"), {})

    def test_unknown_mode_disables_thinking(self) -> None:
        # Defensive: unknown values should not silently enable an invalid mode.
        self.assertEqual(self._kwargs(mode="manual"), {})


class TestVisualContinuityHelpers(unittest.TestCase):
    def test_clean_visual_ledger_removes_empty_bullets(self) -> None:
        from rwta.llm import GameNarrator

        raw = """
        - Red jacket
        -
        •
        * Brass compass
        """

        self.assertEqual(
            GameNarrator._clean_visual_ledger(raw),
            "- Red jacket\n* Brass compass",
        )


class TestContentBlockRoundTrip(unittest.TestCase):
    """Thinking blocks must survive _content_blocks_to_list for tool-use loops."""

    def test_preserves_thinking_block(self) -> None:
        from anthropic.types import TextBlock, ThinkingBlock

        from rwta.llm import GameNarrator

        n = GameNarrator()
        thinking = ThinkingBlock(type="thinking", thinking="(reasoning)", signature="opaque-sig")
        text = TextBlock(type="text", text="Hello.", citations=None)
        result = n._content_blocks_to_list([thinking, text])

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "thinking")
        self.assertEqual(result[0]["thinking"], "(reasoning)")
        self.assertEqual(result[0]["signature"], "opaque-sig")
        self.assertEqual(result[1]["type"], "text")
        self.assertEqual(result[1]["text"], "Hello.")

    def test_preserves_redacted_thinking_block(self) -> None:
        from anthropic.types import RedactedThinkingBlock, TextBlock

        from rwta.llm import GameNarrator

        n = GameNarrator()
        redacted = RedactedThinkingBlock(type="redacted_thinking", data="encrypted-blob")
        text = TextBlock(type="text", text="OK", citations=None)
        result = n._content_blocks_to_list([redacted, text])

        self.assertEqual(result[0], {"type": "redacted_thinking", "data": "encrypted-blob"})
        self.assertEqual(result[1]["type"], "text")


if __name__ == "__main__":
    unittest.main()
