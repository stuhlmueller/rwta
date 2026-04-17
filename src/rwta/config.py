"""Centralized configuration constants for RWTA."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

# --- Data Directory ---
DATA_DIR = Path(os.getenv("RWTA_DATA_DIR", str(Path.home() / ".rwta")))

# --- Timezone ---
LOCAL_TIMEZONE = ZoneInfo(os.getenv("RWTA_TIMEZONE", "America/Los_Angeles"))

# --- API Timeouts (seconds) ---
GEOLOCATION_TIMEOUT = 5.0
WEATHER_TIMEOUT = 5.0
SEARCH_TIMEOUT = 10.0

# --- Cache Settings ---
WEATHER_CACHE_TTL_SECONDS = 300  # 5 minutes
SEARCH_CACHE_TTL_SECONDS = 300  # 5 minutes (per-session cache)

# --- LLM Settings ---
MAX_TOOL_ITERATIONS = 10  # Cap tool use loop to prevent infinite loops
# Opus 4.7 supports a 1M context window. Keep generous headroom below that
# for response + system prompt, and for avoiding runaway context costs.
MAX_CONTEXT_TOKENS = 500_000
MAX_RESPONSE_TOKENS = 4096
SUMMARIZATION_BUFFER_TOKENS = 1000  # Extra space for summary message

# Token estimation when API unavailable: ~4 characters per token
TOKEN_CHAR_ESTIMATE_DIVISOR = 4

# --- Pricing (per million tokens, verified 2026-04 for Claude 4.7 family) ---
# Opus 4.7: $5 input / $25 output (per platform.claude.com)
# Sonnet 4.6: $3 input / $15 output
OPUS_INPUT_PRICE_PER_MILLION = 5.0
OPUS_OUTPUT_PRICE_PER_MILLION = 25.0
SONNET_INPUT_PRICE_PER_MILLION = 3.0
SONNET_OUTPUT_PRICE_PER_MILLION = 15.0

# --- Models ---
PRIMARY_MODEL = os.getenv("RWTA_PRIMARY_MODEL", "claude-opus-4-7")
FAST_MODEL = os.getenv("RWTA_FAST_MODEL", "claude-sonnet-4-6")

# --- UI Settings ---
TYPEWRITER_DELAY_SECONDS = 0.05
LOADING_REFRESH_INTERVAL_SECONDS = 10.0
PARAGRAPH_PAUSE_SECONDS = 0.15
CTRL_C_DOUBLE_PRESS_WINDOW_SECONDS = 2.0

# --- Fast Mode ---
FAST_LOADING_MESSAGE = "Thinking..."

# --- Search Settings ---
MAX_SEARCH_RESULTS = 5

# --- History ---
READLINE_HISTORY_LENGTH = 1000
