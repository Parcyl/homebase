# Architecture Codemap

**Last Updated:** 2026-09-07

**Entry Points:** pipeline/record_session.py (start/stop control), pipeline/doc_generator.py (Pipeline A), pipeline/pipeline_watcher.py + intelligence/run.sh (Pipeline B)

## System Overview

homebase is a local session-capture system: turn a recorded work session (screen video plus spoken narration) into developer-ready documentation. The system has one pluggable capture layer feeding two independent analysis pipelines.

```
User Recording (screen video + narration via RecorderAdapter + TranscriptProvider)
                              |
                              v
                  Shared Capture Layer
                  (providers/recorder/)
                  (providers/transcript/)
                 (pipeline/record_session.py)
                              |
                ____________________________
               /                            \
              v                              v
        Pipeline A                    Pipeline B
        (doc_generator.py)         (pipeline_watcher.py)
        One multimodal call         Intelligence spine
        Via context_config          (intelligence/app)
              |                           |
              v                           v
        recordings/<session_id>/    prds/<session_id>/
        DIGEST.md, PRD.md,         PRD.md,
        workflow-map.md,           handoff-prompt.md,
        bugs/*.md                  workflows/library/...
```

## Two Pipelines

### Pipeline A: doc_generator.py (Bug Triage + PRD)

**Purpose:** "What is broken, what was asked for, sorted by zone and severity"

**Flow:** Session record -> ffmpeg keyframes -> one multimodal Claude call -> structured docs

**Location:** pipeline/doc_generator.py (lines 1-50 define defaults and orchestration)

**Key behavior:**
- Extracts one screenshot per SHOT_INTERVAL_S (15s), up to MAX_SHOTS (48) on disk
- Sends at most MAX_SHOTS_TO_CLAUDE (24) downsampled frames to Claude in one call
- Uses context_config (context/example-webapp.json) to define product zones/severities
- Writes DIGEST.md, PRD.md, INDEX.md, workflow-map.md, TEAM_BRIEF.md, plus bugs/*.md
- Runs continuously with --watch or one-shot with --session <id>
- Manages concurrency via per-session locks; stale locks older than LOCK_STALE_S (1800s) are stolen

**Key files:**
- pipeline/doc_generator.py: main orchestrator, frame extraction, Claude calls, doc writing
- context/example-webapp.json: product zones/severity definitions
- context/schema.md: schema for context_config

### Pipeline B: pipeline_watcher.py + intelligence/ (Workflow Pattern + Handoff)

**Purpose:** "What workflow did I just do, spec'd well enough for an agent to build it"

**Flow:** Session record -> ffmpeg keyframe extraction -> POST /intake to LangGraph spine -> classify -> extract -> ground -> compare -> generate -> write PRD + handoff + workflow pattern to disk

**Watcher location:** pipeline/pipeline_watcher.py

**Spine location:** intelligence/app/main.py

**Key behavior:**
- Polls recordings/ for new raw.mp4 files
- Extracts a fixed KEYFRAME_COUNT (15) evenly-spaced frames independent of video length
- Defers to record_session.py if transcript.json hasn't been written yet
- POSTs IntakeRequest to http://127.0.0.1:8080/intake (LangGraph FastAPI service)
- Writes IntakeResponse to inbox/<session_id>.json for downstream consumers
- Writes workflow-map.md, prds/<session_id>/PRD.md, handoff-prompt.md, workflows/library/<deal_type>/<sub_type>/<intent_slug>/pattern.md
- Appends pattern_match results to memory/patterns.md

**Watcher key files:**
- pipeline/pipeline_watcher.py: polling loop, keyframe extraction, /intake POST
- intelligence/run.sh: starts the FastAPI service

**Spine key files:**
- intelligence/app/main.py: FastAPI /intake endpoint (line 56)
- intelligence/app/graph.py: LangGraph node wiring (classify -> extract -> ground -> compare -> generate -> file_outputs)
- intelligence/app/nodes/: six sequential processing steps

## Shared Capture Layer: Pluggable Adapters

Neither pipeline talks to a screen recorder or dictation tool directly. Two Protocol interfaces sit in between.

### RecorderAdapter

**Protocol location:** providers/recorder/adapter.py (lines 20-45)

**Shipped adapters:**
- ScreenStudioRecorder (providers/recorder/screen_studio.py): AppleScript-driven Screen Studio control via start/stop applescripts
- FileRecorder (providers/recorder/file.py, default): brings-your-own .mp4; start/stop are no-ops

**Interface:**
- start(session_dir) -> None
- stop(session_dir) -> None
- resolve_master(session_start_epoch, session_dir) -> Path | None

**Registration:** providers/recorder/__init__.py, selected by RECORDER env var

### TranscriptProvider

**Protocol location:** providers/transcript/provider.py (lines 74-98)

**Shipped adapters:**
- VowenProvider (providers/transcript/vowen.py): reads ~/Library/Application Support/Vowen/transcription-history.json, only adapter with optional start/stop control
- WisprFlowProvider (providers/transcript/wisprflow.py): reads configured WisprFlow history (best-effort, schema unconfirmed)
- FileProvider (providers/transcript/file.py, default): brings-your-own transcript.json in session dir

**Interface:**
- entries_in_window(start_epoch, stop_epoch, tolerance_s, grace_s) -> list[TranscriptEntry]
- health() -> ProviderHealth

**Registration:** providers/transcript/__init__.py, selected by DICTATION_PROVIDER env var

### record_session.py: Tying Both Seams to One Session

**Location:** pipeline/record_session.py

**Commands:**
- start: creates recordings/<session_id>/, writes active marker to agents/.rec-session.json, records start_epoch
- stop: asks configured TranscriptProvider for entries in [start_epoch - tolerance, stop_epoch + grace], writes transcript.json and fixed window to session.json
- capture: deferred re-run of the same fixed window query (for tools that flush entries late)

**Key logic:** session_is_live() (imported by pipeline_watcher.py from doc_generator.py) checks session.json's start_epoch/stop_epoch to determine if a session is still recording

## Session Directory Contract

**Location:** recordings/<session_id>/

**Contract schema (ARCHITECTURE.md lines 161-176):**
- raw.mp4: adopted from whatever .mp4 lands here
- transcript.json: array of {"epoch": unix_seconds, "text": "..."} or provider-native format
- session.json: {"session_id", "start_epoch", "stop_epoch"} (fixed narration window)
- .processed / .attempts: markers written by whichever pipeline processed the session
- keyframes/: Pipeline B ffmpeg output (kf_0001.jpg ...)
- screenshots/: Pipeline A ffmpeg output + manifest (extracted at SHOT_INTERVAL_S)
- PRD.md, DIGEST.md, INDEX.md, workflow-map.md, TEAM_BRIEF.md, bugs/*.md: Pipeline A canonical outputs
- bugs/*.md: one file per bug, filed under zone code (FE-01, BE-02, etc.)

**Session ID format:** YYYY-MM-DDTHH-MM-SS[-slug] (validated in intelligence/app/models.py line 11)

## Shared State Contract

**File:** agents/pipeline-state.json

**Purpose:** Single source of truth for pipeline run state, read by menubar plugin

**Schema (intelligence/app/pipeline_state.py):**
```
stage: idle|recording|ready|transcribing|classifying|extracting|grounding|comparing|generating|filing|complete|error
session_id: current session identifier
started_at: ISO-8601 UTC timestamp
updated_at: ISO-8601 UTC timestamp
last_prd: path to latest PRD
last_handoff: path to latest handoff prompt
message: human-readable status
error: set when stage=error, otherwise null
```

**Writers:**
- pipeline/record_session.py: writes stage: "recording" on start, "ready" on stop
- pipeline/pipeline_watcher.py: advances stage as graph runs (classifying, extracting, etc.)
- intelligence/app/main.py: invokes pipeline_state.update() on error

**Readers:**
- menubar/homebase_status.10s.py: reads for display + dropdown state
- menubar/actions/*.sh: reads to gate certain operations

## Context Config: Pipeline A Only

**Default location:** context/example-webapp.json

**Configurable via:** CONTEXT_CONFIG env var

**Schema (context/schema.md):**
```json
{
  "product_name": "...",
  "zones": [{"code": "FE", "key": "frontend", "label": "..."}, ...],
  "severities": ["blocker", "high", "medium", "low"],
  "system_prompt": "...{product_name}...{context}...",
  "context_md": "path/to/context.md"
}
```

**Key constraint:** Zones with unknown `key` values are caught by a built-in unclassified zone (UNC), never dropped. system_prompt must contain literal {product_name} and {context} placeholders.

## External LLM Seams

**Pipeline A:** Direct Anthropic client calls (pipeline/doc_generator.py, line 62: ANTHROPIC_MODEL defaults to claude-sonnet-4-6)

**Pipeline B:** Via LangChain's Anthropic integration, lazily loaded in intelligence/app/llm.py

**Planned:** OpenRouter seam noted in README but not yet implemented

## Menubar Integration

**Location:** menubar/homebase_status.10s.py

**Behavior:**
- Title color reflects pipeline health: green idle, yellow processing, red error
- Dropdown shows current stage, optional activity feed, one-click Start/Stop/Copy Handoff/Open PRD
- Reads agents/pipeline-state.json every 10s
- Invokes menubar/actions/*.sh for Start/Stop and other operations
- Respects HOMEBASE_DRY_RUN=1 for testing (all side effects disabled)

**SwiftBar setup:** Symlink only homebase_status.10s.py into ~/SwiftBar/ (do not point SwiftBar at menubar/ directory itself)

## Optional Background Services

**Location:** menubar/launchd/

**Services (documented in menubar/launchd/README.md):**
- com.homebase.docgen.watcher: runs Pipeline A's --watch mode
- com.homebase.pipeline.watcher: runs Pipeline B's polling loop
- com.homebase.intelligence: runs the LangGraph FastAPI service
- com.homebase.audiobackup: fallback mic backup daemon

All are optional; choose which pipelines you need.

## Data Flow: From Click to Disk

1. User clicks Start Session in menubar
2. menubar/actions/start_session.sh calls record_session.py start
3. record_session.py creates recordings/<session_id>/, writes agents/.rec-session.json, remembers start_epoch
4. Calls RecorderAdapter.start() (AppleScript for Screen Studio, no-op for FileRecorder)
5. Calls TranscriptProvider.start() if it has one (Vowen only; starts Hands-Free Mode)
6. User records screen + narrates
7. User clicks Stop Session
8. menubar/actions/stop_session.sh calls record_session.py stop
9. record_session.py stop queries TranscriptProvider in [start_epoch - tolerance, stop_epoch + grace], writes transcript.json and session.json
10. Calls RecorderAdapter.stop() and TranscriptProvider.stop()
11. Either pipeline/doc_generator.py --watch or pipeline/pipeline_watcher.py detects new session
12. Pipeline A: extracts frames, calls Claude once, writes DIGEST/PRD/workflow-map to recordings/<session_id>/
13. Pipeline B: extracts fixed keyframes, POSTs to intelligence/app/main.py /intake, graph runs classify->extract->ground->compare->generate->file_outputs, writes to prds/<session_id>/ + workflows/library/
14. Both pipelines write .processed marker and update agents/pipeline-state.json
15. menubar updates dropdown to show complete/error state

## Related Codemaps

See also:
- backend.md: Intelligence spine service architecture
- data.md: On-disk artifact contracts
- dependencies.md: Per-layer dependencies and CI
