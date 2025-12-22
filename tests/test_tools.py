import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.tools import _parse_duckduckgo_html, execute_tool


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

    def test_update_thread_basic(self) -> None:
        """update_thread tool returns valid UpdateThreadData."""
        result = execute_tool(
            "update_thread",
            {
                "thread_id": "abc-123",
                "summary": "Cat is now home",
                "status": "in_scene",
            },
        )
        self.assertIn("updated", result.message.lower())
        assert result.update_thread_data is not None
        self.assertEqual(result.update_thread_data.thread_id, "abc-123")
        self.assertEqual(result.update_thread_data.summary, "Cat is now home")
        self.assertEqual(result.update_thread_data.status, "in_scene")

    def test_update_thread_with_optional_fields(self) -> None:
        """update_thread accepts optional history_entry and location."""
        result = execute_tool(
            "update_thread",
            {
                "thread_id": "xyz-789",
                "summary": "Detective finished investigation",
                "status": "resolved",
                "history_entry": "Completed the case successfully",
                "location_city": "San Francisco",
                "location_region": "California",
                "location_country": "US",
                "location_address": "Downtown",
            },
        )
        assert result.update_thread_data is not None
        self.assertEqual(result.update_thread_data.history_entry, "Completed the case successfully")
        self.assertEqual(result.update_thread_data.location_city, "San Francisco")
        self.assertEqual(result.update_thread_data.location_address, "Downtown")
        self.assertTrue(result.update_thread_data.has_location())

    def test_update_thread_requires_fields(self) -> None:
        """update_thread requires thread_id, summary, and status."""
        result = execute_tool("update_thread", {"thread_id": "abc"})
        self.assertIn("required", result.message.lower())
        self.assertIsNone(result.update_thread_data)

        result = execute_tool("update_thread", {"thread_id": "abc", "summary": "test"})
        self.assertIn("required", result.message.lower())
        self.assertIsNone(result.update_thread_data)

    def test_update_thread_validates_status(self) -> None:
        """update_thread rejects invalid status values."""
        result = execute_tool(
            "update_thread",
            {
                "thread_id": "abc",
                "summary": "Test",
                "status": "invalid_status",
            },
        )
        self.assertIn("invalid status", result.message.lower())
        self.assertIsNone(result.update_thread_data)

    def test_update_thread_accepts_all_valid_statuses(self) -> None:
        """update_thread accepts all valid status values."""
        for status in ["active", "in_scene", "paused", "resolved"]:
            result = execute_tool(
                "update_thread",
                {
                    "thread_id": "abc",
                    "summary": "Test",
                    "status": status,
                },
            )
            assert result.update_thread_data is not None
            self.assertEqual(result.update_thread_data.status, status)


if __name__ == "__main__":
    unittest.main()
