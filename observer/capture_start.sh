#!/usr/bin/env bash
# Observer rig, browser layer. Orchestrates EXISTING homebase primitives.
# It does NOT modify the recorder/dictation capture flow (see pipeline/record_session.py).
#
# Starts two things:
#   1. A dedicated debug-profile Chrome pointed at your app, CDP enabled.
#   2. chrome_observer.py, the read-only co-observer. It logs, as you click, every
#      JS error, failed API call (4xx/5xx), and route change, to JSONL under
#      <homebase>/.chrome-observer/. It never clicks, navigates, or injects.
#
# It does NOT start screen+voice recording -- that's pipeline/record_session.py (your
# recorder + your dictation provider; see docs/SETUP.md). See README.md for the full flow.
#
# Usage:  observer/capture_start.sh [url]
#         default url = $OBSERVER_URL, or http://localhost:3000
set -uo pipefail

HOMEBASE_ROOT="${HOMEBASE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OBS="$HOMEBASE_ROOT/observer/chrome_observer.py"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$HOME/.chrome-observer-debug"
PORT="${OBSERVER_CDP_PORT:-9222}"
URL="${1:-${OBSERVER_URL:-http://localhost:3000}}"

# The observer needs an interpreter that has websocket-client. Apple's /usr/bin/python3
# does NOT have it on most machines; the Homebrew python3 on PATH usually does. Fail loud
# rather than start a dead observer that silently captures nothing.
PYBIN="$(command -v python3)"
if ! "$PYBIN" -c "import websocket" 2>/dev/null; then
  echo "ERROR: $PYBIN has no websocket-client. The observer would fail silently."
  echo "Fix once:  $PYBIN -m pip install websocket-client"
  exit 1
fi

# 1. Debug Chrome. If CDP already answers, reuse the running instance.
if curl -sf "http://localhost:$PORT/json/version" >/dev/null 2>&1; then
  echo "CDP already up on :$PORT, reusing the running debug Chrome."
else
  echo "Launching debug-profile Chrome -> $URL"
  nohup "$CHROME" \
    --user-data-dir="$PROFILE" \
    --remote-debugging-port="$PORT" \
    --remote-allow-origins='*' \
    --no-first-run --no-default-browser-check \
    "$URL" >/tmp/homebase-observer-chrome.log 2>&1 &
  # curl handles the wait/backoff, no shell sleep needed.
  if ! curl -sf --retry 25 --retry-delay 1 --retry-all-errors --retry-connrefused \
        "http://localhost:$PORT/json/version" >/dev/null; then
    echo "ERROR: CDP did not come up on :$PORT. Is another Chrome holding the profile?"
    exit 1
  fi
  echo "CDP up: $(curl -s "http://localhost:$PORT/json/version" | "$PYBIN" -c 'import sys,json;print(json.load(sys.stdin)["Browser"])')"
fi

# 2. Observer. Replace any running instance so we do not double-attach.
pkill -f "chrome_observer.py" 2>/dev/null && echo "(replaced a running observer)"
cd "$HOMEBASE_ROOT"
OBSERVER_URL="$URL" nohup "$PYBIN" "$OBS" >/tmp/homebase-observer.out 2>&1 &
echo "Observer started (pid $!) with $PYBIN"
echo "Logging to .chrome-observer/ (attaches only to tabs matching \$OBSERVER_URL_FILTER, default: the host of $URL)."
echo
cat <<CHECKLIST
------------------------------------------------------------------------
BROWSER LAYER IS LIVE. Now start the capture layer only you can start:

  SCREEN + VOICE
    First confirm your recorder + dictation provider are ready:
      python3 pipeline/capture_healthcheck.py
    Then start the session:
      python3 pipeline/record_session.py start
    Record with your screen recorder (see providers/recorder/) and narrate with your
    dictation provider (see providers/transcript/). Verify it lands before you rely on it.

  Work your session in the debug Chrome window (already on $URL).

WHEN DONE:
  observer/capture_stop.sh
  python3 pipeline/record_session.py stop
  Export your recording into the session folder record_session.py stop prints.
------------------------------------------------------------------------
CHECKLIST
