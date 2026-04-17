"""Tests for newer state helpers: pop_last_exchange, find_save_by_name, delete_save."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class TestPopLastExchange(unittest.TestCase):
    def setUp(self) -> None:
        from rwta.location import Location
        from rwta.state import GameState

        self.GameState = GameState
        self.location = Location(city="SF", region="CA", country="US")

    def test_returns_none_when_empty(self) -> None:
        state = self.GameState(starting_location=self.location)
        self.assertIsNone(state.pop_last_exchange())
        self.assertEqual(state.messages, [])

    def test_pops_user_assistant_pair(self) -> None:
        state = self.GameState(starting_location=self.location)
        state.add_message("user", "look around")
        state.add_message("assistant", "you see a street")
        popped = state.pop_last_exchange()
        self.assertEqual(popped, "look around")
        self.assertEqual(state.messages, [])

    def test_pops_dangling_user_message(self) -> None:
        state = self.GameState(starting_location=self.location)
        state.add_message("user", "go north")
        popped = state.pop_last_exchange()
        self.assertEqual(popped, "go north")
        self.assertEqual(state.messages, [])

    def test_preserves_earlier_history(self) -> None:
        state = self.GameState(starting_location=self.location)
        state.add_message("user", "first")
        state.add_message("assistant", "first reply")
        state.add_message("user", "second")
        state.add_message("assistant", "second reply")
        popped = state.pop_last_exchange()
        self.assertEqual(popped, "second")
        self.assertEqual([m.content for m in state.messages], ["first", "first reply"])


class TestSaveManagement(unittest.TestCase):
    """Use a temp DATA_DIR so we don't touch the user's real saves."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.data_dir = Path(self.tmpdir.name)

        # Patch the resolved DATA_DIR everywhere it's referenced. Importing
        # state after the env-var override would also work but is fragile;
        # patching the constants is more direct.
        import rwta.config
        import rwta.state

        self._patches = [
            patch.object(rwta.config, "DATA_DIR", self.data_dir),
            patch.object(rwta.state, "DATA_DIR", self.data_dir),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

        os.environ.setdefault("ANTHROPIC_API_KEY", "fake")

    def _make_save(self, name: str) -> Path:
        from rwta.location import Location
        from rwta.state import GameState, save_game

        state = GameState(starting_location=Location(city="SF", region="CA", country="US"))
        return save_game(state, name=name)

    def test_find_save_by_name_exact(self) -> None:
        from rwta.state import find_save_by_name

        path = self._make_save("alpha-1")
        found = find_save_by_name("alpha-1")
        self.assertEqual(found, path)

    def test_find_save_by_name_with_json_suffix(self) -> None:
        from rwta.state import find_save_by_name

        path = self._make_save("beta-2")
        self.assertEqual(find_save_by_name("beta-2.json"), path)

    def test_find_save_by_name_case_insensitive(self) -> None:
        from rwta.state import find_save_by_name

        path = self._make_save("gamma-3")
        self.assertEqual(find_save_by_name("GAMMA-3"), path)

    def test_find_save_by_name_missing(self) -> None:
        from rwta.state import find_save_by_name

        self._make_save("present")
        self.assertIsNone(find_save_by_name("absent"))

    def test_delete_save_removes_file(self) -> None:
        from rwta.state import delete_save, find_save_by_name

        path = self._make_save("to-delete")
        self.assertTrue(path.exists())
        delete_save(path)
        self.assertFalse(path.exists())
        self.assertIsNone(find_save_by_name("to-delete"))


if __name__ == "__main__":
    unittest.main()
