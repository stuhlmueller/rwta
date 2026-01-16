"""Command registry for the text adventure game."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rwta.state import GameState


@dataclass
class Command:
    """A registered command."""

    name: str
    description: str
    handler: Callable[..., Any]


# Command registry: name -> Command
COMMANDS: dict[str, Command] = {}


def command(name: str, description: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a command."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        COMMANDS[name] = Command(name=name, description=description, handler=func)
        return func

    return decorator


@dataclass
class CommandResult:
    """Result of executing a command."""

    new_state: GameState | None = None
    should_quit: bool = False
    narrative: str = ""
    show_status: bool = False
    should_save: bool = False


def get_command(name: str) -> Command | None:
    """Get a command by name (without slash)."""
    return COMMANDS.get(name.lower())


def get_all_commands() -> list[Command]:
    """Get all registered commands, sorted by name."""
    return sorted(COMMANDS.values(), key=lambda c: c.name)


def get_command_names() -> list[str]:
    """Get all command names with slash prefix."""
    return [f"/{name}" for name in sorted(COMMANDS.keys())]
