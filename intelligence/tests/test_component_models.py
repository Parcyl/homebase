"""Tests for the buildable-component schema (PRD rework Story 1).

These models re-aim extraction from a narrative workflow toward a buildable
component spec matching notes/bmad/prd-rework/golden-handoff.md. The rework is
additive: every existing field on Extraction stays default-constructible so the
33 prior tests keep passing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import (
    AcceptanceCriterion,
    Component,
    ComponentCategory,
    DataContract,
    ExistenceClaim,
    Extraction,
    Grounding,
    IntegrationStatus,
    OperatorJudgment,
)

# ── enums ────────────────────────────────────────────────────────────────────


def test_component_category_values():
    assert ComponentCategory.UI_UX.value == "ui_ux"
    assert ComponentCategory.DATA_INTEGRATION.value == "data_integration"
    assert ComponentCategory.CODIFIABLE_LOGIC.value == "codifiable_logic"
    assert ComponentCategory.AI_INTELLIGENCE.value == "ai_intelligence"
    assert ComponentCategory.OPEN_QUESTION.value == "open_question"


def test_integration_status_defaults_to_investigate_when_unspecified():
    # The HF1 guard: a data contract with no explicit status must NOT claim it exists.
    dc = DataContract(source="ATTOM property API", fields=["owner_name", "deed_date"])
    assert dc.integration_status == IntegrationStatus.TO_INVESTIGATE


def test_integration_status_rejects_garbage():
    with pytest.raises(ValidationError):
        DataContract(source="x", integration_status="totally-real-promise")  # type: ignore[arg-type]


def test_component_category_rejects_garbage():
    with pytest.raises(ValidationError):
        Component(name="C1", category="vibes", does="x", encoded_logic="x", logic_rationale="x")  # type: ignore[arg-type]


# ── component ─────────────────────────────────────────────────────────────────


def test_component_minimal_construct_and_scope_default():
    c = Component(
        name="Owner / Buy-Box Filter",
        category=ComponentCategory.CODIFIABLE_LOGIC,
        does="flag motivated unlevered sellers by ownership profile",
        encoded_logic="flag tenure_years >= 10 and owner_type in (individual, single_llc)",
        logic_rationale="syndicators exit in 4-5y so a 10y+ hold signals a motivated mom-and-pop seller",
    )
    assert c.scope == "v1"
    assert c.data_contract is None
    assert c.acceptance_criteria == []
    assert c.example_input == ""
    assert c.example_output == ""


def test_component_full_construct():
    c = Component(
        name="Map Measurement Tool",
        category=ComponentCategory.UI_UX,
        does="return building sqft from footprint polygons",
        encoded_logic="sqft = projected polygon area; target building_sqft >= 25000",
        logic_rationale="geometry math on existing GIS footprints, not computer vision",
        data_contract=DataContract(
            source="Microsoft Building Footprints",
            fields=["geometry", "parcel_id"],
            access_method="open data tiles",
            auth="none",
            integration_status=IntegrationStatus.TO_INVESTIGATE,
        ),
        example_input='{"parcel_id": "HUNT-00123"}',
        example_output='{"total_sqft": 36000, "source": "ms_footprints"}',
        acceptance_criteria=[
            AcceptanceCriterion(
                behavior="footprint area within tolerance of ground truth",
                validation_method="5 parcels with county assessor sqft",
                threshold="within 5%",
            )
        ],
        scope="v1",
    )
    assert c.data_contract.integration_status == IntegrationStatus.TO_INVESTIGATE
    assert c.acceptance_criteria[0].threshold == "within 5%"


# ── operator judgment (HF2 guard) ─────────────────────────────────────────────


def test_operator_judgment_requires_v1_fallback_and_phase2():
    j = OperatorJudgment(
        name="climate-controlled detection",
        description="operator infers climate control from AC condensers and no rear doors",
        why_not_trivial="genuine visual expertise; a CV classifier is not trivial v1 work",
        v1_fallback="operator tags climate vs non-climate per building (one click)",
        phase2_approach="vision model proposes tags for operator confirmation",
    )
    assert j.v1_fallback
    assert j.phase2_approach


# ── grounding (HF1 guard) ─────────────────────────────────────────────────────


def test_grounding_defaults_to_no_repo_and_empty_claims():
    g = Grounding()
    assert g.target_repo is None
    assert g.existence_claims == []


def test_existence_claim_defaults_to_investigate():
    e = ExistenceClaim(fact="ATTOM integration", how_to_verify="grep the target repo for ATTOM client")
    assert e.status == IntegrationStatus.TO_INVESTIGATE


# ── Extraction backward-compat + new fields ───────────────────────────────────


def test_extraction_still_constructs_from_operator_intent_only():
    # The prior tests rely on this exact shape; it must not regress.
    ex = Extraction(operator_intent="x")
    assert ex.components == []
    assert ex.operator_judgments == []
    assert ex.grounding.target_repo is None


def test_extraction_carries_components_and_judgments():
    ex = Extraction(
        operator_intent="underwrite a self-storage acquisition",
        components=[
            Component(
                name="C1",
                category=ComponentCategory.CODIFIABLE_LOGIC,
                does="x",
                encoded_logic="x",
                logic_rationale="x",
            )
        ],
        operator_judgments=[
            OperatorJudgment(
                name="climate detection",
                description="x",
                why_not_trivial="x",
                v1_fallback="operator tag",
                phase2_approach="vision model",
            )
        ],
        grounding=Grounding(target_repo="example-app"),
    )
    assert len(ex.components) == 1
    assert ex.grounding.target_repo == "example-app"
