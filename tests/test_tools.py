import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.tools import (  # noqa: E402
    _cache_search_result,
    _get_cached_search,
    _parse_float,
    _parse_int,
    clear_search_cache,
    execute_tool,
)


class TestTools(unittest.TestCase):
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
        self.assertIn("requires", result.message)
        self.assertIn("region", result.message)
        self.assertIn("country", result.message)
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

    def test_search_cache_stores_and_retrieves(self) -> None:
        clear_search_cache()
        _cache_search_result("test query", "cached result")
        result = _get_cached_search("test query")
        self.assertEqual(result, "cached result")

    def test_search_cache_is_case_insensitive(self) -> None:
        clear_search_cache()
        _cache_search_result("Test Query", "cached result")
        result = _get_cached_search("test query")
        self.assertEqual(result, "cached result")

    def test_search_cache_returns_none_for_missing(self) -> None:
        clear_search_cache()
        result = _get_cached_search("nonexistent query")
        self.assertIsNone(result)

    def test_parse_int_with_int(self) -> None:
        result, error = _parse_int(42, "field")
        self.assertEqual(result, 42)
        self.assertIsNone(error)

    def test_parse_int_with_float(self) -> None:
        result, error = _parse_int(3.7, "field")
        self.assertEqual(result, 3)  # Truncates
        self.assertIsNone(error)

    def test_parse_int_with_string(self) -> None:
        result, error = _parse_int("123", "field")
        self.assertEqual(result, 123)
        self.assertIsNone(error)

    def test_parse_int_with_invalid_string(self) -> None:
        result, error = _parse_int("not a number", "myfield")
        self.assertIsNone(result)
        self.assertIn("myfield", error or "")
        self.assertIn("integer", error or "")

    def test_parse_float_with_int(self) -> None:
        result, error = _parse_float(42, "field")
        self.assertEqual(result, 42.0)
        self.assertIsNone(error)

    def test_parse_float_with_float(self) -> None:
        result, error = _parse_float(3.14, "field")
        self.assertEqual(result, 3.14)
        self.assertIsNone(error)

    def test_parse_float_with_string(self) -> None:
        result, error = _parse_float("3.14", "field")
        self.assertEqual(result, 3.14)
        self.assertIsNone(error)

    def test_parse_float_with_invalid_string(self) -> None:
        result, error = _parse_float("not a number", "myfield")
        self.assertIsNone(result)
        self.assertIn("myfield", error or "")
        self.assertIn("number", error or "")

    def test_advance_time_error_message_is_specific(self) -> None:
        result = execute_tool("advance_time", {"minutes": "invalid", "reason": "test"})
        self.assertIn("integer", result.message)
        self.assertIn("minutes", result.message)


if __name__ == "__main__":
    unittest.main()
