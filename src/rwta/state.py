"""Game state management with save/load functionality."""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

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
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # In-game time (starts at current real time)
    game_time: str = field(default_factory=lambda: datetime.now().isoformat())
    version: int = 1

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
        token_counter: Callable[[list[dict[str, str]]], int] | None = None,
        max_tokens: int = 180000,
    ) -> list[dict[str, str]]:
        """
        Get messages in the format expected by the Anthropic API.

        Trims old messages if the conversation exceeds max_tokens.
        Keeps the first 2 messages (game start) and recent messages.

        Args:
            token_counter: Function to count tokens. If None, uses character estimate.
            max_tokens: Max tokens to keep (default 180k for Opus).

        Returns:
            List of message dicts for the API.
        """
        all_messages = [{"role": m.role, "content": m.content} for m in self.messages]

        # Use provided counter or fall back to estimate (~4 chars per token)
        def count_tokens(msgs: list[dict[str, str]]) -> int:
            if token_counter:
                return token_counter(msgs)
            return sum(len(m["content"]) for m in msgs) // 4

        if count_tokens(all_messages) <= max_tokens:
            return all_messages

        # Keep first 2 messages (game intro) and trim from middle
        if len(all_messages) <= 4:
            return all_messages

        first_messages = all_messages[:2]
        remaining = all_messages[2:]

        # Remove old messages until we're under the limit
        while remaining and count_tokens(first_messages + remaining) > max_tokens:
            # Remove oldest pair (user + assistant) from remaining
            if len(remaining) >= 2:
                remaining = remaining[2:]
            else:
                remaining = remaining[1:]

        return first_messages + remaining

    def to_dict(self) -> dict[str, object]:
        """Convert state to a dictionary for JSON serialization."""
        return {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "game_time": self.game_time,
            "starting_location": asdict(self.starting_location),
            "messages": [asdict(m) for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "GameState":
        """Create a GameState from a dictionary."""
        location_data = data["starting_location"]
        if not isinstance(location_data, dict):
            raise ValueError("Invalid location data")

        # Cast to the expected type
        loc = dict(location_data)

        # Extract address and coordinates, handling None
        address_val = loc.get("address")
        address = str(address_val) if address_val is not None else None

        lat_val = loc.get("latitude")
        latitude = float(lat_val) if lat_val is not None else None

        lon_val = loc.get("longitude")
        longitude = float(lon_val) if lon_val is not None else None

        location = Location(
            city=str(loc.get("city") or ""),
            region=str(loc.get("region") or ""),
            country=str(loc.get("country") or ""),
            address=address,
            latitude=latitude,
            longitude=longitude,
        )

        messages_data = data.get("messages", [])
        if not isinstance(messages_data, list):
            raise ValueError("Invalid messages data")

        messages = [
            Message(role=m["role"], content=m["content"])  # type: ignore[arg-type]
            for m in messages_data
            if isinstance(m, dict)
        ]

        # Handle game_time, defaulting to now if not present (for old saves)
        game_time = data.get("game_time")
        if game_time is None:
            game_time = datetime.now().isoformat()

        return cls(
            starting_location=location,
            messages=messages,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            game_time=str(game_time),
            version=int(data.get("version", 1)),  # type: ignore[arg-type]
        )


def get_saves_dir() -> Path:
    """Get the saves directory, creating it if necessary."""
    saves_dir = Path(__file__).parent.parent.parent / "saves"
    saves_dir.mkdir(exist_ok=True)
    return saves_dir


def save_game(state: GameState, name: str | None = None) -> Path:
    """
    Save the game state to a JSON file.

    Args:
        state: The game state to save.
        name: Optional save name. If not provided, uses timestamp.

    Returns:
        Path to the saved file.
    """
    saves_dir = get_saves_dir()

    if name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"save_{timestamp}"

    # Sanitize filename
    safe_name = "".join(c for c in name if c.isalnum() or c in "._-")
    filepath = saves_dir / f"{safe_name}.json"

    state.updated_at = datetime.now().isoformat()

    with open(filepath, "w") as f:
        json.dump(state.to_dict(), f, indent=2)

    return filepath


def load_game(filepath: Path) -> GameState:
    """
    Load a game state from a JSON file.

    Args:
        filepath: Path to the save file.

    Returns:
        The loaded game state.
    """
    with open(filepath) as f:
        data = json.load(f)

    return GameState.from_dict(data)


def list_saves() -> list[tuple[Path, str, str]]:
    """
    List all available save files.

    Returns:
        List of tuples: (filepath, name, updated_at)
    """
    saves_dir = get_saves_dir()
    saves: list[tuple[Path, str, str]] = []

    for filepath in sorted(saves_dir.glob("*.json"), reverse=True):
        try:
            with open(filepath) as f:
                data = json.load(f)
            updated_at = data.get("updated_at", "Unknown")
            saves.append((filepath, filepath.stem, updated_at))
        except (json.JSONDecodeError, OSError):
            # Skip corrupted save files
            continue

    return saves
