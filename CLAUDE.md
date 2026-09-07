# homebase

A local pipeline that turns a recorded work session (screen video + spoken narration) into a
structured doc set. Bring-your-own dictation and screen recorder via pluggable adapters.

## Layout
- `pipeline/`: the watcher + capture/session logic (`pipeline_watcher.py`, `record_session.py`,
  `capture_*`, `doc_generator.py`).
- `providers/transcript/`: `TranscriptProvider` interface + adapters (`vowen`, `wisprflow`, `file`).
- `providers/recorder/`: `RecorderAdapter` interface + adapters (`screen_studio`, `file`).
- `intelligence/`: the LangGraph spine (classify → extract → generate).
- `menubar/`: macOS SwiftBar one-click record/stop app.
- `observer/`: optional read-only Chrome co-observer.
- `context/`: `context_config` schema + example (product zones, severities, system prompt).
- `templates/`: output doc templates.
- `evals/run.js`: invariant gate; `.github/workflows/ci.yml`: CI.

## Rules
- Configuration comes from `.env` (see `env.example`); never hardcode paths, keys, or tool names
  outside a tool's own adapter file.
- The pipeline talks to the `TranscriptProvider` / `RecorderAdapter` interfaces, never to a tool
  directly. New tool = new adapter, not a change to the pipeline.
- Every invariant in `evals/run.js` must be proven to FAIL on an injected violation.
- macOS-first; keep platform-specific calls inside adapters and document the seam.
