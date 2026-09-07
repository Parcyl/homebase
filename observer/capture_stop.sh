#!/usr/bin/env bash
# Stop the browser layer of the observer rig and summarize what it caught.
# Does not touch the screen/voice recording -- that's pipeline/record_session.py stop.
set -uo pipefail

HOMEBASE_ROOT="${HOMEBASE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OBSDIR="$HOMEBASE_ROOT/.chrome-observer"
PYBIN="$(command -v python3)"

if pkill -f "chrome_observer.py" 2>/dev/null; then
  echo "Observer stopped."
else
  echo "(no observer was running)"
fi

LOG="$(cat "$OBSDIR/current.log" 2>/dev/null || true)"
[ -f "$LOG" ] || LOG="$(ls -t "$OBSDIR"/observe-*.jsonl 2>/dev/null | head -1)"
echo "Observer log: $LOG"

"$PYBIN" - "$LOG" <<'PY'
import json, sys
from collections import Counter
c = Counter()
try:
    for ln in open(sys.argv[1]):
        try: c[json.loads(ln).get("kind")] += 1
        except Exception: pass
    print("Captured event counts:", dict(c))
except Exception as e:
    print("could not summarize:", e)
PY

echo
echo "The screen+voice layer is stopped separately:"
echo "  python3 pipeline/record_session.py stop"
echo "  then export your recording into the session folder it prints."
echo
echo "Then ask Claude to STITCH: turn $LOG into an observer-findings.md alongside the"
echo "recorded session for one full-context record."
