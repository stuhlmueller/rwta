"""Claude API integration for generating game responses."""

import os
from collections.abc import Callable

from anthropic import Anthropic
from anthropic.types import ContentBlock, Message, ToolUseBlock

from rwta.location import get_weather
from rwta.state import GameState
from rwta.tools import ToolResult, execute_tool, get_tools


def get_system_prompt(state: GameState) -> str:
    """
    Generate the system prompt for the game.

    Args:
        state: Current game state.

    Returns:
        System prompt string.
    """
    location = state.starting_location
    game_time = state.get_formatted_game_time()

    # Fetch current weather
    weather = get_weather(location)
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
4. React to the current time of day (morning, afternoon, evening, night) with appropriate descriptions
5. Keep track of where the player is and what they're doing
6. Make the world feel alive with realistic details, weather, people, traffic, etc.

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

Begin!"""


class GameNarrator:
    """Handles LLM interactions for the text adventure."""

    def __init__(self, api_key: str | None = None):
        """
        Initialize the game narrator.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
        """
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = "claude-opus-4-5"

    def count_tokens(
        self,
        messages: list[dict[str, str]],
        system: str,
    ) -> int:
        """Count tokens for a messages request."""
        response = self.client.messages.count_tokens(
            model=self.model,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        )
        return response.input_tokens

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
            max_tokens=180000,  # Leave room for response
        )

        # Initial API call
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            tools=get_tools(),  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )

        # Handle tool use loop
        final_response = self._handle_tool_use(
            response, messages, system, state, progress_callback
        )

        # Add assistant response to state (only if non-empty)
        if final_response.strip():
            state.add_message("assistant", final_response)

        return final_response

    def _handle_tool_use(
        self,
        response: Message,
        messages: list[dict[str, str]],
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
                max_tokens=4096,
                system=system,
                tools=get_tools(),  # type: ignore[arg-type]
                messages=new_messages,  # type: ignore[arg-type]
            )

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
            elif hasattr(block, "text"):
                result.append({"type": "text", "text": block.text})
        return result

    def _extract_text_response(self, content: list[ContentBlock]) -> str:
        """Extract text from response content blocks."""
        text_parts: list[str] = []
        for block in content:
            if hasattr(block, "text"):
                text_parts.append(str(block.text))
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

        return self._extract_text_response(response.content)
