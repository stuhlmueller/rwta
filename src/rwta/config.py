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
# max_tokens is a hard cap on total output INCLUDING thinking tokens. With
# adaptive thinking enabled the model may spend several hundred to a few
# thousand tokens reasoning before emitting visible text, so we leave room.
MAX_RESPONSE_TOKENS = 16_000
SUMMARIZATION_BUFFER_TOKENS = 1000  # Extra space for summary message

# Token estimation when API unavailable: ~4 characters per token
TOKEN_CHAR_ESTIMATE_DIVISOR = 4

# --- Pricing (per million tokens, verified 2026-04 for Claude 4.7 family) ---
# Opus 4.7: $5 input / $25 output (per platform.claude.com)
# Sonnet 4.6: $3 input / $15 output
# Prompt caching: cache writes are 1.25x base input, cache reads are 0.1x.
OPUS_INPUT_PRICE_PER_MILLION = 5.0
OPUS_OUTPUT_PRICE_PER_MILLION = 25.0
SONNET_INPUT_PRICE_PER_MILLION = 3.0
SONNET_OUTPUT_PRICE_PER_MILLION = 15.0
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

# --- Anthropic client ---
# SDK retries with exponential backoff on transient errors (5xx, 408, 429,
# connection issues). Default is 2; bump for a more resilient game session.
ANTHROPIC_MAX_RETRIES = 4

# --- Models ---
PRIMARY_MODEL = os.getenv("RWTA_PRIMARY_MODEL", "claude-opus-4-7")
FAST_MODEL = os.getenv("RWTA_FAST_MODEL", "claude-sonnet-4-6")

# --- Adaptive thinking ---
# Opus 4.7 only supports adaptive thinking (manual budget_tokens is rejected
# with HTTP 400). Adaptive auto-enables interleaved thinking, which lets the
# model reason between tool calls — valuable for our search/time/location
# tool loop. Off by default would forfeit that quality, so default ON.
# Set RWTA_THINKING=off to disable (e.g., to save output-token spend).
THINKING_MODE = os.getenv("RWTA_THINKING", "adaptive").strip().lower()
# Effort guidance for adaptive thinking. "high" is the SDK default and means
# Claude almost always thinks; "low"/"medium" let it skip thinking on simple
# turns, trading depth for latency.
THINKING_EFFORT = os.getenv("RWTA_THINKING_EFFORT", "medium").strip().lower()

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
