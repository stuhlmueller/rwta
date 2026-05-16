#!/usr/bin/env bash
# Build (if needed) and launch the native RWTA Mac app.
#
# Required env:
#   ANTHROPIC_API_KEY  - Claude API key (mandatory)
#   OPENAI_API_KEY     - OpenAI key for scene image generation (optional)
#
# Optional env:
#   RWTA_FAST=1        - use claude-sonnet for narration (cheaper, faster)
#   BUILD=release      - swift build -c release (default: debug)
#
# This script must live in ./mac/ inside the rwta repo.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
mac_dir="$(pwd)"
project_dir="$(cd .. && pwd)"

config="${BUILD:-debug}"

echo "Building Swift app ($config)…" >&2
swift build -c "$config"

bin_path="$(swift build -c "$config" --show-bin-path)/RWTA"
if [[ ! -x "$bin_path" ]]; then
    echo "Could not find built executable at $bin_path" >&2
    exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "WARNING: ANTHROPIC_API_KEY is not set; the backend will fail." >&2
fi

export RWTA_PROJECT_DIR="$project_dir"

exec "$bin_path" "$@"
