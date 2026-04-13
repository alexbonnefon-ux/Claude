#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Setup script: installs dependencies and adds cron jobs.
#
# Usage:
#   chmod +x setup_cron.sh run.sh
#   ./setup_cron.sh
#
# The cron will run at 08:00 and 18:00 Paris time every day.
# Paris is Europe/Paris (UTC+1 in winter, UTC+2 in summer / CEST).
# We use the CRON_TZ variable which is supported by Vixie cron (most Linux).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
RUN_SH="$SCRIPT_DIR/run.sh"
LOG_FILE="$SCRIPT_DIR/cron.log"

# ── 1. Check prerequisites ───────────────────────────────────────────────────
echo "► Checking prerequisites…"
command -v "$PYTHON" >/dev/null 2>&1 || { echo "Error: python3 not found"; exit 1; }
command -v crontab >/dev/null 2>&1  || { echo "Error: crontab not found"; exit 1; }

# ── 2. Create / activate virtual environment ─────────────────────────────────
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo "► Creating virtual environment…"
    "$PYTHON" -m venv "$SCRIPT_DIR/venv"
fi

echo "► Activating virtual environment…"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/venv/bin/activate"

# ── 3. Install Python dependencies ──────────────────────────────────────────
echo "► Installing Python dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

# ── 4. Install ChromeDriver (via webdriver-manager on first run) ─────────────
echo "► Pre-downloading ChromeDriver…"
python -c "from webdriver_manager.chrome import ChromeDriverManager; ChromeDriverManager().install()" \
    2>/dev/null || echo "  (webdriver-manager will download ChromeDriver on first run)"

# ── 5. Copy .env if it doesn't exist ────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo ""
    echo "┌─────────────────────────────────────────────────────────┐"
    echo "│  IMPORTANT: Edit .env before the agent runs!            │"
    echo "│  Set SMTP_USER, SMTP_PASSWORD (Gmail App Password),     │"
    echo "│  and optionally LINKEDIN_EMAIL / LINKEDIN_PASSWORD.     │"
    echo "└─────────────────────────────────────────────────────────┘"
    echo ""
fi

# ── 6. Make run.sh executable ────────────────────────────────────────────────
chmod +x "$RUN_SH"

# ── 7. Install cron jobs ─────────────────────────────────────────────────────
echo "► Installing cron jobs (08:00 and 18:00 Paris time)…"

CRON_MARKER="# job-search-agent"
CRON_ENTRY_AM="0 8 * * * TZ=Europe/Paris $RUN_SH >> $LOG_FILE 2>&1  $CRON_MARKER"
CRON_ENTRY_PM="0 18 * * * TZ=Europe/Paris $RUN_SH >> $LOG_FILE 2>&1  $CRON_MARKER"

# Remove any existing agent entries, then add fresh ones
(
    crontab -l 2>/dev/null | grep -v "$CRON_MARKER" || true
    echo "CRON_TZ=Europe/Paris"
    echo "$CRON_ENTRY_AM"
    echo "$CRON_ENTRY_PM"
) | crontab -

echo "► Cron jobs installed. Current crontab:"
crontab -l | grep -A1 "$CRON_MARKER" || crontab -l | tail -5

echo ""
echo "✓ Setup complete!"
echo ""
echo "  Test a manual run now with:"
echo "    $RUN_SH"
echo ""
echo "  View logs:"
echo "    tail -f $LOG_FILE"
echo "    tail -f $SCRIPT_DIR/agent.log"
