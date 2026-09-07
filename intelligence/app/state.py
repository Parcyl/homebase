"""LangGraph pipeline state. TypedDict so nodes can return partial updates."""

from __future__ import annotations

from typing import Any, TypedDict

from .models import (
    Classification,
    ComparisonResult,
    Extraction,
    GeneratedArtifacts,
    OutputPaths,
)


class PipelineState(TypedDict, total=False):
    # Inputs
    session_id: str
    recording_path: str
    transcript: Any
    keyframe_paths: list[str]
    context_cue: str | None
    target_repo: str | None

    # Node outputs
    classification: Classification
    extraction: Extraction
    comparison: ComparisonResult
    generated: GeneratedArtifacts
    output_paths: OutputPaths

    # Diagnostics
    low_confidence: bool
