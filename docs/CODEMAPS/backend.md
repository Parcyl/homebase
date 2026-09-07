# Backend Codemap: Intelligence Spine

**Last Updated:** 2026-09-07

**Entry Points:** intelligence/run.sh (bootstrap), intelligence/app/main.py (/intake endpoint on line 56)

**Service:** FastAPI + LangGraph reasoning engine that processes recorded sessions into workflow PRDs and handoff prompts (Pipeline B backend)

## Service Architecture

**Start:** `intelligence/run.sh` boots the FastAPI server on LANGGRAPH_PORT (default 8080)

**Endpoint:** POST /intake consumes IntakeRequest, invokes the LangGraph pipeline, returns IntakeResponse

**Graph:** Sequential spine: classify -> extract -> ground -> compare -> generate -> file_outputs (intelligence/app/graph.py lines 18-35)

## Key Layers

### FastAPI Application

**File:** intelligence/app/main.py

**Structure:**
- _configure_logging(): JSON structured logs to stdout (line 24)
- health endpoint: GET /health returns {"status": "ok"} (line 51)
- intake endpoint: POST /intake (line 56)
  - Validates IntakeRequest (session_id format, non-empty transcript)
  - Builds initial graph state from request
  - Invokes _graph.invoke() with initial_state
  - Catches exceptions, updates pipeline_state with error
  - Returns IntakeResponse with classification, outputs, pattern_match, low_confidence

**Error handling:** HTTPException 502 on graph failure, with error_code and message

### Pydantic Models

**File:** intelligence/app/models.py

**Request schema (IntakeRequest, lines 14-42):**
- session_id: str (must match YYYY-MM-DDTHH-MM-SS format)
- recording_path: str (path to raw.mp4, validated for existence)
- transcript: dict | list | str (provider-native or FileProvider JSON)
- keyframe_paths: list[str] (video frame JPEGs)
- context_cue: str | None (optional hint)
- target_repo: str | None (optional repo path for grounding)

**Response schema (IntakeResponse):**
- session_id: str
- classification: Classification (deal_type, sub_type, operator_intent_slug, confidence, rationale)
- library_path: str (path to the workflow pattern library for this classification)
- outputs: list[str] (file paths written: PRD.md, handoff-prompt.md, workflow-map.md, pattern.md)
- pattern_match: PatternComparison (match: new|extends|unknown, target_library_path, rationale)
- low_confidence: bool

**Graph state elements (lines 45-107):**
- Classification: asset classification
- Step: workflow step with order/action/transcript_span/keyframe
- Decision: design decision with heuristic and agent candidate
- ComponentCategory: UI_UX, DATA_INTEGRATION, CODIFIABLE_LOGIC, AI_INTELLIGENCE, OPEN_QUESTION
- IntegrationStatus: INTEGRATED, NEW, TO_INVESTIGATE (default for unverified claims)
- DataContract: one data source dependency
- AcceptanceCriterion: testable acceptance criteria with pass threshold

### LangGraph Pipeline

**File:** intelligence/app/graph.py (lines 18-35 show the wiring)

**Node sequence:**
1. classify: Extract workflow type from transcript/frames (classify_node from nodes/classify.py)
2. extract: Identify steps, decisions, data sources, components (extract_node from nodes/extract.py)
3. ground: Match extraction against transcript and keyframes to validate claims (ground_node from nodes/grounding.py)
4. compare: Diff against existing workflow patterns in library (compare_node from nodes/compare.py)
5. generate: Create PRD, handoff prompt, workflow-map markdown (generate_node from nodes/generate.py)
6. file_outputs: Write outputs atomically to disk (file_outputs_node from nodes/file_outputs.py)

**Graph state:** PipelineState (intelligence/app/state.py) carries all mutable context through the pipeline

### Six Processing Nodes

**Location:** intelligence/app/nodes/

**1. classify.py (Classify)**
- Input: session_id, recording_path, transcript, keyframe_paths
- Calls Claude: Classify the workflow's deal_type, sub_type, operator_intent_slug
- Output: Classification model with confidence and rationale
- Prompt: intelligence/app/prompts/classify.md

**2. extract.py (Extract)**
- Input: Classification, transcript, keyframes
- Calls Claude: Identify workflow steps, decisions, data dependencies, components to build
- Output: State updated with steps list, decisions list, components list, data_sources list
- Prompt: intelligence/app/prompts/extract.md
- Enriches steps with transcript_span and keyframe linkage

**3. grounding.py (Grounding)**
- Input: Steps, decisions, components, original transcript and keyframes
- Best-effort validation: checks whether claimed existence of data sources / integrations can be verified
- Outputs IntegrationStatus for each data source: INTEGRATED, NEW, TO_INVESTIGATE
- Does not call Claude if target_repo is absent (all claims stay TO_INVESTIGATE)
- Anchors text references and keyframe indices to transcript/frame source

**4. compare.py (Compare)**
- Input: Classification, steps, decisions (complete extraction)
- Compares against workflows/library/<deal_type>/<sub_type>/<intent_slug>/pattern.md if it exists
- Output: PatternComparison with match: new|extends|unknown and rationale
- Determines whether this session creates a new pattern or extends an existing one
- Writes to target_library_path for file_outputs to know where to write pattern.md

**5. generate.py (Generate)**
- Input: All prior node outputs (classification, extraction, grounding, comparison)
- Calls Claude once to synthesize:
  - workflow-map.md: step-by-step flow with keyframe links
  - PRD.md: product requirements document for the workflow
  - handoff-prompt.md: Claude Code handoff prompt ready to paste (includes context, steps, acceptance criteria)
- Output: Three markdown strings in state ready for file_outputs to write
- Prompt: intelligence/app/prompts/generate.md

**6. file_outputs.py (File Outputs)**
- Input: All strings from generate.py, classification from classify.py, pattern_match from compare.py
- Atomic writes: write to temp files, fsync, rename into place
- Paths:
  - prds/<session_id>/PRD.md
  - prds/<session_id>/handoff-prompt.md
  - recordings/<session_id>/workflow-map.md
  - workflows/library/<deal_type>/<sub_type>/<intent_slug>/pattern.md (only if pattern_match.match == "new")
  - memory/patterns.md (appended with one-line summary)
- Output: output_paths list (list of written file paths)

### Supporting Modules

**settings.py:** Reads env vars, returns Settings dataclass with:
- anthropic_api_key
- anthropic_model (default claude-sonnet-4-6)
- homebase_root (default repo root)
- langgraph_port (default 8080)
- log_level (default INFO)

**llm.py:** Lazy-loads LangChain Anthropic client, defines get_llm() callable for nodes

**io.py:** Path helpers for reading recordings, writing prds, accessing pattern library

**pipeline_state.py:** Writes to agents/pipeline-state.json with stage tracking (transcribing -> classifying -> extracting -> grounding -> comparing -> generating -> filing -> complete|error)

**state.py:** Defines PipelineState TypedDict that flows through all six nodes

## Prompts

**Location:** intelligence/app/prompts/

All prompts are markdown templates:
- classify.md: "Analyze this recording. What workflow type is this operator executing?"
- extract.md: "Break down the workflow into discrete steps. What decisions did they make? What data sources do they touch?"
- generate.md: "Write three markdown documents: a workflow-map (steps linked to keyframes), a PRD, and a Claude Code handoff prompt"

## Concurrency and State

**Stateless service:** No in-memory session state. All durable state lives under HOMEBASE_ROOT (recordings/ and prds/ directories)

**Per-node invocation:** Each node is deterministic given input state, no caching of prior runs

**Atomic file writes:** file_outputs.py uses temp -> fsync -> rename pattern to ensure partial writes cannot land on disk

## Environment

**Required (.env):**
- ANTHROPIC_API_KEY: Anthropic API credentials
- ANTHROPIC_MODEL: Claude model name (default claude-sonnet-4-6)
- HOMEBASE_ROOT: Root directory for recordings/, prds/, workflows/ (default repo root)
- LANGGRAPH_PORT: Port to listen on (default 8080)

**Optional:**
- LOG_LEVEL: Logging verbosity (default INFO)

## Testing

**Location:** intelligence/tests/

Test structure:
- Mocked Claude calls (do not hit live API)
- Fixture sessions with real transcripts and keyframes
- Node unit tests verify output schema
- Integration tests verify graph.invoke() flow end-to-end

**Run:** cd intelligence && pip install -e ".[dev]" && python -m pytest tests -q

## Related Codemaps

See also:
- architecture.md: System-wide data flow and Pipeline B watcher
- data.md: On-disk artifact contracts and file layouts
- dependencies.md: Python package requirements and CI
