"""File outputs node. Atomic writes for all four artifacts. Updates memory/patterns.md."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .. import pipeline_state
from ..io import atomic_append, atomic_write, session_paths
from ..models import OutputPaths
from ..settings import get_settings
from ..state import PipelineState


def _pattern_note_entry(state: PipelineState) -> str:
    classification = state["classification"]
    comparison = state["comparison"]
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    session_id = state["session_id"]

    if comparison.match == "new":
        return (
            f"\n## {classification.deal_type}/{classification.sub_type}/"
            f"{classification.operator_intent_slug}\n"
            f"- First observed: {session_id} ({today})\n"
            f"- Last observed: {session_id} ({today})\n"
            f"- Sessions: 1\n"
            f"- Library path: `{comparison.target_library_path}/`\n"
            f"- Summary: {classification.rationale}\n"
            f"- Confidence: {classification.confidence:.2f}\n"
        )
    # extends
    return (
        f"\n<!-- session {session_id} extends `{comparison.extends}` "
        f"({today}) -->\n"
    )


def file_outputs_node(state: PipelineState) -> dict:
    pipeline_state.update("filing", state.get("session_id"))
    settings = get_settings()
    generated = state["generated"]
    comparison = state["comparison"]

    paths = session_paths(settings.homebase_root, state["session_id"])
    library_dir = settings.homebase_root / comparison.target_library_path
    pattern_file = library_dir / "pattern.md"
    patterns_memory = settings.homebase_root / "memory" / "patterns.md"

    # Write artifacts atomically
    atomic_write(paths["workflow_map"], generated.workflow_map_md)
    atomic_write(paths["prd"], generated.prd_md)
    atomic_write(paths["handoff"], generated.handoff_md)
    atomic_write(pattern_file, generated.pattern_md)

    # Append pattern note to memory
    atomic_append(patterns_memory, _pattern_note_entry(state))

    def rel(p: Path) -> str:
        return p.relative_to(settings.homebase_root).as_posix()

    output_paths = OutputPaths(
        workflow_map=rel(paths["workflow_map"]),
        prd=rel(paths["prd"]),
        handoff=rel(paths["handoff"]),
        pattern=rel(pattern_file),
    )

    pipeline_state.update(
        "complete",
        state.get("session_id"),
        last_prd=output_paths.prd,
        last_handoff=output_paths.handoff,
        message="pipeline complete",
    )

    return {"output_paths": output_paths}
