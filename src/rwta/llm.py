"""Claude API integration for generating game responses."""

import os
import time
from collections.abc import Callable

from anthropic import Anthropic
from anthropic.types import ContentBlock, Message, TextBlock, ToolUseBlock

from rwta.location import Location, Weather, get_weather
from rwta.state import GameState, Thread
from rwta.tools import execute_tool, get_tools

# Weather cache: stores (location_key, timestamp, weather) tuples
_weather_cache: dict[str, tuple[float, Weather | None]] = {}
WEATHER_CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_location_cache_key(location: Location) -> str:
    """Generate a cache key for a location based on coordinates or city."""
    if location.latitude is not None and location.longitude is not None:
        # Round to 2 decimal places (~1km precision)
        return f"{location.latitude:.2f},{location.longitude:.2f}"
    return f"{location.city},{location.country}".lower()


def get_cached_weather(location: Location) -> Weather | None:
    """Get weather for a location, using cache if available and fresh."""
    cache_key = _get_location_cache_key(location)
    now = time.time()

    # Check cache
    if cache_key in _weather_cache:
        cached_time, cached_weather = _weather_cache[cache_key]
        if now - cached_time < WEATHER_CACHE_TTL_SECONDS:
            return cached_weather

    # Fetch fresh weather
    weather = get_weather(location)

    # Store in cache
    _weather_cache[cache_key] = (now, weather)

    return weather


def _format_threads_for_prompt(threads: list[Thread], game_time_minutes: int) -> str:
    """Format thread list for system prompt (brief overview)."""
    if not threads:
        return ""

    thread_summaries = []
    for t in threads:
        location_str = ""
        if t.location:
            location_str = f" at {t.location.city or t.location.address or 'unknown location'}"
        staleness = game_time_minutes - t.last_advanced_at
        status_note = f" [{t.status}]" if t.status != "active" else ""
        thread_summaries.append(
            f"- ID: {t.id[:8]}... | {t.name}{location_str} ({staleness} min since update){status_note}"
        )

    return "\n".join(thread_summaries)


def get_system_prompt(state: GameState, pending_thread_events: str | None = None) -> str:
    """
    Generate the system prompt for the game.

    Args:
        state: Current game state.
        pending_thread_events: Optional formatted string of recent thread events.

    Returns:
        System prompt string.
    """
    location = state.get_current_location()
    game_time = state.get_formatted_game_time()
    game_time_minutes = state.get_game_time_minutes()

    # Fetch current weather (with caching)
    weather = get_cached_weather(location)
    weather_str = str(weather) if weather else "Weather unknown"

    # Build thread awareness section
    threads_section = ""
    if state.threads:
        thread_list = _format_threads_for_prompt(state.threads, game_time_minutes)
        threads_section = f"""
## Active Threads ({len(state.threads)} parallel storylines)
These are events/characters operating independently in the background:
{thread_list}

"""

    # Build pending thread events section
    thread_events_section = ""
    if pending_thread_events:
        thread_events_section = f"""
## Recent Thread Updates
The following happened in the background while time passed:
{pending_thread_events}

Thread updates are provided as context about what may have happened in the background.
You may incorporate these events if they fit naturally into the world, or ignore them
if they conflict with established facts or would break immersion. Your primary duty
is to the player's experience of a coherent, realistic world.

"""

    return f"""You are the narrator of a text adventure game set in the REAL WORLD. The player exists in the actual, present-day world and can explore real locations, interact with real businesses, and encounter real-world events.

## Setting
- The player is currently in: {location}
- Current in-game date and time: {game_time}
- Current weather: {weather_str}
{threads_section}{thread_events_section}## Your Role
You are an immersive narrator who describes the world around the player. You should:
1. Describe real locations, streets, landmarks, and businesses accurately
2. Use the search_web tool sparingly - only 1-2 searches when truly needed for specific facts you don't know
3. Use the advance_time tool whenever the player performs actions that take time (walking, eating, waiting, etc.)
4. Use the update_location tool when the player moves to a significantly different place (new neighborhood, city, or country)
5. Use the spawn_thread tool when an NPC departs with their own agenda or the player starts a process that runs independently
6. Use the update_thread tool when narrating events that affect an existing thread (see Thread Updates section)
7. React to the current time of day (morning, afternoon, evening, night) with appropriate descriptions
8. Keep track of where the player is and what they're doing
9. Make the world feel alive with realistic details, weather, people, traffic, etc.

## Location Tracking
Use the update_location tool when the player:
- Arrives at a new neighborhood or district within a city
- Travels to a different city (by car, bus, train, plane, etc.)
- Crosses into a different country
- Arrives at a significant landmark that defines their location

Do NOT call update_location for minor movements (walking down the street, entering a building in the same area).
When calling update_location, provide the most specific address/landmark you can for the "address" field.

## Thread Spawning (Parallel Storylines)
Use the spawn_thread tool to create independent background storylines when:
- The player hires someone or dispatches an agent (detective, delivery person, etc.)
- An NPC leaves the scene with a specific activity that has a duration or goal
- The player starts a process that runs independently (cooking, machine running, timer)
- An event is set in motion that will unfold over time

Examples of when to spawn threads:
- Someone going for a run, walk, or exercise routine
- A delivery driver continuing their route
- Someone heading to a meeting or appointment
- An NPC investigating or searching for something
- Food being prepared or delivered
- A machine running (laundry, oven timer, charging device)
- An ongoing event (concert, game, protest, construction work)
- Weather or natural events unfolding (storm approaching, tide coming in)

Threads evolve independently when time passes and may intersect with the player later.
Do not spawn threads for NPCs who simply walk away without a clear ongoing activity.
Do not spawn duplicate threads - if a thread already exists for something, use update_thread instead.

## Thread Updates
Call update_thread when you narrate something that changes a thread's state:

1. Thread intersects player: When a thread's subject returns or appears in the scene
   - Example: "Your cat scratches at the door" → update_thread with status="in_scene"

2. Thread resolves: When a thread completes its goal or reaches an endpoint
   - Example: "The pizza arrives" → update_thread with status="resolved"
   - Example: "The detective calls with findings" → update_thread with status="resolved"

3. Thread pauses: When the player asks something to wait or stop temporarily
   - Example: "Tell the cat to stay here" → update_thread with status="paused"

4. Thread returns to background: After an in_scene thread leaves again
   - Example: "The cat heads back outside" → update_thread with status="active"

This keeps thread state synchronized with your narrative. Without it, a thread continues running in the background even after you've described it interacting with or returning to the player.

## Search Tool Guidelines
- Do NOT search for every detail. Use your knowledge of the world for general descriptions.
- Only search when you need SPECIFIC current facts: exact business names at a location, current news events, specific addresses, etc.
- For the opening scene, at most 1-2 searches to orient yourself to the specific location.
- Prefer fewer, more targeted searches over many broad ones.

## Rules
- Always stay in character as the narrator
- Never break the fourth wall or mention that this is a game
- Be descriptive but concise (2-4 paragraphs typically)
- If the player tries to do something impossible or unrealistic, gently guide them to what is possible
- The player can go anywhere in the real world, but they need to walk, take transportation, etc.
- Use web search to get accurate information about places, current events, and real-world facts
- Always advance time appropriately when the player performs actions:
  - Walking: ~15-20 minutes per mile
  - Taking a bus/subway: varies by route
  - Eating a meal: 30-60 minutes
  - Shopping: 15-30 minutes per store
  - etc.

## Action Granularity
Players must take realistic, step-by-step actions. If a player tries to skip steps or do something too complex in one action, don't execute it. Instead, guide them to break it down:

- WRONG: "Go to Tokyo" -> Respond: "You'll need to first get to an airport, buy a plane ticket (which costs money), go through security, board the flight, etc. Where would you like to start?"
- WRONG: "Rob the bank" -> Respond: "You look at the bank building. What specifically would you like to do? Walk inside? Look around the exterior?"
- WRONG: "Become a millionaire" -> Respond: "That's quite an ambitious goal. What's your first step? Look for job postings? Check out the stock market?"

The player should experience each meaningful step:
- To travel far: need transportation, money, time
- To buy things: need to have money, go to a store, select items
- To meet people: need to go where they are, initiate conversation
- To eat: need to go to a restaurant or store, order/buy food, pay for it

Only execute actions that are immediate and concrete. If an action would take multiple distinct steps, ask the player which step they want to take first.

## Starting the Game
If this is the first message (no conversation history), welcome the player and describe their current location vividly. Use web search if helpful to describe what's actually around them.

Begin!"""


class GameNarrator:
    """Handles LLM interactions for the text adventure."""

    # Pricing per million tokens (as of 2025)
    OPUS_INPUT_PRICE = 15.0
    OPUS_OUTPUT_PRICE = 75.0
    SONNET_INPUT_PRICE = 3.0
    SONNET_OUTPUT_PRICE = 15.0

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize the game narrator.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
            model: Model to use for narration. Defaults to claude-opus-4-5.
        """
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model or "claude-opus-4-5"

        # Token usage tracking
        self.opus_input_tokens = 0
        self.opus_output_tokens = 0
        self.sonnet_input_tokens = 0
        self.sonnet_output_tokens = 0

    def count_tokens(
        self,
        messages: list[dict[str, object]],
        system: str,
    ) -> int:
        """Count tokens for a messages request."""
        response = self.client.messages.count_tokens(
            model=self.model,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        )
        return response.input_tokens

    def _summarize_messages(self, messages: list[dict[str, object]]) -> str:
        """
        Generate a one-sentence summary of key facts from messages.

        Args:
            messages: The messages to summarize.

        Returns:
            A concise summary string.
        """
        # Build a text representation of the messages
        text_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))
            if role == "user":
                text_parts.append(f"Player: {content}")
            else:
                text_parts.append(f"Narrator: {content}")

        conversation_text = "\n".join(text_parts)

        # Truncate if exceeding ~150k tokens worth (Sonnet handles 200k)
        max_chars = 500000
        if len(conversation_text) > max_chars:
            chunk_size = max_chars // 3
            beginning = conversation_text[:chunk_size]
            middle_start = len(conversation_text) // 2 - chunk_size // 2
            middle = conversation_text[middle_start : middle_start + chunk_size]
            end = conversation_text[-chunk_size:]
            conversation_text = f"{beginning}\n\n[...]\n\n{middle}\n\n[...]\n\n{end}"

        prompt = f"""Summarize the key facts from this text adventure conversation in 1-2 sentences.
Focus on: important items obtained, locations visited, people met, and significant events.
Be concise and factual.

{conversation_text}

Summary:"""

        response = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        self._track_sonnet_usage(response)

        return self._extract_text_response(response.content)

    def generate_response(
        self,
        user_input: str,
        state: GameState,
        progress_callback: Callable[[], None] | None = None,
        pending_thread_events: str | None = None,
    ) -> tuple[str, int]:
        """
        Generate a narrative response to the player's input.

        Args:
            user_input: The player's input/action.
            state: Current game state.
            progress_callback: Optional callback to show progress during tool use.
            pending_thread_events: Optional formatted string of recent thread events.

        Returns:
            Tuple of (narrator's response, total minutes time advanced).
        """
        # Add user message to state
        state.add_message("user", user_input)

        # Get system prompt with thread events
        system = get_system_prompt(state, pending_thread_events)

        # Get messages, trimming if needed to fit context
        messages = state.get_messages_for_api(
            token_counter=lambda msgs: self.count_tokens(msgs, system),
            max_tokens=180000,  # Leave room for response
            summarizer=self._summarize_messages,
        )

        # Initial API call
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            tools=get_tools(),  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )
        self._track_opus_usage(response)

        # Handle tool use loop
        final_response, time_advanced = self._handle_tool_use(
            response, messages, system, state, progress_callback, pending_thread_events
        )

        # Add assistant response to state (only if non-empty)
        if final_response.strip():
            state.add_message("assistant", final_response)

        return final_response, time_advanced

    def _handle_tool_use(
        self,
        response: Message,
        messages: list[dict[str, object]],
        system: str,
        state: GameState,
        progress_callback: Callable[[], None] | None = None,
        pending_thread_events: str | None = None,
    ) -> tuple[str, int]:
        """
        Handle tool use in a loop until we get a final text response.

        Args:
            response: Initial API response.
            messages: Conversation messages.
            system: System prompt.
            state: Game state (for time advancement).
            progress_callback: Optional callback to show progress.
            pending_thread_events: Optional thread events for system prompt.

        Returns:
            Tuple of (final text response, total minutes time advanced).
        """
        total_time_advanced = 0

        while response.stop_reason == "tool_use":
            # Find tool use blocks
            tool_uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
            if not tool_uses:
                break

            # Process each tool use
            tool_results: list[dict[str, object]] = []
            for tool_use in tool_uses:
                # Show progress
                if progress_callback:
                    progress_callback()

                # Execute tool
                tool_input = tool_use.input
                if not isinstance(tool_input, dict):
                    tool_input = {}
                result = execute_tool(tool_use.name, tool_input)

                # Handle time advancement
                if result.advance_time_minutes is not None:
                    state.advance_time_minutes(result.advance_time_minutes)
                    total_time_advanced += result.advance_time_minutes

                # Handle location update
                if result.location_update is not None:
                    new_location = Location(
                        city=result.location_update.city,
                        region=result.location_update.region,
                        country=result.location_update.country,
                        address=result.location_update.address,
                        latitude=result.location_update.latitude,
                        longitude=result.location_update.longitude,
                    )
                    state.set_current_location(new_location)

                # Handle thread spawning
                if result.spawn_thread_data is not None:
                    spawn_data = result.spawn_thread_data
                    # Create location if provided
                    thread_location: Location | None = None
                    if spawn_data.has_location():
                        thread_location = Location(
                            city=spawn_data.location_city or "",
                            region=spawn_data.location_region or "",
                            country=spawn_data.location_country or "",
                            address=spawn_data.location_address,
                        )
                    # Create thread
                    new_thread = Thread.create(
                        name=spawn_data.name,
                        description=spawn_data.description,
                        game_time_minutes=state.get_game_time_minutes(),
                        selection_round=state.thread_selection_round,
                        location=thread_location,
                    )
                    state.threads.append(new_thread)

                # Handle thread update
                if result.update_thread_data is not None:
                    update_data = result.update_thread_data
                    # Find the thread by ID
                    for thread in state.threads:
                        if thread.id == update_data.thread_id:
                            # Update thread fields
                            thread.summary = update_data.summary
                            if update_data.status in ("active", "in_scene", "paused", "resolved"):
                                thread.status = update_data.status  # type: ignore[assignment]
                            thread.revision += 1
                            thread.last_advanced_at = state.get_game_time_minutes()

                            # Add history entry if provided
                            if update_data.history_entry:
                                thread.history.append(update_data.history_entry)

                            # Update location if provided
                            if update_data.has_location():
                                thread.location = Location(
                                    city=update_data.location_city or "",
                                    region=update_data.location_region or "",
                                    country=update_data.location_country or "",
                                    address=update_data.location_address,
                                )
                            break

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result.message,
                    }
                )

            # Build new messages with assistant response and tool results
            assistant_content = self._content_blocks_to_list(response.content)
            new_messages = [
                *messages,
                {"role": "assistant", "content": assistant_content},
                {"role": "user", "content": tool_results},
            ]

            # Make next API call with updated system prompt (time may have changed)
            system = get_system_prompt(state, pending_thread_events)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                tools=get_tools(),  # type: ignore[arg-type]
                messages=new_messages,  # type: ignore[arg-type]
            )
            self._track_opus_usage(response)
            messages = new_messages

        # Extract final text response
        return self._extract_text_response(response.content), total_time_advanced

    def _content_blocks_to_list(self, content: list[ContentBlock]) -> list[dict[str, object]]:
        """Convert content blocks to a list of dicts for the API."""
        result: list[dict[str, object]] = []
        for block in content:
            if isinstance(block, ToolUseBlock):
                result.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
            elif isinstance(block, TextBlock):
                result.append({"type": "text", "text": block.text})
        return result

    def _extract_text_response(self, content: list[ContentBlock]) -> str:
        """Extract text from response content blocks."""
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
        return "\n".join(text_parts)

    def start_game(
        self,
        state: GameState,
        progress_callback: Callable[[], None] | None = None,
    ) -> tuple[str, int]:
        """
        Start the game with an initial description.

        Args:
            state: Current game state.
            progress_callback: Optional callback to show progress.

        Returns:
            Tuple of (opening narrative, time advanced in minutes).
        """
        # Send an initial "start" message to kick things off
        return self.generate_response("I just arrived here. Look around.", state, progress_callback)

    def generate_loading_message(self, state: GameState, action: str | None = None) -> str:
        """
        Generate a fun, contextual loading message.

        Args:
            state: Current game state.
            action: Optional player action to contextualize the message.

        Returns:
            A short, fun message to show while loading.
        """
        location = state.starting_location
        game_time = state.get_game_datetime()
        hour = game_time.hour

        # Time-based context
        if 5 <= hour < 12:
            time_context = "morning"
        elif 12 <= hour < 17:
            time_context = "afternoon"
        elif 17 <= hour < 21:
            time_context = "evening"
        else:
            time_context = "night"

        # Get recent scene context (last assistant message)
        recent_context = ""
        for msg in reversed(state.messages):
            if msg.role == "assistant":
                # Take last 500 chars for context
                recent_context = msg.content[-500:] if len(msg.content) > 500 else msg.content
                break

        if action:
            prompt = f"""Generate a single short, atmospheric loading message (max 8 words) for a text adventure.

Recent scene: {recent_context}

The player ({time_context}) just said: "{action}"

Generate a brief, evocative loading message that fits the scene. No quotes, just the message. End with "..."
Examples: "Reaching out...", "The moment stretches...", "Stone cold against skin..." """
        else:
            prompt = f"""Generate a single short, playful loading message (max 8 words) for a text adventure game.
The player is in {location.city} during the {time_context}.
Be creative and atmospheric. No quotes, just the message. End with "..."
Examples: "Scanning the streets...", "Tuning into the city's rhythm...", "The world comes into focus..." """

        response = self.client.messages.create(
            model="claude-sonnet-4-5",  # Use Sonnet for quality
            max_tokens=30,
            messages=[{"role": "user", "content": prompt}],
        )
        self._track_sonnet_usage(response)

        return self._extract_text_response(response.content)

    def _track_opus_usage(self, response: Message) -> None:
        """Track token usage from an Opus API response."""
        self.opus_input_tokens += response.usage.input_tokens
        self.opus_output_tokens += response.usage.output_tokens

    def _track_sonnet_usage(self, response: Message) -> None:
        """Track token usage from a Sonnet API response."""
        self.sonnet_input_tokens += response.usage.input_tokens
        self.sonnet_output_tokens += response.usage.output_tokens

    def get_session_cost(self) -> float:
        """
        Calculate the total cost of the session in USD.

        Returns:
            Total cost in dollars.
        """
        opus_cost = (self.opus_input_tokens / 1_000_000) * self.OPUS_INPUT_PRICE + (
            self.opus_output_tokens / 1_000_000
        ) * self.OPUS_OUTPUT_PRICE
        sonnet_cost = (self.sonnet_input_tokens / 1_000_000) * self.SONNET_INPUT_PRICE + (
            self.sonnet_output_tokens / 1_000_000
        ) * self.SONNET_OUTPUT_PRICE
        return opus_cost + sonnet_cost
