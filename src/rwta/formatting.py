"""Output formatting with rich console styling for the text adventure."""

import re
import shutil
import textwrap
import time

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

# Shared console instance
console = Console()

# ANSI escape codes for text styling
ANSI_BOLD = "\033[1m"
ANSI_ITALIC = "\033[3m"
ANSI_RESET = "\033[0m"


def print_markdown(text: str) -> None:
    """Print markdown-formatted text using rich."""
    console.print(Markdown(text))


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


# --- Styled Output Functions ---


def print_narrative(text: str, typewriter: bool = True) -> None:
    """
    Print narrative text with wrapping and optional typewriter effect.

    Args:
        text: The narrative text to print.
        typewriter: Whether to use typewriter effect.
    """
    if typewriter:
        wrapped = wrap_text(text)
        # Count lines for pre-scroll
        total_lines = wrapped.count("\n") + 2

        # Pre-scroll: print blank lines to reserve space
        print("\n" * total_lines, end="")

        # Move cursor back up
        print(f"\033[{total_lines}A", end="", flush=True)

        # Type out each paragraph
        paragraphs = wrapped.split("\n\n")
        for i, para in enumerate(paragraphs):
            _typewriter_paragraph(para)
            print()  # End the paragraph
            if i < len(paragraphs) - 1:
                print()  # Blank line between paragraphs
                time.sleep(0.15)
    else:
        print_markdown(text)


def _is_single_asterisk(line: str, pos: int) -> bool:
    """Check if the asterisk at pos is a single asterisk (not part of **)."""
    if line[pos] != "*":
        return False
    next_is_asterisk = pos + 1 < len(line) and line[pos + 1] == "*"
    prev_is_asterisk = pos > 0 and line[pos - 1] == "*"
    return not next_is_asterisk and not prev_is_asterisk


def _typewriter_paragraph(text: str, delay: float = 0.05) -> None:
    """Print a paragraph with typewriter effect, word by word. Handles **bold** and *italic*."""
    lines = text.split("\n")
    for line_idx, line in enumerate(lines):
        tokens = _tokenize_markdown_line(line)

        for token in tokens:
            print(token, end="", flush=True)
            is_ansi = token.startswith("\033[")
            if not is_ansi and token != " ":
                time.sleep(delay)

        if line_idx < len(lines) - 1:
            print()


def _tokenize_markdown_line(line: str) -> list[str]:
    """Tokenize a line, converting markdown bold/italic to ANSI codes."""
    tokens: list[str] = []
    current_word = ""
    in_bold = False
    in_italic = False
    i = 0

    while i < len(line):
        # Check for ** bold marker (must check before single *)
        if line[i : i + 2] == "**":
            if current_word:
                tokens.append(current_word)
                current_word = ""
            if in_bold:
                tokens.append(ANSI_RESET + (ANSI_ITALIC if in_italic else ""))
            else:
                tokens.append(ANSI_BOLD)
            in_bold = not in_bold
            i += 2
            continue

        # Check for * italic marker
        if _is_single_asterisk(line, i):
            if current_word:
                tokens.append(current_word)
                current_word = ""
            if in_italic:
                tokens.append(ANSI_RESET + (ANSI_BOLD if in_bold else ""))
            else:
                tokens.append(ANSI_ITALIC)
            in_italic = not in_italic
            i += 1
            continue

        # Check for space (word boundary)
        if line[i] == " ":
            if current_word:
                tokens.append(current_word)
                current_word = ""
            tokens.append(" ")
        else:
            current_word += line[i]
        i += 1

    if current_word:
        tokens.append(current_word)

    if in_bold or in_italic:
        tokens.append(ANSI_RESET)

    return tokens


def parse_suggestions(text: str) -> tuple[str, list[str]]:
    """
    Parse suggested actions from the end of a response.

    Looks for the pattern:
    ---
    1. Action one
    2. Action two
    3. Action three

    Args:
        text: The full response text.

    Returns:
        Tuple of (narrative without suggestions, list of suggestions).
    """
    # Look for the suggestions separator
    parts = text.rsplit("---", 1)
    if len(parts) != 2:
        return text.strip(), []

    narrative = parts[0].strip()
    suggestions_text = parts[1].strip()

    # Parse numbered suggestions
    suggestions: list[str] = []
    for line in suggestions_text.split("\n"):
        line = line.strip()
        # Match "1. text", "2. text", etc.
        match = re.match(r"^\d+\.\s*(.+)$", line)
        if match:
            suggestions.append(match.group(1).strip())

    return narrative, suggestions


def print_suggestions(suggestions: list[str]) -> None:
    """Print suggested actions in a nice format."""
    if not suggestions:
        return

    console.print()
    for i, suggestion in enumerate(suggestions, 1):
        text = Text()
        text.append(f"  [{i}] ", style="dim cyan")
        text.append(suggestion, style="dim")
        console.print(text)


def _print_styled(message: str, style: str, prefix: str = "") -> None:
    """Print a styled message with optional prefix."""
    text = Text()
    if prefix:
        text.append(prefix, style=f"bold {style}")
    text.append(message, style=style)
    console.print(text)


def print_system(message: str) -> None:
    """Print a system message (cyan)."""
    _print_styled(message, "cyan")


def print_success(message: str) -> None:
    """Print a success message (green with checkmark)."""
    _print_styled(message, "green", "✓ ")


def print_error(message: str) -> None:
    """Print an error message (red)."""
    _print_styled(message, "red", "✗ ")


def print_warning(message: str) -> None:
    """Print a warning message (yellow)."""
    _print_styled(message, "yellow", "⚠ ")


def print_dim(message: str) -> None:
    """Print a dim/muted message."""
    _print_styled(message, "dim")


def print_status(location: str, time_str: str) -> None:
    """Print the status line showing location and time."""
    text = Text()
    text.append("\n")
    text.append(location, style="dim")
    text.append(" — ", style="dim")
    text.append(time_str, style="dim")
    console.print(text)


def print_loading(message: str, overwrite: bool = False) -> None:
    """Print a loading message."""
    if overwrite:
        print(f"\r\033[2m{message:<60}\033[0m", end="", flush=True)
    else:
        print(f"\n\033[2m{message}\033[0m", end="", flush=True)


def print_help_command(name: str, description: str) -> None:
    """Print a help entry for a command."""
    text = Text()
    text.append(f"  {name:<10}", style="bold white")
    text.append(f"- {description}", style="")
    console.print(text)


def print_session_stats(words: int, cost: float) -> None:
    """Print session statistics."""
    text = Text()
    text.append(f"Session: {words:,} words, ${cost:.4f}", style="dim")
    console.print(text)


def print_header(title: str) -> None:
    """Print a header line."""
    console.print("=" * 60)
    console.print(f"   {title}")
    console.print("=" * 60)


def print_divider() -> None:
    """Print a divider line."""
    console.print("=" * 60)


def print_token_usage(current: int, max_tokens: int, remaining: int) -> None:
    """Print token usage information."""
    percentage = (current / max_tokens) * 100

    console.print()
    print_system("Token Usage:")
    console.print(f"  Current: {current:,} / {max_tokens:,} ({percentage:.1f}%)")
    console.print(f"  Remaining: {remaining:,}")

    if percentage > 80:
        print_warning("Approaching limit, older messages will be summarized soon")
