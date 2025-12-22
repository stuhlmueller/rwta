"""Main entry point and game loop for the text adventure."""

import atexit
import contextlib
import json
import logging
import queue
import re
import readline
import shutil
import sys
import textwrap
import threading
import time
from pathlib import Path

from anthropic import Anthropic, APIError

from rwta.llm import GameNarrator
from rwta.location import get_city_from_ip, prompt_for_address
from rwta.state import GameState, ThreadResult, list_saves, load_game, save_game
from rwta.threads import (
    SimulationOutput,
    WorldContext,
    archive_dormant_threads,
    condense_thread_history,
    run_thread_simulation,
)

logger = logging.getLogger(__name__)

# Set up readline history
HISTORY_FILE = Path(__file__).parent.parent.parent / ".history"

# Commands for tab completion
COMMANDS = ["/help", "/save", "/load", "/time", "/tokens", "/quit", "/look", "/where", "/threads"]

# Minimum time delta (minutes) before triggering thread simulation
THREAD_SIMULATION_MIN_DELTA = 30

# Module-level state for background thread simulation
_simulation_lock = threading.Lock()
_simulation_running = False
_simulation_queue: queue.Queue[SimulationOutput] = queue.Queue()
_queued_time_delta: int = 0

# Fast mode flag (no typewriter, sonnet narrator, no auto save/load)
_fast_mode = False


def reset_simulation_state() -> None:
    """Reset all background simulation state.

    Call this when loading a game or starting fresh to ensure
    results from prior simulations don't leak into the new state.
    """
    global _simulation_running, _queued_time_delta

    with _simulation_lock:
        _simulation_running = False
        _queued_time_delta = 0

    # Drain and discard any queued results
    while True:
        try:
            _simulation_queue.get_nowait()
        except queue.Empty:
            break


# ANSI color codes
class Colors:
    """ANSI escape codes for terminal colors."""

    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    ITALIC = "\033[3m"

    # Colors
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    WHITE = "\033[1;37m"
    GRAY = "\033[90m"

    # Semantic aliases
    SYSTEM = CYAN  # System messages (help, save, etc.)
    LOADING = DIM  # Loading messages
    TIME = YELLOW  # Time display
    SUCCESS = GREEN  # Success messages


class CommandCompleter:
    """Tab completion for game commands."""

    def __init__(self, commands: list[str]):
        self.commands = commands

    def complete(self, text: str, state: int) -> str | None:
        """Return the next possible completion for text."""
        if text.startswith("/"):
            matches = [c for c in self.commands if c.startswith(text)]
        else:
            matches = []

        if state < len(matches):
            return matches[state]
        return None


def setup_readline() -> None:
    """Configure readline for better input handling."""
    # Load history if it exists
    if HISTORY_FILE.exists():
        with contextlib.suppress(OSError):
            readline.read_history_file(str(HISTORY_FILE))

    # Set history length
    readline.set_history_length(1000)

    # Set up tab completion
    completer = CommandCompleter(COMMANDS)
    readline.set_completer(completer.complete)
    readline.parse_and_bind("tab: complete")

    # Save history on exit
    def _save_history() -> None:
        with contextlib.suppress(OSError):
            readline.write_history_file(str(HISTORY_FILE))

    atexit.register(_save_history)


def get_terminal_width() -> int:
    """Get terminal width, defaulting to 80 if unknown."""
    try:
        return shutil.get_terminal_size().columns
    except (ValueError, OSError):
        return 80


def wrap_text(text: str, width: int | None = None) -> str:
    """
    Wrap text to fit terminal width, preserving paragraph breaks and list items.

    Args:
        text: The text to wrap.
        width: Optional width override. Defaults to terminal width - 4.

    Returns:
        Wrapped text with preserved paragraph structure.
    """
    if width is None:
        width = min(get_terminal_width() - 4, 76)  # Cap at 76 for readability

    # Split into paragraphs (double newline)
    paragraphs = text.split("\n\n")
    wrapped_paragraphs = []

    for para in paragraphs:
        # Check if this paragraph contains list items (lines starting with - or * or numbers)
        lines = para.split("\n")
        is_list = any(
            line.strip().startswith(("-", "*", "•")) or re.match(r"^\d+[.)]\s", line.strip())
            for line in lines
        )

        if is_list:
            # Preserve line breaks for lists, but wrap each item
            wrapped_lines = []
            for line in lines:
                line = line.strip()
                if line:
                    wrapped_lines.append(textwrap.fill(line, width=width, subsequent_indent="  "))
            wrapped_paragraphs.append("\n".join(wrapped_lines))
        else:
            # Regular paragraph - join lines and wrap
            para = " ".join(para.split())
            if para:
                wrapped_paragraphs.append(textwrap.fill(para, width=width))

    return "\n\n".join(wrapped_paragraphs)


def render_markdown(text: str) -> str:
    """
    Convert basic markdown to ANSI escape codes.

    Supports **bold** and *italic*.
    """
    # Bold: **text** -> ANSI bold
    text = re.sub(r"\*\*([^*]+)\*\*", r"\033[1m\1\033[0m", text)

    # Italic: *text* -> ANSI italic (may not work in all terminals)
    text = re.sub(r"\*([^*]+)\*", r"\033[3m\1\033[0m", text)

    return text


def typewriter_print(text: str, delay: float = 0.05) -> None:
    """
    Print text with a typewriter effect, word by word.

    Args:
        text: The text to print.
        delay: Delay between words in seconds.
    """
    # Fast mode: print instantly
    if _fast_mode:
        print(text, end="")
        return

    lines = text.split("\n")
    num_lines = len(lines)

    for line_idx, line in enumerate(lines):
        words = line.split()
        for i, word in enumerate(words):
            print(word, end="", flush=True)
            if i < len(words) - 1:
                print(" ", end="", flush=True)
            time.sleep(delay)

        # Move to next line
        if line_idx < num_lines - 1:
            print()


def print_narrative(text: str) -> None:
    """
    Print narrative text with wrapping and typewriter effect.
    Pre-scrolls to reserve space so the screen doesn't move while typing.

    Args:
        text: The narrative text to print.
    """
    wrapped = wrap_text(text)
    wrapped = render_markdown(wrapped)

    # Fast mode: just print directly
    if _fast_mode:
        print(wrapped)
        return

    # Count exact lines needed (including blank lines between paragraphs)
    total_lines = wrapped.count("\n") + 2  # +1 for last line, +1 for final newline

    # Pre-scroll: print blank lines to reserve space
    print("\n" * total_lines, end="")

    # Move cursor back up
    print(f"\033[{total_lines}A", end="", flush=True)

    # Type out each paragraph
    paragraphs = wrapped.split("\n\n")
    for i, para in enumerate(paragraphs):
        typewriter_print(para)
        print()  # End the paragraph
        if i < len(paragraphs) - 1:
            print()  # Blank line between paragraphs
            time.sleep(0.15)


def print_help() -> None:
    """Print available commands."""
    c = Colors
    print(f"\n{c.SYSTEM}Commands:{c.RESET}")
    print(f"  {c.WHITE}/help{c.RESET}    - Show this help message")
    print(f"  {c.WHITE}/save{c.RESET}    - Save your game (optionally: /save <name>)")
    print(f"  {c.WHITE}/load{c.RESET}    - Load a saved game")
    print(f"  {c.WHITE}/time{c.RESET}    - Show current in-game time")
    print(f"  {c.WHITE}/where{c.RESET}   - Show current location and time")
    print(f"  {c.WHITE}/threads{c.RESET} - Show active background storylines")
    print(f"  {c.WHITE}/tokens{c.RESET}  - Show token usage and context limit")
    print(f"  {c.WHITE}/look{c.RESET}    - Look around (re-describe surroundings)")
    print(f"  {c.WHITE}/quit{c.RESET}    - Exit the game")


def handle_save(state: GameState, args: str, silent: bool = False) -> None:
    """Handle the /save command."""
    name = args.strip() if args.strip() else None
    filepath = save_game(state, name)
    if not silent:
        print(f"{Colors.SUCCESS}Game saved to: {filepath.name}{Colors.RESET}")


def handle_load() -> GameState | None:
    """Handle the /load command. Returns new state if loaded, None otherwise."""
    saves = list_saves()

    if not saves:
        print("No saved games found.")
        return None

    print("\nSaved games:")
    for i, (_filepath, name, updated_at) in enumerate(saves, 1):
        print(f"  {i}. {name} (saved: {updated_at[:19]})")

    print("\nEnter the number to load (or 'cancel'):")
    print("> ", end="", flush=True)

    try:
        choice = input().strip()
        if choice.lower() == "cancel":
            return None

        idx = int(choice) - 1
        if 0 <= idx < len(saves):
            filepath, name, _ = saves[idx]
            try:
                state = load_game(filepath)
            except (OSError, ValueError, KeyError) as e:
                print(f"Error loading save: {e}")
                return None
            else:
                print(f"Loaded: {name}")
                return state
        else:
            print("Invalid selection.")
            return None
    except ValueError:
        print("Invalid input.")
        return None


def handle_time(state: GameState) -> None:
    """Handle the /time command."""
    print(f"{Colors.TIME}Current in-game time: {state.get_formatted_game_time()}{Colors.RESET}")


def handle_where(state: GameState) -> None:
    """Handle the /where command."""
    location = state.get_current_location()
    print(f"{Colors.SYSTEM}Current location: {location}{Colors.RESET}")
    print(f"{Colors.TIME}Time: {state.get_formatted_game_time()}{Colors.RESET}")


def print_status_line(state: GameState) -> None:
    """Print a brief status line showing location and time."""
    location = state.get_current_location()
    # Use short location format and condensed time
    game_dt = state.get_game_datetime()
    time_str = game_dt.strftime("%a %I:%M %p")  # e.g., "Mon 09:15 PM"
    location_str = location.short_str() if hasattr(location, "short_str") else str(location)
    print(f"\n{Colors.DIM}{location_str} — {time_str}{Colors.RESET}")


def handle_tokens(narrator: "GameNarrator", state: GameState) -> None:
    """Handle the /tokens command."""
    max_tokens = 180000
    # Estimate current tokens using the narrator's token counter
    messages: list[dict[str, object]] = [
        {"role": m.role, "content": m.content} for m in state.messages
    ]
    system = ""  # Approximate - actual system prompt varies
    try:
        current_tokens = narrator.count_tokens(messages, system)
    except (ValueError, TypeError, RuntimeError):
        # Fallback to character estimate
        current_tokens = sum(len(m.content) for m in state.messages) // 4

    percentage = (current_tokens / max_tokens) * 100
    remaining = max_tokens - current_tokens

    print(f"\n{Colors.SYSTEM}Token Usage:{Colors.RESET}")
    print(f"  Current: {current_tokens:,} / {max_tokens:,} ({percentage:.1f}%)")
    print(f"  Remaining: {remaining:,}")
    if percentage > 80:
        print(
            f"  {Colors.TIME}Warning: Approaching limit, older messages will be summarized soon{Colors.RESET}"
        )


def count_conversation_words(state: GameState) -> int:
    """Count total words in the conversation history."""
    total = 0
    for msg in state.messages:
        total += len(msg.content.split())
    return total


def format_pending_thread_events(state: GameState) -> str | None:
    """Format pending thread results for narrator context.

    Returns None if no pending results, otherwise a formatted string.
    """
    if not state.pending_thread_results:
        return None

    events = []
    for result in state.pending_thread_results:
        events.append(f"- {result.thread_name}: {result.events}")

    return "\n".join(events)


def apply_thread_simulation_results(
    state: GameState,
    output: SimulationOutput,
    client: Anthropic,
) -> None:
    """Apply simulation results to state with conflict detection.

    Modifies state in place.
    """
    # Apply selection result
    state.thread_selection_round = output.selection_result.new_selection_round

    # Update last_selected_round for selected threads
    selected_ids = set(output.selection_result.selected_ids)
    for thread in state.threads:
        if thread.id in selected_ids:
            thread.last_selected_round = output.selection_result.new_selection_round

    # Apply thread results
    thread_map = {t.id: t for t in state.threads}
    applied_results: list[ThreadResult] = []

    for result in output.results:
        thread = thread_map.get(result.thread_id)
        if thread is None:
            # Thread was archived or deleted during simulation
            logger.debug("Skipping result for missing thread %s", result.thread_id)
            continue

        if thread.revision != result.base_revision:
            # Thread was edited during simulation
            logger.debug("Skipping result for thread %s: revision mismatch", result.thread_id)
            continue

        if thread.last_advanced_at > result.simulated_from:
            # Thread was already advanced
            logger.debug("Skipping result for thread %s: already advanced", result.thread_id)
            continue

        # Apply the result
        thread.summary = result.new_summary
        thread.history.append(result.new_history_entry)
        if result.new_location is not None:
            thread.location = result.new_location
        thread.last_advanced_at = result.advanced_to
        thread.revision += 1

        # Condense history if needed
        condense_thread_history(thread, client)

        applied_results.append(result)

    # Set pending results for narrator
    state.pending_thread_results = applied_results if applied_results else None

    # Archive dormant threads if needed
    archive_dormant_threads(state)


def start_background_simulation(
    state: GameState,
    time_delta: int,
    client: Anthropic,
) -> None:
    """Start background thread simulation if not already running.

    Uses single-flight guard to prevent multiple concurrent simulations.
    Coalesces time deltas if a simulation is already running.
    """
    global _simulation_running, _queued_time_delta

    if not state.threads:
        return

    with _simulation_lock:
        if _simulation_running:
            # Coalesce: add to queued time delta
            _queued_time_delta += time_delta
            logger.debug(
                "Coalescing time delta: +%d (total queued: %d)", time_delta, _queued_time_delta
            )
            return

        _simulation_running = True
        _queued_time_delta = 0

    # Create world context
    location = state.get_current_location()
    world_context = WorldContext(
        player_location=location,
        game_time_minutes=state.get_game_time_minutes(),
        game_time_display=state.get_formatted_game_time(),
        weather=None,  # Could add weather here if needed
    )

    # Create snapshot of threads (shallow copy of list, threads are immutable during simulation)
    threads_snapshot = list(state.threads)
    selection_round_snapshot = state.thread_selection_round

    def run_simulation() -> None:
        global _simulation_running, _queued_time_delta
        success = False
        try:
            # Create a minimal state for simulation
            # We only need threads and selection_round
            class SimState:
                def __init__(self) -> None:
                    self.threads = threads_snapshot
                    self.thread_selection_round = selection_round_snapshot

            sim_state = SimState()

            output = run_thread_simulation(
                sim_state,  # type: ignore[arg-type]
                time_delta,
                world_context,
                client,
            )
            _simulation_queue.put(output)
            success = True
        except (APIError, json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error("Thread simulation failed: %s", e)
        finally:
            with _simulation_lock:
                _simulation_running = False
                if not success:
                    # Restore time_delta so it's not lost on failure
                    _queued_time_delta += time_delta

    # Start background thread
    thread = threading.Thread(target=run_simulation, daemon=True)
    thread.start()
    logger.debug("Started background thread simulation with delta=%d", time_delta)


def drain_simulation_queue(state: GameState, client: Anthropic) -> None:
    """Drain simulation queue and apply results to state."""
    global _queued_time_delta

    while True:
        try:
            output = _simulation_queue.get_nowait()
            apply_thread_simulation_results(state, output, client)
            logger.debug("Applied simulation results for %d threads", len(output.results))
        except queue.Empty:
            break

    # Check if we have queued time delta and should start new simulation
    # Must release lock before calling start_background_simulation to avoid deadlock
    should_start = False
    delta = 0
    with _simulation_lock:
        if _queued_time_delta >= THREAD_SIMULATION_MIN_DELTA and not _simulation_running:
            delta = _queued_time_delta
            _queued_time_delta = 0
            should_start = True

    if should_start:
        start_background_simulation(state, delta, client)


def handle_threads(state: GameState) -> None:
    """Handle the /threads command - list all active and archived threads."""
    c = Colors

    if not state.threads and not state.archived_threads:
        print(f"{c.SYSTEM}No threads active.{c.RESET}")
        return

    game_time_minutes = state.get_game_time_minutes()

    if state.threads:
        print(f"\n{c.SYSTEM}Active Threads ({len(state.threads)}):{c.RESET}")
        for t in state.threads:
            staleness = game_time_minutes - t.last_advanced_at
            location_str = ""
            if t.location:
                location_str = f" @ {t.location.city or t.location.address or 'unknown'}"
            print(f"  {c.WHITE}{t.name}{c.RESET}{location_str}")
            print(f"    {c.DIM}{t.summary[:100]}{'...' if len(t.summary) > 100 else ''}{c.RESET}")
            print(
                f"    {c.DIM}Last update: {staleness} min ago | History: {len(t.history)} entries{c.RESET}"
            )

    if state.archived_threads:
        print(f"\n{c.SYSTEM}Archived Threads ({len(state.archived_threads)}):{c.RESET}")
        for t in state.archived_threads[:5]:  # Show max 5
            print(f"  {c.DIM}{t.name}{c.RESET}")
        if len(state.archived_threads) > 5:
            print(f"  {c.DIM}... and {len(state.archived_threads) - 5} more{c.RESET}")


def print_session_stats(narrator: "GameNarrator", state: GameState) -> None:
    """Print session statistics on exit."""
    cost = narrator.get_session_cost()
    words = count_conversation_words(state)
    print(f"{Colors.DIM}Session: {words:,} words, ${cost:.4f}{Colors.RESET}")


def generate_with_loading(
    narrator: "GameNarrator",
    prompt: str,
    state: GameState,
    action_hint: str | None = None,
    refresh_interval: float = 10.0,
    pending_thread_events: str | None = None,
) -> tuple[str, int]:
    """
    Generate a response while showing periodic loading messages.

    Runs the API call in a background thread and refreshes the loading
    message every refresh_interval seconds until the response is ready.

    Args:
        narrator: The GameNarrator instance.
        prompt: The prompt to send to the model.
        state: Current game state.
        action_hint: Optional hint for loading message context.
        refresh_interval: Seconds between loading message refreshes.
        pending_thread_events: Optional thread events for narrator context.

    Returns:
        Tuple of (generated response text, time advanced in minutes).
    """
    result: tuple[str, int] | None = None
    error: BaseException | None = None

    def run_generation() -> None:
        nonlocal result, error
        try:
            result = narrator.generate_response(
                prompt, state, pending_thread_events=pending_thread_events
            )
        except BaseException as e:
            error = e

    # Start generation in background thread
    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()

    # Show initial loading message
    loading_msg = narrator.generate_loading_message(state, action_hint)
    print(f"\n{Colors.LOADING}{loading_msg}{Colors.RESET}", end="", flush=True)

    # Periodically refresh loading message while waiting
    while thread.is_alive():
        thread.join(timeout=refresh_interval)
        if thread.is_alive():
            # Clear current line and show new loading message
            loading_msg = narrator.generate_loading_message(state, action_hint)
            print(f"\r{Colors.LOADING}{loading_msg:<60}{Colors.RESET}", end="", flush=True)

    print()  # Newline after loading messages

    if error is not None:
        # Re-raise the exception from the background thread
        raise error from None

    if result is None:
        raise RuntimeError("Generation completed but returned no result")
    return result


def main() -> None:
    """Main entry point for the text adventure game."""
    global _fast_mode

    # Reset simulation state at startup (important for tests or multiple calls)
    reset_simulation_state()

    # Set up readline for better input handling
    setup_readline()

    # Check for command line arguments
    start_new = "--new" in sys.argv
    _fast_mode = "--fast" in sys.argv

    print("=" * 60)
    print("   REAL WORLD TEXT ADVENTURE")
    if _fast_mode:
        print("   (fast mode: sonnet, no delays, no auto-save)")
    print("=" * 60)

    # Check for API key
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nError: ANTHROPIC_API_KEY environment variable not set.")
        print("Please set it and try again:")
        print("  export ANTHROPIC_API_KEY='your-api-key'")
        sys.exit(1)

    # Initialize narrator (use sonnet in fast mode)
    model = "claude-sonnet-4-20250514" if _fast_mode else None
    narrator = GameNarrator(model=model)

    state: GameState | None = None

    # Try to load latest save unless --new or --fast is specified
    if not start_new and not _fast_mode:
        saves = list_saves()
        if saves:
            # Load the most recent save (first in the sorted list)
            latest_path, latest_name, _ = saves[0]
            try:
                state = load_game(latest_path)
                print(f"\nResuming: {latest_name}")
            except (ValueError, KeyError) as e:
                print(f"Error loading save: {e}")
                state = None

    # If no save loaded, start new game
    if state is None:
        print("\nDetecting your location...")
        city_location = get_city_from_ip()
        location = prompt_for_address(city_location)

        state = GameState(starting_location=location)

        print("\n" + "=" * 60)

        # Generate and show a fun loading message
        try:
            loading_msg = narrator.generate_loading_message(state)
            print(f"{loading_msg}")
            print("\nExploring your surroundings", end="", flush=True)
        except KeyboardInterrupt:
            print("\n\nGame cancelled.")
            sys.exit(0)

        # Generate opening description (this can take a while due to web searches)
        try:
            opening, time_advanced = narrator.start_game(
                state, progress_callback=lambda: print(".", end="", flush=True)
            )
            print("\n")  # newline after dots
            print_narrative(opening)
            print_status_line(state)
            # Autosave after opening (skip in fast mode)
            if not _fast_mode:
                save_game(state)
        except KeyboardInterrupt:
            print("\n\nGame cancelled.")
            sys.exit(0)
    else:
        # Resuming from save - show current state
        print(f"\nLocation: {state.get_current_location()}")
        print(f"Time: {state.get_formatted_game_time()}")

        # Show last exchange if any
        if state.messages:
            last_assistant = None
            for msg in reversed(state.messages):
                if msg.role == "assistant":
                    last_assistant = msg.content
                    break
            if last_assistant:
                print()
                print_narrative(last_assistant)

    print("\nType /help for commands, or just start exploring!")

    # Track last Ctrl-C time for double-press detection
    last_interrupt_time: float = 0.0

    # Main game loop
    while True:
        try:
            # Drain simulation queue and apply results
            drain_simulation_queue(state, narrator.client)

            # Format pending thread events for narrator context (don't clear yet - only after narration)
            pending_thread_events = format_pending_thread_events(state)

            # Use input() with prompt for proper readline handling
            # \001 and \002 tell readline to ignore ANSI codes when calculating prompt length
            user_input = input("\n\001\033[1;37m\002> \001\033[0m\002").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=1)
                command = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""

                if command == "/quit":
                    if not _fast_mode:
                        handle_save(state, "", silent=True)
                    print_session_stats(narrator, state)
                    print(f"{Colors.SYSTEM}Goodbye!{Colors.RESET}")
                    break

                elif command == "/help":
                    print_help()

                elif command == "/save":
                    handle_save(state, args)

                elif command == "/load":
                    new_state = handle_load()
                    if new_state is not None:
                        # Reset simulation state to avoid leaking results from prior game
                        reset_simulation_state()
                        state = new_state
                        # Show last response
                        if state.messages:
                            for msg in reversed(state.messages):
                                if msg.role == "assistant":
                                    print()
                                    print_narrative(msg.content)
                                    print_status_line(state)
                                    break

                elif command == "/time":
                    handle_time(state)

                elif command == "/where":
                    handle_where(state)

                elif command == "/tokens":
                    handle_tokens(narrator, state)

                elif command == "/threads":
                    handle_threads(state)

                elif command == "/look":
                    # Re-describe surroundings without advancing time
                    response, _ = generate_with_loading(
                        narrator,
                        "Look around and describe my current surroundings in detail. Do not advance time.",
                        state,
                        action_hint="look around",
                        pending_thread_events=pending_thread_events,
                    )
                    # Clear pending results after narrator consumed them
                    state.pending_thread_results = None
                    print_narrative(response)
                    print_status_line(state)
                    if not _fast_mode:
                        save_game(state)

                else:
                    print(f"{Colors.SYSTEM}Unknown command: {command}{Colors.RESET}")
                    print(f"{Colors.SYSTEM}Type /help for available commands.{Colors.RESET}")

                continue

            # Generate response for regular input
            response, time_advanced = generate_with_loading(
                narrator,
                user_input,
                state,
                action_hint=user_input,
                pending_thread_events=pending_thread_events,
            )
            # Clear pending results after narrator consumed them
            state.pending_thread_results = None
            print_narrative(response)
            print_status_line(state)

            # Start background thread simulation if enough time passed
            if time_advanced >= THREAD_SIMULATION_MIN_DELTA and state.threads:
                start_background_simulation(state, time_advanced, narrator.client)

            # Autosave silently (skip in fast mode)
            if not _fast_mode:
                save_game(state)

        except KeyboardInterrupt:
            current_time = time.time()
            if current_time - last_interrupt_time < 2.0:
                # Double Ctrl-C: save (unless fast mode) and quit
                if not _fast_mode:
                    handle_save(state, "", silent=True)
                print_session_stats(narrator, state)
                print(f"{Colors.SYSTEM}Goodbye!{Colors.RESET}")
                break
            else:
                # First Ctrl-C: show warning
                last_interrupt_time = current_time
                msg = (
                    "Press Ctrl-C again to quit."
                    if _fast_mode
                    else "Press Ctrl-C again to save and quit."
                )
                print(f"\n\n{Colors.SYSTEM}{msg}{Colors.RESET}")
        except EOFError:
            if not _fast_mode:
                handle_save(state, "", silent=True)
            print()
            print_session_stats(narrator, state)
            print(f"{Colors.SYSTEM}Goodbye!{Colors.RESET}")
            break


if __name__ == "__main__":
    main()
