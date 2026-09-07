# homebase Menu Bar

A SwiftBar plugin: a one-click front door to homebase plus a passive live gauge of the
pipeline. Pure text scripts in this repo. No Xcode, no notarization, no Swift.

## What it does

- **Title color** reflects health: green idle, yellow processing, red error/service down/
  capture failure.
- **Dropdown** shows current stage, an optional activity feed, and one-click actions:
  - Start Session / Stop Session (toggles based on state)
  - Copy Handoff Prompt (latest, into the clipboard)
  - Open Last PRD
  - Open Last Digest
  - Open Inbox in Finder
  - Tail Logs in Terminal
  - Restart Services

## Install

```bash
brew install --cask swiftbar
```

> **CRITICAL:** Point SwiftBar at a **dedicated folder** containing only a symlink to the
> plugin. Do NOT point it at this `menubar/` directory. SwiftBar loads every executable it
> finds (including in subdirectories) as a separate menu bar item; pointing it here would
> surface stray menu bar entries for everything under `lib/`, `actions/`, and `tests/`.

Set up the dedicated plugin folder (adjust the source path to wherever you cloned this repo):

```bash
cd ~ && mkdir -p SwiftBar && ln -sfn /path/to/homebase/menubar/homebase_status.10s.py SwiftBar/homebase_status.10s.py
```

Open SwiftBar -> Preferences -> "Plugins Folder" -> set to `~/SwiftBar`. Toggle "Run at login".

Make sure everything is executable (run once):

```bash
chmod +x /path/to/homebase/menubar/actions/*.sh /path/to/homebase/menubar/homebase_status.10s.py
```

## Folder layout

```
menubar/
├── homebase_status.10s.py    <- the only file you ever symlink into SwiftBar
├── README.md
├── lib/                       <- shared helpers (state.py for the plugin, state.sh for the action scripts)
├── actions/                   <- 8 shell scripts the plugin invokes on click
├── launchd/                   <- optional background services (watchers, intelligence, mic backup); see launchd/README.md
└── tests/                     <- pytest suite
```

The plugin resolves its own location via `Path(__file__).resolve()`, so even when invoked
through the SwiftBar symlink it finds `actions/` and `lib/` back here in this directory.
Action scripts resolve `pipeline/*.py` the same way, relative to their own fixed location on
disk (`menubar/actions/../..` = repo root) -- never via `$HOMEBASE_ROOT`, which names where
session *data* lives and can be pointed elsewhere (see `lib/state.sh`).

## Recording control: the seams, not a tool

Start/Stop Session never talk to a screen recorder or dictation tool directly. They drive:

- **`RecorderAdapter`** (`providers/recorder/`) via `recorder_start`/`recorder_stop` in
  `lib/state.sh` -- `RECORDER=screen-studio` drives Screen Studio's AppleScript shortcut;
  `RECORDER=file` (default) is a no-op, you drop your own recording into the session folder.
- **`TranscriptProvider`**'s *optional* `start()`/`stop()` control (`dictation_start`/
  `dictation_stop`) -- called ONLY if the configured provider has one. Today only
  `VowenProvider` (`providers/transcript/vowen.py`) implements it, driving Vowen's
  Hands-Free Mode shortcut via AppleScript (`providers/transcript/vowen_start.applescript` /
  `vowen_stop.applescript`). `FileProvider` and `WisprFlowProvider` have no capture to
  control at all, so this is silently a no-op for them -- there is nothing to toggle when
  you're narrating by hand or into a tool this repo only reads from.

Configure both via `.env` (`RECORDER`, `DICTATION_PROVIDER`, see `env.example`). A new
recorder or dictation tool is a new adapter under `providers/`, never a change to this app.

## Environment variables

The shell scripts respect these env vars.

| Var | Default | What it controls |
|---|---|---|
| `HOMEBASE_ROOT` | this repo checkout | Where session data (`recordings/`, `prds/`, `inbox/`, `agents/`) lives |
| `PYTHON_BIN` | `python3` | Python for state writes and pipeline script invocations |
| `LANGGRAPH_URL` | `http://127.0.0.1:8080` | Intelligence spine health endpoint |
| `LANGGRAPH_PORT` | `8080` | Port killed by Restart Services |
| `HOMEBASE_EDITOR_APP` | `Visual Studio Code` | App used to open PRDs/digests |
| `HOMEBASE_DRY_RUN` | `0` | Set to `1` to disable app launches/side effects (used by the test suite) |
| `RECORDER`, `DICTATION_PROVIDER` | `file`, `file` | Which adapters `recorder_start`/`dictation_start` drive -- see `env.example` |

## Dry run for testing

Every action script honors `HOMEBASE_DRY_RUN=1` and exits without launching apps or driving
a real recorder/dictation tool. Used by the test suite:

```bash
cd /path/to/homebase
python3 -m pytest menubar/tests -q
```

## Pipeline state contract

The plugin reads `agents/pipeline-state.json` -- the single state contract documented in
`intelligence/app/pipeline_state.py`. Start/Stop Session write `recording`/`ready`; whichever
watcher you have running (`pipeline/pipeline_watcher.py` or `pipeline/doc_generator.py
--watch`) advances it further if it's wired to this contract (`pipeline_watcher.py` is;
`doc_generator.py` currently tracks its own state in `doc-generator-state.json` at the repo
root -- see that file's `update_state` docstring). The schema:

```json
{
  "stage": "idle|recording|ready|transcribing|classifying|extracting|grounding|comparing|generating|filing|complete|error",
  "session_id": "YYYY-MM-DDTHH-MM-SS[-slug]",
  "started_at": "ISO-8601 UTC",
  "updated_at": "ISO-8601 UTC",
  "last_prd": "prds/<session_id>/PRD.md",
  "last_handoff": "prds/<session_id>/handoff-prompt.md",
  "message": "human-readable status",
  "error": "set when stage=error, otherwise null"
}
```

If you ever see "State file unreadable" or "Unknown" in the menu bar, click Restart Services.
That resets `pipeline-state.json` to `{stage: "idle"}`.

### Optional activity feed

"Recent activity" tails `agents/activity-log.md` if it exists (see
`recent_log_lines` in `lib/state.py`). Nothing in this repo writes that file by default --
it's a bring-your-own feed, the same philosophy as the `file` recorder/dictation adapters:
wire up anything that appends `- [...]` lines and the dropdown will show them.
