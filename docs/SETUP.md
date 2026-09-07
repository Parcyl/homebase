# Setup (macOS)

homebase is macOS-first, the shipped `screen-studio` recorder and `vowen` dictation
adapters drive AppleScript against real macOS apps, and the menubar app is a SwiftBar
plugin. Everything below still works if you skip those adapters and use the `file` /
`file` defaults instead (bring your own `raw.mp4` and `transcript.json`, no Screen Studio
or Vowen required), which is the fastest path to a first run.

## 1. Prerequisites

| Tool | Why | Check |
|---|---|---|
| Python 3.11+ | both pipelines use `datetime.UTC` and modern type syntax (`X \| None`) | `python3 --version` |
| `ffmpeg` / `ffprobe` | frame/keyframe extraction (both pipelines) | `which ffmpeg ffprobe` (`brew install ffmpeg`) |
| Node 20+ | the invariant eval gate, `evals/run.js` (stdlib-only, no npm install needed, `evals/package.json` only sets `"type": "module"`) | `node --version` |
| An Anthropic API key | both pipelines call Claude | `ANTHROPIC_API_KEY` in `.env` |

Optional, only if you use the corresponding adapter:
- **Screen Studio** (`RECORDER=screen-studio`) + Accessibility/Automation permission for
  the app driving its AppleScript shortcuts.
- **Vowen** (`DICTATION_PROVIDER=vowen`) + the same Automation permission for its
  Hands-Free Mode shortcut.
- `mlx-whisper` (`pip install mlx-whisper`), last-resort transcription fallback if no
  transcript provider produced anything; used by both `pipeline_watcher.py:ensure_transcript`
  and `doc_generator.py`'s backup-audio path. Only relevant on Apple Silicon.
- `websocket-client` (`pip install websocket-client`), only for the optional `observer/`
  read-only Chrome co-observer. `observer/capture_start.sh` checks for it and prints the
  exact fix before launching, so you only need it if you use the observer.

## 2. Install

```bash
git clone <your-fork-url> homebase && cd homebase
cp env.example .env
```

Edit `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

Everything else in `env.example` has a working default: `DICTATION_PROVIDER=file`,
`RECORDER=file`, `CONTEXT_CONFIG=context/example-webapp.json`. That combination needs no
external tools at all, see **4. The zero-dependency path** below to smoke-test the whole
pipeline before wiring up a real recorder or dictation tool.

Python dependencies are split per component, not managed by one root install:

```bash
# intelligence/ (Pipeline B) manages its own venv automatically, see step 5b, nothing
# to install by hand here.

# pipeline/ (Pipeline A's doc_generator.py, and mlx-whisper fallback) has no venv of its
# own and is run as `python3 pipeline/<script>.py` directly. Install what it needs into
# whichever python3 you point PYTHON_BIN at:
pip install -r requirements.txt        # runtime deps for pipeline/ (anthropic)
pip install -r requirements-dev.txt    # optional, adds pytest to run pipeline/providers/menubar tests
# Optional extras (uncomment in requirements.txt or install directly):
#   pip install mlx-whisper       # transcription fallback, Apple Silicon only
#   pip install websocket-client  # only for the optional observer/ Chrome co-observer
```

## 3. Choose your recorder and dictation provider

Both are chosen in `.env`, independently of each other:

| `.env` var | Options | Default |
|---|---|---|
| `RECORDER` | `screen-studio`, `file` | `file` |
| `DICTATION_PROVIDER` | `vowen`, `wisprflow`, `file` | `file` |

**`file` / `file` (default, bring-your-own):** nothing to configure. Start a session,
record with whatever screen recorder you like, narrate however you like (or not at all , 
drop a transcript by hand), then drop the exported video and transcript into the session
folder yourself:

```bash
python3 pipeline/record_session.py start --slug my-walkthrough
# ... record + narrate ...
python3 pipeline/record_session.py stop
```

`stop` prints the session id and the exact path to drop your recording into. Then, into
that same `recordings/<session_id>/` folder, drop:
- `raw.mp4` (or any `*.mp4`, the largest one in the folder is adopted if `raw.mp4` isn't
  present)
- `transcript.json`, a JSON array of narration chunks, see `providers/transcript/file.py`
  for the exact schema:
  ```json
  [
    {"epoch": 1782623547.0, "text": "first part"},
    {"ts": "2026-06-01T20:31:00Z", "text": "second part"},
    {"text": "no timestamp, always included, can't be windowed"}
  ]
  ```
  `epoch` (unix seconds) or `ts` (ISO-8601) is optional per entry; an entry with neither is
  always included (the file already lives inside one session's folder, so it's trusted to
  belong to that session).

**`screen-studio`:** set `RECORDER=screen-studio` and, if it lives somewhere non-default,
`SCREEN_STUDIO_DIR` to where Screen Studio exports its `.screenstudio` bundles (default
`~/Documents/Screen Studio`). Note `record_session.py` only drives the `TranscriptProvider`
seam (narration), it never calls `RecorderAdapter.start()`/`.stop()`. Only the menubar app
does that (`menubar/lib/state.sh`'s `recorder_start`/`recorder_stop`), bringing Screen
Studio forward and sending its record shortcut. Without the menubar app, start/stop Screen
Studio yourself; `doc_generator.py` still finds the exported file via
`RecorderAdapter.resolve_master()`, it just doesn't control the app.

**`vowen`:** set `DICTATION_PROVIDER=vowen` and, if non-default,
`VOWEN_HISTORY_PATH` (default `~/Library/Application Support/Vowen/transcription-history.json`).

**`wisprflow`:** set `DICTATION_PROVIDER=wisprflow` and `WISPRFLOW_HISTORY_PATH`. This
adapter is **best-effort**, WisprFlow's on-disk schema wasn't confirmed when it was
ported; treat it as a starting point and verify it reads your actual history file before
relying on it.

## 4. The zero-dependency path (recommended first run)

With `RECORDER=file` and `DICTATION_PROVIDER=file` (the defaults), you don't need Vowen,
Screen Studio, or the menubar app to prove the pipeline works:

```bash
python3 pipeline/record_session.py start --slug smoke-test
# note the session id it prints, e.g. 2026-09-06T10-00-00-smoke-test
```

Now drop into `recordings/2026-09-06T10-00-00-smoke-test/`:
- any short screen recording as `raw.mp4`
- a `transcript.json` following the schema in step 3

Then run whichever pipeline you want to try (see step 5).

## 5. Run a pipeline

### 5a. Pipeline A, walkthrough → bug report (`doc_generator.py`)

No separate service required, just Claude:

```bash
python3 pipeline/doc_generator.py --session 2026-09-06T10-00-00-smoke-test
# or process everything pending once:
python3 pipeline/doc_generator.py --once
# or run as a polling daemon (what com.homebase.docgen.watcher runs):
python3 pipeline/doc_generator.py --watch
```

Uses whichever `context_config` `CONTEXT_CONFIG` points at (default
`context/example-webapp.json`) for zones/severities/prompt, see `docs/ARCHITECTURE.md §4`
to write your own instead of the generic 3-zone example. Output lands directly in the
session folder: `PRD.md`, `DIGEST.md`, `INDEX.md`, `workflow-map.md`, `TEAM_BRIEF.md`,
`bugs/*.md`, `screenshots/`.

### 5b. Pipeline B, workflow → PRD/handoff (`pipeline_watcher.py` + `intelligence/`)

Two processes: the intelligence spine (Claude classify/extract/generate) and the watcher
that feeds it.

```bash
# terminal 1, the intelligence spine (creates its own .venv on first run, then serves on
# LANGGRAPH_HOST:LANGGRAPH_PORT from .env)
cd intelligence && ./run.sh

# terminal 2, the watcher, from the repo root
python3 pipeline/pipeline_watcher.py
# or once:
python3 pipeline/pipeline_watcher.py --once
```

`run.sh` refuses to start without an `intelligence/.env`, copy the repo-root `.env` there
too, or symlink it (`ln -s ../.env intelligence/.env`); it reads `ANTHROPIC_API_KEY`,
`ANTHROPIC_MODEL`, `HOMEBASE_ROOT`, `LANGGRAPH_HOST`, `LANGGRAPH_PORT`, `LOG_LEVEL`.
Output lands in `prds/<session_id>/{PRD.md, handoff-prompt.md}` plus
`recordings/<session_id>/workflow-map.md` and a `workflows/library/...pattern.md` entry , 
see `docs/ARCHITECTURE.md §1` for the full path table.

You do not need to run both pipelines. Pick the one that answers your question, or run
both against the same `recordings/` folder if you want both doc sets.

## 6. The menubar app (optional, one-click Start/Stop)

```bash
brew install --cask swiftbar
mkdir -p ~/SwiftBar
ln -sfn "$(pwd)/menubar/homebase_status.10s.py" ~/SwiftBar/homebase_status.10s.py
chmod +x menubar/actions/*.sh menubar/homebase_status.10s.py
```

Open SwiftBar → Preferences → Plugins Folder → `~/SwiftBar`. **Point it at `~/SwiftBar`,
not `menubar/` directly**, SwiftBar loads every executable it finds, including
`lib/`/`actions/`/`tests/`, as separate menu bar items. Full detail, the environment
variables it respects, and the `agents/pipeline-state.json` contract it reads: `menubar/README.md`.

Test it without touching a real recorder/dictation tool:

```bash
python3 -m pytest menubar/tests -q
```

## 7. Background services (launchd, optional)

Four plists under `menubar/launchd/`, the pipeline watcher, the doc-generator watcher, the
intelligence spine, and an independent mic-backup daemon. None are required for the menubar
app's Start/Stop buttons to work; they're what turns a stopped session into a finished doc
set automatically instead of you running step 5 by hand, plus what "Restart Services" in
the menubar dropdown controls. Install steps, the `__HOMEBASE_ROOT__`/`__PYTHON_BIN__`
placeholder substitution, and required macOS permissions (Accessibility/Automation per
adapter, Microphone for the backup daemon): `menubar/launchd/README.md`.

## 8. Verify

```bash
node evals/run.js
```

Runs the four invariant evals against the shipped engine (`canonical-doc-set`,
`team-brief-complete`, `live-session-never-processed`, `no-identifier-leak`), dependency-free,
exits non-zero on failure. This is also what CI runs on every PR (`.github/workflows/ci.yml`).
