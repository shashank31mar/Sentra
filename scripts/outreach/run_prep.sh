#!/bin/bash
# Wrapper the launchd timer invokes at 8 AM. Keeps the plist simple and gives us
# one place to set env + capture logs. Runs prep only — never sends.
set -euo pipefail

REPO="/Users/shshgup/code/security-mvp/Sentra"
VENV_PY="$REPO/scripts/outreach/venv/bin/python"
LOG_DIR="$REPO/scripts/outreach/state/logs"
mkdir -p "$LOG_DIR"

cd "$REPO"
echo "=== prep run $(date) ===" >> "$LOG_DIR/prep.log"
"$VENV_PY" scripts/outreach/prep_daily.py >> "$LOG_DIR/prep.log" 2>&1
echo "=== prep exit $? $(date) ===" >> "$LOG_DIR/prep.log"
