"""Tests for web search with mocked duckduckgo-search."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from duckduckgo_search.exceptions import DuckDuckGoSearchException  # noqa: E402

from rwta.tools import clear_search_cache, search_web  # noqa: E402


class TestSearchWeb(unittest.TestCase):
    def setUp(self) -> None:
        clear_search_cache()

    @patch("rwta.tools.DDGS")
    def test_successful_search(self, mock_ddgs_cls: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {"title": "Coffee Shop", "href": "https://example.com", "body": "Best coffee in town."},
        ]
        mock_ddgs_cls.return_value = mock_ddgs

        result = search_web("coffee near me")
        self.assertIn("Coffee Shop", result)
        self.assertIn("Best coffee in town", result)

    @patch("rwta.tools.DDGS")
    def test_search_timeout(self, mock_ddgs_cls: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.side_effect = TimeoutError("timeout")
        mock_ddgs_cls.return_value = mock_ddgs

        result = search_web("test query", timeout=5.0)
        self.assertIn("timed out", result)

    @patch("rwta.tools.DDGS")
    def test_search_connection_error(self, mock_ddgs_cls: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.side_effect = ConnectionError("Network down")
        mock_ddgs_cls.return_value = mock_ddgs

        result = search_web("test query")
        self.assertIn("connection failed", result.lower())

    @patch("rwta.tools.DDGS")
    def test_search_no_results(self, mock_ddgs_cls: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = []
        mock_ddgs_cls.return_value = mock_ddgs

        result = search_web("xyznonexistentquery123")
        self.assertIn("No results found", result)

    @patch("rwta.tools.DDGS")
    def test_search_caches_results(self, mock_ddgs_cls: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {"title": "Result", "href": "https://example.com", "body": "Snippet."},
        ]
        mock_ddgs_cls.return_value = mock_ddgs

        # First call hits network
        result1 = search_web("cached query")
        self.assertEqual(mock_ddgs_cls.call_count, 1)

        # Second call should use cache
        result2 = search_web("cached query")
        self.assertEqual(mock_ddgs_cls.call_count, 1)  # No additional call
        self.assertEqual(result1, result2)

    @patch("rwta.tools.DDGS")
    def test_search_ddg_exception(self, mock_ddgs_cls: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.side_effect = DuckDuckGoSearchException("Rate limited")
        mock_ddgs_cls.return_value = mock_ddgs

        result = search_web("test query")
        self.assertIn("Search failed", result)


if __name__ == "__main__":
    unittest.main()
