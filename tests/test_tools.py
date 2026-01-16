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

    def test_update_location_returns_location_update(self) -> None:
        result = execute_tool(
            "update_location",
            {
                "city": "Tokyo",
                "region": "Tokyo",
                "country": "Japan",
                "address": "Shibuya Station",
            },
        )
        self.assertIn("Tokyo", result.message)
        assert result.location_update is not None
        self.assertEqual(result.location_update.city, "Tokyo")
        self.assertEqual(result.location_update.address, "Shibuya Station")

    def test_update_location_requires_city_region_country(self) -> None:
        result = execute_tool("update_location", {"city": "NYC"})
        self.assertIn("required", result.message)
        self.assertIsNone(result.location_update)

    def test_update_location_handles_coordinates(self) -> None:
        result = execute_tool(
            "update_location",
            {
                "city": "Paris",
                "region": "Ile-de-France",
                "country": "France",
                "latitude": 48.8566,
                "longitude": 2.3522,
            },
        )
        assert result.location_update is not None
        self.assertEqual(result.location_update.latitude, 48.8566)
        self.assertEqual(result.location_update.longitude, 2.3522)


if __name__ == "__main__":
    unittest.main()
