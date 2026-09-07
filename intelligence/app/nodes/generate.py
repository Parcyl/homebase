"""Generate node. Produces the four markdown artifacts via a single LLM call."""

from __future__ import annotations

from pathlib import Path

from .. import pipeline_state
from ..llm import get_llm
from ..models import GeneratedArtifacts
from ..settings import get_settings
from ..state import PipelineState

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "generate.md"


def _read_template(name: str) -> str:
    settings = get_settings()
    path = settings.homebase_root / "templates" / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"(template {name} not found at {path})"


def generate_node(state: PipelineState) -> dict:
    pipeline_state.update("generating", state.get("session_id"))
    classification = state["classification"]
    extraction = state["extraction"]
    comparison = state["comparison"]

    prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    rendered = prompt_template.format(
        workflow_map_template=_read_template("workflow-map-template.md"),
        prd_template=_read_template("prd-template.md"),
        handoff_template=_read_template("handoff-template.md"),
        session_id=state["session_id"],
        recording_path=state["recording_path"],
        classification_json=classification.model_dump_json(indent=2),
        extraction_json=extraction.model_dump_json(indent=2),
        comparison_json=comparison.model_dump_json(indent=2),
        library_path=comparison.target_library_path,
    )

    # Four rich, component-shaped artifacts in one structured call exceed 8192
    # output tokens; too small and the later fields (handoff_md, pattern_md)
    # truncate and the call fails validation. 16384 fits the buildable shape.
    #
    # This call generates ~16k tokens and runs for minutes. It MUST stream: a
    # non-streaming request read-times-out on the client and is interrupted by the
    # Anthropic API past ~10 min (Seguin deal, 2026-06-09 post-mortem). Streaming feeds
    # the connection chunk-by-chunk; invoke() aggregates the stream and returns the
    # parsed structured result. The long timeout is a backstop for a stalled stream.
    llm = get_llm(
        temperature=0.3, max_tokens=16384, streaming=True, timeout=900
    ).with_structured_output(GeneratedArtifacts)
    result: GeneratedArtifacts = llm.invoke(rendered)  # type: ignore[assignment]

    return {"generated": result}
