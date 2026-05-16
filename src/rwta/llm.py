"""Claude API integration for generating game responses."""

import logging
import os
import time
from collections.abc import Callable
from typing import cast

from anthropic import Anthropic, APIError
from anthropic.types import (
    ContentBlock,
    Message,
    MessageParam,
    RedactedThinkingBlock,
    TextBlock,
    TextBlockParam,
    ThinkingBlock,
    ToolParam,
    ToolUseBlock,
)

from rwta.config import (
    ANTHROPIC_MAX_RETRIES,
    CACHE_READ_MULTIPLIER,
    CACHE_WRITE_MULTIPLIER,
    FALLBACK_MODEL,
    FAST_MODEL,
    MAX_CONTEXT_TOKENS,
    MAX_RESPONSE_TOKENS,
    MAX_TOOL_ITERATIONS,
    OPUS_INPUT_PRICE_PER_MILLION,
    OPUS_OUTPUT_PRICE_PER_MILLION,
    PRIMARY_MODEL,
    SONNET_INPUT_PRICE_PER_MILLION,
    SONNET_OUTPUT_PRICE_PER_MILLION,
    THINKING_EFFORT,
    THINKING_MODE,
    VISUAL_CONTINUITY_MAX_CHARS,
    VISUAL_TRANSCRIPT_MAX_CHARS,
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


# --- System prompt (split into static + dynamic for prompt caching) ---

# Static portion: rules, role, formatting requirements. Identical across turns,
# so it's a great prefix to cache. With Anthropic prompt caching, this prefix
# is read at 10% of the base input cost on subsequent turns.
_STATIC_SYSTEM_PROMPT = """You are the narrator of a text adventure game set in the REAL WORLD. The player exists in the actual, present-day world and can explore real locations, interact with real businesses, and encounter real-world events.

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


def _dynamic_system_prompt(state: GameState) -> str:
    """Per-turn variable portion of the system prompt (location/time/weather)."""
    location = state.get_current_location()
    game_time = state.get_formatted_game_time()
    weather = get_cached_weather(location)
    weather_str = str(weather) if weather else "Weather unknown"

    return f"""## Setting
- The player is currently in: {location}
- Current in-game date and time: {game_time}
- Current weather: {weather_str}"""


def get_system_prompt(state: GameState) -> str:
    """
    Return the full system prompt as a string (static + dynamic).

    This is what we'd send to the API as `system=` if we weren't using prompt
    caching. It's still useful for `count_tokens` and any human-readable inspection.
    """
    return f"{_STATIC_SYSTEM_PROMPT}\n\n{_dynamic_system_prompt(state)}"


def _system_blocks(state: GameState) -> list[TextBlockParam]:
    """
    Build the system prompt as a list of cacheable text blocks.

    The static block is marked with cache_control so Anthropic caches the
    `tools + static system` prefix. Subsequent turns within ~5 minutes of
    each other read those cached tokens at 10% of the input cost.
    """
    return cast(
        list[TextBlockParam],
        [
            {
                "type": "text",
                "text": _STATIC_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": _dynamic_system_prompt(state)},
        ],
    )


def _to_message_params(messages: list[dict[str, object]]) -> list[MessageParam]:
    """Convert message dicts to MessageParam for the Anthropic API."""
    return cast(list[MessageParam], messages)


def _to_tool_params(tools: list[ToolDefinition]) -> list[ToolParam]:
    """Convert tool definitions to ToolParam for the Anthropic API."""
    return cast(list[ToolParam], tools)


class GameNarrator:
    """Handles LLM interactions for the text adventure."""

    def __init__(self, api_key: str | None = None, fast: bool = False):
        """
        Initialize the game narrator.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
            fast: If True, use the fast model (Sonnet) for narration.
        """
        self.client = Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            max_retries=ANTHROPIC_MAX_RETRIES,
        )
        self.fast = fast
        self.model = FAST_MODEL if fast else PRIMARY_MODEL

        # Token usage tracking. Cache fields track tokens that hit Anthropic's
        # prompt cache vs. tokens that wrote to it (priced differently).
        self.opus_input_tokens = 0
        self.opus_output_tokens = 0
        self.opus_cache_creation_tokens = 0
        self.opus_cache_read_tokens = 0
        self.sonnet_input_tokens = 0
        self.sonnet_output_tokens = 0
        self.sonnet_cache_creation_tokens = 0
        self.sonnet_cache_read_tokens = 0

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

    def _thinking_kwargs(self) -> dict[str, object]:
        """
        Return ``extra_body`` kwargs that turn on adaptive thinking.

        Adaptive thinking is enabled by default on Opus 4.7 (the only mode it
        supports) and Sonnet 4.6. We use ``display: "omitted"`` so the API
        skips streaming thinking text — we don't surface it to the player and
        omitting cuts time-to-first-text-token. Thinking is suppressed in
        --fast mode where latency matters more than depth.

        Both ``output_config`` and the ``display`` field on ``thinking`` are
        newer than the installed Anthropic SDK's TypedDicts (per the docs:
        "No SDK currently includes display in its type definitions"). We pass
        them via ``extra_body`` so the SDK forwards them verbatim.
        """
        if self.fast or THINKING_MODE != "adaptive":
            return {}
        return {
            "extra_body": {
                "thinking": {"type": "adaptive", "display": "omitted"},
                "output_config": {"effort": THINKING_EFFORT},
            }
        }

    def _create_message(
        self, system_blocks: list[TextBlockParam], messages: list[dict[str, object]]
    ) -> Message:
        """Make a primary-model API call with caching enabled and tools attached."""
        return self.client.messages.create(
            model=self.model,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=system_blocks,
            tools=_to_tool_params(get_tools()),
            messages=_to_message_params(messages),
            **self._thinking_kwargs(),  # type: ignore[arg-type]
        )

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

        # Get system prompt (string form for token counting/trimming)
        system_str = get_system_prompt(state)

        # Get messages, trimming if needed to fit context
        messages = state.get_messages_for_api(
            token_counter=lambda msgs: self.count_tokens(msgs, system_str),
            max_tokens=MAX_CONTEXT_TOKENS,
            summarizer=self._summarize_messages,
        )

        # Initial API call (with prompt caching on the static system block)
        logger.debug("Calling %s with %d messages", self.model, len(messages))
        response = self._create_message(_system_blocks(state), messages)
        self._track_opus_usage(response)

        # Handle tool use loop
        final_response = self._handle_tool_use(response, messages, state, progress_callback)

        # Add assistant response to state (only if non-empty)
        if final_response.strip():
            state.add_message("assistant", final_response)
            self.update_visual_continuity(state)

        return final_response

    def update_visual_continuity(self, state: GameState) -> None:
        """
        Maintain a compact visual bible for generated images.

        Image models otherwise tend to silently redesign recurring people,
        places, clothing, vehicles, and carried items from turn to turn. This
        ledger is intentionally short and factual; it is fed into every scene
        image prompt and saved with the game.
        """
        last_assistant = state.get_last_assistant_message()
        if not last_assistant:
            return

        last_user = self._last_user_message(state)
        existing = state.visual_continuity or ""
        if existing:
            source = f"Existing visual continuity ledger:\n{existing}\n\nLatest turn:"
            transcript = self._format_latest_exchange(last_user, last_assistant)
        else:
            source = "Build a visual continuity ledger from this adventure transcript:"
            transcript = self._visual_transcript(state)

        prompt = f"""You maintain the VISUAL CONTINUITY LEDGER for a real-world illustrated text adventure.

Goal: keep generated scene images visually consistent across turns. Track only durable visual facts that should remain stable unless the story explicitly changes them.

Include, when present:
- recurring people: appearance, clothing, posture, distinctive features
- recurring places: stable layout, architecture, landmarks, lighting fixtures, signage
- items/props/vehicles/pets: exact appearance, ownership, location, condition
- current carried or worn items

Rules:
- Do not invent new visual details.
- Preserve exact details already established unless the latest turn explicitly changes them.
- Remove details only when contradicted, lost, left behind, destroyed, or no longer relevant.
- Keep it concise: at most {VISUAL_CONTINUITY_MAX_CHARS} characters.
- Return only the ledger text, as terse bullets. If there are no durable visual facts, return an empty string.

{source}
{transcript}
"""

        try:
            response = self.client.messages.create(
                model=FAST_MODEL,
                max_tokens=500,
                messages=_to_message_params([{"role": "user", "content": prompt}]),
            )
        except APIError as e:
            logger.warning("Visual continuity update failed: %s", e)
            return
        except (OSError, ValueError, TypeError) as e:
            logger.warning("Visual continuity update failed: %s", e)
            return

        self._track_sonnet_usage(response)
        ledger = self._clean_visual_ledger(self._extract_text_response(response.content))
        if len(ledger) > VISUAL_CONTINUITY_MAX_CHARS:
            ledger = ledger[:VISUAL_CONTINUITY_MAX_CHARS].rsplit("\n", 1)[0].strip()
        state.visual_continuity = ledger or None

    @staticmethod
    def _clean_visual_ledger(raw: str) -> str:
        lines = []
        for line in raw.strip().splitlines():
            cleaned = line.strip()
            if cleaned in {"-", "*", "•"}:
                continue
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    @staticmethod
    def _last_user_message(state: GameState) -> str | None:
        for msg in reversed(state.messages):
            if msg.role == "user":
                return msg.content
        return None

    @staticmethod
    def _format_latest_exchange(last_user: str | None, last_assistant: str) -> str:
        parts: list[str] = []
        if last_user:
            parts.append(f"Player: {last_user}")
        parts.append(f"Narrator: {last_assistant}")
        return "\n".join(parts)

    @staticmethod
    def _visual_transcript(state: GameState) -> str:
        lines = [f"Current location: {state.get_current_location()}"]
        for msg in state.messages:
            label = "Player" if msg.role == "user" else "Narrator"
            lines.append(f"{label}: {msg.content}")
        transcript = "\n\n".join(lines)
        if len(transcript) <= VISUAL_TRANSCRIPT_MAX_CHARS:
            return transcript
        head_chars = VISUAL_TRANSCRIPT_MAX_CHARS // 3
        tail_chars = VISUAL_TRANSCRIPT_MAX_CHARS - head_chars
        head = transcript[:head_chars].rsplit("\n", 1)[0]
        tail = transcript[-tail_chars:].split("\n", 1)[-1]
        return f"{head}\n\n[... earlier visual history omitted ...]\n\n{tail}"

    def generate_response_fallback(
        self,
        user_input: str,
        state: GameState,
        model: str = FALLBACK_MODEL,
    ) -> str:
        """Generate a response with OpenAI when Anthropic fails.

        This is deliberately no-tools: it prioritizes recovering the session
        and producing a playable next turn over perfect location/time updates.
        """
        try:
            from openai import OpenAI, OpenAIError
        except ImportError as e:
            raise RuntimeError("openai package not installed") from e

        state.add_message("user", user_input)
        system = get_system_prompt(state)
        messages = state.get_messages_for_api(max_tokens=MAX_CONTEXT_TOKENS)
        openai_messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for msg in messages:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            openai_messages.append({"role": role, "content": content})

        try:
            response = OpenAI().chat.completions.create(
                model=model,
                messages=openai_messages,  # type: ignore[arg-type]
                max_completion_tokens=2000,
            )
        except OpenAIError as e:
            state.pop_last_exchange()
            raise RuntimeError(f"OpenAI fallback failed: {e}") from e

        text = (response.choices[0].message.content or "").strip() if response.choices else ""
        if not text:
            state.pop_last_exchange()
            raise RuntimeError("OpenAI fallback returned an empty response")
        state.add_message("assistant", text)
        self.update_visual_continuity(state)
        return text

    def _handle_tool_use(
        self,
        response: Message,
        messages: list[dict[str, object]],
        state: GameState,
        progress_callback: Callable[[], None] | None = None,
    ) -> str:
        """
        Handle tool use in a loop until we get a final text response.

        Args:
            response: Initial API response.
            messages: Conversation messages.
            state: Game state (for time advancement).
            progress_callback: Optional callback to show progress.

        Returns:
            Final text response from the model.
        """
        iterations = 0
        while response.stop_reason == "tool_use":
            iterations += 1
            if iterations > MAX_TOOL_ITERATIONS:
                logger.warning(
                    "Tool use loop exceeded %d iterations, breaking", MAX_TOOL_ITERATIONS
                )
                break

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

            # Make next API call. The dynamic system block may differ (time
            # advanced, location changed) but the cached static prefix is reused.
            response = self._create_message(_system_blocks(state), new_messages)
            self._track_opus_usage(response)
            messages = new_messages

        # Extract final text response
        return self._extract_text_response(response.content)

    def _content_blocks_to_list(self, content: list[ContentBlock]) -> list[dict[str, object]]:
        """
        Convert content blocks to a list of dicts for the API.

        Thinking blocks (and their encrypted ``signature``) MUST be passed back
        in subsequent turns of a tool-use loop when extended/adaptive thinking
        is active — otherwise the API rejects the request. ``display: "omitted"``
        leaves the visible ``thinking`` field empty but the ``signature`` still
        carries the encrypted full reasoning, which we round-trip unchanged.
        """
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
            elif isinstance(block, ThinkingBlock):
                result.append(
                    {
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": block.signature,
                    }
                )
            elif isinstance(block, RedactedThinkingBlock):
                result.append({"type": "redacted_thinking", "data": block.data})
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
        location = state.get_current_location()
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
        """Track token usage from a primary model API response."""
        if self.fast:
            self._track_sonnet_usage(response)
            return
        usage = response.usage
        self.opus_input_tokens += usage.input_tokens
        self.opus_output_tokens += usage.output_tokens
        self.opus_cache_creation_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.opus_cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0

    def _track_sonnet_usage(self, response: Message) -> None:
        """Track token usage from a Sonnet API response."""
        usage = response.usage
        self.sonnet_input_tokens += usage.input_tokens
        self.sonnet_output_tokens += usage.output_tokens
        self.sonnet_cache_creation_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.sonnet_cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0

    @staticmethod
    def _model_cost(
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        input_price: float,
        output_price: float,
    ) -> float:
        """Compute spend for one model tier given input/output and cache tokens."""
        return (
            (input_tokens / 1_000_000) * input_price
            + (output_tokens / 1_000_000) * output_price
            + (cache_creation_tokens / 1_000_000) * input_price * CACHE_WRITE_MULTIPLIER
            + (cache_read_tokens / 1_000_000) * input_price * CACHE_READ_MULTIPLIER
        )

    def get_session_cost(self) -> float:
        """Calculate the total cost of the session in USD (incl. cache pricing)."""
        opus_cost = self._model_cost(
            self.opus_input_tokens,
            self.opus_output_tokens,
            self.opus_cache_creation_tokens,
            self.opus_cache_read_tokens,
            OPUS_INPUT_PRICE_PER_MILLION,
            OPUS_OUTPUT_PRICE_PER_MILLION,
        )
        sonnet_cost = self._model_cost(
            self.sonnet_input_tokens,
            self.sonnet_output_tokens,
            self.sonnet_cache_creation_tokens,
            self.sonnet_cache_read_tokens,
            SONNET_INPUT_PRICE_PER_MILLION,
            SONNET_OUTPUT_PRICE_PER_MILLION,
        )
        return opus_cost + sonnet_cost

    def get_cache_stats(self) -> tuple[int, int]:
        """Return (cache_creation_tokens, cache_read_tokens) summed across models."""
        creation = self.opus_cache_creation_tokens + self.sonnet_cache_creation_tokens
        read = self.opus_cache_read_tokens + self.sonnet_cache_read_tokens
        return creation, read
