# Real World Text Adventure

A terminal-based open-world text adventure set in the **real world**, powered by Claude Opus 4.5. Explore your actual surroundings, interact with real places and businesses, and experience current events as they happen.

https://github.com/user-attachments/assets/f29b9d63-627f-4cc2-be09-98e0beb96e17

## Features

- **Real-world setting**: Start from your current location (via IP geolocation) or enter a specific address
- **Live data**: The game uses web search to fetch current information about places, news, weather, and more
- **Dynamic time**: In-game time passes realistically based on your actions (walking, eating, traveling)
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

# Or with pip directly
pip install anthropic httpx
```

## Configuration

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY='your-api-key'
```

## Usage

```bash
# Start a new game
python -m rwta.main

# Or if installed
text-adventure

# Load a saved game
python -m rwta.main saves/your_save.json
```

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/save [name]` | Save your game |
| `/load` | Load a saved game |
| `/time` | Show current in-game time |
| `/quit` | Exit the game |

## How It Works

1. **Location Detection**: On startup, the game detects your city via IP geolocation, then asks for a specific address (or picks a notable location)

2. **Time Tracking**: The game starts at the current real-world time. Time advances based on your actions:
   - Walking: ~15-20 min/mile
   - Eating: 30-60 min
   - Shopping: 15-30 min/store

3. **Web Search**: Claude can search the web to get accurate information about real places, current events, business hours, etc.

4. **Granular Actions**: You must take realistic step-by-step actions. To fly somewhere, you need to get to the airport, buy a ticket, board the plane, etc.

## Project Structure

```
text-adventure/
├── pyproject.toml           # Project configuration
├── README.md
├── saves/                   # Save files
└── src/rwta/
    ├── __init__.py
    ├── main.py              # Entry point and game loop
    ├── llm.py               # Claude API integration
    ├── tools.py             # Web search and time tools
    ├── state.py             # Game state and save/load
    └── location.py          # IP geolocation
```

## License

MIT
