"""Main entry point and game loop for the text adventure."""

import atexit
import re
import readline
import shutil
import sys
import textwrap
import threading
import time
from pathlib import Path

from rwta.llm import GameNarrator
from rwta.location import get_city_from_ip, prompt_for_address
from rwta.state import GameState, list_saves, load_game, save_game

# Set up readline history
HISTORY_FILE = Path(__file__).parent.parent.parent / ".history"

# Commands for tab completion
COMMANDS = ["/help", "/save", "/load", "/time", "/tokens", "/quit", "/look", "/where"]

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
    SYSTEM = CYAN       # System messages (help, save, etc.)
    LOADING = DIM       # Loading messages
    TIME = YELLOW       # Time display
    SUCCESS = GREEN     # Success messages


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
        try:
            readline.read_history_file(str(HISTORY_FILE))
        except OSError:
            pass

    # Set history length
    readline.set_history_length(1000)

    # Set up tab completion
    completer = CommandCompleter(COMMANDS)
    readline.set_completer(completer.complete)
    readline.parse_and_bind("tab: complete")

    # Save history on exit
    def _save_history() -> None:
        try:
            readline.write_history_file(str(HISTORY_FILE))
        except OSError:
            pass

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
            line.strip().startswith(("-", "*", "•"))
            or re.match(r'^\d+[.)]\s', line.strip())
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
    text = re.sub(r'\*\*([^*]+)\*\*', r'\033[1m\1\033[0m', text)

    # Italic: *text* -> ANSI italic (may not work in all terminals)
    text = re.sub(r'\*([^*]+)\*', r'\033[3m\1\033[0m', text)

    return text


def typewriter_print(text: str, delay: float = 0.05) -> None:
    """
    Print text with a typewriter effect, word by word.

    Args:
        text: The text to print.
        delay: Delay between words in seconds.
    """
    lines = text.split('\n')
    num_lines = len(lines)

    for line_idx, line in enumerate(lines):
        words = line.split()
        for i, word in enumerate(words):
            print(word, end='', flush=True)
            if i < len(words) - 1:
                print(' ', end='', flush=True)
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

    # Count exact lines needed (including blank lines between paragraphs)
    total_lines = wrapped.count('\n') + 2  # +1 for last line, +1 for final newline

    # Pre-scroll: print blank lines to reserve space
    print('\n' * total_lines, end='')

    # Move cursor back up
    print(f'\033[{total_lines}A', end='', flush=True)

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
    for i, (filepath, name, updated_at) in enumerate(saves, 1):
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
    location_str = location.short_str() if hasattr(location, 'short_str') else str(location)
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
        print(f"  {Colors.TIME}Warning: Approaching limit, older messages will be summarized soon{Colors.RESET}")


def print_session_cost(narrator: "GameNarrator") -> None:
    """Print the session cost on exit."""
    cost = narrator.get_session_cost()
    print(f"{Colors.DIM}Session cost: ${cost:.4f}{Colors.RESET}")


def generate_with_loading(
    narrator: "GameNarrator",
    prompt: str,
    state: GameState,
    action_hint: str | None = None,
    refresh_interval: float = 10.0,
) -> str:
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

    Returns:
        The generated response text.
    """
    result: str | None = None
    error: BaseException | None = None

    def run_generation() -> None:
        nonlocal result, error
        try:
            result = narrator.generate_response(prompt, state)
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
    # Set up readline for better input handling
    setup_readline()

    print("=" * 60)
    print("   REAL WORLD TEXT ADVENTURE")
    print("=" * 60)

    # Check for API key
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nError: ANTHROPIC_API_KEY environment variable not set.")
        print("Please set it and try again:")
        print("  export ANTHROPIC_API_KEY='your-api-key'")
        sys.exit(1)

    # Initialize narrator
    narrator = GameNarrator()

    # Check for command line arguments
    start_new = "--new" in sys.argv

    state: GameState | None = None

    # Try to load latest save unless --new is specified
    if not start_new:
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
            opening = narrator.start_game(state, progress_callback=lambda: print(".", end="", flush=True))
            print("\n")  # newline after dots
            print_narrative(opening)
            print_status_line(state)
            # Autosave after opening
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
                    handle_save(state, "", silent=True)
                    print_session_cost(narrator)
                    print(f"{Colors.SYSTEM}Goodbye!{Colors.RESET}")
                    break

                elif command == "/help":
                    print_help()

                elif command == "/save":
                    handle_save(state, args)

                elif command == "/load":
                    new_state = handle_load()
                    if new_state is not None:
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

                elif command == "/look":
                    # Re-describe surroundings without advancing time
                    response = generate_with_loading(
                        narrator,
                        "Look around and describe my current surroundings in detail. Do not advance time.",
                        state,
                        action_hint="look around",
                    )
                    print_narrative(response)
                    print_status_line(state)
                    save_game(state)

                else:
                    print(f"{Colors.SYSTEM}Unknown command: {command}{Colors.RESET}")
                    print(f"{Colors.SYSTEM}Type /help for available commands.{Colors.RESET}")

                continue

            # Generate response for regular input
            response = generate_with_loading(narrator, user_input, state, action_hint=user_input)
            print_narrative(response)
            print_status_line(state)

            # Autosave silently
            save_game(state)

        except KeyboardInterrupt:
            current_time = time.time()
            if current_time - last_interrupt_time < 2.0:
                # Double Ctrl-C: save and quit
                handle_save(state, "", silent=True)
                print_session_cost(narrator)
                print(f"{Colors.SYSTEM}Goodbye!{Colors.RESET}")
                break
            else:
                # First Ctrl-C: show warning
                last_interrupt_time = current_time
                print(f"\n\n{Colors.SYSTEM}Press Ctrl-C again to save and quit.{Colors.RESET}")
        except EOFError:
            handle_save(state, "", silent=True)
            print()
            print_session_cost(narrator)
            print(f"{Colors.SYSTEM}Goodbye!{Colors.RESET}")
            break


if __name__ == "__main__":
    main()
