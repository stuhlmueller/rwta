"""Extended tests for game state management."""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.config import LOCAL_TIMEZONE  # noqa: E402
from rwta.location import Location  # noqa: E402
from rwta.state import GameState  # noqa: E402


class TestGameTimeAdvancement(unittest.TestCase):
    def test_advance_time_adds_minutes(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
            game_time="2025-01-15T10:00:00-08:00",
        )
        state.advance_time_minutes(30)
        dt = state.get_game_datetime()
        self.assertEqual(dt.hour, 10)
        self.assertEqual(dt.minute, 30)

    def test_advance_time_crosses_hour(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
            game_time="2025-01-15T10:45:00-08:00",
        )
        state.advance_time_minutes(30)
        dt = state.get_game_datetime()
        self.assertEqual(dt.hour, 11)
        self.assertEqual(dt.minute, 15)

    def test_advance_time_zero_minutes(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
            game_time="2025-01-15T10:00:00-08:00",
        )
        state.advance_time_minutes(0)
        dt = state.get_game_datetime()
        self.assertEqual(dt.hour, 10)
        self.assertEqual(dt.minute, 0)

    def test_formatted_game_time(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
            game_time="2025-01-15T14:30:00-08:00",
        )
        formatted = state.get_formatted_game_time()
        self.assertIn("Wednesday", formatted)
        self.assertIn("January", formatted)
        self.assertIn("02:30 PM", formatted)


class TestMessageAddition(unittest.TestCase):
    def test_add_message_appends(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
        )
        state.add_message("user", "hello")
        state.add_message("assistant", "world")
        self.assertEqual(len(state.messages), 2)
        self.assertEqual(state.messages[0].role, "user")
        self.assertEqual(state.messages[1].content, "world")

    def test_add_message_updates_timestamp(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
        )
        old_updated = state.updated_at
        state.add_message("user", "test")
        # updated_at should be at least as recent
        self.assertGreaterEqual(state.updated_at, old_updated)

    def test_get_last_assistant_message(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
        )
        self.assertIsNone(state.get_last_assistant_message())
        state.add_message("user", "hi")
        self.assertIsNone(state.get_last_assistant_message())
        state.add_message("assistant", "hello!")
        self.assertEqual(state.get_last_assistant_message(), "hello!")
        state.add_message("user", "another")
        self.assertEqual(state.get_last_assistant_message(), "hello!")


class TestMessageTrimmingWithSummarizer(unittest.TestCase):
    def test_trimming_calls_summarizer(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
        )
        state.add_message("user", "intro 1")
        state.add_message("assistant", "intro 2")
        for i in range(20):
            state.add_message("user", f"user {i} " + "x" * 200)
            state.add_message("assistant", f"assistant {i} " + "y" * 200)

        summarizer = MagicMock(return_value="Summary of events")

        def counter(msgs: list[dict[str, object]]) -> int:
            return sum(len(str(m.get("content", ""))) for m in msgs)

        trimmed = state.get_messages_for_api(
            token_counter=counter,
            max_tokens=2000,
            summarizer=summarizer,
        )

        # Summarizer should have been called with the trimmed messages
        summarizer.assert_called_once()

        # Result should contain intro + summary + remaining
        self.assertEqual(trimmed[0]["content"], "intro 1")
        self.assertEqual(trimmed[1]["content"], "intro 2")
        # Third message should be the summary
        summary_content = str(trimmed[2]["content"])
        self.assertIn("Earlier in this adventure", summary_content)
        self.assertIn("Summary of events", summary_content)

    def test_trimming_without_summarizer(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
        )
        state.add_message("user", "intro 1")
        state.add_message("assistant", "intro 2")
        for i in range(20):
            state.add_message("user", f"user {i} " + "x" * 200)
            state.add_message("assistant", f"assistant {i} " + "y" * 200)

        def counter(msgs: list[dict[str, object]]) -> int:
            return sum(len(str(m.get("content", ""))) for m in msgs)

        trimmed = state.get_messages_for_api(
            token_counter=counter,
            max_tokens=2000,
            summarizer=None,
        )

        # First two should still be intro
        self.assertEqual(trimmed[0]["content"], "intro 1")
        self.assertEqual(trimmed[1]["content"], "intro 2")
        # No summary message
        self.assertNotIn("Earlier in this adventure", str(trimmed[2].get("content", "")))

    def test_no_trimming_when_under_limit(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
        )
        state.add_message("user", "hello")
        state.add_message("assistant", "world")

        def counter(msgs: list[dict[str, object]]) -> int:
            return sum(len(str(m.get("content", ""))) for m in msgs)

        result = state.get_messages_for_api(
            token_counter=counter,
            max_tokens=100000,
        )
        self.assertEqual(len(result), 2)


class TestSetGameTime(unittest.TestCase):
    def test_set_game_time(self) -> None:
        state = GameState(
            starting_location=Location(city="SF", region="CA", country="US"),
        )
        new_dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=LOCAL_TIMEZONE)
        state.set_game_time(new_dt)
        result = state.get_game_datetime()
        self.assertEqual(result.month, 6)
        self.assertEqual(result.day, 15)
        self.assertEqual(result.hour, 12)


if __name__ == "__main__":
    unittest.main()
