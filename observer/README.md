# Observer

Work a live session in your app and capture everything, with full context.

This ties together two capture layers:

1. **Screen + voice** — homebase's own recorder + dictation seams (see
   `providers/recorder/`, `providers/transcript/`, `pipeline/record_session.py`).
2. **Browser technical layer** — `chrome_observer.py`, a read-only Chrome co-observer that
   logs every JS error, failed API call, and route change as you click. Attaches only to
   tabs matching `$OBSERVER_URL_FILTER` (default: the host of `$OBSERVER_URL`).

The durable record is the recording plus the observer log. The two run at once and get
stitched at the end.

## Run it

**1. Bring up the browser layer (one command):**

    observer/capture_start.sh [url]

`url` defaults to `$OBSERVER_URL`, or `http://localhost:3000`. This launches a dedicated
debug-profile Chrome (a separate profile at `~/.chrome-observer-debug`, isolated from your
everyday browsing) and starts the observer. It then prints the checklist for the recording
layer only you can start.

**2. Start screen + voice.**
Confirm your recorder and dictation provider are ready:

    python3 pipeline/capture_healthcheck.py

Then:

    python3 pipeline/record_session.py start

Record with your screen recorder and narrate with your dictation provider. Verify it lands
before you rely on it -- a running tool proves nothing about whether narration is landing;
see `providers/transcript/`'s health checks.

**3. Work your session** in the debug Chrome window.

**4. Stop:**

    observer/capture_stop.sh          # browser layer + event summary
    python3 pipeline/record_session.py stop
    # export your recording into the session folder record_session.py stop prints

Then ask Claude to stitch the observer log and the recorded session into one full-context
record.

## Know before you go in

- **The observer is read-only.** It never clicks, navigates, or injects anything -- it only
  listens over CDP.
- **The dedicated debug profile matters.** Reusing your everyday Chrome profile risks CDP
  attaching to tabs you didn't intend to observe, or losing your normal session state to the
  `--remote-debugging-port` flag.
- **A dictation tool can look healthy while its capture is dead.** Verify by artifact (does
  a real narration entry land), not by whether the process is running.

## What each piece writes

- Observer JSONL: `<homebase>/.chrome-observer/observe-<stamp>.jsonl`
- Screen+voice session: `<homebase>/recordings/<id>/` (raw.mp4, transcript.json, keyframes)
