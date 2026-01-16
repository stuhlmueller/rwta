"""Web search tool for the LLM to fetch real-world information."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from rwta.location import Location

import httpx


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


def search_web(query: str, max_results: int = 5, timeout: float = 10.0) -> str:
    """
    Search the web using DuckDuckGo HTML interface.

    Args:
        query: The search query.
        max_results: Maximum number of results to return.
        timeout: Request timeout in seconds.

    Returns:
        Formatted string with search results.
    """
    try:
        # Use DuckDuckGo HTML interface (no API key needed)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

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
            return f"No results found for: {query}"

        # Format results
        formatted = f"Search results for: {query}\n\n"
        for i, result in enumerate(results, 1):
            formatted += f"{i}. {result['title']}\n"
            formatted += f"   {result['snippet']}\n\n"

        return formatted.strip()

    except httpx.HTTPError as e:
        return f"Search failed: {e}"


def _parse_duckduckgo_html(html: str, max_results: int) -> list[dict[str, str]]:
    """
    Parse search results from DuckDuckGo HTML response.

    Args:
        html: The HTML response from DuckDuckGo.
        max_results: Maximum number of results to parse.

    Returns:
        List of dictionaries with 'title' and 'snippet' keys.
    """

    class _DDGParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self._capture: str | None = None
            self._capture_tag: str | None = None
            self._buf: list[str] = []
            self.titles: list[str] = []
            self.snippets: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attrs_dict = dict(attrs)
            class_attr = attrs_dict.get("class") or ""
            classes = set(class_attr.split())

            if "result__a" in classes:
                self._capture = "title"
                self._capture_tag = tag
                self._buf = []
            elif "result__snippet" in classes:
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

    parser = _DDGParser()
    parser.feed(html)

    results: list[dict[str, str]] = []
    for i in range(min(len(parser.titles), len(parser.snippets), max_results)):
        title = parser.titles[i].strip()
        snippet = parser.snippets[i].strip()
        if title and snippet:
            results.append({"title": title, "snippet": snippet})

    if results:
        return results

    # Fallback: very loose regex for environments where the HTML is malformed.
    title_pattern = re.compile(r'class="result__a"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

    titles = [unescape(t).strip() for t in title_pattern.findall(html)]
    snippets = [unescape(s).strip() for s in snippet_pattern.findall(html)]

    for i in range(min(len(titles), len(snippets), max_results)):
        title = re.sub(r"<[^>]+>", "", titles[i]).strip()
        snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
        if title and snippet:
            results.append({"title": title, "snippet": snippet})

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
            return ToolResult("Error: No query provided")
        return ToolResult(search_web(query))

    if tool_name == "advance_time":
        minutes = tool_input.get("minutes", 0)
        reason = tool_input.get("reason", "Time passed")
        if not isinstance(minutes, int):
            try:
                minutes = int(minutes)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                return ToolResult("Error: Invalid minutes value")
        if minutes < 0:
            return ToolResult("Error: Minutes must be non-negative")
        return ToolResult(
            f"Time advanced by {minutes} minutes ({reason})",
            advance_time_minutes=minutes,
            advance_time_reason=str(reason),
        )

    if tool_name == "update_location":
        city = str(tool_input.get("city", "")).strip()
        region = str(tool_input.get("region", "")).strip()
        country = str(tool_input.get("country", "")).strip()

        if not city or not region or not country:
            return ToolResult("Error: city, region, and country are required")

        address_val = tool_input.get("address")
        address = str(address_val).strip() if address_val else None

        lat_val = tool_input.get("latitude")
        lon_val = tool_input.get("longitude")

        latitude: float | None = None
        longitude: float | None = None

        if lat_val is not None:
            try:
                latitude = float(lat_val)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                pass

        if lon_val is not None:
            try:
                longitude = float(lon_val)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                pass

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
