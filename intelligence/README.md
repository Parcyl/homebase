# LangGraph Intelligence Spine

Python FastAPI service. Receives transcripts and keyframe paths from n8n, runs them through a LangGraph reasoning graph, writes outputs back to the Homebase repo. Built in Phase 3.

## Status
Placeholder. Not yet implemented.

## Planned shape

```
services/langgraph/
├── pyproject.toml
├── .env.example
├── README.md (this file)
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entrypoint, /intake POST
│   ├── graph.py             # LangGraph definition
│   ├── nodes/
│   │   ├── classify.py      # deal type classification from transcript
│   │   ├── extract.py       # steps, tools, decisions, data sources
│   │   ├── compare.py       # diff against workflows/library/
│   │   ├── generate.py      # PRD.md + handoff-prompt.md
│   │   └── file.py          # write outputs to disk and return paths
│   ├── prompts/
│   │   ├── classify.md
│   │   ├── extract.md
│   │   └── generate.md
│   ├── models.py            # pydantic schemas
│   └── settings.py          # env-driven config
└── tests/
    └── ...
```

## Contract with n8n

### Request
`POST http://127.0.0.1:8080/intake`

```json
{
  "session_id": "2026-05-25T14-30-00-self-storage-roundrock",
  "recording_path": "recordings/2026-05-25T14-30-00-self-storage-roundrock/raw.mp4",
  "transcript": { "...": "Vowen or mlx-whisper JSON" },
  "keyframe_paths": ["recordings/.../keyframes/001.jpg", "..."],
  "context_cue": "self storage, Round Rock, day one"
}
```

### Response
```json
{
  "session_id": "...",
  "classification": {
    "deal_type": "self-storage",
    "sub_type": "acquisition",
    "confidence": 0.92,
    "rationale": "..."
  },
  "library_path": "workflows/library/<dynamic-path>/",
  "outputs": {
    "workflow_map": "recordings/.../workflow-map.md",
    "prd": "prds/<session-id>/PRD.md",
    "handoff": "prds/<session-id>/handoff-prompt.md"
  },
  "pattern_match": {
    "status": "new" | "extends",
    "extends": "workflows/library/<existing-path>/" 
  }
}
```

## Hard rules
- Folder paths under workflows/library/ are derived from the classification result alone. Never hardcoded.
- All LLM calls use claude-sonnet-4-20250514 via langchain-anthropic.
- All file writes are atomic: write to tmp, fsync, rename.
- The service is stateless. State lives in the Homebase repo.
- No network egress beyond Claude API and Ollama localhost.

## Required env
See `.env.example` (added in Phase 3).
- `ANTHROPIC_API_KEY`
- `HOMEBASE_ROOT` (default: repo root)
- `LANGGRAPH_PORT` (default `8080`)
