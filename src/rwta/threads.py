"""Thread management for parallel storylines."""

import json
import logging
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from anthropic import Anthropic, APIError

from rwta.location import Location
from rwta.state import GameState, Thread, ThreadResult

logger = logging.getLogger(__name__)

# Model to use for thread operations (cheaper/faster than Opus)
THREAD_MODEL = "claude-sonnet-4-20250514"


@dataclass
class WorldContext:
    """Context about the world state for thread simulation."""

    player_location: Location
    game_time_minutes: int  # Current game time (minutes since start, derived)
    game_time_display: str  # Human-readable time for prompts
    weather: str | None  # Current weather description (optional)


@dataclass
class SelectionResult:
    """Result from thread selection (no state mutation)."""

    selected_ids: list[str]  # IDs of threads to advance
    new_selection_round: int  # current_round + 1 on success, current_round on failure


@dataclass
class SimulationOutput:
    """Complete output from background thread simulation."""

    results: list[ThreadResult]  # Results for each simulated thread
    selection_result: SelectionResult  # Selection metadata to apply


class ThreadSelector:
    """Selects which threads to advance based on relevance."""

    def __init__(self, client: Anthropic):
        self.client = client

    def select_threads(
        self,
        threads: list[Thread],
        world_context: WorldContext,
        current_round: int,
        n: int = 3,
    ) -> SelectionResult:
        """Select the top N most relevant threads to advance.

        Args:
            threads: All active threads
            world_context: Current world state
            current_round: Current selection round number
            n: Number of threads to select

        Returns:
            SelectionResult with selected IDs and new round number
        """
        # Filter to only "active" threads - others are paused, in_scene, or resolved
        eligible_threads = [t for t in threads if t.status == "active"]

        if not eligible_threads:
            return SelectionResult(selected_ids=[], new_selection_round=current_round)

        # If fewer eligible threads than n, select all eligible
        if len(eligible_threads) <= n:
            return SelectionResult(
                selected_ids=[t.id for t in eligible_threads],
                new_selection_round=current_round + 1,
            )

        # Build thread summaries for selector
        thread_descriptions = []
        for t in eligible_threads:
            staleness = world_context.game_time_minutes - t.last_advanced_at
            staleness_label = "HIGH" if staleness > 60 else "MEDIUM" if staleness > 30 else "LOW"

            location_str = "Unknown"
            if t.location:
                location_str = t.location.city or t.location.address or "Unknown"

            thread_descriptions.append(
                f"Thread ID: {t.id}\n"
                f"Name: {t.name}\n"
                f"Location: {location_str}\n"
                f"Last advanced: {staleness} minutes ago\n"
                f"Summary: {t.summary}\n"
                f"Staleness: {staleness_label}"
            )

        threads_text = "\n\n".join(thread_descriptions)

        player_loc = world_context.player_location
        player_location_str = player_loc.city or player_loc.address or "Unknown"

        prompt = f"""You are selecting which background threads to advance in a real-world text adventure game.

Current game time: {world_context.game_time_display}
Player location: {player_location_str}

Here are the active threads:

{threads_text}

Select the {n} most important threads to advance. Consider:
1. Staleness - threads that haven't been advanced recently should be prioritized
2. Location proximity - threads near the player may be more relevant
3. Activity level - threads with active ongoing events vs those waiting
4. Story relevance - threads that might intersect with the player soon

Return ONLY a JSON array of thread IDs, nothing else. Example: ["id1", "id2", "id3"]"""

        try:
            response = self.client.messages.create(
                model=THREAD_MODEL,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse response
            content = response.content[0]
            if content.type != "text":
                logger.error("Selector returned non-text response")
                return SelectionResult(selected_ids=[], new_selection_round=current_round)

            # Extract JSON array from response
            text = content.text.strip()
            # Handle potential markdown code blocks
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

            selected_ids = json.loads(text)
            if not isinstance(selected_ids, list):
                logger.error("Selector returned non-list: %s", selected_ids)
                return SelectionResult(selected_ids=[], new_selection_round=current_round)

            # Validate IDs exist in eligible threads
            valid_ids = {t.id for t in eligible_threads}
            selected_ids = [id for id in selected_ids if id in valid_ids][:n]

            # Only advance selection round if at least one valid thread was selected
            new_round = current_round + 1 if selected_ids else current_round
            return SelectionResult(
                selected_ids=selected_ids,
                new_selection_round=new_round,
            )

        except json.JSONDecodeError as e:
            logger.error("Failed to parse selector response: %s", e)
            return SelectionResult(selected_ids=[], new_selection_round=current_round)


class ThreadSimulator:
    """Simulates a single thread's progression."""

    def __init__(self, client: Anthropic):
        self.client = client

    def simulate_thread(
        self,
        thread: Thread,
        time_delta: int,
        world_context: WorldContext,
    ) -> ThreadResult:
        """Simulate what happens to a thread over a time period.

        Args:
            thread: The thread to simulate
            time_delta: Time elapsed in minutes
            world_context: Current world state

        Returns:
            ThreadResult with simulation results
        """
        location_str = "Unknown location"
        if thread.location:
            location_str = thread.location.address or thread.location.city or "Unknown"

        history_text = ""
        if thread.history:
            history_text = "\n".join(f"- {h}" for h in thread.history[-5:])  # Last 5 entries
            history_text = f"\n\nRecent history:\n{history_text}"

        player_loc = world_context.player_location
        player_location_str = player_loc.city or player_loc.address or "Unknown"

        prompt = f"""You are simulating a background thread in a real-world text adventure game.

Thread: {thread.name}
Description: {thread.description}
Current location: {location_str}
Current summary: {thread.summary}{history_text}

Time passing: {time_delta} minutes
Current game time: {world_context.game_time_display}
Player is currently at: {player_location_str}

Simulate what happens to this thread over the {time_delta} minutes. Consider:
- What realistic actions or events would occur?
- Does the thread move to a new location?
- Any significant developments?

Respond with a JSON object containing:
{{
    "events": "Detailed narrative of what happened (2-3 sentences)",
    "new_summary": "Updated summary of thread's current state (~50-100 words)",
    "new_history_entry": "One sentence summary for history log",
    "new_location": null or {{"city": "...", "region": "...", "country": "...", "address": "..."}} if moved
}}

Return ONLY the JSON object, nothing else."""

        try:
            response = self.client.messages.create(
                model=THREAD_MODEL,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0]
            if content.type != "text":
                return self._error_result(thread, world_context, "Non-text response")

            text = content.text.strip()
            # Handle potential markdown code blocks
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

            data = json.loads(text)

            # Parse new_location if present
            new_location: Location | None = None
            loc_data = data.get("new_location")
            if loc_data and isinstance(loc_data, dict):
                new_location = Location(
                    city=str(loc_data.get("city", "")),
                    region=str(loc_data.get("region", "")),
                    country=str(loc_data.get("country", "")),
                    address=loc_data.get("address"),
                )

            return ThreadResult(
                thread_id=thread.id,
                thread_name=thread.name,
                base_revision=thread.revision,
                events=str(data.get("events", "")),
                new_summary=str(data.get("new_summary", thread.summary)),
                new_history_entry=str(data.get("new_history_entry", "")),
                new_location=new_location,
                simulated_from=thread.last_advanced_at,
                advanced_to=world_context.game_time_minutes,
            )

        except json.JSONDecodeError as e:
            logger.error("Failed to parse simulator response for thread %s: %s", thread.id, e)
            return self._error_result(thread, world_context, f"Parse error: {e}")

    def _error_result(
        self, thread: Thread, world_context: WorldContext, error: str
    ) -> ThreadResult:
        """Create an error result that makes minimal changes."""
        return ThreadResult(
            thread_id=thread.id,
            thread_name=thread.name,
            base_revision=thread.revision,
            events=f"[Simulation error: {error}]",
            new_summary=thread.summary,  # Keep existing
            new_history_entry="[Time passed uneventfully]",
            new_location=None,  # Don't change location
            simulated_from=thread.last_advanced_at,
            advanced_to=world_context.game_time_minutes,
        )


def run_thread_simulation(
    state: GameState,
    time_delta: int,
    world_context: WorldContext,
    client: Anthropic,
) -> SimulationOutput:
    """Run thread selection and simulation.

    Args:
        state: Current game state (used as snapshot, not modified)
        time_delta: Time elapsed in minutes
        world_context: Current world state
        client: Anthropic client

    Returns:
        SimulationOutput with results for all simulated threads
    """
    threads = state.threads
    current_round = state.thread_selection_round

    if not threads:
        return SimulationOutput(
            results=[],
            selection_result=SelectionResult(
                selected_ids=[],
                new_selection_round=current_round,
            ),
        )

    # Select threads
    selector = ThreadSelector(client)
    selection_result = selector.select_threads(
        threads=threads,
        world_context=world_context,
        current_round=current_round,
        n=3,
    )

    if not selection_result.selected_ids:
        return SimulationOutput(results=[], selection_result=selection_result)

    # Get selected thread objects
    thread_map = {t.id: t for t in threads}
    selected_threads = [thread_map[id] for id in selection_result.selected_ids if id in thread_map]

    # Simulate threads in parallel
    simulator = ThreadSimulator(client)
    results: list[ThreadResult] = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(simulator.simulate_thread, t, time_delta, world_context): t
            for t in selected_threads
        }

        for future in as_completed(futures):
            thread = futures[future]
            try:
                result = future.result()
                results.append(result)
            except (
                APIError,
                json.JSONDecodeError,
                CancelledError,
                TimeoutError,
                AttributeError,
            ) as e:
                logger.error("Thread simulation failed for %s: %s", thread.id, e)
                # Create error result
                results.append(
                    ThreadResult(
                        thread_id=thread.id,
                        thread_name=thread.name,
                        base_revision=thread.revision,
                        events=f"[Simulation error: {e}]",
                        new_summary=thread.summary,
                        new_history_entry="[Time passed uneventfully]",
                        new_location=None,
                        simulated_from=thread.last_advanced_at,
                        advanced_to=world_context.game_time_minutes,
                    )
                )

    return SimulationOutput(results=results, selection_result=selection_result)


def condense_thread_history(thread: Thread, client: Anthropic) -> None:
    """Condense old history entries if history exceeds 20 entries.

    Summarizes entries 0-9 into a single entry, keeping entries 10+ intact.
    Modifies thread in place.

    Args:
        thread: Thread to condense (modified in place)
        client: Anthropic client for summarization
    """
    if len(thread.history) <= 20:
        return

    old_entries = thread.history[:10]
    old_text = "\n".join(f"- {e}" for e in old_entries)

    prompt = f"""Summarize these history entries for a background thread named "{thread.name}" into 2-3 sentences:

{old_text}

Return ONLY the summary, nothing else."""

    try:
        response = client.messages.create(
            model=THREAD_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0]
        if content.type == "text":
            summary = content.text.strip()
            thread.history = [f"[Earlier: {summary}]", *thread.history[10:]]
    except (APIError, json.JSONDecodeError, IndexError, KeyError) as e:
        logger.error("Failed to condense history for thread %s: %s", thread.id, e)
        # On failure, just truncate without summarizing
        thread.history = ["[Earlier history truncated]", *thread.history[10:]]


def archive_dormant_threads(state: GameState) -> None:
    """Move dormant threads to archived list when count exceeds 50.

    Dormant = not selected in last 10 selection rounds.
    Modifies state in place.

    Args:
        state: Game state to modify
    """
    if len(state.threads) <= 50:
        return

    current_round = state.thread_selection_round
    dormant_threshold = 10

    # Identify dormant threads
    dormant: list[Thread] = []
    active: list[Thread] = []

    for t in state.threads:
        rounds_since_selected = current_round - t.last_selected_round
        if rounds_since_selected >= dormant_threshold:
            dormant.append(t)
        else:
            active.append(t)

    # Sort dormant by last_advanced_at (oldest first)
    dormant.sort(key=lambda t: t.last_advanced_at)

    # Archive enough to get under 50
    num_to_archive = len(state.threads) - 50
    to_archive = dormant[:num_to_archive]
    to_keep_dormant = dormant[num_to_archive:]

    state.archived_threads.extend(to_archive)
    state.threads = active + to_keep_dormant

    if to_archive:
        logger.info("Archived %d dormant threads", len(to_archive))
