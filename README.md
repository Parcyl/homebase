# homebase

Record your work once; homebase turns the recording into a structured doc set —
automatically. **Bring your own tools:** pick your dictation source and your screen
recorder, and homebase watches for a finished session and does the rest.

One shared capture layer feeds **two independent analysis pipelines**, so pick the one that
answers your question (or run both against the same recording):

```
record  (your recorder + your dictation)
  → homebase watches the session folder for a finished raw.mp4 + transcript
  →
     Pipeline A — doc_generator.py               Pipeline B — pipeline_watcher.py
     "what's broken / what was asked"             "what workflow did I just do"
     zoned bug triage via context_config          LangGraph spine (classify → extract →
     + one multimodal Claude call                 ground → compare → generate)
       ↓                                              ↓
     PRD + DIGEST + per-bug cards +               PRD + Claude Code handoff prompt +
     screenshots + team brief, in the             reusable workflow pattern, in
     session folder                               prds/<session>/
```

Full architecture, including the adapter/seam pattern and exact output paths:
**`docs/ARCHITECTURE.md`**.

## Bring-your-own seams

Two things are pluggable, chosen in `.env`:

| Seam | Options | Default |
|------|---------|---------|
| **Dictation** (`DICTATION_PROVIDER`) | `vowen`, `wisprflow`, `file` | `file` — drop your own `transcript.json` |
| **Recorder** (`RECORDER`) | `screen-studio`, `file` | `file` — drop your own MP4 |

Pipeline A's product-specific structure (the "zones" and triage prompt) lives in a
swappable `context_config` — see `context/example-webapp.json`. Pipeline B has no
equivalent config; its LangGraph nodes classify generically.

## Quick start (macOS)

```bash
cp env.example .env       # add your Anthropic key; choose your recorder + provider
# then follow docs/SETUP.md
```

Full setup, provider/recorder configuration, and writing your own adapter: **`docs/SETUP.md`**.
Architecture and the adapter pattern: **`docs/ARCHITECTURE.md`**.

## Status

Pre-release. macOS-first (Linux/Windows are documented seams, not yet shipped).

## License

MIT — see [LICENSE](LICENSE).
