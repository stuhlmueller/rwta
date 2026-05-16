"""Game state management with save/load functionality."""

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from rwta.config import (
    DATA_DIR,
    LOCAL_TIMEZONE,
    SUMMARIZATION_BUFFER_TOKENS,
    TOKEN_CHAR_ESTIMATE_DIVISOR,
)
from rwta.location import Location

logger = logging.getLogger(__name__)


def _now_local() -> datetime:
    """Get current time with explicit local timezone."""
    return datetime.now(LOCAL_TIMEZONE)


def _now_local_iso() -> str:
    """Get current time as ISO string with timezone."""
    return _now_local().isoformat()


@dataclass
class Message:
    """A single message in the conversation history."""

    role: Literal["user", "assistant"]
    content: str


@dataclass
class ImageHistoryEntry:
    """A cached generated scene image for one narrator turn and style."""

    id: str
    turn_index: int
    style_id: str
    style_name: str
    path: str
    prompt: str
    created_at: str = field(default_factory=_now_local_iso)


@dataclass
class GameState:
    """Complete game state."""

    starting_location: Location
    current_location: Location | None = None  # None means same as starting_location
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=_now_local_iso)
    updated_at: str = field(default_factory=_now_local_iso)
    # In-game time (starts at current real time)
    game_time: str = field(default_factory=_now_local_iso)
    version: int = 4  # Bumped for visual_continuity
    # Name for auto-saves (derived from location on first save)
    save_name: str | None = None
    # Compact visual bible for scene image consistency across turns.
    visual_continuity: str | None = None
    # Cached generated scene images for this run, in creation order.
    image_history: list[ImageHistoryEntry] = field(default_factory=list)

    def get_current_location(self) -> Location:
        """Get the player's current location (falls back to starting if not set)."""
        return self.current_location if self.current_location else self.starting_location

    def set_current_location(self, location: Location) -> None:
        """Update the player's current location."""
        self.current_location = location
        self.updated_at = _now_local_iso()

    def get_game_datetime(self) -> datetime:
        """Get the current in-game datetime."""
        return datetime.fromisoformat(self.game_time)

    def set_game_time(self, dt: datetime) -> None:
        """Set the in-game time."""
        self.game_time = dt.isoformat()

    def advance_time_minutes(self, minutes: int) -> None:
        """Advance the in-game time by the specified number of minutes."""
        current = self.get_game_datetime()
        new_time = current + timedelta(minutes=minutes)
        self.game_time = new_time.isoformat()

    def get_formatted_game_time(self) -> str:
        """Get a human-readable formatted game time."""
        dt = self.get_game_datetime()
        return dt.strftime("%A, %B %d, %Y at %I:%M %p")

    def add_message(self, role: Literal["user", "assistant"], content: str) -> None:
        """Add a message to the conversation history."""
        self.messages.append(Message(role=role, content=content))
        self.updated_at = _now_local_iso()

    def get_last_assistant_message(self) -> str | None:
        """Get the content of the most recent assistant message, or None if none exists."""
        for msg in reversed(self.messages):
            if msg.role == "assistant":
                return msg.content
        return None

    def pop_last_exchange(self) -> str | None:
        """
        Remove the most recent user/assistant exchange and return the user input.

        Used by ``/regenerate`` to re-roll the last response and by error
        handlers that need to roll back a partially-completed turn.

        Returns:
            The text of the popped user message, or ``None`` if there is no
            user message to pop.
        """
        # Drop a trailing assistant message if present.
        changed = False
        if self.messages and self.messages[-1].role == "assistant":
            self.messages.pop()
            changed = True
        # Then drop a trailing user message and return its content.
        if self.messages and self.messages[-1].role == "user":
            user_msg = self.messages.pop()
            self.visual_continuity = None
            self.image_history = [
                img for img in self.image_history if img.turn_index < len(self.messages)
            ]
            self.updated_at = _now_local_iso()
            return user_msg.content
        if changed:
            self.visual_continuity = None
            self.image_history = [
                img for img in self.image_history if img.turn_index < len(self.messages)
            ]
            self.updated_at = _now_local_iso()
        return None

    def get_messages_for_api(
        self,
        token_counter: Callable[[list[dict[str, object]]], int] | None = None,
        max_tokens: int = 180000,
        summarizer: Callable[[list[dict[str, object]]], str] | None = None,
    ) -> list[dict[str, object]]:
        """
        Get messages in the format expected by the Anthropic API.

        Trims old messages if the conversation exceeds max_tokens.
        Keeps the first 2 messages (game start) and recent messages.
        If trimming occurs and a summarizer is provided, includes a summary
        of the trimmed messages.

        Args:
            token_counter: Function to count tokens. If None, uses character estimate.
            max_tokens: Max tokens to keep (default 180k for Opus).
            summarizer: Optional function to summarize trimmed messages.

        Returns:
            List of message dicts for the API.
        """
        all_messages: list[dict[str, object]] = [
            {"role": m.role, "content": m.content} for m in self.messages
        ]

        # Use provided counter or fall back to character-based estimate
        # (~4 chars per token is a rough approximation for English text)
        def count_tokens(msgs: list[dict[str, object]]) -> int:
            if token_counter:
                return token_counter(msgs)
            return sum(len(str(m.get("content", ""))) for m in msgs) // TOKEN_CHAR_ESTIMATE_DIVISOR

        # If everything fits, return as-is
        if count_tokens(all_messages) <= max_tokens:
            return all_messages

        # Need at least 4 messages (2 intro + 1 pair) for trimming to make sense
        if len(all_messages) <= 4:
            return all_messages

        # Strategy: keep the first 2 messages (game intro / opening narrative)
        # and the most recent messages. Remove pairs from the middle, oldest first.
        # If a summarizer is provided, summarize the removed messages and insert
        # the summary after the intro to preserve context.
        first_messages = all_messages[:2]
        remaining = all_messages[2:]
        trimmed: list[dict[str, object]] = []

        # Reserve space for the summary message if we'll be generating one
        target_tokens = max_tokens - SUMMARIZATION_BUFFER_TOKENS if summarizer else max_tokens

        # Remove oldest user+assistant pairs from the front of 'remaining'
        # until the combined size (intro + remaining) fits within the limit
        while remaining and count_tokens(first_messages + remaining) > target_tokens:
            if len(remaining) >= 2:
                trimmed.extend(remaining[:2])
                remaining = remaining[2:]
            else:
                trimmed.extend(remaining[:1])
                remaining = remaining[1:]

        # Insert a summary of the trimmed messages so the LLM retains
        # key context (items found, people met, locations visited)
        if trimmed and summarizer:
            logger.debug("Trimmed %d messages, generating summary", len(trimmed))
            summary = summarizer(trimmed)
            summary_msg: dict[str, object] = {
                "role": "user",
                "content": f"[Earlier in this adventure: {summary}]",
            }
            return first_messages + [summary_msg] + remaining

        return first_messages + remaining

    def to_dict(self) -> dict[str, object]:
        """Convert state to a dictionary for JSON serialization."""
        result: dict[str, object] = {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "game_time": self.game_time,
            "starting_location": asdict(self.starting_location),
            "messages": [asdict(m) for m in self.messages],
        }
        if self.current_location is not None:
            result["current_location"] = asdict(self.current_location)
        if self.save_name is not None:
            result["save_name"] = self.save_name
        if self.visual_continuity:
            result["visual_continuity"] = self.visual_continuity
        if self.image_history:
            result["image_history"] = [asdict(img) for img in self.image_history]
        return result

    @classmethod
    def _parse_float(cls, value: object) -> float | None:
        """Parse a value to float, returning None on failure."""
        if value is None:
            return None
        try:
            return float(str(value))
        except ValueError:
            return None

    @classmethod
    def _parse_location(cls, loc_data: dict[str, object]) -> Location:
        """Parse a location dictionary into a Location object."""
        address_val = loc_data.get("address")
        return Location(
            city=str(loc_data.get("city") or ""),
            region=str(loc_data.get("region") or ""),
            country=str(loc_data.get("country") or ""),
            address=str(address_val) if address_val is not None else None,
            latitude=cls._parse_float(loc_data.get("latitude")),
            longitude=cls._parse_float(loc_data.get("longitude")),
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "GameState":
        """Create a GameState from a dictionary."""
        location_data = data["starting_location"]
        if not isinstance(location_data, dict):
            raise ValueError("Invalid location data")

        # Cast to proper type for _parse_location
        starting_loc_dict: dict[str, object] = {str(k): v for k, v in location_data.items()}
        starting_location = cls._parse_location(starting_loc_dict)

        # Parse current_location if present (migration: old saves won't have it)
        current_location: Location | None = None
        current_loc_data = data.get("current_location")
        if current_loc_data is not None and isinstance(current_loc_data, dict):
            current_loc_dict: dict[str, object] = {str(k): v for k, v in current_loc_data.items()}
            current_location = cls._parse_location(current_loc_dict)

        messages_data = data.get("messages", [])
        if not isinstance(messages_data, list):
            raise ValueError("Invalid messages data")

        messages: list[Message] = []
        for item in messages_data:
            if not isinstance(item, dict):
                continue
            msg = cast(dict[str, object], item)
            role = msg.get("role")
            content = msg.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append(Message(role=role, content=content))

        # Handle game_time, defaulting to now if not present (for old saves)
        game_time = data.get("game_time")
        if game_time is None:
            game_time = _now_local_iso()

        # Parse save_name if present (migration: old saves won't have it)
        save_name_data = data.get("save_name")
        save_name = str(save_name_data) if save_name_data is not None else None

        # Parse visual_continuity if present (migration: old saves won't have it)
        visual_data = data.get("visual_continuity")
        visual_continuity = str(visual_data) if visual_data else None

        image_history_data = data.get("image_history", [])
        image_history: list[ImageHistoryEntry] = []
        if isinstance(image_history_data, list):
            for item in image_history_data:
                if not isinstance(item, dict):
                    continue
                entry = cast(dict[str, object], item)
                try:
                    image_history.append(
                        ImageHistoryEntry(
                            id=str(entry.get("id") or ""),
                            turn_index=int(str(entry.get("turn_index") or 0)),
                            style_id=str(entry.get("style_id") or "photo"),
                            style_name=str(entry.get("style_name") or "Photo"),
                            path=str(entry.get("path") or ""),
                            prompt=str(entry.get("prompt") or ""),
                            created_at=str(entry.get("created_at") or _now_local_iso()),
                        )
                    )
                except ValueError:
                    continue

        return cls(
            starting_location=starting_location,
            current_location=current_location,
            messages=messages,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            game_time=str(game_time),
            version=4,  # Upgrade to current version
            save_name=save_name,
            visual_continuity=visual_continuity,
            image_history=image_history,
        )


def get_saves_dir() -> Path:
    """Get the saves directory, creating it if necessary."""
    saves_dir = DATA_DIR / "saves"
    saves_dir.mkdir(parents=True, exist_ok=True)
    return saves_dir


def _generate_save_name(state: GameState) -> str:
    """Generate a save name from the starting location."""
    location = state.starting_location
    # Use city name, lowercased, with timestamp for uniqueness
    city = location.city.lower().replace(" ", "-")
    # Sanitize
    city = "".join(c for c in city if c.isalnum() or c == "-")
    timestamp = _now_local().strftime("%m%d")
    return f"{city}-{timestamp}"


def save_game(state: GameState, name: str | None = None) -> Path:
    """
    Save the game state to a JSON file.

    Args:
        state: The game state to save.
        name: Optional explicit save name. If not provided, uses auto-save name.

    Returns:
        Path to the saved file.
    """
    saves_dir = get_saves_dir()

    if name is not None:
        # Explicit save - use provided name
        save_name = name
    else:
        # Auto-save - use or generate save_name
        if state.save_name is None:
            state.save_name = _generate_save_name(state)
        save_name = state.save_name

    # Sanitize filename
    safe_name = "".join(c for c in save_name if c.isalnum() or c in "._-")
    filepath = saves_dir / f"{safe_name}.json"

    state.updated_at = _now_local_iso()

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)

    logger.debug("Game saved to %s (%d messages)", filepath.name, len(state.messages))
    return filepath


def load_game(filepath: Path) -> GameState:
    """
    Load a game state from a JSON file.

    Args:
        filepath: Path to the save file.

    Returns:
        The loaded game state.
    """
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    state = GameState.from_dict(data)

    # If no save_name in file, derive from filename (for migration)
    if state.save_name is None:
        state.save_name = filepath.stem

    logger.debug("Game loaded from %s (%d messages)", filepath.name, len(state.messages))
    return state


def list_saves() -> list[tuple[Path, str, str]]:
    """
    List all available save files, sorted by updated_at (most recent first).

    Returns:
        List of tuples: (filepath, name, updated_at)
    """
    saves_dir = get_saves_dir()
    saves: list[tuple[Path, str, str]] = []

    for filepath in saves_dir.glob("*.json"):
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            updated_at = data.get("updated_at", "")
            saves.append((filepath, filepath.stem, updated_at))
        except (json.JSONDecodeError, OSError):
            # Skip corrupted save files
            continue

    # Sort by updated_at timestamp (most recent first)
    saves.sort(key=lambda x: x[2], reverse=True)

    return saves


def find_save_by_name(name: str) -> Path | None:
    """
    Find a save file by its name (with or without ``.json`` suffix).

    Always returns the path with the on-disk filename casing (matters on
    case-insensitive filesystems like macOS APFS). Performs an exact match
    first, then a case-insensitive fallback. Returns ``None`` if no save
    matches.
    """
    saves_dir = get_saves_dir()
    stem = name[:-5] if name.endswith(".json") else name

    # Iterate the directory once and pick the best match. We do this rather
    # than a direct ``Path.exists()`` check because case-insensitive
    # filesystems would happily report ``GAMMA-3.json`` as existing when the
    # real file on disk is ``gamma-3.json``, leaving callers with a path that
    # looks wrong in error messages and breaks string comparisons.
    fallback: Path | None = None
    target_lower = stem.lower()
    for filepath in saves_dir.glob("*.json"):
        if filepath.stem == stem:
            return filepath
        if fallback is None and filepath.stem.lower() == target_lower:
            fallback = filepath
    return fallback


def delete_save(filepath: Path) -> None:
    """Delete a save file. Raises ``OSError`` on failure."""
    filepath.unlink()
