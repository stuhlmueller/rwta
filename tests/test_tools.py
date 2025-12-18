import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.tools import _parse_duckduckgo_html, execute_tool  # noqa: E402


class TestTools(unittest.TestCase):
    def test_parse_duckduckgo_html(self) -> None:
        html = """
        <html>
          <body>
            <a class="result__a" href="https://example.com">Example Title</a>
            <a class="result__snippet" href="https://example.com">Example snippet.</a>
            <a class="result__a" href="https://example.org">Second</a>
            <a class="result__snippet" href="https://example.org">Second snippet.</a>
          </body>
        </html>
        """
        results = _parse_duckduckgo_html(html, max_results=5)
        self.assertEqual(
            results,
            [
                {"title": "Example Title", "snippet": "Example snippet."},
                {"title": "Second", "snippet": "Second snippet."},
            ],
        )

    def test_advance_time_rejects_negative(self) -> None:
        result = execute_tool("advance_time", {"minutes": -5, "reason": "oops"})
        self.assertIn("non-negative", result.message)


if __name__ == "__main__":
    unittest.main()

