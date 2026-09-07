# launchd services

Four optional background services. None of them are required to use the menu bar app's
Start/Stop Session actions -- those just write session markers and drive your configured
recorder/dictation provider directly. These services are what turn a stopped session into
a finished doc set, and what the mic backup and "Restart Services" action need.

| Label | Runs | RunAtLoad / KeepAlive | What it does |
|---|---|---|---|
| `com.homebase.pipeline.watcher` | `pipeline/pipeline_watcher.py` | true / true | Polls `recordings/`, POSTs each finished session to the intelligence spine's `/intake`. |
| `com.homebase.docgen.watcher` | `pipeline/doc_generator.py --watch` | true / true | Polls `recordings/`, turns each session into PRD/DIGEST/workflow-map/bugs directly (no separate service). |
| `com.homebase.intelligence` | `intelligence/run.sh` | true / true | The FastAPI/LangGraph service `pipeline_watcher` posts to. |
| `com.homebase.audiobackup` | `pipeline/audio_backup_daemon.py` | false / false | Idle until kickstarted by `menubar/actions/start_session.sh`; records an independent mic backup under its own launchd Microphone permission. |

You do not need both watchers -- pick the pipeline that fits (see `pipeline/doc_generator.py`
and `intelligence/` docstrings for the trade-off) or run both against the same `recordings/`
folder. `com.homebase.audiobackup` is only useful if you've configured a dictation provider
worth backing up (see `providers/transcript/`).

## Install

These plists use two placeholders you must substitute before loading them:

- `__HOMEBASE_ROOT__` -- absolute path to this repo checkout.
- `__PYTHON_BIN__` -- absolute path to the Python 3 interpreter you want the services to
  run under (`which python3`).
- `__FFMPEG_BIN__` / `__FFPROBE_BIN__` -- absolute paths to `ffmpeg`/`ffprobe`
  (`which ffmpeg`), only used by the watcher and audiobackup plists.

```bash
HOMEBASE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # or wherever you cloned this repo
PYTHON_BIN="$(command -v python3)"
FFMPEG_BIN="$(command -v ffmpeg)"
FFPROBE_BIN="$(command -v ffprobe)"

mkdir -p ~/Library/LaunchAgents
for plist in menubar/launchd/com.homebase.*.plist; do
    name="$(basename "$plist")"
    sed -e "s#__HOMEBASE_ROOT__#$HOMEBASE_ROOT#g" \
        -e "s#__PYTHON_BIN__#$PYTHON_BIN#g" \
        -e "s#__FFMPEG_BIN__#$FFMPEG_BIN#g" \
        -e "s#__FFPROBE_BIN__#$FFPROBE_BIN#g" \
        "$plist" > ~/Library/LaunchAgents/"$name"
    launchctl load ~/Library/LaunchAgents/"$name"
done
```

Uninstall the same way with `launchctl unload` and remove the file from
`~/Library/LaunchAgents`.

Logs land at `HOMEBASE_ROOT/agents/<service>.std{out,err}.log` -- also what
`menubar/actions/tail_logs.sh` tails, and `menubar/actions/restart_services.sh` kickstarts
the watcher labels and restarts `com.homebase.intelligence` by killing its port and
re-running `run.sh`.

## Required permissions

System Settings -> Privacy & Security -> Accessibility / Automation, whichever your
configured `RECORDER` and `DICTATION_PROVIDER` adapters need (Screen Studio + System Events
for `screen-studio`, Vowen + System Events for `vowen`; `file` adapters need neither).
`com.homebase.audiobackup` additionally needs its own Microphone permission, granted the
first time it runs (grant it to the process at `__PYTHON_BIN__`, not to SwiftBar -- that's
the whole reason this runs as its own launchd agent, see pipeline/audio_backup_daemon.py).
