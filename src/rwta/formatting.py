"""Output formatting with rich console styling for the text adventure."""

import re
import shutil
import textwrap
import time

from rich.console import Console
from rich.text import Text

# Shared console instance
console = Console()


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
    wrapped = wrap_text(text)

    if typewriter:
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
        # Render markdown styling and print
        styled = _render_markdown_to_text(wrapped)
        console.print(styled)


def _typewriter_paragraph(text: str, delay: float = 0.05) -> None:
    """Print a paragraph with typewriter effect, word by word."""
    lines = text.split("\n")
    for line_idx, line in enumerate(lines):
        words = line.split()
        for i, word in enumerate(words):
            print(word, end="", flush=True)
            if i < len(words) - 1:
                print(" ", end="", flush=True)
            time.sleep(delay)

        if line_idx < len(lines) - 1:
            print()


def _render_markdown_to_text(text: str) -> Text:
    """Convert basic markdown to rich Text with styling."""
    result = Text()

    # Process text character by character to handle markdown
    i = 0
    while i < len(text):
        # Bold: **text**
        if text[i : i + 2] == "**":
            end = text.find("**", i + 2)
            if end != -1:
                result.append(text[i + 2 : end], style="bold")
                i = end + 2
                continue

        # Italic: *text*
        if text[i] == "*" and (i == 0 or text[i - 1] != "*"):
            end = text.find("*", i + 1)
            if end != -1 and (end + 1 >= len(text) or text[end + 1] != "*"):
                result.append(text[i + 1 : end], style="italic")
                i = end + 1
                continue

        result.append(text[i])
        i += 1

    return result


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
