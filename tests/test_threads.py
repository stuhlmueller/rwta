"""Tests for thread management and simulation."""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rwta.location import Location
from rwta.state import GameState, Thread, ThreadResult
from rwta.threads import (
    ThreadSelector,
    ThreadSimulator,
    WorldContext,
    archive_dormant_threads,
    condense_thread_history,
    run_thread_simulation,
)


class TestThreadSerialization(unittest.TestCase):
    """Tests for Thread serialization/deserialization."""

    def test_thread_create(self) -> None:
        """Thread.create() sets default values correctly."""
        thread = Thread.create(
            name="Test Thread",
            description="A test thread",
            game_time_minutes=100,
            selection_round=5,
        )
        self.assertEqual(thread.name, "Test Thread")
        self.assertEqual(thread.description, "A test thread")
        self.assertEqual(thread.summary, "A test thread")  # Initial summary is description
        self.assertEqual(thread.created_at, 100)
        self.assertEqual(thread.last_advanced_at, 100)
        self.assertEqual(thread.last_selected_round, 5)
        self.assertEqual(thread.revision, 0)
        self.assertEqual(thread.history, [])
        self.assertIsNone(thread.location)
        self.assertTrue(thread.id)  # UUID generated

    def test_thread_create_with_location(self) -> None:
        """Thread.create() accepts optional location."""
        loc = Location(city="SF", region="CA", country="US")
        thread = Thread.create(
            name="Located Thread",
            description="Has a location",
            game_time_minutes=0,
            selection_round=0,
            location=loc,
        )
        self.assertIsNotNone(thread.location)
        self.assertEqual(thread.location.city, "SF")  # type: ignore[union-attr]

    def test_thread_round_trip(self) -> None:
        """Thread serializes and deserializes correctly."""
        thread = Thread.create(
            name="Test",
            description="Desc",
            game_time_minutes=50,
            selection_round=2,
            location=Location(city="NYC", region="NY", country="US", address="123 Main"),
        )
        thread.summary = "Updated summary"
        thread.history = ["Event 1", "Event 2"]
        thread.revision = 3

        data = thread.to_dict()
        loaded = Thread.from_dict(data, GameState._parse_location)

        self.assertEqual(loaded.id, thread.id)
        self.assertEqual(loaded.name, "Test")
        self.assertEqual(loaded.summary, "Updated summary")
        self.assertEqual(loaded.history, ["Event 1", "Event 2"])
        self.assertEqual(loaded.revision, 3)
        self.assertEqual(loaded.location.city, "NYC")  # type: ignore[union-attr]

    def test_thread_round_trip_no_location(self) -> None:
        """Thread without location serializes correctly."""
        thread = Thread.create("No Loc", "Desc", 0, 0)
        data = thread.to_dict()
        loaded = Thread.from_dict(data, GameState._parse_location)
        self.assertIsNone(loaded.location)

    def test_thread_status_default(self) -> None:
        """Thread.create() defaults to status='active'."""
        thread = Thread.create("Test", "Desc", 0, 0)
        self.assertEqual(thread.status, "active")

    def test_thread_status_custom(self) -> None:
        """Thread.create() accepts custom status."""
        thread = Thread.create("Test", "Desc", 0, 0, status="paused")
        self.assertEqual(thread.status, "paused")

    def test_thread_status_serialization(self) -> None:
        """Thread status is properly serialized and deserialized."""
        for status in ["active", "in_scene", "paused", "resolved"]:
            thread = Thread.create("Test", "Desc", 0, 0, status=status)  # type: ignore[arg-type]
            data = thread.to_dict()
            self.assertEqual(data["status"], status)

            loaded = Thread.from_dict(data, GameState._parse_location)
            self.assertEqual(loaded.status, status)

    def test_thread_status_migration_default(self) -> None:
        """Old thread data without status defaults to 'active'."""
        data = {
            "id": "test-id",
            "name": "Test",
            "description": "Desc",
            "location": None,
            "summary": "Summary",
            "history": [],
            "created_at": 0,
            "last_advanced_at": 0,
            "last_selected_round": 0,
            "revision": 0,
            # Note: no "status" field
        }
        loaded = Thread.from_dict(data, GameState._parse_location)
        self.assertEqual(loaded.status, "active")


class TestThreadResultSerialization(unittest.TestCase):
    """Tests for ThreadResult serialization/deserialization."""

    def test_thread_result_round_trip(self) -> None:
        """ThreadResult serializes and deserializes correctly."""
        result = ThreadResult(
            thread_id="abc-123",
            thread_name="Test Thread",
            base_revision=2,
            events="Something happened",
            new_summary="New state",
            new_history_entry="Brief entry",
            new_location=Location(city="LA", region="CA", country="US"),
            simulated_from=100,
            advanced_to=130,
        )

        data = result.to_dict()
        loaded = ThreadResult.from_dict(data, GameState._parse_location)

        self.assertEqual(loaded.thread_id, "abc-123")
        self.assertEqual(loaded.thread_name, "Test Thread")
        self.assertEqual(loaded.base_revision, 2)
        self.assertEqual(loaded.events, "Something happened")
        self.assertEqual(loaded.new_summary, "New state")
        self.assertEqual(loaded.new_history_entry, "Brief entry")
        self.assertEqual(loaded.new_location.city, "LA")  # type: ignore[union-attr]
        self.assertEqual(loaded.simulated_from, 100)
        self.assertEqual(loaded.advanced_to, 130)

    def test_thread_result_no_location(self) -> None:
        """ThreadResult without new_location works."""
        result = ThreadResult(
            thread_id="x",
            thread_name="X",
            base_revision=0,
            events="",
            new_summary="",
            new_history_entry="",
            new_location=None,
            simulated_from=0,
            advanced_to=0,
        )
        data = result.to_dict()
        loaded = ThreadResult.from_dict(data, GameState._parse_location)
        self.assertIsNone(loaded.new_location)


class TestGameStateThreads(unittest.TestCase):
    """Tests for thread fields in GameState."""

    def test_threads_in_game_state_serialization(self) -> None:
        """Threads are properly saved and loaded with GameState."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        thread = Thread.create("Agent", "Following someone", 10, 1)
        state.threads.append(thread)
        state.thread_selection_round = 5

        data = state.to_dict()
        loaded = GameState.from_dict(data)

        self.assertEqual(len(loaded.threads), 1)
        self.assertEqual(loaded.threads[0].name, "Agent")
        self.assertEqual(loaded.thread_selection_round, 5)

    def test_archived_threads_serialization(self) -> None:
        """Archived threads are saved and loaded."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        archived = Thread.create("Old Thread", "Desc", 0, 0)
        state.archived_threads.append(archived)

        data = state.to_dict()
        loaded = GameState.from_dict(data)

        self.assertEqual(len(loaded.archived_threads), 1)
        self.assertEqual(loaded.archived_threads[0].name, "Old Thread")

    def test_pending_results_serialization(self) -> None:
        """Pending thread results are saved and loaded."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        result = ThreadResult(
            thread_id="abc",
            thread_name="Thread",
            base_revision=0,
            events="Events",
            new_summary="Summary",
            new_history_entry="Entry",
            new_location=None,
            simulated_from=0,
            advanced_to=30,
        )
        state.pending_thread_results = [result]

        data = state.to_dict()
        loaded = GameState.from_dict(data)

        self.assertIsNotNone(loaded.pending_thread_results)
        self.assertEqual(len(loaded.pending_thread_results), 1)  # type: ignore[arg-type]
        self.assertEqual(loaded.pending_thread_results[0].thread_name, "Thread")  # type: ignore[index]

    def test_pending_results_survive_multiple_reads(self) -> None:
        """Pending results are not cleared by read operations."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        result = ThreadResult(
            thread_id="abc",
            thread_name="Thread",
            base_revision=0,
            events="Events",
            new_summary="Summary",
            new_history_entry="Entry",
            new_location=None,
            simulated_from=0,
            advanced_to=30,
        )
        state.pending_thread_results = [result]

        # Multiple reads should not clear pending results
        for _ in range(3):
            self.assertIsNotNone(state.pending_thread_results)
            self.assertEqual(len(state.pending_thread_results), 1)  # type: ignore[arg-type]
            self.assertEqual(state.pending_thread_results[0].thread_name, "Thread")  # type: ignore[index]
            # Access other state without clearing
            _ = state.get_current_location()
            _ = state.get_game_datetime()
            _ = state.threads

        # Still not cleared
        self.assertIsNotNone(state.pending_thread_results)

        # Only explicit clear removes them
        state.pending_thread_results = None
        self.assertIsNone(state.pending_thread_results)

    def test_migration_to_v3(self) -> None:
        """Old saves without thread fields are migrated."""
        data = {
            "version": 2,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "game_time": datetime.now().isoformat(),
            "starting_location": {"city": "X", "region": "Y", "country": "Z"},
            "messages": [],
        }
        loaded = GameState.from_dict(data)
        self.assertEqual(loaded.threads, [])
        self.assertEqual(loaded.archived_threads, [])
        self.assertIsNone(loaded.pending_thread_results)
        self.assertEqual(loaded.thread_selection_round, 0)
        self.assertEqual(loaded.version, 3)


class TestThreadSelector(unittest.TestCase):
    """Tests for ThreadSelector."""

    def _create_mock_client(self, response_text: str) -> MagicMock:
        """Create a mock Anthropic client that returns the given text."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = response_text
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        return mock_client

    def test_select_no_threads(self) -> None:
        """Selection with no threads returns empty list."""
        mock_client = self._create_mock_client("[]")
        selector = ThreadSelector(mock_client)
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday at 10:00 AM",
            weather=None,
        )
        result = selector.select_threads([], world, current_round=0)
        self.assertEqual(result.selected_ids, [])
        self.assertEqual(result.new_selection_round, 0)

    def test_select_fewer_than_n(self) -> None:
        """When fewer threads than N, all are selected."""
        mock_client = self._create_mock_client("[]")  # Won't be called
        selector = ThreadSelector(mock_client)
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday at 10:00 AM",
            weather=None,
        )
        threads = [Thread.create(f"T{i}", f"Desc{i}", 0, 0) for i in range(2)]
        result = selector.select_threads(threads, world, current_round=5, n=3)
        self.assertEqual(len(result.selected_ids), 2)
        self.assertEqual(result.new_selection_round, 6)

    def test_select_parses_response(self) -> None:
        """Selection parses JSON response correctly."""
        threads = [Thread.create(f"T{i}", f"Desc{i}", 0, 0) for i in range(5)]
        ids = [threads[0].id, threads[2].id, threads[4].id]
        mock_client = self._create_mock_client(f'["{ids[0]}", "{ids[1]}", "{ids[2]}"]')
        selector = ThreadSelector(mock_client)
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday at 10:00 AM",
            weather=None,
        )
        result = selector.select_threads(threads, world, current_round=3, n=3)
        self.assertEqual(result.selected_ids, ids)
        self.assertEqual(result.new_selection_round, 4)

    def test_select_handles_invalid_ids(self) -> None:
        """Selection filters out invalid thread IDs."""
        threads = [Thread.create("T1", "Desc", 0, 0)]
        mock_client = self._create_mock_client(f'["{threads[0].id}", "invalid-id"]')
        selector = ThreadSelector(mock_client)
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday at 10:00 AM",
            weather=None,
        )
        result = selector.select_threads(threads, world, current_round=0)
        self.assertEqual(result.selected_ids, [threads[0].id])

    def test_select_round_unchanged_when_all_ids_invalid(self) -> None:
        """Selection round does not advance when all returned IDs are invalid."""
        # Need more threads than n to trigger LLM call
        threads = [Thread.create(f"T{i}", "Desc", 0, 0) for i in range(5)]
        # Return only invalid IDs
        mock_client = self._create_mock_client('["invalid-1", "invalid-2", "invalid-3"]')
        selector = ThreadSelector(mock_client)
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday",
            weather=None,
        )
        result = selector.select_threads(threads, world, current_round=7, n=3)
        self.assertEqual(result.selected_ids, [])
        self.assertEqual(result.new_selection_round, 7)  # Not incremented

    def test_select_handles_parse_error(self) -> None:
        """Selection handles JSON parse errors gracefully."""
        mock_client = self._create_mock_client("not valid json")
        selector = ThreadSelector(mock_client)
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday",
            weather=None,
        )
        # Need more threads than n (default 3) to trigger LLM call
        threads = [Thread.create(f"T{i}", "Desc", 0, 0) for i in range(5)]
        result = selector.select_threads(threads, world, current_round=5)
        self.assertEqual(result.selected_ids, [])
        self.assertEqual(result.new_selection_round, 5)  # Not incremented

    def test_select_excludes_non_active_threads(self) -> None:
        """Selection only considers threads with status='active'."""
        mock_client = self._create_mock_client("[]")  # Won't be called
        selector = ThreadSelector(mock_client)
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday",
            weather=None,
        )

        # Create 5 threads with different statuses
        threads = []
        for i, status in enumerate(["active", "in_scene", "paused", "resolved", "active"]):
            t = Thread.create(f"T{i}", "Desc", 0, 0, status=status)  # type: ignore[arg-type]
            threads.append(t)

        result = selector.select_threads(threads, world, current_round=0, n=3)

        # Should only select from active threads (T0 and T4)
        self.assertEqual(len(result.selected_ids), 2)
        self.assertIn(threads[0].id, result.selected_ids)
        self.assertIn(threads[4].id, result.selected_ids)
        self.assertNotIn(threads[1].id, result.selected_ids)  # in_scene
        self.assertNotIn(threads[2].id, result.selected_ids)  # paused
        self.assertNotIn(threads[3].id, result.selected_ids)  # resolved

    def test_select_empty_when_no_active_threads(self) -> None:
        """Selection returns empty when all threads are non-active."""
        mock_client = self._create_mock_client("[]")
        selector = ThreadSelector(mock_client)
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday",
            weather=None,
        )

        # All threads are non-active
        threads = [
            Thread.create("T1", "Desc", 0, 0, status="in_scene"),
            Thread.create("T2", "Desc", 0, 0, status="resolved"),
            Thread.create("T3", "Desc", 0, 0, status="paused"),
        ]

        result = selector.select_threads(threads, world, current_round=5, n=3)
        self.assertEqual(result.selected_ids, [])
        self.assertEqual(result.new_selection_round, 5)  # Not incremented


class TestThreadSimulator(unittest.TestCase):
    """Tests for ThreadSimulator."""

    def _create_mock_client(self, response_text: str) -> MagicMock:
        """Create a mock Anthropic client."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = response_text
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        return mock_client

    def test_simulate_basic(self) -> None:
        """Basic thread simulation produces valid result."""
        response_json = """{
            "events": "The detective followed the suspect to a cafe.",
            "new_summary": "Detective is observing suspect at cafe",
            "new_history_entry": "Followed suspect to cafe",
            "new_location": null
        }"""
        mock_client = self._create_mock_client(response_json)
        simulator = ThreadSimulator(mock_client)

        thread = Thread.create("Detective", "Following John", 0, 0)
        world = WorldContext(
            player_location=Location(city="SF", region="CA", country="US"),
            game_time_minutes=60,
            game_time_display="Monday at 11:00 AM",
            weather="Sunny",
        )

        result = simulator.simulate_thread(thread, time_delta=30, world_context=world)

        self.assertEqual(result.thread_id, thread.id)
        self.assertEqual(result.thread_name, "Detective")
        self.assertEqual(result.base_revision, 0)
        self.assertIn("detective", result.events.lower())
        self.assertEqual(result.new_summary, "Detective is observing suspect at cafe")
        self.assertEqual(result.new_history_entry, "Followed suspect to cafe")
        self.assertIsNone(result.new_location)
        self.assertEqual(result.advanced_to, 60)

    def test_simulate_with_location_change(self) -> None:
        """Simulation can update thread location."""
        response_json = """{
            "events": "Moved to new area",
            "new_summary": "Now in downtown",
            "new_history_entry": "Moved downtown",
            "new_location": {"city": "SF", "region": "CA", "country": "US", "address": "Downtown"}
        }"""
        mock_client = self._create_mock_client(response_json)
        simulator = ThreadSimulator(mock_client)

        thread = Thread.create("Agent", "Moving around", 0, 0)
        world = WorldContext(
            player_location=Location(city="SF", region="CA", country="US"),
            game_time_minutes=100,
            game_time_display="Monday",
            weather=None,
        )

        result = simulator.simulate_thread(thread, time_delta=60, world_context=world)

        self.assertIsNotNone(result.new_location)
        self.assertEqual(result.new_location.address, "Downtown")  # type: ignore[union-attr]

    def test_simulate_handles_parse_error(self) -> None:
        """Simulation handles JSON errors gracefully."""
        mock_client = self._create_mock_client("not json")
        simulator = ThreadSimulator(mock_client)

        thread = Thread.create("Test", "Desc", 0, 0)
        thread.summary = "Original summary"
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=50,
            game_time_display="Monday",
            weather=None,
        )

        result = simulator.simulate_thread(thread, time_delta=30, world_context=world)

        self.assertIn("error", result.events.lower())
        self.assertEqual(result.new_summary, "Original summary")  # Preserved


class TestHistoryCondensation(unittest.TestCase):
    """Tests for condense_thread_history."""

    def test_no_condensation_under_threshold(self) -> None:
        """History with <= 20 entries is not modified."""
        mock_client = MagicMock()
        thread = Thread.create("Test", "Desc", 0, 0)
        thread.history = [f"Event {i}" for i in range(20)]

        condense_thread_history(thread, mock_client)

        self.assertEqual(len(thread.history), 20)
        mock_client.messages.create.assert_not_called()

    def test_condensation_over_threshold(self) -> None:
        """History with > 20 entries condenses first 10."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Summary of early events"
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        thread = Thread.create("Test", "Desc", 0, 0)
        thread.history = [f"Event {i}" for i in range(25)]

        condense_thread_history(thread, mock_client)

        # Should have 1 (summary) + 15 (kept) = 16 entries
        self.assertEqual(len(thread.history), 16)
        self.assertIn("[Earlier:", thread.history[0])
        self.assertEqual(thread.history[1], "Event 10")
        self.assertEqual(thread.history[-1], "Event 24")


class TestArchiving(unittest.TestCase):
    """Tests for archive_dormant_threads."""

    def test_no_archiving_under_threshold(self) -> None:
        """No archiving when thread count <= 50."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        for i in range(50):
            state.threads.append(Thread.create(f"T{i}", "Desc", 0, 0))

        archive_dormant_threads(state)

        self.assertEqual(len(state.threads), 50)
        self.assertEqual(len(state.archived_threads), 0)

    def test_archiving_over_threshold(self) -> None:
        """Archives dormant threads when count > 50."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        state.thread_selection_round = 20

        # Create 55 threads - some active, some dormant
        for i in range(55):
            thread = Thread.create(f"T{i}", "Desc", i, 0)
            # Threads 0-9 are dormant (not selected in 15 rounds)
            if i < 10:
                thread.last_selected_round = 5
            else:
                thread.last_selected_round = 15  # Active
            state.threads.append(thread)

        archive_dormant_threads(state)

        # Should archive 5 threads to get to 50
        self.assertEqual(len(state.threads), 50)
        self.assertEqual(len(state.archived_threads), 5)

    def test_archiving_prefers_oldest_dormant(self) -> None:
        """Archiving removes oldest dormant threads first."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        state.thread_selection_round = 20

        # Create 52 dormant threads with varying last_advanced_at
        for i in range(52):
            thread = Thread.create(f"T{i}", "Desc", 0, 0)
            thread.last_selected_round = 5  # All dormant
            thread.last_advanced_at = i * 10  # Older threads have lower values
            state.threads.append(thread)

        archive_dormant_threads(state)

        # Should archive 2 oldest (T0 and T1)
        self.assertEqual(len(state.archived_threads), 2)
        archived_names = [t.name for t in state.archived_threads]
        self.assertIn("T0", archived_names)
        self.assertIn("T1", archived_names)


class TestRunThreadSimulation(unittest.TestCase):
    """Tests for run_thread_simulation orchestration."""

    def test_no_threads_returns_empty(self) -> None:
        """Empty thread list returns empty results."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        mock_client = MagicMock()
        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday",
            weather=None,
        )

        output = run_thread_simulation(
            state, time_delta=30, world_context=world, client=mock_client
        )

        self.assertEqual(output.results, [])
        self.assertEqual(output.selection_result.selected_ids, [])

    def test_simulation_runs_for_selected_threads(self) -> None:
        """Simulation runs for selected threads."""
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        threads = [Thread.create(f"T{i}", f"Desc{i}", 0, 0) for i in range(2)]
        state.threads = threads

        # Mock client that returns selection, then simulation results
        mock_client = MagicMock()
        call_count = [0]

        def mock_create(**kwargs: object) -> MagicMock:
            call_count[0] += 1
            mock_response = MagicMock()
            mock_content = MagicMock()
            mock_content.type = "text"

            if call_count[0] == 1:  # Selection call
                mock_content.text = f'["{threads[0].id}", "{threads[1].id}"]'
            else:  # Simulation calls
                mock_content.text = """{
                    "events": "Something happened",
                    "new_summary": "Updated",
                    "new_history_entry": "Entry",
                    "new_location": null
                }"""

            mock_response.content = [mock_content]
            return mock_response

        mock_client.messages.create.side_effect = mock_create

        world = WorldContext(
            player_location=Location(city="X", region="Y", country="Z"),
            game_time_minutes=100,
            game_time_display="Monday",
            weather=None,
        )

        output = run_thread_simulation(
            state, time_delta=30, world_context=world, client=mock_client
        )

        self.assertEqual(len(output.results), 2)
        self.assertEqual(output.selection_result.new_selection_round, 1)


class TestSimulationStateManagement(unittest.TestCase):
    """Tests for background simulation state management."""

    def setUp(self) -> None:
        """Reset simulation state before each test."""
        # Import here to avoid circular imports
        from rwta import main

        self.main = main
        main.reset_simulation_state()

    def tearDown(self) -> None:
        """Clean up simulation state after each test."""
        self.main.reset_simulation_state()

    def test_reset_clears_all_state(self) -> None:
        """reset_simulation_state() clears all simulation globals."""
        # Set up dirty state
        with self.main._simulation_lock:
            self.main._simulation_running = True
            self.main._queued_time_delta = 100

        # Add something to the queue
        from rwta.threads import SelectionResult, SimulationOutput

        output = SimulationOutput(
            results=[],
            selection_result=SelectionResult(selected_ids=[], new_selection_round=5),
        )
        self.main._simulation_queue.put(output)

        # Reset
        self.main.reset_simulation_state()

        # Verify all cleared
        with self.main._simulation_lock:
            self.assertFalse(self.main._simulation_running)
            self.assertEqual(self.main._queued_time_delta, 0)

        # Queue should be empty
        self.assertTrue(self.main._simulation_queue.empty())

    def test_time_delta_preserved_on_simulation_failure(self) -> None:
        """time_delta is restored to queue on simulation failure."""
        from unittest.mock import MagicMock

        from anthropic import APIError

        # Create a state with more threads than n (default 3) to trigger API selection
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        for i in range(5):
            state.threads.append(Thread.create(f"T{i}", "Desc", 0, 0))

        # Create a mock client that raises an error on the selection call
        # (first API call when there are > n threads)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = APIError(
            message="API Error",
            request=MagicMock(),
            body=None,
        )

        # Start simulation (this will fail during selection)
        self.main.start_background_simulation(state, time_delta=60, client=mock_client)

        # Wait for background thread to finish (should be quick since it errors)
        import time

        timeout = 2.0
        start = time.time()
        while True:
            with self.main._simulation_lock:
                if not self.main._simulation_running:
                    break
            if time.time() - start > timeout:
                self.fail("Simulation didn't complete within timeout")
            time.sleep(0.1)

        # The time_delta should be restored to the queue
        with self.main._simulation_lock:
            self.assertEqual(self.main._queued_time_delta, 60)

    def test_successful_simulation_does_not_restore_delta(self) -> None:
        """time_delta is not restored when simulation succeeds."""
        from unittest.mock import MagicMock

        # Create a minimal state with threads
        state = GameState(
            starting_location=Location(city="X", region="Y", country="Z"),
        )
        thread = Thread.create("T1", "Desc", 0, 0)
        state.threads = [thread]

        # Create a mock client that succeeds
        mock_client = MagicMock()

        def mock_create(**kwargs: object) -> MagicMock:
            mock_response = MagicMock()
            mock_content = MagicMock()
            mock_content.type = "text"
            # First call is selection, second is simulation
            if "Select" in str(kwargs.get("messages", "")):
                mock_content.text = f'["{thread.id}"]'
            else:
                mock_content.text = """{
                    "events": "Something",
                    "new_summary": "Summary",
                    "new_history_entry": "Entry",
                    "new_location": null
                }"""
            mock_response.content = [mock_content]
            return mock_response

        mock_client.messages.create.side_effect = mock_create

        # Start simulation
        self.main.start_background_simulation(state, time_delta=60, client=mock_client)

        # Wait for background thread to finish
        import time

        timeout = 2.0
        start = time.time()
        while True:
            with self.main._simulation_lock:
                if not self.main._simulation_running:
                    break
            if time.time() - start > timeout:
                self.fail("Simulation didn't complete within timeout")
            time.sleep(0.1)

        # time_delta should NOT be restored (success case)
        with self.main._simulation_lock:
            self.assertEqual(self.main._queued_time_delta, 0)

        # But there should be a result in the queue
        self.assertFalse(self.main._simulation_queue.empty())


if __name__ == "__main__":
    unittest.main()
