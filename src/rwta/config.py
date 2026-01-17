"""Centralized configuration constants for RWTA."""

from zoneinfo import ZoneInfo

# --- Timezone ---
# Use local timezone by default, but make it explicit
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")  # Override per deployment if needed

# --- API Timeouts (seconds) ---
GEOLOCATION_TIMEOUT = 5.0
WEATHER_TIMEOUT = 5.0
SEARCH_TIMEOUT = 10.0

# --- Cache Settings ---
WEATHER_CACHE_TTL_SECONDS = 300  # 5 minutes
SEARCH_CACHE_TTL_SECONDS = 300  # 5 minutes (per-session cache)

# --- LLM Settings ---
MAX_CONTEXT_TOKENS = 180_000  # Leave room for response within Opus's 200k limit
MAX_RESPONSE_TOKENS = 4096
SUMMARIZATION_BUFFER_TOKENS = 1000  # Extra space for summary message

# Token estimation when API unavailable: ~4 characters per token
TOKEN_CHAR_ESTIMATE_DIVISOR = 4

# --- Pricing (per million tokens, as of 2025) ---
OPUS_INPUT_PRICE_PER_MILLION = 15.0
OPUS_OUTPUT_PRICE_PER_MILLION = 75.0
SONNET_INPUT_PRICE_PER_MILLION = 3.0
SONNET_OUTPUT_PRICE_PER_MILLION = 15.0

# --- Models ---
PRIMARY_MODEL = "claude-opus-4-5"
FAST_MODEL = "claude-sonnet-4-5"

# --- UI Settings ---
TYPEWRITER_DELAY_SECONDS = 0.05
LOADING_REFRESH_INTERVAL_SECONDS = 10.0
PARAGRAPH_PAUSE_SECONDS = 0.15
CTRL_C_DOUBLE_PRESS_WINDOW_SECONDS = 2.0

# --- Search Settings ---
MAX_SEARCH_RESULTS = 5
SEARCH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# --- History ---
READLINE_HISTORY_LENGTH = 1000
