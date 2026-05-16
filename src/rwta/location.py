"""IP-based geolocation and weather for determining player's environment."""

import logging
import readline
from dataclasses import dataclass, replace

import httpx

from rwta.config import GEOLOCATION_TIMEOUT, WEATHER_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class Weather:
    """Current weather conditions."""

    description: str
    temperature_f: float
    feels_like_f: float
    humidity: int
    wind_mph: float

    def __str__(self) -> str:
        """Return a human-readable weather string."""
        return (
            f"{self.description}, {self.temperature_f:.0f}°F "
            f"(feels like {self.feels_like_f:.0f}°F), "
            f"{self.humidity}% humidity, wind {self.wind_mph:.0f} mph"
        )


@dataclass
class Location:
    """Represents a geographic location."""

    city: str
    region: str
    country: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def __str__(self) -> str:
        """Return a human-readable location string."""
        if self.address:
            return f"{self.address}, {self.city}, {self.region}, {self.country}"
        parts = [self.city, self.region, self.country]
        return ", ".join(p for p in parts if p)

    def short_str(self) -> str:
        """Return a short location string (city, country)."""
        return f"{self.city}, {self.country}"


def get_city_from_ip(timeout: float | None = None) -> Location:
    """
    Get the current city based on IP address.

    Uses the free ipinfo.io API. Falls back to a default location
    if the API is unavailable.

    Args:
        timeout: Request timeout in seconds (default from config).

    Returns:
        Location object with city, region, and country (no street address).
    """
    if timeout is None:
        timeout = GEOLOCATION_TIMEOUT
    try:
        response = httpx.get("https://ipinfo.io/json", timeout=timeout)
        response.raise_for_status()
        data = response.json()

        # Parse latitude/longitude if available
        lat, lon = None, None
        if "loc" in data:
            try:
                lat_str, lon_str = data["loc"].split(",")
                lat, lon = float(lat_str), float(lon_str)
            except (ValueError, AttributeError):
                pass

        return Location(
            city=data.get("city", "Unknown City"),
            region=data.get("region", "Unknown Region"),
            country=data.get("country", "Unknown Country"),
            latitude=lat,
            longitude=lon,
        )
    except httpx.HTTPError as e:
        logger.warning("Geolocation failed, using default (San Francisco): %s", e)
        return Location(
            city="San Francisco",
            region="California",
            country="US",
        )


def geocode_location(query: str, timeout: float | None = None) -> Location | None:
    """Geocode a free-form place/address using OpenStreetMap Nominatim."""
    if timeout is None:
        timeout = GEOLOCATION_TIMEOUT
    cleaned = query.strip()
    if not cleaned:
        return None

    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": cleaned, "format": "jsonv2", "limit": 1, "addressdetails": 1},
            headers={"User-Agent": "rwta/0.1 (https://github.com/stuhlmueller/rwta)"},
            timeout=timeout,
        )
        response.raise_for_status()
        results = response.json()
    except httpx.HTTPError as e:
        logger.warning("Geocoding failed for %r: %s", cleaned, e)
        return None

    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    address = first.get("address") if isinstance(first.get("address"), dict) else {}
    assert isinstance(address, dict)

    city = str(
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("county")
        or cleaned
    )
    region = str(address.get("state") or address.get("region") or "")
    country = str(address.get("country") or "")
    address_text = None if cleaned.casefold() == city.casefold() else cleaned
    try:
        latitude = float(str(first.get("lat")))
        longitude = float(str(first.get("lon")))
    except (TypeError, ValueError):
        latitude = None
        longitude = None

    return Location(
        city=city,
        region=region,
        country=country,
        address=address_text,
        latitude=latitude,
        longitude=longitude,
    )


def prompt_for_address(city_location: Location) -> Location:
    """
    Prompt the user for a specific street address within their city.

    The detected location is pre-filled as default text that the user can
    edit or accept by pressing Enter.

    Args:
        city_location: The city-level location from IP geolocation.

    Returns:
        New Location with the user's specified address (original is not mutated).
    """
    default_address = city_location.short_str()

    def prefill_input() -> None:
        readline.insert_text(default_address)

    print("\nEnter your starting address (edit or press Enter to accept):")

    # Set up the prefill hook
    readline.set_startup_hook(prefill_input)
    try:
        address = input("> ").strip()
    finally:
        # Clear the hook so it doesn't affect future inputs
        readline.set_startup_hook(None)

    return replace(city_location, address=address or None)


def get_weather(location: Location, timeout: float | None = None) -> Weather | None:
    """
    Fetch current weather for a location using Open-Meteo API (free, no key needed).

    Args:
        location: Location with latitude/longitude.
        timeout: Request timeout in seconds (default from config).

    Returns:
        Weather object or None if fetch fails.
    """
    if location.latitude is None or location.longitude is None:
        return None

    if timeout is None:
        timeout = WEATHER_TIMEOUT

    try:
        # Open-Meteo free weather API
        response = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()

        current = data.get("current", {})

        # Map weather codes to descriptions
        weather_code = current.get("weather_code", 0)
        description = _weather_code_to_description(weather_code)

        return Weather(
            description=description,
            temperature_f=current.get("temperature_2m", 0),
            feels_like_f=current.get("apparent_temperature", 0),
            humidity=current.get("relative_humidity_2m", 0),
            wind_mph=current.get("wind_speed_10m", 0),
        )
    except httpx.HTTPError as e:
        logger.warning("Weather fetch failed for %s: %s", location.city, e)
        return None


def _weather_code_to_description(code: int) -> str:
    """Convert WMO weather code to human-readable description."""
    codes = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return codes.get(code, "Unknown conditions")
