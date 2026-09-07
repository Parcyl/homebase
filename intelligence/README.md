# Intelligence Spine

The reasoning engine behind **Pipeline B** (workflow → PRD/handoff). A Python FastAPI service
that receives a recording's transcript and keyframes, runs them through a LangGraph graph, and
writes the generated docs. `pipeline/pipeline_watcher.py` POSTs finished sessions to it.

## Status
Implemented. See `app/` for the real service; run it with `./run.sh`.

## Shape

```
intelligence/
├── pyproject.toml
├── run.sh                    # starts the FastAPI service (reads intelligence/.env)
├── app/
│   ├── main.py               # FastAPI entrypoint, POST /intake
│   ├── graph.py              # LangGraph definition
│   ├── nodes/
│   │   ├── classify.py       # classify the recorded workflow's type
│   │   ├── extract.py        # steps, tools, decisions, data sources
│   │   ├── grounding.py      # ground the extraction in the real transcript/frames
│   │   ├── compare.py        # diff against the existing pattern library
│   │   ├── generate.py       # workflow-map + PRD + handoff
│   │   └── file_outputs.py   # atomic writes; returns output paths
│   ├── prompts/{classify,extract,generate}.md
│   ├── models.py             # pydantic schemas
│   ├── io.py / settings.py   # session paths + env-driven config
│   └── pipeline_state.py     # shared run-state contract
└── tests/                    # pytest suite
```

## Contract

`POST http://127.0.0.1:8080/intake`

```json
{
  "session_id": "2026-01-01T09-00-00-example",
  "recording_path": "recordings/2026-01-01T09-00-00-example/raw.mp4",
  "transcript": { "...": "transcript JSON from your dictation provider" },
  "keyframe_paths": ["recordings/.../keyframes/001.jpg", "..."],
  "context_cue": "optional free-text hint"
}
```

Returns the classification plus the written output paths (`workflow-map.md`, `prds/<id>/PRD.md`,
`prds/<id>/handoff-prompt.md`) and whether the run started a new pattern or extended an existing one.

## Rules
- Pattern-library folder paths are derived from the classification, never hardcoded.
- LLM model comes from `ANTHROPIC_MODEL` (env); all file writes are atomic (tmp → fsync → rename).
- Stateless service; durable state lives under `HOMEBASE_ROOT`.

## Required env (`intelligence/.env`)
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL` (default `claude-sonnet-4-6`)
- `HOMEBASE_ROOT` (default: repo root)
- `LANGGRAPH_PORT` (default `8080`)
