"""Game state management with save/load functionality."""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from rwta.location import Location


@dataclass
class Message:
    """A single message in the conversation history."""

    role: Literal["user", "assistant"]
    content: str


@dataclass
class GameState:
    """Complete game state."""

    starting_location: Location
    current_location: Location | None = None  # None means same as starting_location
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # In-game time (starts at current real time)
    game_time: str = field(default_factory=lambda: datetime.now().isoformat())
    version: int = 3  # Bumped for save_name
    # Name for auto-saves (derived from location on first save)
    save_name: str | None = None

    def get_current_location(self) -> Location:
        """Get the player's current location (falls back to starting if not set)."""
        return self.current_location if self.current_location else self.starting_location

    def set_current_location(self, location: Location) -> None:
        """Update the player's current location."""
        self.current_location = location
        self.updated_at = datetime.now().isoformat()

    def get_game_datetime(self) -> datetime:
        """Get the current in-game datetime."""
        return datetime.fromisoformat(self.game_time)

    def set_game_time(self, dt: datetime) -> None:
        """Set the in-game time."""
        self.game_time = dt.isoformat()

    def advance_time_minutes(self, minutes: int) -> None:
        """Advance the in-game time by the specified number of minutes."""
        from datetime import timedelta

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
        self.updated_at = datetime.now().isoformat()

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

        # Use provided counter or fall back to estimate (~4 chars per token)
        def count_tokens(msgs: list[dict[str, object]]) -> int:
            if token_counter:
                return token_counter(msgs)
            return sum(len(str(m.get("content", ""))) for m in msgs) // 4

        if count_tokens(all_messages) <= max_tokens:
            return all_messages

        # Keep first 2 messages (game intro) and trim from middle
        if len(all_messages) <= 4:
            return all_messages

        first_messages = all_messages[:2]
        remaining = all_messages[2:]
        trimmed: list[dict[str, object]] = []

        # Remove old messages until we're under the limit
        # Account for space needed by summary message (~200 tokens buffer)
        target_tokens = max_tokens - 1000 if summarizer else max_tokens
        while remaining and count_tokens(first_messages + remaining) > target_tokens:
            # Remove oldest pair (user + assistant) from remaining
            if len(remaining) >= 2:
                trimmed.extend(remaining[:2])
                remaining = remaining[2:]
            else:
                trimmed.extend(remaining[:1])
                remaining = remaining[1:]

        # Generate summary of trimmed messages if summarizer provided
        if trimmed and summarizer:
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
            if isinstance(item, dict):
                msg = cast(dict[str, object], item)
                role = msg.get("role")
                content = msg.get("content")
                if role == "user" and isinstance(content, str):
                    messages.append(Message(role="user", content=content))
                elif role == "assistant" and isinstance(content, str):
                    messages.append(Message(role="assistant", content=content))

        # Handle game_time, defaulting to now if not present (for old saves)
        game_time = data.get("game_time")
        if game_time is None:
            game_time = datetime.now().isoformat()

        # Parse save_name if present (migration: old saves won't have it)
        save_name_data = data.get("save_name")
        save_name = str(save_name_data) if save_name_data is not None else None

        return cls(
            starting_location=starting_location,
            current_location=current_location,
            messages=messages,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            game_time=str(game_time),
            version=3,  # Upgrade to current version
            save_name=save_name,
        )


def get_saves_dir() -> Path:
    """Get the saves directory, creating it if necessary."""
    saves_dir = Path(__file__).parent.parent.parent / "saves"
    saves_dir.mkdir(exist_ok=True)
    return saves_dir


def _generate_save_name(state: GameState) -> str:
    """Generate a save name from the starting location."""
    location = state.starting_location
    # Use city name, lowercased, with timestamp for uniqueness
    city = location.city.lower().replace(" ", "-")
    # Sanitize
    city = "".join(c for c in city if c.isalnum() or c == "-")
    timestamp = datetime.now().strftime("%m%d")
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

    state.updated_at = datetime.now().isoformat()

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)

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
