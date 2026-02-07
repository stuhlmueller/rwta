"""Tests for web search with mocked HTTP."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.tools import clear_search_cache, search_web  # noqa: E402


class TestSearchWeb(unittest.TestCase):
    def setUp(self) -> None:
        clear_search_cache()

    @patch("rwta.tools.httpx.get")
    def test_successful_search(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = """
        <html><body>
            <a class="result__a" href="https://example.com">Coffee Shop</a>
            <a class="result__snippet" href="https://example.com">Best coffee in town.</a>
        </body></html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = search_web("coffee near me")
        self.assertIn("Coffee Shop", result)
        self.assertIn("Best coffee in town", result)

    @patch("rwta.tools.httpx.get")
    def test_search_timeout(self, mock_get: MagicMock) -> None:
        import httpx

        mock_get.side_effect = httpx.TimeoutException("timeout")

        result = search_web("test query", timeout=5.0)
        self.assertIn("timed out", result)

    @patch("rwta.tools.httpx.get")
    def test_search_connection_error(self, mock_get: MagicMock) -> None:
        import httpx

        mock_get.side_effect = httpx.ConnectError("Network down")

        result = search_web("test query")
        self.assertIn("connection failed", result.lower())

    @patch("rwta.tools.httpx.get")
    def test_search_no_results(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = "<html><body>No results</body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = search_web("xyznonexistentquery123")
        self.assertIn("No results found", result)

    @patch("rwta.tools.httpx.get")
    def test_search_caches_results(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = """
        <html><body>
            <a class="result__a" href="https://example.com">Result</a>
            <a class="result__snippet" href="https://example.com">Snippet.</a>
        </body></html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # First call hits network
        result1 = search_web("cached query")
        self.assertEqual(mock_get.call_count, 1)

        # Second call should use cache
        result2 = search_web("cached query")
        self.assertEqual(mock_get.call_count, 1)  # No additional call
        self.assertEqual(result1, result2)

    @patch("rwta.tools.httpx.get")
    def test_search_http_error(self, mock_get: MagicMock) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.reason_phrase = "Service Unavailable"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=mock_response
        )
        mock_get.return_value = mock_response

        result = search_web("test query")
        self.assertIn("503", result)


if __name__ == "__main__":
    unittest.main()
