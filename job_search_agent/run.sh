#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Cron wrapper for job_search_agent/main.py
# Loads the .env file, activates the venv (if present), then runs the agent.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment variables from .env
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Activate virtual environment if it exists
if [ -d "$SCRIPT_DIR/venv" ]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/venv/bin/activate"
elif [ -d "$SCRIPT_DIR/.venv" ]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Run the agent
exec python "$SCRIPT_DIR/main.py" "$@"
