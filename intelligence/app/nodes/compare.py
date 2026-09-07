"""Compare node. Deterministic. No LLM.

Decides whether the extracted workflow is a new pattern or extends an existing one in
workflows/library/. The target library path is always the dynamic path computed from the
classification. Whether it is "new" vs "extends" depends on overlap with existing entries.
"""

from __future__ import annotations

from pathlib import Path

from .. import pipeline_state
from ..io import library_path, slugify
from ..models import ComparisonResult
from ..settings import get_settings
from ..state import PipelineState


def _existing_patterns(library_root: Path) -> list[Path]:
    """Every subfolder of workflows/library/ that contains a pattern.md."""
    if not library_root.exists():
        return []
    return sorted(p.parent for p in library_root.rglob("pattern.md"))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _tools_in_pattern(pattern_md: Path) -> set[str]:
    """Cheap extractor. Reads bullet-listed tools from a pattern.md if present."""
    try:
        text = pattern_md.read_text(encoding="utf-8").lower()
    except OSError:
        return set()
    out: set[str] = set()
    in_tools = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## tools") or line.startswith("## tools commonly used"):
            in_tools = True
            continue
        if in_tools:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                out.add(slugify(line[2:].split(":", 1)[0]))
    return out


def compare_node(state: PipelineState) -> dict:
    pipeline_state.update("comparing", state.get("session_id"))
    settings = get_settings()
    classification = state["classification"]
    extraction = state["extraction"]

    target = library_path(
        settings.homebase_root,
        classification.deal_type,
        classification.sub_type,
        classification.operator_intent_slug,
    )
    relative_target = target.relative_to(settings.homebase_root).as_posix()

    library_root = settings.homebase_root / "workflows" / "library"
    observed_tools = {slugify(t) for t in extraction.tools_observed}

    # Exact path hit
    if target.exists() and (target / "pattern.md").exists():
        return {
            "comparison": ComparisonResult(
                match="extends",
                target_library_path=relative_target,
                extends=relative_target,
                rationale="Exact library path already exists.",
            )
        }

    # Fuzzy tool overlap within same deal_type/sub_type bucket
    bucket = (
        settings.homebase_root
        / "workflows"
        / "library"
        / slugify(classification.deal_type)
        / slugify(classification.sub_type)
    )
    if bucket.exists():
        for candidate in _existing_patterns(bucket):
            candidate_tools = _tools_in_pattern(candidate / "pattern.md")
            similarity = _jaccard(observed_tools, candidate_tools)
            if similarity >= 0.6:
                rel = candidate.relative_to(settings.homebase_root).as_posix()
                return {
                    "comparison": ComparisonResult(
                        match="extends",
                        target_library_path=rel,
                        extends=rel,
                        rationale=(
                            f"Tool overlap with existing pattern (Jaccard {similarity:.2f})."
                        ),
                    )
                }

    # Otherwise new
    _ = _existing_patterns(library_root)  # cheap touch for side-effect-free behavior
    return {
        "comparison": ComparisonResult(
            match="new",
            target_library_path=relative_target,
            extends=None,
            rationale="No existing pattern matched by path or tool overlap.",
        )
    }
