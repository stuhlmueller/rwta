import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.location import Location  # noqa: E402
from rwta.state import GameState  # noqa: E402


class TestGameState(unittest.TestCase):
    def test_round_trip_serialization(self) -> None:
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z", address="123 Main St"),
        )
        state.add_message("user", "hi")
        state.add_message("assistant", "hello")

        data = state.to_dict()
        loaded = GameState.from_dict(data)

        self.assertEqual(str(loaded.starting_location), "123 Main St, X, Y, Z")
        self.assertEqual([(m.role, m.content) for m in loaded.messages], [("user", "hi"), ("assistant", "hello")])

    def test_from_dict_skips_invalid_messages(self) -> None:
        data = {
            "version": 1,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "game_time": datetime.now().isoformat(),
            "starting_location": {"city": "X", "region": "Y", "country": "Z"},
            "messages": [
                {"role": "user", "content": "ok"},
                {"role": "system", "content": "nope"},
                {"role": "assistant", "content": 123},
                "not even a dict",
            ],
        }

        loaded = GameState.from_dict(data)
        self.assertEqual([(m.role, m.content) for m in loaded.messages], [("user", "ok")])

    def test_trimming_keeps_first_two_messages(self) -> None:
        state = GameState(starting_location=Location(city="X", region="Y", country="Z"))
        state.add_message("user", "intro 1")
        state.add_message("assistant", "intro 2")
        for i in range(30):
            state.add_message("user", f"user {i} " + ("x" * 200))
            state.add_message("assistant", f"assistant {i} " + ("y" * 200))

        def counter(msgs: list[dict[str, object]]) -> int:
            return sum(len(str(m.get("content", ""))) for m in msgs)

        trimmed = state.get_messages_for_api(token_counter=counter, max_tokens=2000)
        self.assertGreaterEqual(len(trimmed), 2)
        self.assertEqual(trimmed[0]["content"], "intro 1")
        self.assertEqual(trimmed[1]["content"], "intro 2")


if __name__ == "__main__":
    unittest.main()

