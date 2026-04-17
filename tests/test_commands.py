"""Tests for the command registry."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Importing rwta.main registers all built-in commands via @command decorators.
import rwta.main  # noqa: F401, E402
from rwta.commands import (  # noqa: E402
    COMMANDS,
    Command,
    CommandResult,
    command,
    get_all_commands,
    get_command,
    get_command_names,
)


class TestCommandRegistry(unittest.TestCase):
    def test_built_in_commands_registered(self) -> None:
        names = {c.name for c in get_all_commands()}
        # Spot-check a representative set
        for required in ("help", "save", "load", "quit", "look", "tokens"):
            self.assertIn(required, names)

    def test_new_commands_registered(self) -> None:
        names = {c.name for c in get_all_commands()}
        for required in ("cost", "regenerate", "saves", "delete"):
            self.assertIn(required, names, f"/{required} should be registered")

    def test_get_command_is_case_insensitive(self) -> None:
        cmd = get_command("HELP")
        self.assertIsNotNone(cmd)
        assert cmd is not None
        self.assertEqual(cmd.name, "help")

    def test_get_command_unknown_returns_none(self) -> None:
        self.assertIsNone(get_command("definitely-not-a-real-command"))

    def test_get_command_names_have_slash_prefix_and_are_sorted(self) -> None:
        names = get_command_names()
        self.assertTrue(all(n.startswith("/") for n in names))
        self.assertEqual(names, sorted(names))

    def test_get_all_commands_sorted_by_name(self) -> None:
        cmds = get_all_commands()
        self.assertEqual([c.name for c in cmds], sorted(c.name for c in cmds))

    def test_command_decorator_registers(self) -> None:
        sentinel_name = "__test_sentinel_cmd"
        try:

            @command(sentinel_name, "test command")
            def _handler(state: object, narrator: object, args: str) -> CommandResult:
                return CommandResult()

            cmd = get_command(sentinel_name)
            self.assertIsNotNone(cmd)
            assert cmd is not None
            self.assertIsInstance(cmd, Command)
            self.assertEqual(cmd.description, "test command")
        finally:
            COMMANDS.pop(sentinel_name, None)


if __name__ == "__main__":
    unittest.main()
