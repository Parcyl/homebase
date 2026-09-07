"""Classify node. Calls the LLM with structured output to produce a Classification."""

from __future__ import annotations

import json
from pathlib import Path

from .. import pipeline_state
from ..llm import get_llm
from ..models import Classification
from ..state import PipelineState

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "classify.md"


def _transcript_text(transcript: object) -> str:
    """Best-effort serialization of any transcript shape to text the LLM can read."""
    if isinstance(transcript, str):
        return transcript
    return json.dumps(transcript, indent=2, default=str)


def classify_node(state: PipelineState) -> dict:
    pipeline_state.update("classifying", state.get("session_id"))
    prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    rendered = prompt_template.format(
        context_cue=state.get("context_cue") or "(none)",
        transcript=_transcript_text(state["transcript"]),
    )

    llm = get_llm(temperature=0.0).with_structured_output(Classification)
    result: Classification = llm.invoke(rendered)  # type: ignore[assignment]

    return {
        "classification": result,
        "low_confidence": result.confidence < 0.5,
    }
