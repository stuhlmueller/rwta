"""Game state management with save/load functionality."""

import contextlib
import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from rwta.location import Location

# Thread status values
ThreadStatus = Literal["active", "in_scene", "paused", "resolved"]


@dataclass
class Message:
    """A single message in the conversation history."""

    role: Literal["user", "assistant"]
    content: str


@dataclass
class Thread:
    """A parallel thread - side character, machine, or mechanism operating independently."""

    id: str  # UUID
    name: str  # e.g., "Detective hired to follow John"
    description: str  # Initial goal/purpose
    location: Location | None  # Current location (if physical)
    summary: str  # Short summary for selector (~100 words)
    history: list[str]  # List of event summaries (not full messages)
    created_at: int  # Game-time minutes since game start
    last_advanced_at: int  # Game-time minutes since game start (for staleness calc)
    last_selected_round: int  # Selection round marker for archiving
    revision: int  # Increment on any thread edits (conflict detection)
    status: ThreadStatus = "active"  # Lifecycle status: active, in_scene, paused, resolved

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        game_time_minutes: int,
        selection_round: int,
        location: Location | None = None,
        status: ThreadStatus = "active",
    ) -> "Thread":
        """Create a new thread with default values."""
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            location=location,
            summary=description,  # Initial summary is the description
            history=[],
            created_at=game_time_minutes,
            last_advanced_at=game_time_minutes,
            last_selected_round=selection_round,
            revision=0,
            status=status,
        )

    def to_dict(self) -> dict[str, object]:
        """Convert thread to a dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "location": asdict(self.location) if self.location else None,
            "summary": self.summary,
            "history": self.history,
            "created_at": self.created_at,
            "last_advanced_at": self.last_advanced_at,
            "last_selected_round": self.last_selected_round,
            "revision": self.revision,
            "status": self.status,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, object], parse_location: Callable[[dict[str, object]], Location]
    ) -> "Thread":
        """Create a Thread from a dictionary."""
        location: Location | None = None
        loc_data = data.get("location")
        if loc_data is not None and isinstance(loc_data, dict):
            location = parse_location(cast("dict[str, object]", loc_data))

        history_data = data.get("history", [])
        history: list[str] = []
        if isinstance(history_data, list):
            history = [str(h) for h in history_data]

        def safe_int(val: object, default: int = 0) -> int:
            if val is None:
                return default
            try:
                return int(str(val))
            except ValueError:
                return default

        # Parse status with validation and default
        raw_status = data.get("status", "active")
        status: ThreadStatus = "active"
        if raw_status in ("active", "in_scene", "paused", "resolved"):
            status = raw_status  # type: ignore[assignment]

        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            location=location,
            summary=str(data.get("summary", "")),
            history=history,
            created_at=safe_int(data.get("created_at"), 0),
            last_advanced_at=safe_int(data.get("last_advanced_at"), 0),
            last_selected_round=safe_int(data.get("last_selected_round"), 0),
            revision=safe_int(data.get("revision"), 0),
            status=status,
        )


@dataclass
class ThreadResult:
    """Result from simulating a thread - used for pending results in GameState."""

    thread_id: str
    thread_name: str
    base_revision: int  # Thread revision from snapshot
    events: str  # Detailed narrative of what happened (for narrator context)
    new_summary: str  # Updated summary (~100 words, replaces thread.summary)
    new_history_entry: str  # One-sentence summary to append to thread.history
    new_location: Location | None  # If thread moved (None = no change)
    simulated_from: int  # Snapshot game-time minutes
    advanced_to: int  # Game-time minutes after simulation

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
            "base_revision": self.base_revision,
            "events": self.events,
            "new_summary": self.new_summary,
            "new_history_entry": self.new_history_entry,
            "new_location": asdict(self.new_location) if self.new_location else None,
            "simulated_from": self.simulated_from,
            "advanced_to": self.advanced_to,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, object], parse_location: Callable[[dict[str, object]], Location]
    ) -> "ThreadResult":
        """Create a ThreadResult from a dictionary."""
        new_location: Location | None = None
        loc_data = data.get("new_location")
        if loc_data is not None and isinstance(loc_data, dict):
            new_location = parse_location(cast("dict[str, object]", loc_data))

        def safe_int(val: object, default: int = 0) -> int:
            if val is None:
                return default
            try:
                return int(str(val))
            except ValueError:
                return default

        return cls(
            thread_id=str(data.get("thread_id", "")),
            thread_name=str(data.get("thread_name", "")),
            base_revision=safe_int(data.get("base_revision"), 0),
            events=str(data.get("events", "")),
            new_summary=str(data.get("new_summary", "")),
            new_history_entry=str(data.get("new_history_entry", "")),
            new_location=new_location,
            simulated_from=safe_int(data.get("simulated_from"), 0),
            advanced_to=safe_int(data.get("advanced_to"), 0),
        )


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
    # Thread-related fields
    threads: list[Thread] = field(default_factory=list)
    archived_threads: list[Thread] = field(default_factory=list)
    pending_thread_results: list[ThreadResult] | None = None
    thread_selection_round: int = 0
    version: int = 3  # Bumped for threads migration

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

    def get_game_time_minutes(self) -> int:
        """Get minutes elapsed since game start (for thread time math)."""
        start = datetime.fromisoformat(self.created_at)
        current = datetime.fromisoformat(self.game_time)
        return int((current - start).total_seconds() // 60)

    def minutes_to_game_time(self, minutes: int) -> datetime:
        """Convert minutes-since-start to datetime."""
        start = datetime.fromisoformat(self.created_at)
        return start + timedelta(minutes=minutes)

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
            return [*first_messages, summary_msg, *remaining]

        return [*first_messages, *remaining]

    def to_dict(self) -> dict[str, object]:
        """Convert state to a dictionary for JSON serialization."""
        result: dict[str, object] = {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "game_time": self.game_time,
            "starting_location": asdict(self.starting_location),
            "messages": [asdict(m) for m in self.messages],
            # Thread-related fields
            "threads": [t.to_dict() for t in self.threads],
            "archived_threads": [t.to_dict() for t in self.archived_threads],
            "pending_thread_results": (
                [r.to_dict() for r in self.pending_thread_results]
                if self.pending_thread_results is not None
                else None
            ),
            "thread_selection_round": self.thread_selection_round,
        }
        if self.current_location is not None:
            result["current_location"] = asdict(self.current_location)
        return result

    @classmethod
    def _parse_location(cls, loc_data: dict[str, object]) -> Location:
        """Parse a location dictionary into a Location object."""
        address_val = loc_data.get("address")
        address = str(address_val) if address_val is not None else None

        latitude: float | None = None
        lat_val = loc_data.get("latitude")
        if lat_val is not None:
            with contextlib.suppress(ValueError):
                latitude = float(str(lat_val))

        longitude: float | None = None
        lon_val = loc_data.get("longitude")
        if lon_val is not None:
            with contextlib.suppress(ValueError):
                longitude = float(str(lon_val))

        return Location(
            city=str(loc_data.get("city") or ""),
            region=str(loc_data.get("region") or ""),
            country=str(loc_data.get("country") or ""),
            address=address,
            latitude=latitude,
            longitude=longitude,
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "GameState":
        """Create a GameState from a dictionary."""

        def safe_int(val: object, default: int = 0) -> int:
            if val is None:
                return default
            try:
                return int(str(val))
            except ValueError:
                return default

        # Handle version migration
        version = safe_int(data.get("version"), 1)
        if version < 3:
            data = cls._migrate_to_v3(data)

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
                msg = cast("dict[str, object]", item)
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

        # Parse threads
        threads: list[Thread] = []
        threads_data = data.get("threads", [])
        if isinstance(threads_data, list):
            for t_data in threads_data:
                if isinstance(t_data, dict):
                    threads.append(
                        Thread.from_dict(cast("dict[str, object]", t_data), cls._parse_location)
                    )

        # Parse archived_threads
        archived_threads: list[Thread] = []
        archived_data = data.get("archived_threads", [])
        if isinstance(archived_data, list):
            for t_data in archived_data:
                if isinstance(t_data, dict):
                    archived_threads.append(
                        Thread.from_dict(cast("dict[str, object]", t_data), cls._parse_location)
                    )

        # Parse pending_thread_results
        pending_thread_results: list[ThreadResult] | None = None
        pending_data = data.get("pending_thread_results")
        if pending_data is not None and isinstance(pending_data, list):
            pending_thread_results = []
            for r_data in pending_data:
                if isinstance(r_data, dict):
                    pending_thread_results.append(
                        ThreadResult.from_dict(
                            cast("dict[str, object]", r_data), cls._parse_location
                        )
                    )

        return cls(
            starting_location=starting_location,
            current_location=current_location,
            messages=messages,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            game_time=str(game_time),
            threads=threads,
            archived_threads=archived_threads,
            pending_thread_results=pending_thread_results,
            thread_selection_round=safe_int(data.get("thread_selection_round"), 0),
            version=3,  # Upgrade to current version
        )

    @classmethod
    def _migrate_to_v3(cls, data: dict[str, object]) -> dict[str, object]:
        """Migrate save data from v1/v2 to v3 (add thread fields)."""
        data["threads"] = []
        data["archived_threads"] = []
        data["pending_thread_results"] = None
        data["thread_selection_round"] = 0
        data["version"] = 3
        return data


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

    return GameState.from_dict(data)


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
