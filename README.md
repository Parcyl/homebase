# homebase

Record your work once; homebase turns the recording into a structured doc set — a PRD, a
prioritized digest, per-item cards with screenshots, and a team handoff — automatically.

**Bring your own tools.** Pick your dictation source and your screen recorder; homebase does
the rest. It watches for a finished session, extracts frames, runs a multimodal + LangGraph
intelligence pipeline over the video and narration, and writes the docs.

## How it works

```
record  (your recorder + your dictation)
  → homebase watches the session folder
  → frame extraction (ffmpeg) + narration (your transcript provider)
  → intelligence spine  (classify → extract → generate)
  → canonical doc set + handoff bundle
```

## Bring-your-own seams

Two things are pluggable, chosen in `.env`:

| Seam | Options | Default |
|------|---------|---------|
| **Dictation** (`DICTATION_PROVIDER`) | `vowen`, `wisprflow`, `file` | `file` — drop your own `transcript.json` |
| **Recorder** (`RECORDER`) | `screen-studio`, `file` | `file` — drop your own MP4 |

Your product's structure (the "zones" and prompt the analysis uses) lives in a swappable
`context_config` — see `context/example-webapp.json`.

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
