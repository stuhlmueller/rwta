# Real World Text Adventure

A terminal-based open-world text adventure set in the **real world**, powered by Claude Opus 4.5. Explore your actual surroundings, interact with real places and businesses, and experience current events as they happen.

https://github.com/user-attachments/assets/f29b9d63-627f-4cc2-be09-98e0beb96e17

## Features

- **Real-world setting**: Start from your current location (via IP geolocation) or enter a specific address
- **Live data**: The game uses web search to fetch current information about places, news, weather, and more
- **Dynamic time**: In-game time passes realistically based on your actions (walking, eating, traveling)
- **Location tracking**: Your current location updates as you move through the world, with weather that changes based on where you are
- **Save/load**: Save your progress and continue later
- **Action granularity**: Experience the world step-by-step - no teleporting or skipping ahead

## Installation

Requires Python 3.11+.

```bash
# Clone the repository
git clone <repo-url>
cd text-adventure

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

## Usage

```bash
# Start the game (shows menu to continue a story or start new)
python -m rwta.main

# Or if installed
text-adventure

# Skip the menu and start a fresh game
python -m rwta.main --new
```

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/save [name]` | Save your game |
| `/load` | Load a saved game |
| `/time` | Show current in-game time |
| `/where` | Show current location and time |
| `/tokens` | Show token usage and context limit |
| `/look` | Re-describe your current surroundings |
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
