"""Web search tool for the LLM to fetch real-world information."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from rwta.location import Location

import httpx

from rwta.config import (
    MAX_SEARCH_RESULTS,
    SEARCH_CACHE_TTL_SECONDS,
    SEARCH_TIMEOUT,
    SEARCH_USER_AGENT,
)

# Search cache: stores (query_key, timestamp, results) - session-scoped
_search_cache: dict[str, tuple[float, str]] = {}


def clear_search_cache() -> None:
    """Clear the search cache (useful for testing or new sessions)."""
    _search_cache.clear()


def _get_cached_search(query: str) -> str | None:
    """Get cached search result if available and fresh."""
    cache_key = query.lower().strip()
    if cache_key in _search_cache:
        cached_time, cached_result = _search_cache[cache_key]
        if time.time() - cached_time < SEARCH_CACHE_TTL_SECONDS:
            return cached_result
    return None


def _cache_search_result(query: str, result: str) -> None:
    """Cache a search result."""
    cache_key = query.lower().strip()
    _search_cache[cache_key] = (time.time(), result)


class ToolDefinition(TypedDict):
    """Type for Anthropic tool definition."""

    name: str
    description: str
    input_schema: dict[str, object]


# Tool definitions for Claude
SEARCH_WEB_TOOL: ToolDefinition = {
    "name": "search_web",
    "description": (
        "Search the web for current information about real-world places, events, news, "
        "businesses, directions, or any other factual information. Use this tool when you "
        "need up-to-date information about the real world to make the game more immersive "
        "and accurate. For example: search for nearby restaurants, local news, weather, "
        "historical facts about locations, business hours, etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up",
            },
        },
        "required": ["query"],
    },
}

ADVANCE_TIME_TOOL: ToolDefinition = {
    "name": "advance_time",
    "description": (
        "Advance the in-game time by a specified number of minutes. Use this whenever "
        "the player performs an action that takes time: walking somewhere (estimate based "
        "on distance, ~15-20 min per mile), waiting, sleeping, eating a meal, etc. "
        "Be realistic about how long activities take."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "minutes": {
                "type": "integer",
                "description": "Number of minutes to advance the in-game time",
            },
            "reason": {
                "type": "string",
                "description": "Brief description of what caused time to pass",
            },
        },
        "required": ["minutes", "reason"],
    },
}

UPDATE_LOCATION_TOOL: ToolDefinition = {
    "name": "update_location",
    "description": (
        "Update the player's current location when they move to a significantly different "
        "place (different neighborhood, city, or country). Use this when the player walks "
        "to a new area, takes transportation to a different part of town, or travels to "
        "another city. Don't call this for minor movements within the same immediate area."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "The city name (e.g., 'San Francisco', 'Tokyo')",
            },
            "region": {
                "type": "string",
                "description": "The state/province/region (e.g., 'California', 'Tokyo')",
            },
            "country": {
                "type": "string",
                "description": "The country code or name (e.g., 'US', 'Japan')",
            },
            "address": {
                "type": "string",
                "description": "Specific address or landmark (e.g., '123 Main St', 'Golden Gate Park')",
            },
            "latitude": {
                "type": "number",
                "description": "Latitude coordinate (optional, for weather accuracy)",
            },
            "longitude": {
                "type": "number",
                "description": "Longitude coordinate (optional, for weather accuracy)",
            },
        },
        "required": ["city", "region", "country"],
    },
}


def get_tools() -> list[ToolDefinition]:
    """Return the list of available tools."""
    return [SEARCH_WEB_TOOL, ADVANCE_TIME_TOOL, UPDATE_LOCATION_TOOL]


def search_web(query: str, max_results: int | None = None, timeout: float | None = None) -> str:
    """
    Search the web using DuckDuckGo HTML interface.

    Args:
        query: The search query.
        max_results: Maximum number of results to return (default from config).
        timeout: Request timeout in seconds (default from config).

    Returns:
        Formatted string with search results.
    """
    if max_results is None:
        max_results = MAX_SEARCH_RESULTS
    if timeout is None:
        timeout = SEARCH_TIMEOUT

    # Check cache first
    cached = _get_cached_search(query)
    if cached is not None:
        return cached

    try:
        headers = {"User-Agent": SEARCH_USER_AGENT}

        response = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()

        # Parse results from HTML
        results = _parse_duckduckgo_html(response.text, max_results)

        if not results:
            result = f"No results found for: {query}"
            _cache_search_result(query, result)
            return result

        # Format results
        formatted = f"Search results for: {query}\n\n"
        for i, result in enumerate(results, 1):
            formatted += f"{i}. {result['title']}\n"
            formatted += f"   {result['snippet']}\n\n"

        result = formatted.strip()
        _cache_search_result(query, result)
        return result

    except httpx.TimeoutException:
        return f"Search timed out after {timeout}s for query: {query}"
    except httpx.ConnectError as e:
        return f"Search connection failed (network issue): {e}"
    except httpx.HTTPStatusError as e:
        return f"Search failed with HTTP {e.response.status_code}: {e.response.reason_phrase}"
    except httpx.HTTPError as e:
        return f"Search request failed: {type(e).__name__}: {e}"


def _parse_duckduckgo_html(html: str, max_results: int) -> list[dict[str, str]]:
    """
    Parse search results from DuckDuckGo HTML response.

    Uses multiple parsing strategies for robustness against layout changes:
    1. Primary HTML parser looking for known class names
    2. Alternative class name patterns (DDG has changed these historically)
    3. Fallback regex patterns

    Args:
        html: The HTML response from DuckDuckGo.
        max_results: Maximum number of results to parse.

    Returns:
        List of dictionaries with 'title' and 'snippet' keys.
    """
    # Known DDG class names (current and historical)
    title_classes = {"result__a", "result-link", "js-result-title-link"}
    snippet_classes = {"result__snippet", "result-snippet", "js-result-snippet"}

    class _DDGParser(HTMLParser):
        def __init__(self, title_cls: set[str], snippet_cls: set[str]):
            super().__init__()
            self._title_classes = title_cls
            self._snippet_classes = snippet_cls
            self._capture: str | None = None
            self._capture_tag: str | None = None
            self._buf: list[str] = []
            self.titles: list[str] = []
            self.snippets: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attrs_dict = dict(attrs)
            class_attr = attrs_dict.get("class") or ""
            classes = set(class_attr.split())

            if classes & self._title_classes:  # Intersection - any match
                self._capture = "title"
                self._capture_tag = tag
                self._buf = []
            elif classes & self._snippet_classes:
                self._capture = "snippet"
                self._capture_tag = tag
                self._buf = []

        def handle_data(self, data: str) -> None:
            if self._capture:
                self._buf.append(data)

        def handle_endtag(self, tag: str) -> None:
            if not self._capture or self._capture_tag != tag:
                return

            text = unescape("".join(self._buf)).strip()
            if text:
                if self._capture == "title":
                    self.titles.append(text)
                else:
                    self.snippets.append(text)

            self._capture = None
            self._capture_tag = None
            self._buf = []

    # Try primary parser with known class names
    parser = _DDGParser(title_classes, snippet_classes)
    try:
        parser.feed(html)
    except Exception:
        # HTMLParser can fail on malformed HTML
        pass

    results: list[dict[str, str]] = []
    for i in range(min(len(parser.titles), len(parser.snippets), max_results)):
        title = parser.titles[i].strip()
        snippet = parser.snippets[i].strip()
        if title and snippet:
            results.append({"title": title, "snippet": snippet})

    if results:
        return results

    # Fallback 1: Regex patterns for known class names
    for title_cls in title_classes:
        for snippet_cls in snippet_classes:
            title_pattern = re.compile(
                rf'class="[^"]*{re.escape(title_cls)}[^"]*"[^>]*>(.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )
            snippet_pattern = re.compile(
                rf'class="[^"]*{re.escape(snippet_cls)}[^"]*"[^>]*>(.*?)</(?:a|div|span)>',
                re.DOTALL | re.IGNORECASE,
            )

            titles = [unescape(t).strip() for t in title_pattern.findall(html)]
            snippets = [unescape(s).strip() for s in snippet_pattern.findall(html)]

            for i in range(min(len(titles), len(snippets), max_results)):
                title = re.sub(r"<[^>]+>", "", titles[i]).strip()
                snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
                if title and snippet:
                    results.append({"title": title, "snippet": snippet})

            if results:
                return results

    # Fallback 2: Very generic pattern - look for links followed by text
    # This catches result blocks even if class names change completely
    generic_pattern = re.compile(
        r'<a[^>]+href="[^"]*"[^>]*>([^<]+)</a>\s*'
        r"(?:<[^>]+>)*\s*"
        r"([^<]{20,200})",  # Snippet: at least 20 chars, max 200
        re.DOTALL,
    )

    for match in generic_pattern.finditer(html):
        title = unescape(match.group(1)).strip()
        snippet = unescape(match.group(2)).strip()
        # Filter out navigation links and other non-result content
        if (
            title
            and snippet
            and len(title) > 5
            and not title.lower().startswith(("duck", "privacy", "settings", "about"))
        ):
            results.append({"title": title, "snippet": snippet})
            if len(results) >= max_results:
                break

    return results


@dataclass
class LocationUpdate:
    """Data for a location update."""

    city: str
    region: str
    country: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def to_location(self) -> Location:
        """Convert to a Location object."""
        from rwta.location import Location

        return Location(
            city=self.city,
            region=self.region,
            country=self.country,
            address=self.address,
            latitude=self.latitude,
            longitude=self.longitude,
        )


@dataclass
class ToolResult:
    """Result of a tool execution."""

    message: str
    advance_time_minutes: int | None = None
    advance_time_reason: str | None = None
    location_update: LocationUpdate | None = None


def _parse_int(value: object, field_name: str) -> tuple[int | None, str | None]:
    """Parse an object to int, returning (value, error_message)."""
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        return int(value), None
    if isinstance(value, str):
        try:
            return int(value), None
        except ValueError:
            return None, f"Error: {field_name} must be an integer, got '{value}'"
    return None, f"Error: {field_name} must be an integer, got type {type(value).__name__}"


def _parse_float(value: object, field_name: str) -> tuple[float | None, str | None]:
    """Parse an object to float, returning (value, error_message)."""
    if isinstance(value, int | float):
        return float(value), None
    if isinstance(value, str):
        try:
            return float(value), None
        except ValueError:
            return None, f"Error: {field_name} must be a number, got '{value}'"
    return None, f"Error: {field_name} must be a number, got type {type(value).__name__}"


def execute_tool(tool_name: str, tool_input: dict[str, object]) -> ToolResult:
    """
    Execute a tool by name with the given input.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Input parameters for the tool.

    Returns:
        ToolResult with execution result and any state changes needed.
    """
    if tool_name == "search_web":
        query = str(tool_input.get("query", "")).strip()
        if not query:
            return ToolResult("Error: search_web requires a 'query' parameter")
        return ToolResult(search_web(query))

    if tool_name == "advance_time":
        minutes_raw = tool_input.get("minutes", 0)
        reason = tool_input.get("reason", "Time passed")

        minutes, error = _parse_int(minutes_raw, "minutes")
        if error:
            return ToolResult(error)
        if minutes is None:
            return ToolResult("Error: minutes parameter is required")
        if minutes < 0:
            return ToolResult(f"Error: minutes must be non-negative, got {minutes}")
        return ToolResult(
            f"Time advanced by {minutes} minutes ({reason})",
            advance_time_minutes=minutes,
            advance_time_reason=str(reason),
        )

    if tool_name == "update_location":
        city = str(tool_input.get("city", "")).strip()
        region = str(tool_input.get("region", "")).strip()
        country = str(tool_input.get("country", "")).strip()

        missing = []
        if not city:
            missing.append("city")
        if not region:
            missing.append("region")
        if not country:
            missing.append("country")
        if missing:
            return ToolResult(f"Error: update_location requires: {', '.join(missing)}")

        address_val = tool_input.get("address")
        address = str(address_val).strip() if address_val else None

        lat_val = tool_input.get("latitude")
        lon_val = tool_input.get("longitude")

        latitude: float | None = None
        longitude: float | None = None

        if lat_val is not None:
            latitude, _ = _parse_float(lat_val, "latitude")
            # Ignore parse errors for optional coordinates

        if lon_val is not None:
            longitude, _ = _parse_float(lon_val, "longitude")
            # Ignore parse errors for optional coordinates

        location_update = LocationUpdate(
            city=city,
            region=region,
            country=country,
            address=address,
            latitude=latitude,
            longitude=longitude,
        )

        location_str = f"{address}, {city}" if address else city
        return ToolResult(
            f"Location updated to: {location_str}, {region}, {country}",
            location_update=location_update,
        )

    return ToolResult(f"Unknown tool: {tool_name}")
