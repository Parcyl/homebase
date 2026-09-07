"""Pydantic schemas. Same shapes flow through the graph state and the HTTP boundary."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SESSION_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}[a-z0-9\-]*$")


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    recording_path: str
    transcript: dict[str, Any] | list[Any] | str
    keyframe_paths: list[str] = Field(default_factory=list)
    context_cue: str | None = None
    target_repo: str | None = Field(
        default=None,
        description="Optional path/name of the repo this workflow will build into. "
        "When set, grounding reads it; when absent, all existence claims stay to_investigate.",
    )

    @field_validator("session_id")
    @classmethod
    def _valid_session_id(cls, v: str) -> str:
        if not SESSION_ID_RE.match(v):
            raise ValueError(
                "session_id must match YYYY-MM-DDTHH-MM-SS optionally followed by -slug"
            )
        return v

    @field_validator("transcript")
    @classmethod
    def _non_empty_transcript(cls, v: Any) -> Any:
        if not v:
            raise ValueError("transcript is empty")
        return v


class Classification(BaseModel):
    deal_type: str = Field(..., description="Asset class (operator language)")
    sub_type: str = Field(..., description="Sub-segment within the asset class")
    operator_intent_slug: str = Field(
        ..., description="Short kebab-case slug describing what the operator was doing"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str


class Step(BaseModel):
    order: int
    action: str
    transcript_span: str = Field(default="", description="e.g. '00:12-00:34'")
    keyframe: str | None = None


class Decision(BaseModel):
    summary: str
    heuristic: str
    agent_candidate: str | None = None


class ComponentCategory(str, Enum):
    """What kind of thing a builder is being asked to build."""

    UI_UX = "ui_ux"
    DATA_INTEGRATION = "data_integration"
    CODIFIABLE_LOGIC = "codifiable_logic"
    AI_INTELLIGENCE = "ai_intelligence"
    OPEN_QUESTION = "open_question"


class IntegrationStatus(str, Enum):
    """Whether a data source / integration already exists. Defaults to
    TO_INVESTIGATE so the pipeline never asserts code it has not verified (HF1)."""

    INTEGRATED = "integrated"
    NEW = "new"
    TO_INVESTIGATE = "to_investigate"


class DataContract(BaseModel):
    """A concrete sketch of one data source a component depends on."""

    source: str = Field(..., description="System / API / dataset name")
    fields: list[str] = Field(default_factory=list, description="Key fields used")
    access_method: str = Field(default="", description="REST API, GIS layer, query, file, etc.")
    auth: str = Field(default="", description="API key, OAuth, none, to investigate")
    integration_status: IntegrationStatus = IntegrationStatus.TO_INVESTIGATE
    notes: str = Field(default="")


class AcceptanceCriterion(BaseModel):
    """A testable criterion: behavior + how to validate + the success threshold."""

    behavior: str
    validation_method: str = Field(default="", description="fixture / dataset / procedure")
    threshold: str = Field(default="", description="the pass bar, e.g. 'within 5%'")


class Component(BaseModel):
    """One buildable unit of the workflow. The unit of the golden handoff."""

    name: str
    category: ComponentCategory
    does: str = Field(..., description="One sentence: what this component does for the user")
    encoded_logic: str = Field(..., description="The operator rule turned into an encodable spec")
    logic_rationale: str = Field(..., description="WHY the rule holds, in operator reasoning")
    data_contract: DataContract | None = None
    example_input: str = Field(default="", description="Sample input as JSON text")
    example_output: str = Field(default="", description="Sample output as JSON text")
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    scope: str = Field(default="v1", description="v1 | Phase 2 | etc.")


class OperatorJudgment(BaseModel):
    """Visual or experiential judgment that must NOT be specced as trivial MVP
    automation (HF2). Each carries a v1 operator-assisted fallback and a later
    automation approach."""

    name: str
    description: str = Field(..., description="The judgment the operator made")
    why_not_trivial: str = Field(..., description="Why automating it is real work, not MVP")
    v1_fallback: str = Field(..., description="The operator-assisted v1 behavior")
    phase2_approach: str = Field(..., description="How automation arrives later")


class ExistenceClaim(BaseModel):
    """A claim about what already exists in a target codebase. Defaults to
    TO_INVESTIGATE; only a real repo read promotes it to INTEGRATED/NEW."""

    fact: str
    status: IntegrationStatus = IntegrationStatus.TO_INVESTIGATE
    how_to_verify: str = Field(default="", description="How to confirm this against the repo")


class Grounding(BaseModel):
    """Grounding of 'what exists'. With no named target repo, every existence
    claim stays TO_INVESTIGATE so nothing is fabricated (HF1 kill switch)."""

    target_repo: str | None = None
    existence_claims: list[ExistenceClaim] = Field(default_factory=list)


class Extraction(BaseModel):
    operator_intent: str
    steps: list[Step] = Field(default_factory=list)
    tools_observed: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    heuristics: list[str] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    # Buildable-component layer (PRD rework). All defaulted -> backward compatible.
    components: list[Component] = Field(default_factory=list)
    operator_judgments: list[OperatorJudgment] = Field(default_factory=list)
    grounding: Grounding = Field(default_factory=Grounding)


class ComparisonResult(BaseModel):
    match: Literal["new", "extends"]
    target_library_path: str
    extends: str | None = None
    rationale: str


class GeneratedArtifacts(BaseModel):
    workflow_map_md: str
    prd_md: str
    handoff_md: str
    pattern_md: str


class OutputPaths(BaseModel):
    workflow_map: str
    prd: str
    handoff: str
    pattern: str


class IntakeResponse(BaseModel):
    session_id: str
    classification: Classification
    library_path: str
    outputs: OutputPaths
    pattern_match: ComparisonResult
    low_confidence: bool = False


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict[str, Any] | None = None
