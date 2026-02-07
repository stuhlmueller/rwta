"""Tests for geolocation and weather with mocked HTTP."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.location import Location, Weather, get_city_from_ip, get_weather  # noqa: E402


class TestGetCityFromIp(unittest.TestCase):
    @patch("rwta.location.httpx.get")
    def test_successful_geolocation(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "city": "Oakland",
            "region": "California",
            "country": "US",
            "loc": "37.8044,-122.2712",
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        location = get_city_from_ip()
        self.assertEqual(location.city, "Oakland")
        self.assertEqual(location.region, "California")
        self.assertEqual(location.country, "US")
        self.assertAlmostEqual(location.latitude or 0, 37.8044, places=3)
        self.assertAlmostEqual(location.longitude or 0, -122.2712, places=3)

    @patch("rwta.location.httpx.get")
    def test_geolocation_missing_loc(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "city": "Tokyo",
            "region": "Tokyo",
            "country": "JP",
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        location = get_city_from_ip()
        self.assertEqual(location.city, "Tokyo")
        self.assertIsNone(location.latitude)
        self.assertIsNone(location.longitude)

    @patch("rwta.location.httpx.get")
    def test_geolocation_fallback_on_error(self, mock_get: MagicMock) -> None:
        import httpx

        mock_get.side_effect = httpx.ConnectError("Network down")

        location = get_city_from_ip()
        self.assertEqual(location.city, "San Francisco")
        self.assertEqual(location.region, "California")

    @patch("rwta.location.httpx.get")
    def test_geolocation_fallback_on_http_error(self, mock_get: MagicMock) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = mock_response

        location = get_city_from_ip()
        self.assertEqual(location.city, "San Francisco")


class TestGetWeather(unittest.TestCase):
    @patch("rwta.location.httpx.get")
    def test_successful_weather(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "current": {
                "temperature_2m": 65.0,
                "apparent_temperature": 63.0,
                "relative_humidity_2m": 55,
                "weather_code": 0,
                "wind_speed_10m": 8.5,
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        location = Location(city="SF", region="CA", country="US", latitude=37.8, longitude=-122.4)
        weather = get_weather(location)

        self.assertIsNotNone(weather)
        assert weather is not None
        self.assertEqual(weather.temperature_f, 65.0)
        self.assertEqual(weather.feels_like_f, 63.0)
        self.assertEqual(weather.humidity, 55)
        self.assertEqual(weather.description, "Clear sky")
        self.assertEqual(weather.wind_mph, 8.5)

    def test_weather_without_coordinates(self) -> None:
        location = Location(city="SF", region="CA", country="US")
        weather = get_weather(location)
        self.assertIsNone(weather)

    @patch("rwta.location.httpx.get")
    def test_weather_fallback_on_error(self, mock_get: MagicMock) -> None:
        import httpx

        mock_get.side_effect = httpx.ConnectError("Network down")

        location = Location(city="SF", region="CA", country="US", latitude=37.8, longitude=-122.4)
        weather = get_weather(location)
        self.assertIsNone(weather)


class TestWeatherStr(unittest.TestCase):
    def test_weather_string_format(self) -> None:
        weather = Weather(
            description="Clear sky",
            temperature_f=72.0,
            feels_like_f=70.0,
            humidity=45,
            wind_mph=5.0,
        )
        result = str(weather)
        self.assertIn("Clear sky", result)
        self.assertIn("72", result)
        self.assertIn("70", result)
        self.assertIn("45%", result)
        self.assertIn("5 mph", result)


class TestLocationStr(unittest.TestCase):
    def test_location_with_address(self) -> None:
        loc = Location(city="SF", region="CA", country="US", address="123 Main St")
        self.assertEqual(str(loc), "123 Main St, SF, CA, US")

    def test_location_without_address(self) -> None:
        loc = Location(city="SF", region="CA", country="US")
        self.assertEqual(str(loc), "SF, CA, US")

    def test_location_short_str(self) -> None:
        loc = Location(city="SF", region="CA", country="US")
        self.assertEqual(loc.short_str(), "SF, US")


if __name__ == "__main__":
    unittest.main()
