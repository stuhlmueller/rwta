"""Claude API integration for generating game responses."""

import logging
import os
import time
from collections.abc import Callable
from typing import cast

from anthropic import Anthropic
from anthropic.types import ContentBlock, Message, MessageParam, TextBlock, ToolParam, ToolUseBlock

from rwta.config import (
    FAST_MODEL,
    MAX_CONTEXT_TOKENS,
    MAX_RESPONSE_TOKENS,
    OPUS_INPUT_PRICE_PER_MILLION,
    OPUS_OUTPUT_PRICE_PER_MILLION,
    PRIMARY_MODEL,
    SONNET_INPUT_PRICE_PER_MILLION,
    SONNET_OUTPUT_PRICE_PER_MILLION,
    WEATHER_CACHE_TTL_SECONDS,
)
from rwta.location import Location, Weather, get_weather
from rwta.state import GameState
from rwta.tools import ToolDefinition, execute_tool, get_tools

logger = logging.getLogger(__name__)

# Weather cache: stores (location_key, timestamp, weather) tuples
_weather_cache: dict[str, tuple[float, Weather | None]] = {}


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


def get_system_prompt(state: GameState) -> str:
    """
    Generate the system prompt for the game.

    Args:
        state: Current game state.

    Returns:
        System prompt string.
    """
    location = state.get_current_location()
    game_time = state.get_formatted_game_time()

    # Fetch current weather (with caching)
    weather = get_cached_weather(location)
    weather_str = str(weather) if weather else "Weather unknown"

    return f"""You are the narrator of a text adventure game set in the REAL WORLD. The player exists in the actual, present-day world and can explore real locations, interact with real businesses, and encounter real-world events.

## Setting
- The player is currently in: {location}
- Current in-game date and time: {game_time}
- Current weather: {weather_str}

## Your Role
You are an immersive narrator who describes the world around the player. You should:
1. Describe real locations, streets, landmarks, and businesses accurately
2. Use the search_web tool SPARINGLY - only 1-2 searches when truly needed for specific facts you don't know
3. Use the advance_time tool whenever the player performs actions that take time (walking, eating, waiting, etc.)
4. Use the update_location tool when the player moves to a significantly different place (new neighborhood, city, or country)
5. React to the current time of day (morning, afternoon, evening, night) with appropriate descriptions
6. Keep track of where the player is and what they're doing
7. Make the world feel alive with realistic details, weather, people, traffic, etc.

## Location Tracking
Use the update_location tool when the player:
- Arrives at a new neighborhood or district within a city
- Travels to a different city (by car, bus, train, plane, etc.)
- Crosses into a different country
- Arrives at a significant landmark that defines their location

Do NOT call update_location for minor movements (walking down the street, entering a building in the same area).
When calling update_location, provide the most specific address/landmark you can for the "address" field.

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

## Action Granularity (IMPORTANT)
Players must take realistic, step-by-step actions. If a player tries to skip steps or do something too complex in one action, DO NOT execute it. Instead, guide them to break it down:

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

## Suggested Actions (REQUIRED)
At the end of EVERY response, include exactly 3 suggested actions the player could take next. Format them as:

---
1. [Brief action description]
2. [Brief action description]
3. [Brief action description]

These should be concrete, immediate actions appropriate to the current situation. Keep each to 5-10 words.
Examples: "Walk toward the coffee shop", "Ask the stranger for directions", "Check your pockets for money"

Begin!"""


def _to_message_params(messages: list[dict[str, object]]) -> list[MessageParam]:
    """Convert message dicts to MessageParam for the Anthropic API."""
    return cast(list[MessageParam], messages)


def _to_tool_params(tools: list[ToolDefinition]) -> list[ToolParam]:
    """Convert tool definitions to ToolParam for the Anthropic API."""
    return cast(list[ToolParam], tools)


class GameNarrator:
    """Handles LLM interactions for the text adventure."""

    def __init__(self, api_key: str | None = None):
        """
        Initialize the game narrator.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
        """
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = PRIMARY_MODEL

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
            messages=_to_message_params(messages),
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
            model=FAST_MODEL,
            max_tokens=150,
            messages=_to_message_params([{"role": "user", "content": prompt}]),
        )
        self._track_sonnet_usage(response)

        return self._extract_text_response(response.content)

    def generate_response(
        self,
        user_input: str,
        state: GameState,
        progress_callback: Callable[[], None] | None = None,
    ) -> str:
        """
        Generate a narrative response to the player's input.

        Args:
            user_input: The player's input/action.
            state: Current game state.
            progress_callback: Optional callback to show progress during tool use.

        Returns:
            The narrator's response.
        """
        # Add user message to state
        state.add_message("user", user_input)

        # Get system prompt
        system = get_system_prompt(state)

        # Get messages, trimming if needed to fit context
        messages = state.get_messages_for_api(
            token_counter=lambda msgs: self.count_tokens(msgs, system),
            max_tokens=MAX_CONTEXT_TOKENS,
            summarizer=self._summarize_messages,
        )

        # Initial API call
        logger.debug("Calling %s with %d messages", self.model, len(messages))
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=system,
            tools=_to_tool_params(get_tools()),
            messages=_to_message_params(messages),
        )
        self._track_opus_usage(response)

        # Handle tool use loop
        final_response = self._handle_tool_use(response, messages, system, state, progress_callback)

        # Add assistant response to state (only if non-empty)
        if final_response.strip():
            state.add_message("assistant", final_response)

        return final_response

    def _handle_tool_use(
        self,
        response: Message,
        messages: list[dict[str, object]],
        system: str,
        state: GameState,
        progress_callback: Callable[[], None] | None = None,
    ) -> str:
        """
        Handle tool use in a loop until we get a final text response.

        Args:
            response: Initial API response.
            messages: Conversation messages.
            system: System prompt.
            state: Game state (for time advancement).
            progress_callback: Optional callback to show progress.

        Returns:
            Final text response from the model.
        """
        while response.stop_reason == "tool_use":
            # Find tool use blocks
            tool_uses = [block for block in response.content if isinstance(block, ToolUseBlock)]
            if not tool_uses:
                break

            # Process each tool use
            tool_results: list[dict[str, object]] = []
            for tool_use in tool_uses:
                logger.debug("Executing tool: %s", tool_use.name)
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

                # Handle location update
                if result.location_update is not None:
                    state.set_current_location(result.location_update.to_location())

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result.message,
                    }
                )

            # Build new messages with assistant response and tool results
            assistant_content = self._content_blocks_to_list(response.content)
            new_messages = messages + [
                {"role": "assistant", "content": assistant_content},
                {"role": "user", "content": tool_results},
            ]

            # Make next API call with updated system prompt (time may have changed)
            system = get_system_prompt(state)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_RESPONSE_TOKENS,
                system=system,
                tools=_to_tool_params(get_tools()),
                messages=_to_message_params(new_messages),
            )
            self._track_opus_usage(response)
            messages = new_messages

        # Extract final text response
        return self._extract_text_response(response.content)

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
    ) -> str:
        """
        Start the game with an initial description.

        Args:
            state: Current game state.
            progress_callback: Optional callback to show progress.

        Returns:
            Opening narrative.
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
        hour = state.get_game_datetime().hour

        # Time-based context
        if hour < 5:
            time_context = "night"
        elif hour < 12:
            time_context = "morning"
        elif hour < 17:
            time_context = "afternoon"
        elif hour < 21:
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
            model=FAST_MODEL,
            max_tokens=30,
            messages=_to_message_params([{"role": "user", "content": prompt}]),
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
        opus_cost = (self.opus_input_tokens / 1_000_000) * OPUS_INPUT_PRICE_PER_MILLION + (
            self.opus_output_tokens / 1_000_000
        ) * OPUS_OUTPUT_PRICE_PER_MILLION
        sonnet_cost = (self.sonnet_input_tokens / 1_000_000) * SONNET_INPUT_PRICE_PER_MILLION + (
            self.sonnet_output_tokens / 1_000_000
        ) * SONNET_OUTPUT_PRICE_PER_MILLION
        return opus_cost + sonnet_cost
