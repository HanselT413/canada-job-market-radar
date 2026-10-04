#!/bin/bash
# Radar run: fetch new postings and refresh the exports.
# Called daily by the macOS LaunchAgent that scripts/install_daily_mac.sh sets up,
# or run it by hand:  bash scripts/run_radar.sh

set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
LOG_DIR="$REPO/data/logs"
LOG="$LOG_DIR/run_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"
cd "$REPO" || exit 1
export PYTHONPATH="$REPO/src"

FETCH_ARGS=""
[ "${RADAR_SAMPLE:-0}" = "1" ] && FETCH_ARGS="--sample"   # used by tests

{
  echo "=== Job radar run: $(date) ==="
  "$PYTHON" -m radar.pipeline fetch $FETCH_ARGS && "$PYTHON" -m radar.pipeline export
  status=$?
  echo "=== Finished with status $status: $(date) ==="
} >> "$LOG" 2>&1

# Keep the last 30 logs
ls -1t "$LOG_DIR"/run_*.log 2>/dev/null | tail -n +31 | while read -r old; do rm -f "$old"; done

exit "${status:-1}"
