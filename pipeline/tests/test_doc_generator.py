"""Tests for doc_generator (ported from the source project's capture-processor test suite).

Pure stdlib + injected Claude/ffmpeg/recorder. No video, no network, no real Screen Studio.
Exercises the two seams doc_generator was built to be product-agnostic through:
  - RecorderAdapter (recorder/) via resolve_recording / find_pending
  - context_config (context/) via ContextConfig / load_context_config
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import doc_generator as dg


def _cfg(*, zones=None, severities=("blocker", "high", "medium", "low")) -> dg.ContextConfig:
    zones = zones or (
        dg.Zone(code="NB", key="notebook", label="Right — Notebook"),
        dg.Zone(code="RL", key="rail", label="Left — Rail"),
        dg.Zone(code="WS", key="workstation", label="Bottom — Workstation"),
        dg.Zone(code="CX", key="connections", label="Connections — cross-zone wiring"),
    )
    return dg.ContextConfig(
        product_name="Testware",
        zones=zones,
        severities=severities,
        system_prompt_template="Triaging {product_name}.\n\n{context}",
        context_md_text="ground truth layout",
    )


# --- context_config -----------------------------------------------------

def test_load_context_config_reads_json_and_context_md(tmp_path: Path):
    (tmp_path / "layout.md").write_text("The app has two panels.", encoding="utf-8")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({
        "product_name": "Acme",
        "zones": [{"code": "FE", "key": "frontend", "label": "Frontend"}],
        "severities": ["blocker", "low"],
        "system_prompt": "You triage {product_name}.\n\n{context}",
        "context_md": "layout.md",
    }), encoding="utf-8")

    cfg = dg.load_context_config(cfg_path, homebase=tmp_path)
    assert cfg.product_name == "Acme"
    assert cfg.zone_keys == ("frontend", "unclassified")
    assert "two panels" in cfg.context_md_text


def test_context_config_build_system_prompt_injects_product_and_context():
    cfg = _cfg()
    prompt = cfg.build_system_prompt()
    assert "Testware" in prompt
    assert "ground truth layout" in prompt
    # never leaks the example config's own product name into an unrelated config
    assert "Your Web App" not in prompt


def test_context_config_capture_tool_enum_matches_configured_zones_only():
    cfg = _cfg()
    tool = cfg.capture_tool()
    zone_enum = tool["input_schema"]["properties"]["bugs"]["items"]["properties"]["zone"]["enum"]
    assert set(zone_enum) == {"notebook", "rail", "workstation", "connections"}
    assert dg.UNCLASSIFIED_ZONE_KEY not in zone_enum  # never offered as a real choice


def test_example_webapp_context_config_loads_and_is_generic():
    repo_root = Path(__file__).resolve().parents[2]
    cfg = dg.load_context_config(repo_root / "context" / "example-webapp.json", homebase=repo_root)
    assert cfg.product_name == "Your Web App"
    assert set(cfg.zone_keys) >= {"frontend", "backend", "infra"}


# --- small pure helpers -----------------------------------------------------

def test_transcript_text_handles_dict_list_and_str():
    assert dg.transcript_text({"text": "  hello  "}) == "hello"
    assert dg.transcript_text({"segments": [{"text": "a"}, {"text": "b"}]}) == "a\nb"
    assert dg.transcript_text([{"text": "x"}, {"text": "y"}]) == "x\ny"
    assert dg.transcript_text("raw text") == "raw text"
    assert dg.transcript_text(None) == ""


def test_fmt_timecode():
    assert dg.fmt_timecode(0) == "00:00"
    assert dg.fmt_timecode(75) == "01:15"


def test_plan_shot_times_is_bounded_and_centred():
    times = dg.plan_shot_times(600.0, interval_s=15.0, max_shots=48)
    assert len(times) == 40  # 600 / 15
    assert all(0 < t < 600 for t in times)
    assert len(dg.plan_shot_times(100000.0)) == dg.MAX_SHOTS
    assert dg.plan_shot_times(None) == [0.0]


def test_sample_for_vision_caps_evenly():
    manifest = [{"id": f"shot_{i:04d}"} for i in range(100)]
    sampled = dg.sample_for_vision(manifest, cap=10)
    assert len(sampled) == 10
    assert sampled[0]["id"] == "shot_0000"


# --- bug id assignment + zoning ---------------------------------------------

def test_assign_bug_ids_zones_orders_and_coerces_to_unclassified():
    cfg = _cfg()
    bugs = [
        {"title": "rail thing", "zone": "rail", "severity": "low"},
        {"title": "notebook crash", "zone": "notebook", "severity": "blocker"},
        {"title": "notebook polish", "zone": "notebook", "severity": "low"},
        {"title": "weird zone", "zone": "banana", "severity": "high"},  # -> unclassified
    ]
    out = dg.assign_bug_ids(bugs, cfg)
    by_title = {b["title"]: b for b in out}
    assert by_title["notebook crash"]["id"] == "NB-01"
    assert by_title["notebook polish"]["id"] == "NB-02"
    assert by_title["rail thing"]["id"] == "RL-01"
    assert by_title["weird zone"]["zone"] == dg.UNCLASSIFIED_ZONE_KEY
    assert by_title["weird zone"]["id"] == "UNC-01"
    assert by_title["notebook crash"]["filename"].startswith("notebook-01-")


def test_screenshot_refs_md_relative_paths():
    manifest_by_id = {"shot_0003": {"id": "shot_0003", "file": "shot_0003.jpg", "timecode": "00:45"}}
    from_bug = dg._screenshot_refs_md(["shot_0003"], manifest_by_id, from_subdir=True)
    assert "../screenshots/shot_0003.jpg" in from_bug
    from_root = dg._screenshot_refs_md(["shot_0003"], manifest_by_id, from_subdir=False)
    assert "screenshots/shot_0003.jpg" in from_root and "../" not in from_root
    assert dg._screenshot_refs_md(["nope"], manifest_by_id, from_subdir=False) == "_No screenshot linked._"


# --- rendering --------------------------------------------------------------

def _sample_result() -> dict:
    return {
        "summary": "A pass over the notebook and rail.",
        "prd_md": "# PRD\nbody",
        "workflow_map_md": "Notebook connects to Workstation.",
        "bugs": [
            {"title": "Notebook will not scroll", "zone": "notebook", "severity": "blocker",
             "screen": "right panel", "timecode": "01:10", "what": "stuck", "repro": "scroll",
             "expected": "scrolls", "suggested_fix": "fix overflow", "screenshot_refs": ["shot_0001"]},
            {"title": "CRM list empty", "zone": "rail", "severity": "high", "what": "no rows"},
            {"title": "Panel handoff drops state", "zone": "connections", "severity": "high",
             "what": "state lost between rail and workstation"},
        ],
    }


def test_render_index_groups_by_zone():
    cfg = _cfg()
    bugs = dg.assign_bug_ids(_sample_result()["bugs"], cfg)
    idx = dg.render_index("2026-06-25T10-00-00", bugs, cfg)
    assert "Right — Notebook" in idx and "Left — Rail" in idx and "Connections" in idx
    assert "NB-01" in idx and "bugs/notebook-01-" in idx


def test_render_digest_has_all_zone_sections_and_map():
    cfg = _cfg()
    bugs = dg.assign_bug_ids(_sample_result()["bugs"], cfg)
    manifest_by_id = {"shot_0001": {"id": "shot_0001", "file": "shot_0001.jpg", "timecode": "01:10"}}
    digest = dg.render_digest("sid", {"stop_iso": "2026-06-25"}, bugs, _sample_result(), manifest_by_id, cfg)
    for zone in cfg.zones:
        assert zone.label in digest
    assert "Workflow-connection map" in digest
    assert "Notebook connects to Workstation." in digest
    assert "screenshots/shot_0001.jpg" in digest  # root-relative ref in digest


# --- write_outputs ----------------------------------------------------------

def test_write_outputs_creates_all_files(tmp_path: Path):
    cfg = _cfg()
    session_dir = tmp_path / "sid"
    session_dir.mkdir()
    manifest = [{"id": "shot_0001", "file": "shot_0001.jpg", "t": 70.0, "timecode": "01:10"}]
    written = dg.write_outputs(session_dir, "sid", {"recording_path": "x"}, _sample_result(), manifest, cfg)
    assert (session_dir / "PRD.md").exists()
    assert (session_dir / "workflow-map.md").exists()
    assert (session_dir / "INDEX.md").exists()
    assert (session_dir / "DIGEST.md").exists()
    bug_files = list((session_dir / "bugs").glob("*.md"))
    assert len(bug_files) == 3
    assert written["bug_count"] == "3"
    nb = (session_dir / "bugs" / "notebook-01-notebook-will-not-scroll.md").read_text()
    assert "NB-01" in nb and "../screenshots/shot_0001.jpg" in nb


def test_assemble_team_brief_consolidates_and_fixes_refs(tmp_path: Path):
    cfg = _cfg()
    session_dir = tmp_path / "sid"
    session_dir.mkdir()
    manifest = [{"id": "shot_0001", "file": "shot_0001.jpg", "t": 70.0, "timecode": "01:10"}]
    dg.write_outputs(session_dir, "sid", {"recording_path": "x"}, _sample_result(), manifest, cfg)
    brief = (session_dir / "TEAM_BRIEF.md").read_text()
    assert "Session Bug & Wiring Brief" in brief
    assert "3 items total" in brief
    assert "Notebook will not scroll" in brief and "CRM list empty" in brief
    assert "Panel handoff drops state" in brief
    assert "screenshots/shot_0001.jpg" in brief and "../screenshots/" not in brief
    assert "Workflow-Connection Map" in brief and "Appendix: PRD" in brief


def test_assemble_team_brief_never_drops_non_canonical_zones(tmp_path: Path):
    """Bugs whose zone-prefix isn't a configured zone must still ship in the brief."""
    cfg = _cfg()
    session_dir = tmp_path / "sid"
    session_dir.mkdir()
    bugs = session_dir / "bugs"
    bugs.mkdir()
    (bugs / "notebook-01-canonical-zone.md").write_text("# Canonical zone bug\n")
    (bugs / "sage-01-non-canonical-zone.md").write_text("# Sage zone bug\n")
    (bugs / "maptools-01-also-non-canonical.md").write_text("# Maptools zone bug\n")

    assert dg.assemble_team_brief(session_dir, cfg) == "TEAM_BRIEF.md"
    brief = (session_dir / "TEAM_BRIEF.md").read_text()

    assert "3 items total" in brief
    assert "Canonical zone bug" in brief
    assert "Sage zone bug" in brief
    assert "Maptools zone bug" in brief
    assert "# Sage" in brief and "# Maptools" in brief


# --- recording adoption via RecorderAdapter ---------------------------------

def test_resolve_recording_returns_existing_raw(tmp_path: Path):
    session_dir = tmp_path / "sid"
    session_dir.mkdir()
    (session_dir / "raw.mp4").write_bytes(b"already there")
    recorder = _FakeRecorder(master=None)
    got = dg.resolve_recording(session_dir, recorder, 1000.0)
    assert got == session_dir / "raw.mp4"


class _FakeRecorder:
    name = "fake"

    def __init__(self, master: Path | None):
        self.master = master

    def start(self, session_dir: Path) -> None:
        pass

    def stop(self, session_dir: Path) -> None:
        pass

    def resolve_master(self, session_start_epoch: float, session_dir: Path) -> Path | None:
        return self.master


def test_resolve_recording_renames_stray_inside_session_dir(tmp_path: Path):
    session_dir = tmp_path / "sid"
    session_dir.mkdir()
    stray = session_dir / "Area.mp4"
    stray.write_bytes(b"video")
    recorder = _FakeRecorder(master=stray)
    out = dg.resolve_recording(session_dir, recorder, 1000.0)
    assert out.name == "raw.mp4"
    assert (session_dir / "raw.mp4").exists() and not stray.exists()


def test_resolve_recording_copies_master_from_outside_session_dir(tmp_path: Path):
    session_dir = tmp_path / "sid"
    session_dir.mkdir()
    master = tmp_path / "elsewhere" / "master.mp4"
    master.parent.mkdir()
    master.write_bytes(b"VIDEO-BYTES")
    recorder = _FakeRecorder(master=master)
    out = dg.resolve_recording(session_dir, recorder, 1000.0)
    assert out == session_dir / "raw.mp4"
    assert (session_dir / "raw.mp4").read_bytes() == b"VIDEO-BYTES"
    assert not (session_dir / "raw.mp4.partial").exists()
    assert master.exists()  # source untouched, this was a copy not a move


def test_resolve_recording_none_when_recorder_finds_nothing(tmp_path: Path):
    session_dir = tmp_path / "sid"
    session_dir.mkdir()
    recorder = _FakeRecorder(master=None)
    assert dg.resolve_recording(session_dir, recorder, 1000.0) is None


def test_find_pending_skips_processed_and_uses_recorder(tmp_path: Path):
    base = tmp_path / dg.SESSIONS_DIR
    base.mkdir(parents=True)
    ready = base / "ready"
    ready.mkdir()
    (ready / "raw.mp4").write_bytes(b"x")
    old = (ready / "raw.mp4").stat().st_mtime - 600
    os.utime(ready / "raw.mp4", (old, old))

    done = base / "done"
    done.mkdir()
    (done / "raw.mp4").write_bytes(b"x")
    (done / ".processed").touch()

    no_mp4 = base / "empty"
    no_mp4.mkdir()

    pending = dg.find_pending(tmp_path, recorder=_FakeRecorder(master=None))
    names = {p.name for p in pending}
    assert names == {"ready"}


def test_find_pending_alerts_on_stale_session_no_recording(tmp_path: Path, monkeypatch):
    homebase = tmp_path
    sd = homebase / dg.SESSIONS_DIR / "sid"
    sd.mkdir(parents=True)
    (sd / "session.json").write_text(json.dumps({"start_epoch": 1.0}), encoding="utf-8")  # ancient
    monkeypatch.setattr(dg.os, "system", lambda *a, **k: 0)
    pend = dg.find_pending(homebase, recorder=_FakeRecorder(master=None))
    assert sd not in pend
    assert (sd / ".capture-alert").exists()
    assert (sd / ".stale-alerted").exists()  # alerts once, not every poll


def test_find_pending_skips_session_that_is_still_recording(tmp_path: Path):
    import time as _time
    homebase = tmp_path
    sd = homebase / dg.SESSIONS_DIR / "sid"
    sd.mkdir(parents=True)
    (sd / "session.json").write_text(json.dumps({"start_epoch": _time.time()}), encoding="utf-8")
    raw = sd / "raw.mp4"
    raw.write_bytes(b"PARTIAL")
    old = raw.stat().st_mtime - 600
    os.utime(raw, (old, old))
    assert sd not in dg.find_pending(homebase, recorder=_FakeRecorder(master=raw))


# --- end to end process_session (injected Claude + ffmpeg + recorder + context) --------

def _fake_claude(system: str, content: list[dict], capture_tool: dict) -> dict:
    return _sample_result()


def _fake_extract(mp4: Path, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    return [{"id": "shot_0001", "file": "shot_0001.jpg", "t": 70.0, "timecode": "01:10"}]


def test_process_session_end_to_end(tmp_path: Path):
    cfg = _cfg()
    homebase = tmp_path
    session_dir = homebase / dg.SESSIONS_DIR / "2026-06-25T10-00-00"
    session_dir.mkdir(parents=True)
    (session_dir / "raw.mp4").write_bytes(b"not a real video")
    (session_dir / "transcript.json").write_text(
        json.dumps({"text": "the notebook will not scroll and the CRM is empty", "source": "file"}),
        encoding="utf-8",
    )
    (session_dir / "session.json").write_text(json.dumps({"stop_iso": "2026-06-25T10-05"}), encoding="utf-8")

    captured = {}

    def claude_fn(system, content, capture_tool):
        captured["system"] = system
        captured["content"] = content
        captured["capture_tool"] = capture_tool
        return _sample_result()

    stage = dg.process_session(homebase, session_dir, cfg=cfg, recorder=_FakeRecorder(master=None),
                               claude_fn=claude_fn, extract_fn=_fake_extract)
    assert stage == "ok"
    assert (session_dir / "DIGEST.md").exists()
    assert (session_dir / ".processed").exists()
    assert len(list((session_dir / "bugs").glob("*.md"))) == 3
    assert "notebook will not scroll" in captured["content"][-1]["text"]
    assert captured["capture_tool"]["name"] == "submit_capture"
    # the context_config's product name reached the system prompt, not a hardcoded one
    assert cfg.product_name in captured["system"]
    state = json.loads((homebase / dg.STATE_FILE).read_text())
    assert state["stage"] == "complete"


def test_process_session_retries_when_no_transcript(tmp_path: Path):
    cfg = _cfg()
    homebase = tmp_path
    session_dir = homebase / dg.SESSIONS_DIR / "sid"
    session_dir.mkdir(parents=True)
    (session_dir / "raw.mp4").write_bytes(b"x")
    # no transcript.json, no session.json -> ensure_transcript returns None

    called = {"n": 0}

    def claude_fn(system, content, capture_tool):
        called["n"] += 1
        return _sample_result()

    stage = dg.process_session(homebase, session_dir, cfg=cfg, recorder=_FakeRecorder(master=None),
                               claude_fn=claude_fn, extract_fn=lambda m, o: [])
    assert stage == "error"
    assert called["n"] == 0  # never reached the model
    assert not (session_dir / ".processed").exists()  # transient -> retry next poll


def test_process_session_lock_blocks_concurrent_run(tmp_path: Path):
    cfg = _cfg()
    homebase = tmp_path
    sd = homebase / dg.SESSIONS_DIR / "sid"
    sd.mkdir(parents=True)
    (sd / "raw.mp4").write_bytes(b"x")
    (sd / "transcript.json").write_text(json.dumps({"text": "the notebook is broken"}), encoding="utf-8")
    (sd / ".lock").write_text("held", encoding="utf-8")
    called = {"n": 0}
    stage = dg.process_session(
        homebase, sd, cfg=cfg, recorder=_FakeRecorder(master=None),
        claude_fn=lambda s, c, t: called.__setitem__("n", called["n"] + 1) or _sample_result(),
        extract_fn=lambda m, o: [])
    assert stage == "locked"
    assert called["n"] == 0
    assert (sd / ".lock").exists()


def test_process_session_steals_stale_lock(tmp_path: Path):
    cfg = _cfg()
    homebase = tmp_path
    sd = homebase / dg.SESSIONS_DIR / "sid"
    sd.mkdir(parents=True)
    (sd / "raw.mp4").write_bytes(b"x")
    (sd / "transcript.json").write_text(json.dumps({"text": "broken notebook"}), encoding="utf-8")
    lock = sd / ".lock"
    lock.write_text("old", encoding="utf-8")
    old = lock.stat().st_mtime - (dg.LOCK_STALE_S + 60)
    os.utime(lock, (old, old))
    stage = dg.process_session(homebase, sd, cfg=cfg, recorder=_FakeRecorder(master=None),
                               claude_fn=lambda s, c, t: _sample_result(), extract_fn=lambda m, o: [])
    assert stage == "ok"
    assert not lock.exists()


# --- backup-audio narration fallback (provider-independent) -----------------

def test_transcribe_audio_backup_recovers_text(tmp_path: Path):
    import capture_audio_backup as cab
    sd = tmp_path / "sid"
    sd.mkdir()
    (sd / cab.BACKUP_NAME).write_bytes(b"\x00" * (dg.MIN_BACKUP_AUDIO_BYTES + 10))
    text = dg.transcribe_audio_backup(sd, transcriber=lambda p: "  recovered narration  ")
    assert text == "recovered narration"
    assert (sd / ".narration-source").exists()


def test_transcribe_audio_backup_none_when_no_file(tmp_path: Path):
    sd = tmp_path / "sid"
    sd.mkdir()
    assert dg.transcribe_audio_backup(sd, transcriber=lambda p: "x") is None


def test_transcribe_audio_backup_none_when_too_small(tmp_path: Path):
    import capture_audio_backup as cab
    sd = tmp_path / "sid"
    sd.mkdir()
    (sd / cab.BACKUP_NAME).write_bytes(b"\x00" * 10)  # header-only, not speech
    assert dg.transcribe_audio_backup(sd, transcriber=lambda p: "x") is None


def test_transcribe_audio_backup_swallows_transcriber_error(tmp_path: Path):
    import capture_audio_backup as cab
    sd = tmp_path / "sid"
    sd.mkdir()
    (sd / cab.BACKUP_NAME).write_bytes(b"\x00" * (dg.MIN_BACKUP_AUDIO_BYTES + 10))

    def boom(_p):
        raise RuntimeError("model unavailable")

    assert dg.transcribe_audio_backup(sd, transcriber=boom) is None


def test_process_session_uses_backup_when_provider_empty(tmp_path: Path, monkeypatch):
    import capture_audio_backup as cab
    cfg = _cfg()
    homebase = tmp_path
    sd = homebase / dg.SESSIONS_DIR / "sid"
    sd.mkdir(parents=True)
    (sd / "raw.mp4").write_bytes(b"x")
    # transcript.json present but EMPTY (the silent-freeze shape), backup has audio.
    (sd / "transcript.json").write_text(json.dumps({"text": ""}), encoding="utf-8")
    (sd / cab.BACKUP_NAME).write_bytes(b"\x00" * (dg.MIN_BACKUP_AUDIO_BYTES + 10))
    monkeypatch.setattr(dg, "_mlx_transcribe", lambda a: "backup says fix the notebook")

    seen = {}

    def claude_fn(system, content, capture_tool):
        seen["content"] = content
        return _sample_result()

    stage = dg.process_session(homebase, sd, cfg=cfg, recorder=_FakeRecorder(master=None),
                               claude_fn=claude_fn, extract_fn=lambda m, o: [])
    assert stage == "ok"
    blob = json.dumps(seen["content"])
    assert "backup says fix the notebook" in blob
    assert (sd / ".narration-source").exists()
