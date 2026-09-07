"""Session capture processor.

Turns a narrated walkthrough (screen video + narration) into a developer-ready digest: a
full PRD, a workflow-connection map, and a zoned bug list (one MD per bug + an index + a
single master DIGEST partitioned by zone) -- plus a self-contained TEAM_BRIEF.md.

Ported from the source project's session-capture processor script. Two couplings were
swapped for pluggable seams so this file has no product-specific knowledge left in it:

  - the screen recorder      -> providers/recorder/ (RecorderAdapter), see resolve_recording
  - the zones/severities/prompt -> context/ (context_config), see ContextConfig below

Everything else -- ffmpeg frame extraction, the streaming multimodal Claude call, the
doc-set rendering, the concurrency lock, the Screen-Studio-export auto-adopt lock-in, the
backup-audio narration fallback -- is the same logic, unchanged.

Reused, proven primitives:
- record_session.py for deferred TranscriptProvider capture (same flow the recording
  start/stop markers use).
- ffmpeg fast input-seek frame extraction.
- the streaming-Claude lesson: a large structured generation MUST stream or it read-times-
  out and the Anthropic API interrupts it past ~10 min.

Side effects (ffmpeg, the Anthropic call, the recorder) are isolated behind injectable
callables so the logic is unit-testable without a GPU, a video, or a network.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
for _p in (_REPO_ROOT, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from providers.recorder import RecorderAdapter, get_recorder  # noqa: E402
import capture_audio_backup  # noqa: E402

DEFAULT_HOMEBASE = Path(os.environ.get("HOMEBASE_ROOT", str(_REPO_ROOT)))
# Must match record_session.py's own default so Start/Stop and this processor agree on
# where sessions live.
SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "recordings")
DEFAULT_CONTEXT_CONFIG = os.environ.get("CONTEXT_CONFIG", "context/example-webapp.json")

DEFAULT_FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
DEFAULT_FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

POLL_INTERVAL_S = 5
# Backstop only. session_is_live() is the real "still recording" gate; this just lets a
# just-finished copy finish flushing.
RECORDING_SETTLE_S = 30
MAX_TRANSCRIPT_ATTEMPTS = 3
# Past this, a session with no stop_epoch is abandoned (crash / forced quit) rather than
# recording, so it stops being shielded by session_is_live() and can alert as stale.
MAX_LIVE_SESSION_S = float(os.environ.get("MAX_LIVE_SESSION_S", str(6 * 3600)))
STALE_RECORDING_ALERT_S = float(os.environ.get("STALE_ALERT_S", "600"))  # 10 min
# A per-session lock older than this is assumed orphaned by a crashed run and stolen, so a
# session can never wedge forever. A real run finishes well under this.
LOCK_STALE_S = 1800

# Frame extraction: one shot per SHOT_INTERVAL_S, bounded by MAX_SHOTS on disk. To keep the
# vision payload (and cost) sane, at most MAX_SHOTS_TO_CLAUDE evenly-sampled frames are fed
# to the model; all extracted frames stay on disk for review.
SHOT_INTERVAL_S = 15.0
MAX_SHOTS = 48
MAX_SHOTS_TO_CLAUDE = 24
SHOT_WIDTH = 768  # downscale width for the frames fed to Claude

# Always available on top of whatever zones a context_config declares, so a bug the model
# files under an unrecognized zone is never dropped. See context/schema.md.
UNCLASSIFIED_ZONE_KEY = "unclassified"
UNCLASSIFIED_ZONE_LABEL = "Unclassified"
UNCLASSIFIED_ZONE_CODE = "UNC"

log = logging.getLogger("homebase.doc_generator")


# --- context_config -----------------------------------------------------------

@dataclass(frozen=True)
class Zone:
    code: str
    key: str
    label: str


@dataclass(frozen=True)
class ContextConfig:
    """Product-specific analysis context, loaded from a JSON file (see context/schema.md).

    Nothing in this module hardcodes a product's zones, severities, or triage prompt --
    point CONTEXT_CONFIG at a different config file and doc_generator analyzes a different
    product with no code change.
    """

    product_name: str
    zones: tuple[Zone, ...]
    severities: tuple[str, ...]
    system_prompt_template: str
    context_md_text: str

    @property
    def zone_keys(self) -> tuple[str, ...]:
        return tuple(z.key for z in self.zones) + (UNCLASSIFIED_ZONE_KEY,)

    @property
    def zone_label(self) -> dict[str, str]:
        return {**{z.key: z.label for z in self.zones}, UNCLASSIFIED_ZONE_KEY: UNCLASSIFIED_ZONE_LABEL}

    @property
    def zone_code(self) -> dict[str, str]:
        return {**{z.key: z.code for z in self.zones}, UNCLASSIFIED_ZONE_KEY: UNCLASSIFIED_ZONE_CODE}

    @property
    def severity_rank(self) -> dict[str, int]:
        return {s: i for i, s in enumerate(self.severities)}

    def build_system_prompt(self) -> str:
        return self.system_prompt_template.format(
            product_name=self.product_name, context=self.context_md_text)

    def capture_tool(self) -> dict[str, Any]:
        """The forced-tool schema for the structured Claude call. `zone` is constrained to
        the CONFIGURED zones only (not the unclassified catch-all) -- that bucket exists to
        absorb a model deviating from the schema, not to be offered as a real choice."""
        return {
            "name": "submit_capture",
            "description": "Return the full PRD, the workflow-connection map, and the zoned bug list.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "1-2 sentence overview of the pass."},
                    "prd_md": {"type": "string", "description": "Full PRD in markdown for this walkthrough."},
                    "workflow_map_md": {
                        "type": "string",
                        "description": "Markdown map of how the workflows/zones should connect.",
                    },
                    "bugs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "zone": {"type": "string", "enum": [z.key for z in self.zones]},
                                "severity": {"type": "string", "enum": list(self.severities)},
                                "screen": {"type": "string", "description": "Where in the app."},
                                "timecode": {"type": "string", "description": "mm:ss into the recording, if known."},
                                "what": {"type": "string", "description": "What is broken."},
                                "repro": {"type": "string", "description": "Steps to reproduce."},
                                "expected": {"type": "string", "description": "Expected behavior."},
                                "suggested_fix": {"type": "string"},
                                "screenshot_refs": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Shot ids shown to you, e.g. shot_0007.",
                                },
                                "notes": {"type": "string"},
                            },
                            "required": ["title", "zone", "severity", "what"],
                        },
                    },
                },
                "required": ["summary", "prd_md", "workflow_map_md", "bugs"],
            },
        }


def _resolve_repo_path(raw: str, homebase: Path = DEFAULT_HOMEBASE) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else homebase / path


def load_context_config(path: Path, *, homebase: Path = DEFAULT_HOMEBASE) -> ContextConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    zones = tuple(Zone(code=z["code"], key=z["key"], label=z["label"]) for z in data["zones"])
    context_md_path = _resolve_repo_path(data["context_md"], homebase)
    context_md_text = context_md_path.read_text(encoding="utf-8") if context_md_path.exists() else ""
    return ContextConfig(
        product_name=data["product_name"],
        zones=zones,
        severities=tuple(data["severities"]),
        system_prompt_template=data["system_prompt"],
        context_md_text=context_md_text,
    )


# --- helpers --------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len].strip("-") or "item"


def fmt_timecode(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def transcript_text(transcript: Any) -> str:
    """Pull plain narration text from a provider dict, a segment list, or a raw string."""
    if transcript is None:
        return ""
    if isinstance(transcript, str):
        return transcript.strip()
    if isinstance(transcript, dict):
        if isinstance(transcript.get("text"), str):
            return transcript["text"].strip()
        segments = transcript.get("segments")
        if isinstance(segments, list):
            return "\n".join(
                seg.get("text", "").strip() for seg in segments if isinstance(seg, dict)
            ).strip()
        return ""
    if isinstance(transcript, list):
        parts: list[str] = []
        for seg in transcript:
            if isinstance(seg, dict) and isinstance(seg.get("text"), str):
                parts.append(seg["text"].strip())
            elif isinstance(seg, str):
                parts.append(seg.strip())
        return "\n".join(p for p in parts if p).strip()
    return ""


# --- screenshots ------------------------------------------------------------

def probe_duration(mp4: Path, ffprobe_bin: str = DEFAULT_FFPROBE) -> float | None:
    cmd = [
        ffprobe_bin, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(mp4),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        duration = float(out.stdout.decode("utf-8", "replace").strip())
        return duration if duration > 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError) as e:
        log.warning("ffprobe_duration_failed err=%s", e)
        return None


def plan_shot_times(duration: float | None, interval_s: float = SHOT_INTERVAL_S,
                    max_shots: int = MAX_SHOTS) -> list[float]:
    """Evenly-spaced sample times. One per interval_s, capped at max_shots, centred so the
    first and last frames (often blank/transition) are avoided. Length-aware and fast: each
    frame is grabbed by input seek, never a full decode."""
    if not duration or duration <= 0:
        return [0.0]
    count = max(1, min(max_shots, int(duration // interval_s) or 1))
    return [duration * (i + 0.5) / count for i in range(count)]


def extract_screenshots(
    mp4: Path,
    shots_dir: Path,
    *,
    ffmpeg_bin: str = DEFAULT_FFMPEG,
    ffprobe_bin: str = DEFAULT_FFPROBE,
    width: int = SHOT_WIDTH,
    runner: Callable[[list[str]], None] | None = None,
) -> list[dict]:
    """Extract evenly-spaced, downscaled frames. Returns a manifest list of
    {id, file, t, timecode}. Writes manifest.json alongside the frames. Best-effort per
    frame; never raises. `runner` is injectable for tests."""
    shots_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(mp4, ffprobe_bin)
    times = plan_shot_times(duration)

    def _run(cmd: list[str]) -> None:
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)

    run = runner or _run
    manifest: list[dict] = []
    for idx, t in enumerate(times, start=1):
        shot_id = f"shot_{idx:04d}"
        fname = f"{shot_id}.jpg"
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", f"{t:.3f}", "-i", str(mp4),
            "-frames:v", "1",
            "-vf", f"scale={width}:-1",
            "-q:v", "4",
            str(shots_dir / fname),
        ]
        try:
            run(cmd)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            log.warning("ffmpeg_shot_failed t=%.3f err=%s", t, e)
        if (shots_dir / fname).exists():
            manifest.append({"id": shot_id, "file": fname, "t": round(t, 3), "timecode": fmt_timecode(t)})

    (shots_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log.info("shots_extracted produced=%d planned=%d duration=%s", len(manifest), len(times), duration)
    return manifest


def sample_for_vision(manifest: list[dict], cap: int = MAX_SHOTS_TO_CLAUDE) -> list[dict]:
    """Evenly sample at most `cap` frames from the manifest to feed Claude."""
    if len(manifest) <= cap:
        return list(manifest)
    step = len(manifest) / cap
    return [manifest[int(i * step)] for i in range(cap)]


# --- Claude call ------------------------------------------------------------

def build_user_content(narration: str, vision_shots: list[dict], shots_dir: Path,
                       coverage_md: str = "") -> list[dict]:
    """Interleave a labelled text block + image for each frame, then the full narration.

    If coverage_md is provided (a checklist of items a prior audit found missing), it is
    appended as a REQUIRED-coverage block so a regeneration does not drop them again.
    """
    content: list[dict] = [{
        "type": "text",
        "text": (
            "Screenshots from the recording follow, each labelled with its shot id and "
            "timecode. Cite these ids in screenshot_refs."
        ),
    }]
    for shot in vision_shots:
        img_path = shots_dir / shot["file"]
        try:
            data = base64.standard_b64encode(img_path.read_bytes()).decode("ascii")
        except OSError:
            continue
        content.append({"type": "text", "text": f"{shot['id']} @ {shot['timecode']}"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
        })
    content.append({
        "type": "text",
        "text": "=== NARRATION (source of truth) ===\n\n" + (narration or "(no narration captured)"),
    })
    if coverage_md.strip():
        content.append({
            "type": "text",
            "text": (
                "=== REQUIRED COVERAGE CHECKLIST ===\n\n"
                "A prior audit found these items in the narration were missed or only partially "
                "captured. You MUST represent each one, either as its own bug or as explicit "
                "detail inside the relevant bug. Do not drop any. Stay grounded in the narration.\n\n"
                + coverage_md
            ),
        })
    return content


def call_claude(system: str, content: list[dict], capture_tool: dict, *,
                model: str = ANTHROPIC_MODEL, api_key: str | None = None) -> dict:
    """Streaming, forced-tool structured call. Returns the tool input dict.

    MUST stream: a 16k-token structured generation read-times-out non-streaming and the API
    interrupts it past ~10 min. messages.stream + get_final_message keeps the read clock
    fed and aggregates the final tool_use block.
    """
    import anthropic  # imported lazily so the module imports without the SDK (tests)

    client = anthropic.Anthropic(api_key=api_key or _resolve_api_key())
    with client.messages.stream(
        model=model,
        # A dense walkthrough yields a large zoned bug list + PRD + workflow map. 16k
        # truncated the structured tool input mid-JSON and failed validation; 32k fits a
        # full session with headroom. Streaming keeps the read clock fed regardless.
        max_tokens=32000,
        temperature=0.3,
        system=system,
        tools=[capture_tool],
        tool_choice={"type": "tool", "name": capture_tool["name"]},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        final = stream.get_final_message()

    for block in final.content:
        if getattr(block, "type", None) == "tool_use" and block.name == capture_tool["name"]:
            return dict(block.input)
    raise RuntimeError(f"Claude returned no {capture_tool['name']} tool call")


def _resolve_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    # Fallback to the repo-root .env so this runs the same standalone as under a service.
    env_path = DEFAULT_HOMEBASE / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


# --- output writers ---------------------------------------------------------

def _screenshot_refs_md(refs: list[str], manifest_by_id: dict[str, dict], *, from_subdir: bool) -> str:
    prefix = "../screenshots/" if from_subdir else "screenshots/"
    lines: list[str] = []
    for ref in refs or []:
        entry = manifest_by_id.get(ref)
        if not entry:
            continue
        lines.append(f"![{ref} @ {entry['timecode']}]({prefix}{entry['file']})")
    return "\n\n".join(lines) if lines else "_No screenshot linked._"


def assign_bug_ids(bugs: list[dict], cfg: ContextConfig) -> list[dict]:
    """Stable, zone-scoped ids (NB-01, RL-01, ...) and a filename for each bug.

    Sorted within a zone by severity so blockers come first. Returns new dicts (immutable).
    A bug whose zone isn't one of cfg's configured zones is coerced to the built-in
    unclassified catch-all rather than dropped.
    """
    out: list[dict] = []
    zone_keys = cfg.zone_keys
    zone_code = cfg.zone_code
    severity_rank = cfg.severity_rank
    # An unrecognized/missing severity sorts to the middle of the configured scale, not to
    # either extreme.
    default_rank = len(cfg.severities) // 2
    by_zone: dict[str, list[dict]] = {z: [] for z in zone_keys}
    for bug in bugs:
        zone = bug.get("zone") if bug.get("zone") in zone_keys else UNCLASSIFIED_ZONE_KEY
        by_zone[zone].append(bug)
    for zone in zone_keys:
        ordered = sorted(
            by_zone[zone],
            key=lambda b: severity_rank.get(b.get("severity", ""), default_rank),
        )
        for n, bug in enumerate(ordered, start=1):
            bid = f"{zone_code[zone]}-{n:02d}"
            enriched = {
                **bug,
                "zone": zone,
                "id": bid,
                "filename": f"{zone}-{n:02d}-{slugify(bug.get('title', ''))}.md",
            }
            out.append(enriched)
    return out


def render_bug_md(bug: dict, manifest_by_id: dict[str, dict], cfg: ContextConfig) -> str:
    return (
        f"# {bug['id']} — {bug.get('title', '(untitled)')}\n\n"
        f"- **Zone:** {cfg.zone_label.get(bug['zone'], bug['zone'])}\n"
        f"- **Severity:** {bug.get('severity', '')}\n"
        f"- **Screen / location:** {bug.get('screen', '_(unspecified)_')}\n"
        f"- **Timecode:** {bug.get('timecode', '_(unknown)_')}\n\n"
        f"## What is broken\n{bug.get('what', '')}\n\n"
        f"## Steps to reproduce\n{bug.get('repro', '_(not specified)_')}\n\n"
        f"## Expected behavior\n{bug.get('expected', '_(not specified)_')}\n\n"
        f"## Suggested fix\n{bug.get('suggested_fix', '_(none suggested)_')}\n\n"
        f"## Screenshots\n{_screenshot_refs_md(bug.get('screenshot_refs', []), manifest_by_id, from_subdir=True)}\n\n"
        f"## Notes\n{bug.get('notes', '_(none)_')}\n"
    )


def _counts(bugs: list[dict], cfg: ContextConfig) -> dict[str, int]:
    c = {s: 0 for s in cfg.severities}
    for bug in bugs:
        sev = bug.get("severity", "")
        if sev in c:
            c[sev] += 1
    return c


def _counts_line(c: dict[str, int]) -> str:
    return ", ".join(f"{count} {sev}" for sev, count in c.items())


def render_index(session_id: str, bugs: list[dict], cfg: ContextConfig) -> str:
    lines = [f"# Bug Index — {session_id}\n"]
    c = _counts(bugs, cfg)
    lines.append(f"{len(bugs)} items: {_counts_line(c)}.\n")
    for zone in cfg.zone_keys:
        zone_bugs = [b for b in bugs if b["zone"] == zone]
        if not zone_bugs:
            continue
        lines.append(f"## {cfg.zone_label[zone]}\n")
        lines.append("| ID | Severity | Title | File |")
        lines.append("| --- | --- | --- | --- |")
        for b in zone_bugs:
            lines.append(
                f"| {b['id']} | {b.get('severity', '')} | {b.get('title', '')} "
                f"| [{b['filename']}](bugs/{b['filename']}) |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _zone_section(bugs: list[dict], zone: str, manifest_by_id: dict[str, dict]) -> str:
    zone_bugs = [b for b in bugs if b["zone"] == zone]
    if not zone_bugs:
        return "_No items in this zone._"
    blocks: list[str] = []
    for b in zone_bugs:
        shots = _screenshot_refs_md(b.get("screenshot_refs", []), manifest_by_id, from_subdir=False)
        blocks.append(
            f"### {b['id']} — {b.get('title', '')}  ·  `{b.get('severity', '')}`\n\n"
            f"- **Screen:** {b.get('screen', '_(unspecified)_')}  ·  **Timecode:** {b.get('timecode', '—')}\n"
            f"- **Broken:** {b.get('what', '')}\n"
            f"- **Expected:** {b.get('expected', '_(not specified)_')}\n"
            f"- **Fix:** {b.get('suggested_fix', '_(none suggested)_')}\n"
            f"- **Detail:** [`bugs/{b['filename']}`](bugs/{b['filename']})\n\n"
            f"{shots}"
        )
    return "\n\n".join(blocks)


def _dispatch_md(cfg: ContextConfig) -> str:
    lines = ["## How to dispatch this\n"]
    for zone in cfg.zones:
        lines.append(f"- **{zone.label}** -> one developer.")
    lines.append("\nHand this file to Claude and it can fan out an agent per zone.\n")
    return "\n".join(lines)


def render_digest(session_id: str, meta: dict, bugs: list[dict], result: dict,
                  manifest_by_id: dict[str, dict], cfg: ContextConfig) -> str:
    c = _counts(bugs, cfg)
    captured = meta.get("stop_iso") or meta.get("start_iso") or _now_iso()
    recording = meta.get("recording_path", f"{SESSIONS_DIR}/{session_id}/raw.mp4")
    summary = result.get("summary", "").strip()
    sections = "\n\n".join(
        f"## {cfg.zone_label[z]}\n\n{_zone_section(bugs, z, manifest_by_id)}"
        for z in cfg.zone_keys
    )
    return (
        f"# {cfg.product_name} — Session Digest — {session_id}\n\n"
        "> Single hand-off doc. Each zone is a self-contained worklist so one developer can "
        "take it end to end. Per-bug detail lives in `bugs/`.\n\n"
        f"- **Captured:** {captured}\n"
        f"- **Recording:** `{recording}`\n"
        f"- **Totals:** {len(bugs)} items — {_counts_line(c)}\n\n"
        + (f"**Summary.** {summary}\n\n" if summary else "")
        + _dispatch_md(cfg) + "\n---\n\n"
        + sections + "\n\n---\n\n"
        f"## Workflow-connection map\n\n{result.get('workflow_map_md', '').strip()}\n"
    )


def assemble_team_brief(session_dir: Path, cfg: ContextConfig) -> str | None:
    """Stitch the on-disk session outputs into ONE self-contained TEAM_BRIEF.md.

    Reads the already-rendered bugs/*.md, workflow-map.md, and PRD.md (so there is one
    source of truth, not a second renderer) and concatenates them into a single shareable
    file. Screenshot refs are rewritten from ../screenshots/ to screenshots/ so they
    resolve from the session root. Returns the brief filename or None if nothing to assemble.
    """
    bugs_dir = session_dir / "bugs"
    if not bugs_dir.exists():
        return None

    def _fix_refs(md: str) -> str:
        return md.replace("../screenshots/", "screenshots/")

    parts: list[str] = []
    parts.append(f"# {cfg.product_name} — Session Bug & Wiring Brief\n\nSession: `{session_dir.name}`\n")
    parts.append(
        "This is the complete hand-off from a narrated walkthrough. Every bug and every "
        "workflow that needs connecting is below, in full, grouped by the zone it lives in. "
        "Screenshots are in the `screenshots/` folder next to this file.\n"
    )
    parts.append(
        "## Zones\n\n" + "\n".join(f"- **{z.label}** (`zone: {z.key}`)" for z in cfg.zones) + "\n"
    )
    parts.append(
        _dispatch_md(cfg) + "\n"
        "Each section below is self-contained. You can also drop this file into Claude Code "
        "and ask it to fan out one agent per zone.\n\n---\n"
    )

    total = 0
    rendered: set[Path] = set()
    for zone in cfg.zone_keys:
        zone_files = sorted(bugs_dir.glob(f"{zone}-*.md"))
        if not zone_files:
            continue
        parts.append(f"\n# {cfg.zone_label[zone]}  ({len(zone_files)} items)\n")
        for f in zone_files:
            total += 1
            rendered.add(f)
            parts.append(_fix_refs(f.read_text(encoding="utf-8")).rstrip() + "\n\n---\n")

    # Anything whose filename prefix isn't a configured zone still has to ship: a model can
    # deviate from the tool schema's enum on a long generation, and a brief that omits
    # captured work is worse than one with an unexpected heading. Group the strays by their
    # own prefix rather than discarding them.
    strays = sorted(set(bugs_dir.glob("*.md")) - rendered)
    if strays:
        by_prefix: dict[str, list[Path]] = {}
        for f in strays:
            prefix = f.name.split("-", 1)[0]
            by_prefix.setdefault(prefix, []).append(f)
        for prefix, files in sorted(by_prefix.items()):
            parts.append(f"\n# {prefix.title()}  ({len(files)} items)\n")
            for f in files:
                total += 1
                parts.append(_fix_refs(f.read_text(encoding="utf-8")).rstrip() + "\n\n---\n")

    wf = session_dir / "workflow-map.md"
    if wf.exists():
        parts.append("\n# Workflow-Connection Map\n\n" + _fix_refs(wf.read_text(encoding="utf-8")).strip() + "\n")

    prd = session_dir / "PRD.md"
    if prd.exists():
        parts.append("\n---\n\n# Appendix: PRD\n\n" + prd.read_text(encoding="utf-8").strip() + "\n")

    # Insert the total just under the title.
    parts.insert(1, f"\n**{total} items total.** Full detail on each below.\n")

    (session_dir / "TEAM_BRIEF.md").write_text("\n".join(parts), encoding="utf-8")
    return "TEAM_BRIEF.md"


def write_outputs(session_dir: Path, session_id: str, meta: dict, result: dict,
                  manifest: list[dict], cfg: ContextConfig) -> dict[str, str]:
    """Write PRD.md, workflow-map.md, bugs/*.md, INDEX.md, DIGEST.md, TEAM_BRIEF.md."""
    bugs = assign_bug_ids(result.get("bugs", []) or [], cfg)
    manifest_by_id = {m["id"]: m for m in manifest}

    written: dict[str, str] = {}

    prd = (result.get("prd_md") or "").strip() + "\n"
    (session_dir / "PRD.md").write_text(prd, encoding="utf-8")
    written["prd"] = "PRD.md"

    (session_dir / "workflow-map.md").write_text(
        (result.get("workflow_map_md") or "").strip() + "\n", encoding="utf-8"
    )
    written["workflow_map"] = "workflow-map.md"

    bugs_dir = session_dir / "bugs"
    bugs_dir.mkdir(parents=True, exist_ok=True)
    for bug in bugs:
        (bugs_dir / bug["filename"]).write_text(render_bug_md(bug, manifest_by_id, cfg), encoding="utf-8")
    written["bug_count"] = str(len(bugs))

    (session_dir / "INDEX.md").write_text(render_index(session_id, bugs, cfg), encoding="utf-8")
    written["index"] = "INDEX.md"

    (session_dir / "DIGEST.md").write_text(
        render_digest(session_id, meta, bugs, result, manifest_by_id, cfg), encoding="utf-8"
    )
    written["digest"] = "DIGEST.md"

    brief = assemble_team_brief(session_dir, cfg)
    if brief:
        written["team_brief"] = brief
    return written


# --- orchestration ----------------------------------------------------------

STATE_FILE = "doc-generator-state.json"


def update_state(homebase: Path, stage: str, session_id: str | None = None, **extra: Any) -> None:
    """Own state file for this processor, at <homebase>/doc-generator-state.json.

    Kept separate from intelligence/'s shared agents/pipeline-state.json contract (that
    spine tracks the deal-recording pipeline; wiring the two together is future work, not
    part of this seam). Deliberately NOT under <homebase>/agents/: that path is this repo's
    own build-harness directory when HOMEBASE_ROOT defaults to the repo root (see
    .gitignore), and colliding a shipped runtime file with harness tooling is exactly the
    kind of odd path that trips up a fresh clone.
    """
    path = homebase / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    current: dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8")) or {}
            if not isinstance(current, dict):
                current = {}
        except (OSError, json.JSONDecodeError):
            current = {}
    current["stage"] = stage
    if session_id is not None:
        current["session_id"] = session_id
    current["updated_at"] = _now_iso()
    current["error"] = None if stage != "error" else extra.get("error")
    for k, v in extra.items():
        current[k] = v
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def resolve_recording(
    session_dir: Path, recorder: RecorderAdapter, start_epoch: float, *, copy_fn=shutil.copy2,
) -> Path | None:
    """Ensure raw.mp4 exists in session_dir, via the configured RecorderAdapter.

    Asks the recorder to resolve its master file for this session, then adopts it into
    place: a stray file already inside session_dir (e.g. FileRecorder finding "Area.mp4")
    is renamed; a master living elsewhere (outside session_dir, e.g. a recorder-managed
    bundle) is copied in via a temp-then-rename so a half-copied file is never mistaken for
    a complete recording.
    Returns raw.mp4, the master left in place if adoption failed, or None if the recorder
    found nothing yet.
    """
    raw = session_dir / "raw.mp4"
    if raw.exists():
        return raw
    master = recorder.resolve_master(start_epoch, session_dir)
    if master is None:
        return None
    if master == raw:
        return raw
    try:
        if master.parent == session_dir:
            master.rename(raw)
            log.info("adopted_recording renamed=%s session=%s", master.name, session_dir.name)
        else:
            tmp = session_dir / "raw.mp4.partial"
            copy_fn(str(master), str(tmp))
            tmp.rename(raw)
            log.info("adopted_recording copied_from=%s session=%s", master, session_dir.name)
        return raw
    except OSError as e:
        log.warning("recording_adopt_failed session=%s err=%s", session_dir.name, e)
        return master


def _alert_stale_session(session_dir: Path) -> None:
    """Fail loud once: a session that never got a recording must surface, not sit silent."""
    if (session_dir / ".stale-alerted").exists():
        return
    msg = "session has no recording and the configured recorder found no match -- pipeline cannot run"
    try:
        (session_dir / ".capture-alert").write_text(msg + "\n", encoding="utf-8")
        (session_dir / ".stale-alerted").touch()
    except OSError:
        pass
    log.error("stale_session_no_recording session=%s", session_dir.name)
    os.system("osascript -e 'display notification \"Session has no recording. Check your "
              "recorder.\" with title \"homebase\"' 2>/dev/null")


def session_is_live(session_dir: Path) -> bool:
    """True while the session is still recording, so the watcher must leave it alone.

    session.json gets start_epoch at Start and stop_epoch at Stop, so the absence of
    stop_epoch is the authoritative "still recording" signal. It is per-session and it
    survives a daemon restart, unlike an in-memory marker.

    A session with no session.json is NOT treated as live: hand-assembled and reprocessed
    sessions have no marker and must stay processable.

    A session that never got a stop_epoch because something crashed would otherwise read as
    live forever. Past MAX_LIVE_SESSION_S it is treated as abandoned so the normal
    stale-alert path resumes.
    """
    meta = _read_meta(session_dir)
    if not meta:
        return False
    start = meta.get("start_epoch")
    if not start or meta.get("stop_epoch"):
        return False
    return (time.time() - float(start)) < MAX_LIVE_SESSION_S


def find_pending(homebase: Path, recorder: RecorderAdapter | None = None) -> list[Path]:
    base = homebase / SESSIONS_DIR
    if not base.exists():
        return []
    active_recorder = recorder or get_recorder()
    pending: list[Path] = []
    now = time.time()
    for session_dir in sorted(base.iterdir()):
        if not session_dir.is_dir():
            continue
        if (session_dir / ".processed").exists():
            continue
        if session_is_live(session_dir):
            continue
        meta = _read_meta(session_dir)
        start_epoch = meta.get("start_epoch") or 0.0
        mp4 = resolve_recording(session_dir, active_recorder, float(start_epoch))
        if mp4 is None:
            age = now - float(start_epoch) if start_epoch else 0.0
            if age > STALE_RECORDING_ALERT_S:
                _alert_stale_session(session_dir)
            continue
        try:
            if now - mp4.stat().st_mtime < RECORDING_SETTLE_S:
                continue
        except OSError:
            continue
        pending.append(session_dir)
    return pending


def ensure_transcript(session_dir: Path, *, python_bin: str | None = None) -> Any | None:
    """Existing transcript.json, or run record_session.py's deferred provider capture."""
    transcript_path = session_dir / "transcript.json"
    if transcript_path.exists():
        try:
            return json.loads(transcript_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return transcript_path.read_text(encoding="utf-8")

    record_script = _HERE / "record_session.py"
    if (session_dir / "session.json").exists() and record_script.exists():
        timeout = int(os.environ.get("TRANSCRIPT_CAPTURE_TIMEOUT_S", "300"))
        try:
            subprocess.run(
                [python_bin or sys.executable, str(record_script), "capture",
                 "--session", session_dir.name, "--homebase", str(DEFAULT_HOMEBASE),
                 "--sessions-dir", SESSIONS_DIR],
                capture_output=True, timeout=timeout, check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            log.warning("transcript_capture_failed session=%s err=%s", session_dir.name, e)
        if transcript_path.exists():
            try:
                return json.loads(transcript_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


# 16 kHz mono 16-bit PCM = 32000 bytes/sec. Below ~0.5s of audio there is nothing worth
# transcribing (just the WAV header + a blip).
MIN_BACKUP_AUDIO_BYTES = 16000
# Apple-Silicon MLX whisper model used for the provider-independent fallback transcription.
BACKUP_WHISPER_MODEL = os.environ.get("BACKUP_WHISPER_MODEL", "mlx-community/whisper-small.en-mlx")


def _mlx_transcribe(audio: Path) -> str:
    """Transcribe with mlx-whisper. Imported lazily so this module does not hard-depend on
    it (only the fallback path needs it). Provider-independent by design: this must work
    when the configured TranscriptProvider is the thing that died."""
    import mlx_whisper  # type: ignore

    result = mlx_whisper.transcribe(str(audio), path_or_hf_repo=BACKUP_WHISPER_MODEL)
    return (result or {}).get("text", "") or ""


def transcribe_audio_backup(
    session_dir: Path,
    *,
    transcriber: Callable[[Path], str] | None = None,
) -> str | None:
    """Recover narration from the independent mic backup track (capture_audio_backup.py)
    when the configured TranscriptProvider captured none.

    Returns the transcribed text, or None if there is no usable backup or transcription
    fails. Writes a .narration-source marker so the provenance (backup, not the provider)
    is visible. transcriber is injectable for tests."""
    audio = session_dir / capture_audio_backup.BACKUP_NAME
    try:
        if not audio.exists() or audio.stat().st_size < MIN_BACKUP_AUDIO_BYTES:
            return None
    except OSError:
        return None

    fn = transcriber or _mlx_transcribe
    try:
        text = (fn(audio) or "").strip()
    except Exception as e:  # transcription is best-effort; never crash the run
        log.warning("backup_transcribe_failed session=%s err=%s", session_dir.name, e)
        return None

    if not text:
        return None
    try:
        (session_dir / ".narration-source").write_text(
            "backup-audio (mlx-whisper fallback; the dictation provider captured nothing)\n",
            encoding="utf-8")
    except OSError:
        pass
    return text


def _bump_attempts(session_dir: Path) -> int:
    marker = session_dir / ".attempts"
    try:
        current = int(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        current = 0
    current += 1
    try:
        marker.write_text(str(current), encoding="utf-8")
    except OSError:
        pass
    return current


def _read_meta(session_dir: Path) -> dict:
    try:
        meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        return meta if isinstance(meta, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def process_session(
    homebase: Path,
    session_dir: Path,
    *,
    cfg: ContextConfig | None = None,
    recorder: RecorderAdapter | None = None,
    claude_fn: Callable[[str, list[dict], dict], dict] | None = None,
    extract_fn: Callable[[Path, Path], list[dict]] | None = None,
) -> str:
    """Run one session end to end. Returns a stage string ('ok' / 'error').

    Marks .processed only on success or a permanent failure, so a transient hiccup retries
    on the next poll but a doomed run does not loop forever. cfg, recorder, claude_fn, and
    extract_fn are all injectable for tests."""
    session_id = session_dir.name

    # Concurrency guard: a poll daemon and a manual --session run can both call this.
    # Without a lock, removing .processed to force a regen while the daemon is live would
    # let BOTH process the session and write two overlapping bug sets. An atomic O_EXCL
    # lock lets exactly one run proceed; a stale lock from a hard crash (>LOCK_STALE_S old)
    # is stolen so a session can never wedge permanently.
    lock = session_dir / ".lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        try:
            stale = (time.time() - lock.stat().st_mtime) > LOCK_STALE_S
        except OSError:
            stale = False
        if not stale:
            log.info("session_locked skip session=%s", session_id)
            return "locked"
        log.warning("stealing_stale_lock session=%s", session_id)
        try:
            lock.unlink()
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except OSError:
            return "locked"
    try:
        return _process_session_locked(
            homebase, session_dir, cfg=cfg, recorder=recorder,
            claude_fn=claude_fn, extract_fn=extract_fn)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _process_session_locked(
    homebase: Path,
    session_dir: Path,
    *,
    cfg: ContextConfig | None = None,
    recorder: RecorderAdapter | None = None,
    claude_fn: Callable[[str, list[dict], dict], dict] | None = None,
    extract_fn: Callable[[Path, Path], list[dict]] | None = None,
) -> str:
    session_id = session_dir.name
    log.info("process_start session=%s", session_id)
    update_state(homebase, "transcribing", session_id, message="transcript + screenshots")

    active_cfg = cfg or load_context_config(
        _resolve_repo_path(DEFAULT_CONTEXT_CONFIG, homebase), homebase=homebase)
    active_recorder = recorder or get_recorder()

    # Adopt whatever the configured recorder resolves (e.g. a stray export) so no manual
    # rename is needed.
    meta = _read_meta(session_dir)
    resolve_recording(session_dir, active_recorder, float(meta.get("start_epoch") or 0.0))

    # GUARD: Verify both inputs exist before attempting processing. If both are missing,
    # this is a fatal capture failure. Mark it processed so it does not loop forever, but
    # loud-fail so the operator sees it.
    mp4 = session_dir / "raw.mp4"
    transcript_path = session_dir / "transcript.json"
    if not mp4.exists() and not transcript_path.exists():
        msg = "FATAL: both transcript and MP4 missing -- narration and/or recording failed to capture"
        log.error("capture_inputs_missing session=%s", session_id)
        update_state(homebase, "error", session_id, error=msg)
        (session_dir / ".processed").touch()
        return "error"

    transcript = ensure_transcript(session_dir)
    narration = transcript_text(transcript)
    if not narration:
        # The dictation provider produced nothing (e.g. it silently froze). Fall back to
        # the independent mic backup track recorded alongside the session. This is the
        # whole point of the backup: a dead provider no longer means a lost session.
        recovered = transcribe_audio_backup(session_dir)
        if recovered:
            narration = recovered
            log.warning("narration_recovered_from_backup session=%s chars=%d",
                        session_id, len(narration))
    if not narration:
        attempts = _bump_attempts(session_dir)
        if attempts >= MAX_TRANSCRIPT_ATTEMPTS:
            update_state(homebase, "error", session_id,
                         error=f"no narration after {attempts} attempts; gave up")
            (session_dir / ".processed").touch()
            return "error"
        update_state(homebase, "error", session_id,
                     error=f"no narration yet (attempt {attempts}/{MAX_TRANSCRIPT_ATTEMPTS}); will retry")
        return "error"

    update_state(homebase, "extracting", session_id, message="screenshots")
    shots_dir = session_dir / "screenshots"
    extract = extract_fn or (lambda mp4, out: extract_screenshots(mp4, out))
    manifest = extract(session_dir / "raw.mp4", shots_dir)

    update_state(homebase, "generating", session_id, message="PRD + bugs + workflow map")
    system = active_cfg.build_system_prompt()
    capture_tool = active_cfg.capture_tool()
    vision = sample_for_vision(manifest)
    # Optional: a coverage checklist from a prior audit (drop it at <session>/coverage_checklist.md)
    # so a regeneration cannot silently re-drop items. Absent on normal runs.
    checklist_path = session_dir / "coverage_checklist.md"
    coverage_md = checklist_path.read_text(encoding="utf-8") if checklist_path.exists() else ""
    content = build_user_content(narration, vision, shots_dir, coverage_md)

    fn = claude_fn or call_claude
    try:
        result = fn(system, content, capture_tool)
    except Exception as e:  # the network/SDK call; keep the daemon alive and retry next poll
        update_state(homebase, "error", session_id, error=f"Claude call failed: {e}")
        log.exception("claude_call_failed session=%s", session_id)
        return "error"

    meta = _read_meta(session_dir)
    meta["recording_path"] = str(session_dir / "raw.mp4")
    written = write_outputs(session_dir, session_id, meta, result, manifest, active_cfg)

    (session_dir / ".processed").touch()
    update_state(homebase, "complete", session_id, message="digest ready",
                 bugs=written.get("bug_count"), digest=str(session_dir / "DIGEST.md"))
    log.info("process_done session=%s bugs=%s", session_id, written.get("bug_count"))
    return "ok"


def main_loop(homebase: Path) -> None:
    log.info("watcher_start homebase=%s", homebase)
    while True:
        try:
            for session_dir in find_pending(homebase):
                process_session(homebase, session_dir)
        except Exception:
            log.exception("loop_error")
        time.sleep(POLL_INTERVAL_S)


def _setup_logging() -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="homebase session capture processor")
    parser.add_argument("--homebase", type=Path, default=DEFAULT_HOMEBASE)
    parser.add_argument("--once", action="store_true", help="process all pending sessions once and exit")
    parser.add_argument("--session", default=None, help="process one session id and exit")
    parser.add_argument("--watch", action="store_true", help="run as a polling daemon")
    args = parser.parse_args()
    _setup_logging()

    if args.session:
        session_dir = args.homebase / SESSIONS_DIR / args.session
        if not session_dir.is_dir():
            print(f"no such session: {session_dir}", file=sys.stderr)
            sys.exit(1)
        process_session(args.homebase, session_dir)
        return
    if args.once:
        for session_dir in find_pending(args.homebase):
            process_session(args.homebase, session_dir)
        return
    if args.watch:
        main_loop(args.homebase)
        return
    parser.print_help()


if __name__ == "__main__":
    cli()
