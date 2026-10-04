#!/bin/bash
# Set up (or remove) a daily automatic run on macOS using a LaunchAgent.
#
#   bash scripts/install_daily_mac.sh            # install: every day at 9:07 am
#   bash scripts/install_daily_mac.sh 9 13 18    # install: daily at 9:07, 13:07 and 18:07
#   bash scripts/install_daily_mac.sh uninstall  # remove
#
# Adzuna's free limit is 2,500 calls a month; one run uses about 20-25 calls,
# so up to 3 runs a day fits. Keep manual runs to a minimum on top of that.
#
# If the Mac is asleep at that time, the run happens when it wakes up.
# If it is shut down, that day's run is skipped.

set -eu
LABEL="com.jobradar.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Weekly run removed."
  exit 0
fi

if [ "$(uname)" != "Darwin" ]; then
  echo "This script is for macOS." >&2
  exit 1
fi

# macOS blocks background jobs from reading Downloads, Desktop and Documents
# unless they are given Full Disk Access. A folder like ~/projects avoids that.
case "$REPO" in
  "$HOME/Downloads"*|"$HOME/Desktop"*|"$HOME/Documents"*)
    echo "The project is in a protected folder: $REPO"
    echo "macOS will block the background run there. Move it first, for example:"
    echo ""
    echo "  mkdir -p ~/projects && mv \"$REPO\" ~/projects/"
    echo "  cd ~/projects/$(basename "$REPO") && bash scripts/install_daily_mac.sh"
    exit 1
    ;;
esac

if [ ! -f "$REPO/.env" ]; then
  echo "No .env file found in $REPO (it holds your Adzuna key). Add it first." >&2
  exit 1
fi

PYTHON="$(command -v python3)"
echo "Using Python: $PYTHON"
"$PYTHON" -c "import pandas, yaml, requests, statsmodels" || {
  echo "Missing packages. Run: pip3 install -r requirements.txt" >&2
  exit 1
}

HOURS="${*:-9}"
INTERVALS=""
for h in $HOURS; do
  case "$h" in
    ''|*[!0-9]*) echo "Hours must be numbers 0-23, e.g. 9 13 18" >&2; exit 1 ;;
  esac
  [ "$h" -le 23 ] || { echo "Hour out of range: $h" >&2; exit 1; }
  INTERVALS="$INTERVALS    <dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>7</integer></dict>
"
done
RUNS=$(echo $HOURS | wc -w | tr -d ' ')
[ "$RUNS" -le 3 ] || { echo "More than 3 runs a day would exceed Adzuna's monthly limit." >&2; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/data/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/scripts/run_radar.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHON</key>
    <string>$PYTHON</string>
  </dict>
  <key>StartCalendarInterval</key>
  <array>
$INTERVALS  </array>
  <key>StandardErrorPath</key>
  <string>$REPO/data/logs/launchd_error.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"

echo ""
echo "Done. The radar will run every day at minute 7 of hour(s): $HOURS"
echo "Logs:            $REPO/data/logs/"
echo "Test it now:     launchctl kickstart $DOMAIN/$LABEL"
echo "Remove it:       bash scripts/install_daily_mac.sh uninstall"
