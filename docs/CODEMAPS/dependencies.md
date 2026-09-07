# Dependencies Codemap

**Last Updated:** 2026-09-07

**Scope:** Per-layer Python packages, CLI tools, optional features, and CI jobs

## Layer 1: Pipeline (Pipeline A + Record/Capture)

**Location:** requirements.txt (runtime), requirements-dev.txt (dev)

### Runtime Dependencies

**File:** requirements.txt

```
anthropic>=0.40
```

**Runtime behavior:**
- anthropic: Anthropic SDK for Claude API calls (used by pipeline/doc_generator.py line 62 for streaming multimodal calls)
- Lazy imports: doc_generator.py imports stdlib-only; heavy dependencies (Anthropic, ffmpeg) are invoked via subprocess or at call time
- No other Python runtime dependencies for the pipeline layer

### Optional Features (commented in requirements.txt)

```
mlx-whisper       # Apple Silicon-only, fallback transcription if TranscriptProvider fails
websocket-client  # observer/ read-only Chrome co-observer feature (not core pipeline)
```

### Development Dependencies

**File:** requirements-dev.txt

```
pytest>=8.2
pytest-cov>=4.1
```

Used by: pipeline/tests/, providers/tests/, menubar/tests/ test suites

### External CLI Tools (Required)

**ffmpeg/ffprobe (must be in PATH)**
- Used by: pipeline/doc_generator.py (SHOT_INTERVAL_S frame extraction)
- Used by: pipeline/pipeline_watcher.py (KEYFRAME_COUNT fixed-frame extraction)
- Env var override: FFMPEG_BIN (default: ffmpeg), FFPROBE_BIN (default: ffprobe)
- Install: brew install ffmpeg (macOS), apt-get install ffmpeg (Linux), chocolatey install ffmpeg (Windows)

**Python 3.11+** (requirement)
- Used by: entire codebase
- Type hints require 3.11+

### Platform-Specific CLI Tools

**AppleScript (macOS only)**
- Used by: providers/recorder/screen_studio_start.applescript, providers/recorder/screen_studio_stop.applescript
- Used by: providers/transcript/vowen_start.applescript, providers/transcript/vowen_stop.applescript
- Executed via: osascript (built-in on macOS)

## Layer 2: Intelligence Spine (Pipeline B Backend)

**Location:** intelligence/pyproject.toml (all dependencies)

### Runtime Dependencies

```
fastapi>=0.115
uvicorn[standard]>=0.32
pydantic>=2.9
pydantic-settings>=2.6
langgraph>=0.2.50
langchain-anthropic>=0.3
langchain-core>=0.3
python-dotenv>=1.0
httpx>=0.27
```

**Package purposes:**
- fastapi: HTTP framework for /intake endpoint (intelligence/app/main.py)
- uvicorn[standard]: ASGI server with uvicorn CLI (started by intelligence/run.sh)
- pydantic/pydantic-settings: Request/response validation and env var parsing (intelligence/app/models.py, settings.py)
- langgraph: Workflow orchestration for classify -> extract -> ground -> compare -> generate -> file nodes
- langchain-anthropic: LangChain integration with Anthropic models (lazy-loaded in intelligence/app/llm.py)
- langchain-core: Shared LangChain interfaces and types
- python-dotenv: .env file loading in intelligence/.env
- httpx: Async HTTP client (for potential future integrations)

### Development Dependencies

```
pytest>=8.3
pytest-asyncio>=0.24
ruff>=0.7
```

**pytest/pytest-asyncio:** Intelligence test suite (intelligence/tests/) with async graph node testing

**ruff:** Code formatting and linting (line-length 100, Python 3.11+ target)

### Python Version

```
requires-python = ">=3.11"
```

## Layer 3: Menubar Plugin (SwiftBar)

**No Python package dependencies.**

**Script stack:** Pure shell and Python stdlib only

**External requirements:**
- SwiftBar (installed via: brew install --cask swiftbar)
- Python 3.11+ (for menubar/homebase_status.10s.py and menubar/actions/*.sh invocations)

**Shell scripts used by actions (menubar/actions/*.sh):**
- Standard POSIX tools: source, grep, find, xargs, date, cat
- macOS-specific: osascript (AppleScript execution)

## Layer 4: Invariant Evals Gate

**Location:** evals/run.js

**Runtime:** Node.js (pure JavaScript, no npm dependencies)

**External CLI invocation:** Shells out to python3 for find_pending() probe

**File:** evals/package.json (if it exists, for reference only; gate runs without npm install)

**Current state (evals/package.json exists but is unused):** gate is dependency-free Node; no packages required

## CI/CD

### GitHub Actions Workflow

**File:** .github/workflows/ci.yml

**Two parallel jobs:**

#### Job 1: invariants (Node 20 + Python 3.12)

```yaml
- name: Run homebase invariant evals
  run: node evals/run.js
```

**Behavior:** Runs the dependency-free evals gate on every PR and push to main

**Environment:** ubuntu-latest, Node.js 20, Python 3.12

**No npm install or package install needed**

#### Job 2: python-tests (Python 3.12 only)

**Pipeline layer tests:**
```bash
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest pipeline/tests providers menubar/tests -q
```

**Environment:** ubuntu-latest, Python 3.12

**Duration:** Covers all pytest suites except intelligence/

**Intelligence layer tests:**
```bash
cd intelligence
pip install -e ".[dev]"
python -m pytest tests -q
```

**Environment:** Same ubuntu-latest runner, after pipeline tests

**Combined coverage:** All test/ directories in pipeline/, providers/, menubar/, and intelligence/

### Workflow Triggers

**On:** pull_request, push to main

**Permissions:** contents: read (no write access required by CI)

## Environment Variables

### Pipeline Layer (record_session.py, doc_generator.py, pipeline_watcher.py)

```
HOMEBASE_ROOT              default: repo root, where recordings/, prds/, workflows/ live
SESSIONS_DIR               default: recordings, relative to HOMEBASE_ROOT
PYTHON_BIN                 default: python3, used to invoke python scripts
RECORDER                   default: file, selected via providers.recorder.get_recorder()
DICTATION_PROVIDER         default: file, selected via providers.transcript.get_provider()
CONTEXT_CONFIG             default: context/example-webapp.json
FFMPEG_BIN                 default: ffmpeg
FFPROBE_BIN                default: ffprobe
ANTHROPIC_MODEL            default: claude-sonnet-4-6
ANTHROPIC_API_KEY          required: Anthropic API credentials
LANGGRAPH_URL              default: http://127.0.0.1:8080
LANGGRAPH_PORT             default: 8080
LANGGRAPH_POST_TIMEOUT_S   default: 1200 (timeout for /intake POST)
TRANSCRIPT_CAPTURE_TIMEOUT_S default: 300 (timeout for deferred transcript capture)
MAX_LIVE_SESSION_S         default: 21600 (6 hours, max session length before abandon)
STALE_ALERT_S              default: 600 (10 min, time to wait before stale recording alert)
```

### Intelligence Layer (intelligence/.env)

```
ANTHROPIC_API_KEY          required: Anthropic API credentials
ANTHROPIC_MODEL            default: claude-sonnet-4-6
HOMEBASE_ROOT              default: repo root
LANGGRAPH_PORT             default: 8080
LOG_LEVEL                  default: INFO
```

### Menubar Layer (menubar/actions/*.sh reads these)

```
HOMEBASE_ROOT              default: repo root
PYTHON_BIN                 default: python3
LANGGRAPH_URL              default: http://127.0.0.1:8080
LANGGRAPH_PORT             default: 8080
HOMEBASE_EDITOR_APP        default: Visual Studio Code (app to open PRDs)
HOMEBASE_DRY_RUN           default: 0 (set to 1 for test suite)
RECORDER                   default: file
DICTATION_PROVIDER         default: file
```

## Build / Setup Instructions

### Quick Start (Entire System)

```bash
# Clone and configure (see README / docs/SETUP.md for the repo URL)
cd homebase
cp env.example .env        # add ANTHROPIC_API_KEY
pip install -r requirements.txt -r requirements-dev.txt

# Prepare intelligence service
cd intelligence
pip install -e .
cd ..

# Run tests
node evals/run.js          # invariants (dependency-free)
python -m pytest pipeline/tests providers menubar/tests -q
cd intelligence && python -m pytest tests -q && cd ..

# Start services (in separate terminals)
python3 intelligence/run.sh  # starts FastAPI on :8080
python3 pipeline/pipeline_watcher.py --watch

# Install menubar plugin (optional)
brew install --cask swiftbar
ln -sfn $(pwd)/menubar/homebase_status.10s.py ~/SwiftBar/
chmod +x menubar/actions/*.sh menubar/homebase_status.10s.py
```

### Pipeline Layer Only

```bash
pip install -r requirements.txt
python3 pipeline/doc_generator.py --watch
```

### Intelligence Layer Only

```bash
cd intelligence
pip install -e .
./run.sh
```

## Dependency Security

### Notable Attack Surface

- **Anthropic SDK:** Network calls to api.anthropic.com, credentials via ANTHROPIC_API_KEY env var
- **LangChain:** Deep dependency tree, used for LLM orchestration (intelligence layer)
- **ffmpeg:** Subprocess invocation with user-controlled file paths; input validation done in doc_generator.py and pipeline_watcher.py
- **TranscriptProvider adapters:** Read local files (vowen.py reads ~/Library/..., wisprflow.py reads configured path)
- **RecorderAdapter adapters:** AppleScript execution via osascript (ScreenStudioRecorder only)

### Mitigation

- ANTHROPIC_API_KEY never logged (scrubbed in pipeline_state.py, intelligence/app/main.py)
- File I/O uses pathlib.Path with resolved() calls to prevent directory traversal
- Subprocess calls use Path.iterdir() / glob() rather than shell expansion
- No use of subprocess with shell=True in any capture code

## Related Codemaps

See also:
- architecture.md: System architecture and component roles
- backend.md: Intelligence spine service implementation
- data.md: On-disk file contracts and I/O patterns
