# Threads Feature Implementation Plan

## Overview

Add parallel "threads" - side characters, machines, or mechanisms that operate independently of the player. When time advances, an LLM selects the top 3 most relevant threads to simulate, keeping the world alive while staying efficient.

## Core Data Structures

### New: `Thread` dataclass (in `state.py`)

```python
@dataclass
class Thread:
    id: str                    # UUID
    name: str                  # "Detective hired to follow John"
    description: str           # Initial goal/purpose
    location: Location | None  # Current location (if physical)
    summary: str               # Short summary for selector (~100 words)
    history: list[str]         # List of event summaries (not full messages)
    created_at: int            # Game-time minutes since game start
    last_advanced_at: int      # Game-time minutes since game start (for staleness calc)
    last_selected_round: int   # Selection round marker for archiving
    revision: int              # Increment on any thread edits (conflict detection)
```

### Time Representation

Game time is stored in one form:
- `game_time: str` (ISO format) - for display and weather API calls
- Derived: `game_time_minutes` computed on demand for thread math (not persisted)

**Conversion helpers in state.py:**
```python
def get_game_time_minutes(self) -> int:
    """Get minutes elapsed since game start."""
    start = datetime.fromisoformat(self.created_at)
    current = datetime.fromisoformat(self.game_time)
    return int((current - start).total_seconds() // 60)

def minutes_to_game_time(self, minutes: int) -> datetime:
    """Convert minutes-since-start to datetime."""
    start = datetime.fromisoformat(self.created_at)
    return start + timedelta(minutes=minutes)
```

This uses `created_at` as epoch (game start time). Thread timestamps are relative to this.
Minutes-since-start should be derived via helpers to avoid drift between stored and computed time.

### GameState additions

```python
@dataclass
class GameState:
    # ... existing fields ...
    threads: list[Thread] = field(default_factory=list)
    archived_threads: list[Thread] = field(default_factory=list)
    pending_thread_results: list[ThreadResult] | None = None
    thread_selection_round: int = 0
```

## Architecture

### Flow on Each Turn

```
1. Player input
2. Apply any pending thread results from previous turn and stage them for the prompt (clear after prompt assembly)
3. Narrator generates response
   - System prompt includes thread summaries + staged pending thread results
   - May call spawn_thread tool (creates new Thread)
   - May call advance_time tool
4. Response printed to player
5. IF time advanced >= 30 minutes AND threads exist:
   - Kick off background thread simulation (async)
   - Does NOT block user input
6. State saved with updated threads
7. While user reads/types, background simulation completes:
   a. Thread Selector (Sonnet) picks top 3 threads
   b. Thread Simulators (Sonnet, parallel) advance selected threads
   c. Results queued for merge on main thread
8. Next turn, queued results applied before narrator prompt, then cleared and saved
```

### Key: Background Processing

Thread simulation runs AFTER the narrator responds, in parallel with user reading/typing.
This means thread events are incorporated in the NEXT turn's response, not the current one.
This is acceptable since threads are background processes - a 1-turn delay is natural.
All thread updates are merged on the main thread to avoid concurrent state mutation.


### New Tools

**`spawn_thread`** (called by narrator)
- Input: `name`, `description`, `location` (optional)
- Creates new Thread with initial summary = description
- Returns confirmation message
- Initializes `last_selected_round` to current `thread_selection_round`

### Communication: Time Advancement → Background Simulation

The `generate_response()` method needs to return how much time advanced so main.py can decide whether to trigger background simulation. Options:
1. Return tuple `(response_text, time_advanced_minutes)` from `generate_response()`
2. Track cumulative time advancement in GameState per turn
3. Compare game_time before/after response generation

**Recommended**: Option 1 - modify return signature to include time advanced.

Time math uses integer minutes derived from `game_time` via helpers to avoid timezone issues.
If multiple `advance_time` tool calls occur in one narrator pass, their deltas are accumulated before deciding whether to trigger background simulation.

### New Modules

**`threads.py`** - Thread management

```python
@dataclass
class WorldContext:
    """Context about the world state for thread simulation."""
    player_location: Location
    game_time_minutes: int      # Current game time (minutes since start, derived)
    game_time_display: str      # Human-readable time for prompts
    weather: str | None         # Current weather description (optional)

@dataclass
class SelectionResult:
    """Result from thread selection (no state mutation)."""
    selected_ids: list[str]     # IDs of threads to advance
    new_selection_round: int    # current_round + 1 on success, current_round on failure
```

- `ThreadSelector` class (uses Sonnet)
  - `select_threads(threads, world_context, current_round, n=3) -> SelectionResult`
  - Input: All thread summaries, world context, current selection round
  - Output: SelectionResult (selected IDs + computed round number)
  - **Does NOT mutate state** - returns data for main thread to apply
  - Model returns IDs only; wrapper computes `new_selection_round`

- `ThreadSimulator` class (uses Sonnet)
  - `simulate_thread(thread, time_delta, world_context) -> ThreadResult`
  - Input: Thread snapshot, time delta in minutes, world context
  - Output: ThreadResult with events, new_summary, new_history_entry, new_location, advanced_to

## Key Design Decisions

### 1. Thread Selector Prompt Strategy

The selector sees a compact view of all threads:
```
Thread ID: abc123
Name: Detective following John
Location: Downtown cafe
Last advanced: 120 minutes ago
Summary: Followed John to his apartment. Waiting outside.
Staleness score: HIGH

Thread ID: def456
Name: Pizza oven preheating
Location: Player's kitchen
Last advanced: 10 minutes ago
Summary: Oven reaching temperature. At 350°F, needs 400°F.
Staleness score: LOW
```

Selector considers:
- Staleness (time since last advanced)
- Location proximity to player
- Activity level (some threads are "waiting", others are "active")
- Story relevance

### 2. Thread Summarization

After each simulation, the thread's summary is regenerated:
- Old summary + what happened → new summary (~100 words)
- History list gets `new_history_entry` appended (for long-term recall)
- History entries are short (~1 sentence each)

**History Condensation** (in `threads.py`):
```python
def condense_thread_history(thread: Thread, client: Anthropic) -> None:
    """Condense old history entries if history exceeds 20 entries.

    Called during result application in main.py.
    Summarizes entries 0-9 into a single entry, keeping entries 10+ intact.
    """
    if len(thread.history) <= 20:
        return

    old_entries = thread.history[:10]
    # Use Sonnet to summarize old entries into 2-3 sentences
    summary = _summarize_history_entries(old_entries, client)
    thread.history = [f"[Earlier: {summary}]"] + thread.history[10:]
```

This keeps history bounded while preserving key events.

### 3. Narrator Awareness

Narrator's system prompt includes:
- Count of active threads
- Brief list of thread names/locations (for consistency)
- NOT full thread details (context efficiency)

When threads are simulated, narrator receives:
- Summary of what happened to each advanced thread
- Narrator decides if any events are visible to player

### 4. Intersection Detection & Narrator Authority

The narrator decides what the player perceives based on:
- Location overlap (thread and player in same place)
- Sensory proximity (sounds, visible events)
- Communication (thread sends message to player)

This is handled in the narrator's response generation, not as a separate system.

**Critical: Narrator has final authority over thread events.**
- Thread simulation outputs are *suggestions*, not mandates
- If a thread result doesn't make sense in the world context, the narrator can ignore it
- The narrator should never force unrealistic or inconsistent events into the story
- The primary goal is building a realistic, coherent world for the player
- Threads exist to create agency and events that evolve independently of the player, enriching the world - not to override narrative coherence

The system prompt should instruct the narrator:
```
Thread updates are provided as context about what may have happened in the background.
You may incorporate these events if they fit naturally into the world, or ignore them
if they conflict with established facts or would break immersion. Your primary duty
is to the player's experience of a coherent, realistic world.
```

### 5. Spawn Triggers

Threads spawn via:
- Narrator tool call (player hires someone, starts a process)
- Narrator autonomously (NPC leaves scene with their own agenda)

The narrator prompt will include guidance on when to spawn threads.

## Files to Modify

1. **`state.py`**
   - Add `Thread`, `ThreadResult` dataclasses
   - Add fields to `GameState`: `threads`, `archived_threads`, `pending_thread_results`, `thread_selection_round`
   - Add time conversion helpers: `get_game_time_minutes()`, `minutes_to_game_time()`
   - Update `to_dict` / `from_dict` for serialization
   - Add version migration (v2 → v3)

2. **`tools.py`**
   - Add `spawn_thread` tool definition and handler

3. **`llm.py`**
   - Update system prompt to include thread awareness and guidance
   - Add `spawn_thread` to tools list
   - Update `_handle_tool_use()` to process spawn_thread
   - Modify `generate_response()` to return time advanced

4. **`threads.py`** (NEW)
   - `WorldContext`, `SelectionResult`, `SimulationOutput` dataclasses
   - `ThreadSelector` class
   - `ThreadSimulator` class
   - `run_thread_simulation()` orchestration function
   - `condense_thread_history()` helper
   - `archive_dormant_threads()` helper

5. **`main.py`**
   - Background simulation with single-flight guard and coalescing
   - Result application with conflict detection
   - Add `/threads` command to list active and archived threads

## Efficiency Considerations

- Selector call: ~500 tokens input, ~50 tokens output (cheap)
- Simulator calls: ~1000 tokens input, ~200 tokens output × 3 threads
- Total per time advance: ~4 Sonnet calls (~$0.01-0.02)
- Only runs when time advances >= 30 minutes AND threads exist
- Runs in background, doesn't block user interaction

## Decided Design Parameters

1. **Parallel simulation**: YES - run 3 thread simulations in parallel for speed
2. **Time threshold**: 30 minutes minimum before triggering thread simulation
3. **Thread cap**: 50 threads max - archive oldest dormant threads when exceeded
4. **Player visibility**: `/threads` command to list all threads and summaries
5. **Background processing**: Thread simulation runs async after narrator responds

## Thread Archiving (when >50 threads)

When thread count exceeds 50:
1. Sort threads by `last_advanced_at` (oldest first)
2. Identify threads not selected in the last 10 selection rounds (`thread_selection_round - last_selected_round >= 10`)
3. Archive oldest dormant threads to `archived_threads` list
4. Archived threads removed from selector consideration
5. Archived threads still visible in `/threads` output (marked as archived)

```python
@dataclass
class GameState:
    # ... existing fields ...
    threads: list[Thread] = field(default_factory=list)
    archived_threads: list[Thread] = field(default_factory=list)
    pending_thread_results: list[ThreadResult] | None = None

@dataclass
class ThreadResult:
    thread_id: str
    thread_name: str
    base_revision: int        # Thread revision from snapshot
    events: str               # Detailed narrative of what happened (for narrator context)
    new_summary: str          # Updated summary (~100 words, replaces thread.summary)
    new_history_entry: str    # One-sentence summary to append to thread.history
    new_location: Location | None  # If thread moved (None = no change)
    simulated_from: int       # Snapshot game-time minutes
    advanced_to: int          # Game-time minutes after simulation

@dataclass
class SimulationOutput:
    """Complete output from background thread simulation."""
    results: list[ThreadResult]      # Results for each simulated thread
    selection_result: SelectionResult  # Selection metadata to apply
```

## Implementation Order

### Phase 1: Data Structures (state.py)
1. Add `Thread` dataclass
2. Add `ThreadResult` dataclass (used for pending results in GameState)
3. Add fields to `GameState`: `threads`, `archived_threads`, `pending_thread_results`, `thread_selection_round`
4. Add time conversion helpers: `get_game_time_minutes()`, `minutes_to_game_time()`
5. Update `to_dict()` / `from_dict()` for serialization (handle Location | None, list of threads)
6. Bump version to 3, add migration from v2

### Phase 2: Thread Engine (threads.py - NEW FILE)
1. `WorldContext`, `SelectionResult`, `SimulationOutput` dataclasses

2. `ThreadSelector` class
   - `select_threads(threads, world_context, current_round, n=3) -> SelectionResult`
   - Uses Sonnet to pick most relevant threads
   - Considers staleness, location, activity
   - Returns `SelectionResult` with selected IDs and computed round number
   - **Does NOT mutate state** - main thread applies changes

3. `ThreadSimulator` class
   - `simulate_thread(thread, time_delta, world_context) -> ThreadResult`
   - Uses Sonnet to advance single thread
   - Generates events, new_summary, new_history_entry, new_location, advanced_to

4. `run_thread_simulation(state_snapshot, time_delta, world_context) -> SimulationOutput`
   - Takes immutable snapshot, returns all data needed to update state
   - Returns `SimulationOutput` containing:
     - `results: list[ThreadResult]`
     - `selection_result: SelectionResult`
   - Orchestrates selection + parallel simulation
   - Stamps results with `simulated_from`, `advanced_to`, and `base_revision`
   - If selector fails, return `SelectionResult(selected_ids=[], new_selection_round=current_round)` and no simulations
   - Handles simulator errors by skipping failed threads and returning partial results

5. `condense_thread_history(thread, client)` - Summarize old history entries when >20

6. `archive_dormant_threads(state)` - Move threads to archived when >50 total

### Phase 3: Tool Updates (tools.py)
1. Add `SPAWN_THREAD_TOOL` definition
2. Add `spawn_thread()` function
3. Update `execute_tool()` to handle spawn_thread

### Phase 4: Narrator Integration (llm.py)
1. Update `get_system_prompt()` to include:
   - Thread count and brief list of thread names/locations
   - Pending thread results (if any) for narrative context
   - Guidance on when to spawn threads
2. Add `spawn_thread` to tools list
3. Update `_handle_tool_use()` to process spawn_thread results
4. Clear `pending_thread_results` after they are included in a prompt

### Phase 5: Background Processing (main.py)

**Module-level state:**
```python
_simulation_lock = threading.Lock()
_simulation_running = False
_simulation_queue: queue.Queue[SimulationOutput] = queue.Queue()
_queued_time_delta: int = 0  # Accumulated time to simulate next
```

**After each turn** (if time advanced >= 30min AND threads exist):
1. Acquire `_simulation_lock`
2. If `_simulation_running`:
   - Add time_delta to `_queued_time_delta` (coalesce)
   - Release lock and continue
3. Otherwise:
   - Set `_simulation_running = True`
   - Create state snapshot and WorldContext
   - Release lock
   - Kick off `run_thread_simulation` in background thread
   - Background thread puts `SimulationOutput` in `_simulation_queue` when done
   - On failure: log error, reset `_simulation_running` in `finally`, keep `_queued_time_delta` for retry

**At the start of each turn** (main thread):
1. Drain `_simulation_queue` (non-blocking)
2. For each `SimulationOutput`:
   - Apply `selection_result`: update `thread_selection_round`, update `last_selected_round` on selected threads
   - For each `ThreadResult`:
     - Find thread by `thread_id` (skip if not found/archived)
     - Skip if `thread.revision != result.base_revision` (edited during simulation)
     - Skip if `thread.last_advanced_at > result.simulated_from` (already advanced)
     - Apply: `thread.summary = result.new_summary`
     - Apply: `thread.history.append(result.new_history_entry)`
     - Apply: `thread.location = result.new_location` (if not None)
     - Apply: `thread.last_advanced_at = result.advanced_to`
     - Bump: `thread.revision += 1`
     - Call `condense_thread_history(thread, client)` if needed
   - Call `archive_dormant_threads(state)` if >50 threads
   - Set `state.pending_thread_results = [applied results]` (for narrator)
3. Check if `_queued_time_delta > 0`:
   - If so, start new simulation with queued delta, reset `_queued_time_delta = 0`
4. Save state

**Coalescing Semantics:**
- If simulation is running when new time advances, accumulate delta
- When simulation completes, apply its results normally
- Then immediately start new simulation with accumulated delta (if any)
- This avoids wasting work while keeping threads reasonably up-to-date

**On clean shutdown:**
1. Wait for running simulation to complete (with timeout)
2. Drain queue and apply any remaining results
3. Save state

**Commands:**
- Add `/threads` command to COMMANDS list
- Add `handle_threads()` function to display active + archived threads

## Serialization Notes

**Thread.location** (Location | None):
```python
# In Thread.to_dict():
"location": asdict(self.location) if self.location else None

# In Thread.from_dict():
location = Location(**data["location"]) if data.get("location") else None
```

**ThreadResult.new_location** - Same pattern as above.

**pending_thread_results** (list[ThreadResult] | None):
- Serialize as list of dicts when not None
- Deserialize back to ThreadResult objects
- Handle None case explicitly

**Version Migration (v2 → v3):**
```python
def _migrate_v2_to_v3(data: dict) -> dict:
    """Add thread-related fields with defaults."""
    data["threads"] = []
    data["archived_threads"] = []
    data["pending_thread_results"] = None
    data["thread_selection_round"] = 0
    data["version"] = 3
    return data
```

## Testing Notes

**tests/test_threads.py** should cover:

1. **Thread Selection**
   - Selector picks stalest threads
   - Selector considers location proximity
   - Returns correct SelectionResult structure

2. **Thread Simulation**
   - Simulator generates valid ThreadResult
   - Handles thread with no location
   - Handles thread that moves location

3. **Conflict Detection**
   - Result skipped when `revision` mismatch
   - Result skipped when `last_advanced_at > simulated_from`
   - Result skipped when thread archived during simulation

4. **History Condensation**
   - No-op when history <= 20 entries
   - Condenses first 10 entries (indices 0-9) into single entry when > 20

5. **Archiving**
   - Threads archived when count > 50
   - Only dormant threads (not selected in 10 rounds) archived
   - Archived threads not selected

6. **Coalescing**
   - Time delta accumulated when simulation running
   - New simulation started with accumulated delta after completion

## File Changes Summary

| File | Changes |
|------|---------|
| `src/rwta/state.py` | Add Thread, ThreadResult dataclasses; update GameState with thread fields; add time conversion helpers; serialization |
| `src/rwta/threads.py` | NEW: WorldContext, SelectionResult, SimulationOutput dataclasses; ThreadSelector, ThreadSimulator classes; run_thread_simulation, condense_thread_history, archive_dormant_threads functions |
| `src/rwta/tools.py` | Add spawn_thread tool definition and handler |
| `src/rwta/llm.py` | Update system prompt with thread awareness; add spawn_thread tool; return time_advanced from generate_response |
| `src/rwta/main.py` | Background simulation with single-flight guard, coalescing, conflict resolution; result application; /threads command |
| `tests/test_threads.py` | NEW: Tests for selection, simulation, conflicts, history condensation, archiving, coalescing |
