# Data Codemap: On-Disk Contracts

**Last Updated:** 2026-09-07

**Scope:** Session directory structure, transcript/frame formats, state files, output locations

## Root Directory Layout

```
homebase/
├── recordings/           <- all session directories and Pipeline A outputs
├── prds/                 <- Pipeline B PRD/handoff output
├── workflows/library/    <- Pipeline B workflow pattern library
├── agents/               <- shared state files (pipeline-state.json, .rec-session.json, activity-log.md)
├── inbox/                <- Pipeline B raw /intake responses
├── memory/               <- learnings archive (patterns.md appended by file_outputs node)
├── pipeline/             <- Python watcher and capture scripts
├── intelligence/         <- LangGraph FastAPI service
├── providers/            <- pluggable recorder and transcript adapters
├── menubar/              <- SwiftBar menu bar plugin
├── context/              <- Pipeline A context configs (zones/severities)
├── templates/            <- markdown doc templates
├── evals/                <- invariant eval gate
└── docs/                 <- this README + architecture docs
```

**Root is determined by:** HOMEBASE_ROOT env var (default: the repo root)

## Session Directory: recordings/<session_id>/

**Session ID format:** YYYY-MM-DDTHH-MM-SS[-slug] (validated against SESSION_ID_RE in intelligence/app/models.py line 11)

**Full path example:** recordings/2026-09-07T14-30-00-user-walkthrough/

### Video and Narration Files

**raw.mp4** (required)
- The recorded screen video, adopted from whatever .mp4 lands in this directory
- Pipeline A resolves via RecorderAdapter.resolve_master() (screen_studio.py or file.py)
- Pipeline B resolves via session_mp4() helper in pipeline_watcher.py
- No fixed size/codec; ffmpeg-readable file

**transcript.json** (required)
- JSON array of narration entries in one of two formats:
  - FileProvider format (default): `[{"epoch": 1234567890.5, "text": "..."}, ...]`
  - Provider-native format: varies by provider (Vowen/WisprFlow). See providers/transcript/vowen.py (lines 110-120) for Vowen's structure
- Entries must be oldest-first in the array
- Written by record_session.py stop command after querying the configured TranscriptProvider
- Also fed directly to intelligence/app/main.py /intake endpoint (sent as-is in IntakeRequest.transcript field)

**session.json** (required)
- Fixed narration window contract, ensures deferred captures use the same bounds
- Schema: `{"session_id": "...", "start_epoch": 1234567890.5, "stop_epoch": 1234567900.5}`
- Written by record_session.py stop, read by pipeline watchers to determine session liveness
- start_epoch/stop_epoch are fixed at stop time; later captures re-apply the same window

### Processing Markers

**.processed** (written by either pipeline)
- Zero-byte marker file, indicates this session has been processed
- Prevents re-processing the same session on next watcher poll
- Format: empty file, presence only

**.attempts** (written by pipelines on transient failure)
- Counter file, incremented on each retry (transcript capture timeouts, partial /intake failures)
- Format: plain text integer (e.g., "2")
- Used to back off after MAX_TRANSCRIPT_ATTEMPTS (3) failed deferred captures

### Extracted Frames

**keyframes/** (Pipeline B only)
- Fixed set of evenly-spaced keyframes extracted by pipeline_watcher.py via ffmpeg
- Count: exactly KEYFRAME_COUNT (15) frames, independent of video length
- Format: kf_0001.jpg, kf_0002.jpg, ..., kf_0015.jpg (JPEG)
- Frame selection: fast input seek via ffmpeg, not full decode
- These frames are POSTed to intelligence/app/main.py in IntakeRequest.keyframe_paths

**screenshots/** (Pipeline A only)
- Variable set of screenshots extracted by doc_generator.py via ffmpeg
- Count: up to MAX_SHOTS (48) on disk, one per SHOT_INTERVAL_S (15s)
- Sent to Claude: at most MAX_SHOTS_TO_CLAUDE (24) downsampled to SHOT_WIDTH (768) pixels
- Format: shot_001.jpg, shot_002.jpg, ..., shot_NNN.jpg
- Also written: manifest.json (index of timestamps and filenames)

### Pipeline A Outputs

All written to recordings/<session_id>/ by doc_generator.py:

**PRD.md**
- Product requirements document
- Includes overview, acceptance criteria, known issues, workflow summary
- Written directly by Claude's multimodal call via doc_generator.py's capture_tool (doc_generator.py line ~800)

**DIGEST.md**
- Triage summary of all bugs discovered in the session
- Structure: headline, sorted-by-zone bug table, per-zone bug details with repro/screenshot links
- Links to timecodes: e.g., "[screenshot at 01:23](../screenshots/shot_012.jpg)"
- One multimodal Claude call per session generates this

**INDEX.md**
- Cross-reference index: bugs by severity, workflow touch-points, key decisions
- Extracted from DIGEST.md and structured data

**workflow-map.md**
- Hand-drawn or auto-generated diagram of screens/panels and how they connect
- Created by Pipeline A, also created independently by Pipeline B's generate node
- If both pipelines run, Pipeline B's version overwrites this file

**TEAM_BRIEF.md**
- Executive summary: one-page top-line findings and next steps
- Derived from DIGEST.md and PRD.md via template

**bugs/<zone>-<num>.md** (e.g., bugs/FE-01.md, bugs/BE-03.md)
- One file per bug, filed under the zone code defined in context_config
- Schema: bug ID, title, severity, description, repro steps, expected behavior, suggested fix, screenshot link + timecode
- Written atomically by doc_generator.py's write_bugs function

## Pipeline B Outputs

**prds/<session_id>/PRD.md**
- Product requirements document generated by intelligence/app/nodes/generate.py
- Includes workflow overview, steps with keyframe links, decisions, data dependencies, acceptance criteria

**prds/<session_id>/handoff-prompt.md**
- Claude Code handoff prompt, ready to paste into a chat
- Full context, step-by-step instructions, acceptance criteria, dependencies
- Generated by generate node (intelligence/app/nodes/generate.py line ~30)

**recordings/<session_id>/workflow-map.md**
- Also written by Pipeline B's generate node (in parallel with prds/ outputs)
- If Pipeline A runs first, this file is overwritten by Pipeline B

**workflows/library/<deal_type>/<sub_type>/<intent_slug>/pattern.md**
- Reusable workflow pattern template, written only if compare node determines match == "new"
- deal_type/sub_type/intent_slug come from Classification model (intelligence/app/models.py line 45)
- Example path: workflows/library/commercial-real-estate/mixed-use/zoning-audit/pattern.md
- Appended to memory/patterns.md as a one-line summary

## Shared State Files

**agents/pipeline-state.json**
- Single source of truth for current pipeline stage and session state
- Read by menubar every 10s (menubar/homebase_status.10s.py)
- Schema (documented in intelligence/app/pipeline_state.py):
  ```json
  {
    "stage": "idle|recording|ready|transcribing|classifying|extracting|grounding|comparing|generating|filing|complete|error",
    "session_id": "2026-09-07T14-30-00",
    "started_at": "2026-09-07T14:30:00Z",
    "updated_at": "2026-09-07T14:30:45Z",
    "last_prd": "prds/2026-09-07T14-30-00/PRD.md",
    "last_handoff": "prds/2026-09-07T14-30-00/handoff-prompt.md",
    "message": "Processing complete",
    "error": null
  }
  ```
- Written by: pipeline_watcher.py (pipeline_state.update() in intelligence/app/pipeline_state.py), record_session.py start/stop
- Read by: menubar plugin, action scripts for gating

**agents/.rec-session.json**
- Active recording marker, written by record_session.py start, deleted by stop
- Schema: `{"session_id": "...", "start_epoch": 1234567890.5}`
- Used to prevent starting two concurrent recordings

**agents/activity-log.md** (optional, bring-your-own)
- Optional activity feed appended by external systems
- Tailed by menubar plugin's "Recent activity" section if present
- Format: markdown bullet list with `- [TIMESTAMP] Message` lines

## Pipeline B Intermediate: inbox/

**inbox/<session_id>.json**
- Raw IntakeResponse from /intake endpoint, dropped by pipeline_watcher.py
- Mirrors what the /intake endpoint returned: classification, outputs, pattern_match, low_confidence
- Preserved for downstream consumers or audit

## Memory and Learnings

**memory/patterns.md**
- Appended by file_outputs node each time a new workflow pattern is written
- One-line summaries: `- YYYY-MM-DDTHH-MM-SS [deal_type/sub_type/intent] workflow pattern learned`
- Serves as a learnings archive for pattern library growth tracking

## On-Disk Invariants

**enforced by evals/run.js:**
- Active sessions have both start_epoch/stop_epoch in session.json (no incomplete sessions)
- .processed marker exists iff the session has been fully processed
- Output files exist at the paths claimed in IntakeResponse.outputs or DIGEST.md links
- No stray .mp4 files left in session directories after adoption
- DIGEST.md and pattern.md files use relative links (no absolute paths)

**enforced by tests:**
- Session IDs match YYYY-MM-DDTHH-MM-SS format (pytest providers/transcript/tests/)
- Transcript entries are oldest-first
- keyframes/ contains exactly 15 JPEG files
- All file writes are atomic (tmpfile -> fsync -> rename, see file_outputs.py)

## File I/O Patterns

**Atomic writes (file_outputs.py pattern):**
```python
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(content)
tmp.fsync()
tmp.rename(path)
```

**Lazy transcript capture (doc_generator.py and pipeline_watcher.py):**
- If transcript.json doesn't exist, shell out to record_session.py capture
- Subprocess timeout: TRANSCRIPT_CAPTURE_TIMEOUT_S (300s)
- Retries up to MAX_TRANSCRIPT_ATTEMPTS (3) times
- Shares session.json fixed window to ensure consistency across retries

**Concurrent processing (doc_generator.py):**
- Per-session lock file under the session dir
- Lock held during entire processing to prevent double-processing
- Stale locks (older than LOCK_STALE_S = 1800s) are assumed orphaned and stolen

## Related Codemaps

See also:
- architecture.md: Data flow and session lifecycle
- backend.md: Intelligence spine output generation
- dependencies.md: Dependencies and CI
