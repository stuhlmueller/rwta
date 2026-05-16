# Real World Text Adventure

A terminal-based open-world text adventure set in the **real world**, powered by Claude Opus 4.7. Explore your actual surroundings, interact with real places and businesses, and experience current events as they happen.

https://github.com/user-attachments/assets/f29b9d63-627f-4cc2-be09-98e0beb96e17

## Quickstart

```bash
pip install git+https://github.com/stuhlmueller/rwta.git
export ANTHROPIC_API_KEY='your-api-key'
rwta
```

## Native Mac app

A SwiftUI macOS app with a MapKit map, selectable OpenAI-generated scene
image styles, cached image history, and a more game-like adventure UI lives
under [`mac/`](mac/). Launch it with `mac/run.sh` (requires `swift`, `uv`,
`ANTHROPIC_API_KEY`, and optionally `OPENAI_API_KEY`).

## Features

- **Real-world setting**: Start from your current location (via IP geolocation) or enter a specific address
- **Live data**: The game uses web search to fetch current information about places, news, weather, and more
- **Dynamic time**: In-game time passes realistically based on your actions (walking, eating, traveling)
- **Location tracking**: Your current location updates as you move through the world, with weather that changes based on where you are
- **Save/load**: Save your progress and continue later
- **Action granularity**: Experience the world step-by-step - no teleporting or skipping ahead
- **Prompt caching**: System prompt is cached on Anthropic's servers between turns, cutting input cost ~90% on cached tokens
- **Adaptive thinking**: Opus 4.7 thinks between tool calls for higher-quality multi-step actions; thinking is hidden from the player for snappier output
- **Visual continuity ledger**: The native Mac app keeps a compact visual bible for recurring people, places, and items so generated scene images stay consistent across turns
- **Image style + cache**: Scene images default to photorealistic, can be rerendered in alternate styles, are cached in `~/.rwta/images/`, appear as previews on the save menu, and can be paged through after loading a save

## Installation

Requires Python 3.11+.

```bash
# Clone the repository
git clone https://github.com/stuhlmueller/rwta.git
cd rwta

# Install dependencies
pip install -e .

# For development (includes ruff, pyright, pytest, pre-commit)
pip install -e ".[dev]"
pre-commit install
```

## Configuration

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY='your-api-key'
```

Optional environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `RWTA_TIMEZONE` | `America/Los_Angeles` | IANA timezone for in-game time |
| `RWTA_PRIMARY_MODEL` | `claude-opus-4-7` | Primary LLM model for narration |
| `RWTA_FAST_MODEL` | `claude-sonnet-4-6` | Fast model for loading messages and summaries |
| `RWTA_FALLBACK_MODEL` | `gpt-5.5` | OpenAI model used by the Mac app's retry button if the narrator fails |
| `RWTA_THINKING` | `adaptive` | Thinking mode for the primary model: `adaptive` or `off`. Opus 4.7 only supports `adaptive`. |
| `RWTA_THINKING_EFFORT` | `medium` | Soft guide for how much to think when adaptive: `low`, `medium`, `high`, `xhigh`, `max`. |
| `RWTA_DATA_DIR` | `~/.rwta` | Directory for saves, exports, and history |
| `RWTA_LOG_LEVEL` | `WARNING` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `RWTA_VISUAL_CONTINUITY_MAX_CHARS` | `1400` | Maximum length of the image consistency ledger saved with each game |
| `RWTA_VISUAL_TRANSCRIPT_MAX_CHARS` | `9000` | Transcript budget used when rebuilding the visual continuity ledger |

## Usage

```bash
# Start the game (shows menu to continue a story or start new)
rwta

# Show all CLI options
rwta --help

# Skip the menu and start a fresh game
rwta --new

# Resume a specific save without going through the menu
rwta --load oakland-0115

# List all saved games (and their paths) and exit
rwta --list

# Fast mode (Sonnet, no typewriter delay, no auto-save)
rwta --fast

# Combine flags
rwta --fast --new
```

After the narrator's response, you can press `1`, `2`, or `3` to pick the
corresponding suggested action without retyping it.

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/save [name]` | Save your game (auto-named if no name given) |
| `/load` | Load a saved game (interactive picker) |
| `/saves` | List saved games |
| `/delete <name>` | Delete a saved game by name |
| `/regenerate` | Re-roll the most recent narrator response |
| `/time` | Show current in-game time |
| `/where` | Show current location and time |
| `/look` | Re-describe your current surroundings |
| `/tokens` | Show token usage and context limit |
| `/cost` | Show running session cost (incl. cache hits) |
| `/export [name]` | Export story as markdown file |
| `/quit` | Exit the game |

You can also press `Ctrl-C` twice to save and quit.

## How It Works

1. **Location Detection**: On startup, the game detects your city via IP geolocation, then asks for a specific address (or picks a notable location)

2. **Location Tracking**: As you move through the world, your current location updates automatically. The game tracks both your starting location and where you currently are. Weather updates based on your current position (cached for 5 minutes to avoid excessive API calls).

3. **Time Tracking**: The game starts at the current real-world time. Time advances based on your actions:
   - Walking: ~15-20 min/mile
   - Eating: 30-60 min
   - Shopping: 15-30 min/store

4. **Web Search**: Claude can search the web to get accurate information about real places, current events, business hours, etc.

5. **Granular Actions**: You must take realistic step-by-step actions. To fly somewhere, you need to get to the airport, buy a ticket, board the plane, etc.

## License

MIT
