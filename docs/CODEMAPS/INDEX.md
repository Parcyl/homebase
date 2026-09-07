# Codemaps Index

**Last Updated:** 2026-09-07

This directory contains architectural documentation generated from the homebase codebase. All codemaps are written from actual code; every statement is grounded in specific repo-relative file paths.

## Quick Navigation

- **architecture.md**: Shared capture layer, two pipelines (A and B), pluggable adapters, session flow, menubar integration
- **backend.md**: Intelligence spine: FastAPI service, LangGraph graph, six processing nodes (classify through file_outputs), models and state
- **data.md**: On-disk contracts: session directory structure, transcript and frame formats, output locations, state files, atomic write patterns
- **dependencies.md**: Python packages per layer, CLI tools, CI jobs, environment variables, setup instructions

## System at a Glance

**homebase:** A local recording-to-documentation pipeline with one pluggable capture layer and two independent analysis modes.

```
You record screen + narrate -> shared capture (RecorderAdapter + TranscriptProvider)
                            -> Pipeline A: doc_generator.py (one Claude call, zoned bug triage)
                            -> Pipeline B: pipeline_watcher.py + intelligence/ (LangGraph spine, workflow PRD)
```

## Entry Points

| Purpose | Command | File |
|---------|---------|------|
| Start/stop recording | menubar click or script | pipeline/record_session.py |
| Run Pipeline A (bug triage) | `python3 pipeline/doc_generator.py --watch` | pipeline/doc_generator.py |
| Run Pipeline B (workflow spec) | `python3 pipeline/pipeline_watcher.py` + intelligence service | pipeline/pipeline_watcher.py + intelligence/run.sh |
| Run intelligence backend | `intelligence/run.sh` | intelligence/app/main.py |
| Run evals gate | `node evals/run.js` | evals/run.js |

## Key Modules

| Layer | Purpose | Files |
|-------|---------|-------|
| **Capture** | Record screen, narrate, manage session | pipeline/record_session.py, providers/recorder/, providers/transcript/ |
| **Pipeline A** | Bug digest + PRD via multimodal Claude | pipeline/doc_generator.py, context/ |
| **Pipeline B watcher** | Poll for sessions, extract frames, POST to service | pipeline/pipeline_watcher.py |
| **Intelligence backend** | LangGraph reasoning: classify to generate to file | intelligence/app/{main,graph,nodes,models,settings}.py |
| **Menubar** | One-click UI, state display, background services | menubar/homebase_status.10s.py, menubar/actions/, menubar/launchd/ |
| **Adapters** | Pluggable recorders and transcription providers | providers/recorder/{screen_studio,file}.py, providers/transcript/{vowen,wisprflow,file}.py |
| **Evals** | Invariant enforcement gate | evals/run.js |

## Data Flow Phases

**1. Capture (pipeline/record_session.py)**
- User clicks Start
- Creates recordings/<session_id>/, starts RecorderAdapter and TranscriptProvider
- User records and narrates
- User clicks Stop
- Queries TranscriptProvider for entries, writes transcript.json and session.json

**2. Pipeline A (pipeline/doc_generator.py)** (optional)
- Watches recordings/ for new sessions
- Calls session_is_live() to check if recording has finished
- Extracts frames via ffmpeg (one per SHOT_INTERVAL_S)
- One streaming multimodal Claude call with frames and context_config
- Writes DIGEST.md, PRD.md, workflow-map.md, bugs/*.md

**3. Pipeline B (pipeline_watcher.py + intelligence/)**  (optional)
- Watches recordings/ for new sessions
- Extracts fixed KEYFRAME_COUNT (15) keyframes via ffmpeg
- POSTs IntakeRequest to intelligence/app/main.py /intake
- LangGraph spine runs: classify -> extract -> ground -> compare -> generate -> file_outputs
- Writes prds/<session_id>/PRD.md, handoff-prompt.md, workflows/library/pattern.md
- Updates agents/pipeline-state.json

**4. Completion**
- Menubar reads agents/pipeline-state.json, displays stage
- User copies handoff prompt, pastes into Claude Code
- Or reviews DIGEST.md and PRD.md directly

## Pluggable Points

| Seam | Interface | Shipped Adapters | Selection |
|------|-----------|-----------------|-----------|
| Screen recorder | RecorderAdapter (providers/recorder/adapter.py) | ScreenStudioRecorder, FileRecorder (default) | RECORDER env var |
| Dictation/transcription | TranscriptProvider (providers/transcript/provider.py) | VowenProvider, WisprFlowProvider, FileProvider (default) | DICTATION_PROVIDER env var |
| LLM model | Environment only | claude-sonnet-4-6 (default) | ANTHROPIC_MODEL env var |
| OpenRouter integration | Planned, not implemented | N/A | N/A |

## Configuration

**Main:** .env file (see env.example for template)

**Context config (Pipeline A only):** context/example-webapp.json defines product zones, severities, and triage system prompt

**Environment variables:** See dependencies.md "Environment Variables" section for full list

## Testing

**Evals gate (CI, dependency-free):** `node evals/run.js`

**Pipeline layer tests:** `python -m pytest pipeline/tests providers menubar/tests -q`

**Intelligence tests:** `cd intelligence && python -m pytest tests -q`

**Full CI workflow:** See .github/workflows/ci.yml (runs both jobs on PR and push to main)

## Files Worth Reading First

To understand homebase quickly, read in this order:

1. **README.md** (repo root): 2-minute overview, use cases, quick start
2. **architecture.md** (this directory): How the pieces fit together
3. **ARCHITECTURE.md** (docs/): Original detailed architecture (more verbose, same info)
4. **docs/SETUP.md**: Full installation and configuration guide
5. **pipeline/doc_generator.py** (lines 1-100): Code entry point for Pipeline A
6. **pipeline/pipeline_watcher.py** (lines 1-80): Code entry point for Pipeline B
7. **intelligence/app/main.py**: FastAPI endpoint, graph invocation, response handling

## Known Limitations

- macOS-first: Screen Studio adapter is AppleScript-only; file recorder works everywhere
- WisprFlow adapter is best-effort (schema not yet confirmed)
- Windows and Linux documented as seams, not shipped
- Pattern library and memory services are write-only (read not yet implemented)
- grounding node does best-effort validation only (target_repo not yet wired for real codebase reads)

## Related Documentation

- **docs/SETUP.md**: Installation and configuration walkthrough
- **docs/ARCHITECTURE.md**: Extended architecture doc (section 1-6 map to the codemaps here)
- **context/schema.md**: context_config JSON schema (Pipeline A configuration)
- **intelligence/README.md**: Intelligence spine overview and contract
- **menubar/README.md**: Menu bar plugin usage and launchd services
- **evals/run.js**: Invariant checks that verify the codebase itself
