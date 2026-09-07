"""Outcome smoke for Pipeline A (walkthrough -> bug digest).

Runs doc_generator.process_session end to end on the REAL context_config and asserts the full
canonical doc set is produced with zero personal identifiers in the output. Frame extraction and
the model call are stubbed so the smoke runs offline and deterministically; a real run uses ffmpeg
plus your ANTHROPIC_API_KEY.

    python3 smoke/smoke_pipeline_a.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT))
import doc_generator as dg  # noqa: E402


class _StubRecorder:
    name = "stub"

    def start(self, session_dir):
        ...

    def stop(self, session_dir):
        ...

    def resolve_master(self, session_start_epoch, session_dir):
        return None  # the raw.mp4 is already in the session dir


def _stub_extract(mp4, out):
    out.mkdir(parents=True, exist_ok=True)
    return [{"id": "shot_0001", "file": "shot_0001.jpg", "t": 30.0, "timecode": "00:30"}]


def _stub_model(system, content, capture_tool):
    return {
        "summary": "Smoke pass over the example web app.",
        "prd_md": "# PRD\nThe app has a broken save flow.",
        "workflow_map_md": "Frontend save -> Backend submit.",
        "bugs": [
            {"title": "Save button does nothing", "zone": "frontend", "severity": "blocker",
             "screen": "editor", "timecode": "00:30", "what": "click no-op", "repro": "click save",
             "expected": "saves", "suggested_fix": "wire the handler", "screenshot_refs": ["shot_0001"]},
            {"title": "Submit returns 500", "zone": "backend", "severity": "high",
             "what": "500 on POST /submit"},
        ],
    }


def main() -> None:
    cfg = dg.load_context_config(ROOT / "context" / "example-webapp.json")
    home = Path(tempfile.mkdtemp())
    session_dir = home / dg.SESSIONS_DIR / "2026-01-01T09-00-00-smoke"
    session_dir.mkdir(parents=True)
    (session_dir / "raw.mp4").write_bytes(b"placeholder video bytes")
    (session_dir / "transcript.json").write_text(json.dumps(
        {"text": "the frontend save button does nothing and the backend returns 500 on submit",
         "source": "file"}), encoding="utf-8")
    (session_dir / "session.json").write_text(
        json.dumps({"stop_iso": "2026-01-01T09-05"}), encoding="utf-8")

    seen: dict = {}

    def model(system, content, capture_tool):
        seen["system"] = system
        return _stub_model(system, content, capture_tool)

    stage = dg.process_session(home, session_dir, cfg=cfg, recorder=_StubRecorder(),
                               claude_fn=model, extract_fn=_stub_extract)
    assert stage == "ok", f"process_session stage={stage!r}"

    missing = [f for f in ("DIGEST.md", "PRD.md", "INDEX.md", "workflow-map.md", "TEAM_BRIEF.md")
               if not (session_dir / f).exists()]
    assert not missing, f"missing canonical doc-set files: {missing}"
    assert list((session_dir / "bugs").glob("*.md")), "no bug cards produced"
    assert cfg.product_name in seen["system"], "context_config product_name did not reach the prompt"

    leak = subprocess.run(["grep", "-rIiE", "parcyl|brady|/Users/|Syndnet", str(session_dir)],
                          capture_output=True, text=True)
    assert leak.returncode != 0, f"identifier leak in produced output:\n{leak.stdout}"

    print("SMOKE PASS: full canonical doc set produced on the real context_config, zero identifiers.")


if __name__ == "__main__":
    main()
