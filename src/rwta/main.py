"""Main entry point and game loop for the text adventure."""

import atexit
import os
import readline
import sys
import threading
import time
from pathlib import Path

from rwta.commands import CommandResult, command, get_all_commands, get_command, get_command_names
from rwta.formatting import (
    parse_suggestions,
    print_divider,
    print_error,
    print_header,
    print_help_command,
    print_loading,
    print_narrative,
    print_session_stats,
    print_status,
    print_success,
    print_suggestions,
    print_system,
    print_token_usage,
    print_warning,
)
from rwta.llm import GameNarrator
from rwta.location import get_city_from_ip, prompt_for_address
from rwta.state import GameState, list_saves, load_game, save_game

# Set up readline history
HISTORY_FILE = Path(__file__).parent.parent.parent / ".history"


class CommandCompleter:
    """Tab completion for game commands."""

    def complete(self, text: str, state: int) -> str | None:
        """Return the next possible completion for text."""
        if text.startswith("/"):
            commands = get_command_names()
            matches = [c for c in commands if c.startswith(text)]
        else:
            matches = []

        if state < len(matches):
            return matches[state]
        return None


def setup_readline() -> None:
    """Configure readline for better input handling."""
    # Load history if it exists
    if HISTORY_FILE.exists():
        try:
            readline.read_history_file(str(HISTORY_FILE))
        except OSError:
            pass

    # Set history length
    readline.set_history_length(1000)

    # Set up tab completion
    completer = CommandCompleter()
    readline.set_completer(completer.complete)
    readline.parse_and_bind("tab: complete")

    # Save history on exit
    def _save_history() -> None:
        try:
            readline.write_history_file(str(HISTORY_FILE))
        except OSError:
            pass

    atexit.register(_save_history)


# --- Command Handlers ---
# These are registered via @command decorator


@command("help", "Show available commands")
def cmd_help(state: GameState, narrator: GameNarrator, args: str) -> CommandResult:
    """Show all available commands."""
    print()
    print_system("Commands:")
    for cmd in get_all_commands():
        print_help_command(f"/{cmd.name}", cmd.description)
    return CommandResult()


@command("save", "Save your game (optionally: /save <name>)")
def cmd_save(state: GameState, narrator: GameNarrator, args: str) -> CommandResult:
    """Save the current game."""
    name = args.strip() if args.strip() else None
    filepath = save_game(state, name)
    print_success(f"Game saved to: {filepath.name}")
    return CommandResult()


@command("load", "Load a saved game")
def cmd_load(state: GameState, narrator: GameNarrator, args: str) -> CommandResult:
    """Load a saved game."""
    saves = list_saves()

    if not saves:
        print_system("No saved games found.")
        return CommandResult()

    print("\nSaved games:")
    _print_save_list(saves)

    new_state = _choose_save(saves, "\nEnter the number to load (or 'cancel'):")
    if new_state is not None and isinstance(new_state, GameState):
        narrative = new_state.get_last_assistant_message() or ""
        return CommandResult(new_state=new_state, narrative=narrative, show_status=True)
    return CommandResult()


@command("time", "Show current in-game time")
def cmd_time(state: GameState, narrator: GameNarrator, args: str) -> CommandResult:
    """Show the current in-game time."""
    print_system(f"Current in-game time: {state.get_formatted_game_time()}")
    return CommandResult()


@command("where", "Show current location and time")
def cmd_where(state: GameState, narrator: GameNarrator, args: str) -> CommandResult:
    """Show current location and time."""
    location = state.get_current_location()
    print_system(f"Current location: {location}")
    print_system(f"Time: {state.get_formatted_game_time()}")
    return CommandResult()


@command("tokens", "Show token usage and context limit")
def cmd_tokens(state: GameState, narrator: GameNarrator, args: str) -> CommandResult:
    """Show token usage information."""
    max_tokens = 180000
    messages: list[dict[str, object]] = [
        {"role": m.role, "content": m.content} for m in state.messages
    ]
    system = ""
    try:
        current_tokens = narrator.count_tokens(messages, system)
    except (ValueError, TypeError, RuntimeError):
        current_tokens = sum(len(m.content) for m in state.messages) // 4

    remaining = max_tokens - current_tokens
    print_token_usage(current_tokens, max_tokens, remaining)
    return CommandResult()


@command("look", "Look around (re-describe surroundings)")
def cmd_look(state: GameState, narrator: GameNarrator, args: str) -> CommandResult:
    """Re-describe the current surroundings."""
    response = _generate_with_loading(
        narrator,
        "Look around and describe my current surroundings in detail. Do not advance time.",
        state,
        action_hint="look around",
    )
    return CommandResult(narrative=response, show_status=True, should_save=True)


@command("quit", "Exit the game")
def cmd_quit(state: GameState, narrator: GameNarrator, args: str) -> CommandResult:
    """Save and exit the game."""
    _exit_game(state, narrator)
    return CommandResult(should_quit=True)


# --- Helper Functions ---


def _print_save_list(saves: list[tuple[Path, str, str]], offset: int = 0) -> None:
    """Print a numbered list of saves."""
    for i, (_, name, updated_at) in enumerate(saves, offset + 1):
        print(f"  {i}. {name} (saved: {updated_at[:19]})")


def _choose_save(
    saves: list[tuple[Path, str, str]], prompt: str, allow_new: bool = False
) -> GameState | None | str:
    """Let user choose from a list of saves."""
    print(prompt)
    print("> ", end="", flush=True)

    try:
        choice = input().strip()
        if choice.lower() in ("cancel", "c", ""):
            return None

        if allow_new and choice.lower() in ("n", "new"):
            return "new"

        idx = int(choice) - 1
        if 0 <= idx < len(saves):
            filepath, name, _ = saves[idx]
            try:
                loaded_state = load_game(filepath)
            except (OSError, ValueError, KeyError) as e:
                print_error(f"Error loading save: {e}")
                return None
            else:
                print(f"Loaded: {name}")
                return loaded_state
        else:
            print_error("Invalid selection.")
            return None
    except ValueError:
        print_error("Invalid input.")
        return None


def _choose_story() -> GameState | None | str:
    """Show startup menu to choose an existing story or start new."""
    saves = list_saves()

    if not saves:
        return "new"

    print("\nStories:")
    _print_save_list(saves)
    print("  n. New Game")

    return _choose_save(saves, "\nEnter number to continue, 'n' for new game:", allow_new=True)


def _print_status_line(state: GameState) -> None:
    """Print a brief status line showing location and time."""
    location = state.get_current_location()
    game_dt = state.get_game_datetime()
    time_str = game_dt.strftime("%a %I:%M %p")
    location_str = location.short_str() if hasattr(location, "short_str") else str(location)
    print_status(location_str, time_str)


def _count_conversation_words(state: GameState) -> int:
    """Count total words in the conversation history."""
    return sum(len(msg.content.split()) for msg in state.messages)


def _exit_game(state: GameState, narrator: GameNarrator, save: bool = True) -> None:
    """Save game (if requested), print session stats, and print goodbye."""
    if save:
        save_game(state)
    words = _count_conversation_words(state)
    cost = narrator.get_session_cost()
    print_session_stats(words, cost)
    print_system("Goodbye!")


def _generate_with_loading(
    narrator: GameNarrator,
    prompt: str,
    state: GameState,
    action_hint: str | None = None,
    refresh_interval: float = 10.0,
) -> str:
    """Generate a response while showing periodic loading messages."""
    result: str | None = None
    error: BaseException | None = None

    def run_generation() -> None:
        nonlocal result, error
        try:
            result = narrator.generate_response(prompt, state)
        except BaseException as e:
            error = e

    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()

    loading_msg = narrator.generate_loading_message(state, action_hint)
    print_loading(loading_msg)

    while thread.is_alive():
        thread.join(timeout=refresh_interval)
        if thread.is_alive():
            loading_msg = narrator.generate_loading_message(state, action_hint)
            print_loading(loading_msg, overwrite=True)

    print("\n")  # Blank line after loading messages

    if error is not None:
        raise error from None

    if result is None:
        raise RuntimeError("Generation completed but returned no result")
    return result


def main() -> None:
    """Main entry point for the text adventure game."""
    setup_readline()

    print_header("REAL WORLD TEXT ADVENTURE")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print_error("ANTHROPIC_API_KEY environment variable not set.")
        print("Please set it and try again:")
        print("  export ANTHROPIC_API_KEY='your-api-key'")
        sys.exit(1)

    narrator = GameNarrator()
    start_new = "--new" in sys.argv
    state: GameState | None = None
    current_suggestions: list[str] = []

    # Choose story unless --new is specified
    if not start_new:
        choice = _choose_story()
        if choice is None:
            print_system("Goodbye!")
            sys.exit(0)
        elif isinstance(choice, GameState):
            state = choice

    # If no save loaded, start new game
    if state is None:
        print("\nDetecting your location...")
        city_location = get_city_from_ip()
        location = prompt_for_address(city_location)

        state = GameState(starting_location=location)

        print()
        print_divider()

        try:
            loading_msg = narrator.generate_loading_message(state)
            print(f"{loading_msg}")
            print("\nExploring your surroundings", end="", flush=True)
        except KeyboardInterrupt:
            print("\n\nGame cancelled.")
            sys.exit(0)

        try:
            opening = narrator.start_game(
                state, progress_callback=lambda: print(".", end="", flush=True)
            )
            print("\n")
            narrative, suggestions = parse_suggestions(opening)
            print_narrative(narrative)
            _print_status_line(state)
            print_suggestions(suggestions)
            save_game(state)
        except KeyboardInterrupt:
            print("\n\nGame cancelled.")
            sys.exit(0)
        current_suggestions = suggestions
    else:
        # Resuming from save
        print(f"\nLocation: {state.get_current_location()}")
        print(f"Time: {state.get_formatted_game_time()}")

        last_assistant = state.get_last_assistant_message()
        if last_assistant:
            print()
            narrative, current_suggestions = parse_suggestions(last_assistant)
            print_narrative(narrative)
            print_suggestions(current_suggestions)

    print("\nType /help for commands, or just start exploring!")

    # At this point, state is guaranteed to be set (either loaded or new)
    assert state is not None
    game_state: GameState = state

    last_interrupt_time: float = 0.0

    # Main game loop
    while True:
        try:
            user_input = input("\n\001\033[1;37m\002> \001\033[0m\002").strip()

            if not user_input:
                continue

            # Check if input is a suggestion selection (1, 2, or 3)
            if user_input in ("1", "2", "3"):
                idx = int(user_input) - 1
                if idx < len(current_suggestions):
                    user_input = current_suggestions[idx]
                    print_system(f"→ {user_input}\n")
                # If no suggestions available, treat as regular input

            # Handle commands
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=1)
                cmd_name = parts[0][1:].lower()  # Remove leading /
                args = parts[1] if len(parts) > 1 else ""

                cmd = get_command(cmd_name)
                if cmd is None:
                    print_error(f"Unknown command: /{cmd_name}")
                    print_system("Type /help for available commands.")
                    continue

                result = cmd.handler(game_state, narrator, args)

                if result.new_state is not None:
                    game_state = result.new_state

                if result.narrative:
                    print()
                    print_narrative(result.narrative)

                if result.show_status:
                    _print_status_line(game_state)

                if result.should_save:
                    save_game(game_state)

                if result.should_quit:
                    break

                continue

            # Generate response for regular input
            response = _generate_with_loading(
                narrator, user_input, game_state, action_hint=user_input
            )

            # Parse narrative and suggestions
            narrative, current_suggestions = parse_suggestions(response)

            print_narrative(narrative)
            _print_status_line(game_state)
            print_suggestions(current_suggestions)
            save_game(game_state)

        except KeyboardInterrupt:
            current_time = time.time()
            if current_time - last_interrupt_time < 2.0:
                _exit_game(game_state, narrator)
                break
            last_interrupt_time = current_time
            print()
            print_warning("Press Ctrl-C again to save and quit.")
        except EOFError:
            print()
            _exit_game(game_state, narrator)
            break


if __name__ == "__main__":
    main()
