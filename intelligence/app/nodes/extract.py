"""Extract node. Pulls steps, tools, decisions, data sources, heuristics, open loops.

Vision-aware: keyframes are passed as base64 image blocks alongside the transcript
text so Claude can see what was on the operator's screen. The screen often contains
context the operator never verbalized (CoStar comp page, T12 spreadsheet, plat
viewer). Capped at MAX_KEYFRAMES evenly-spaced frames to control token cost.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage

from .. import pipeline_state
from ..llm import get_llm
from ..models import Extraction
from ..state import PipelineState

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extract.md"
MAX_KEYFRAMES = 10

log = logging.getLogger("homebase.extract")


def _transcript_text(transcript: object) -> str:
    if isinstance(transcript, str):
        return transcript
    return json.dumps(transcript, indent=2, default=str)


def select_keyframes(paths: list[str], max_count: int = MAX_KEYFRAMES) -> list[str]:
    """Return at most max_count keyframes, evenly spaced across the input.

    First and last frames are always included so the visual context spans
    the full session. When len(paths) <= max_count the input is returned
    unchanged.
    """
    if not paths:
        return []
    if len(paths) <= max_count:
        return list(paths)
    last = len(paths) - 1
    indices = [round(i * last / (max_count - 1)) for i in range(max_count)]
    return [paths[i] for i in indices]


def _read_image_b64(path: str) -> str | None:
    """Return base64-encoded file content, or None if the file is unreadable."""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None


def _build_content(prompt_text: str, keyframe_paths: list[str]) -> list[dict]:
    """Compose the multimodal HumanMessage content: prompt text plus image blocks."""
    blocks: list[dict] = [{"type": "text", "text": prompt_text}]
    for kf in keyframe_paths:
        encoded = _read_image_b64(kf)
        if encoded is None:
            log.warning("keyframe_unreadable path=%s", kf)
            continue
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            }
        )
    return blocks


def extract_node(state: PipelineState) -> dict:
    pipeline_state.update("extracting", state.get("session_id"))

    prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    raw_keyframes: list[str] = state.get("keyframe_paths") or []
    selected = select_keyframes(raw_keyframes, MAX_KEYFRAMES)

    keyframe_note = (
        f"{len(selected)} keyframes attached as images "
        f"(evenly sampled from {len(raw_keyframes)} total)"
        if selected
        else "(none)"
    )
    rendered_prompt = prompt_template.format(
        transcript=_transcript_text(state["transcript"]),
        keyframe_paths=keyframe_note,
    )

    content = _build_content(rendered_prompt, selected)
    message = HumanMessage(content=content)

    llm = get_llm(temperature=0.3, max_tokens=8192).with_structured_output(Extraction)
    result: Extraction = llm.invoke([message])  # type: ignore[assignment]

    return {"extraction": result}
