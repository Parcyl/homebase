"""Template-shape tests (PRD rework Story 4).

The PRD and handoff templates must carry the golden component shape: a grounded
'what exists', per-component contracts with category/logic/IO/criteria/scope, and
the operator-assisted judgment section. These pin that shape so a future edit
cannot quietly revert the templates to the narrative form that scored 9/100.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATES = Path(__file__).parent.parent.parent / "templates"


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8").lower()


def test_handoff_template_has_grounding_and_component_shape():
    t = _read("handoff-template.md")
    assert "target context (grounding" in t
    assert "to investigate" in t
    assert "components to build" in t
    assert "category:" in t
    assert "data contract" in t
    assert "acceptance criteria" in t
    assert "threshold" in t
    assert "scope:" in t


def test_handoff_template_has_operator_assisted_judgment_section():
    t = _read("handoff-template.md")
    assert "operator-assisted judgment" in t
    assert "phase 2" in t
    assert "hard error to spec this as a trivial v1 classifier" in t


def test_prd_template_is_component_centric_not_agent_centric():
    t = _read("prd-template.md")
    assert "components" in t
    assert "encoded logic" in t
    assert "rationale" in t
    assert "integration status" in t
    # the fictional agent-candidate framing must be gone
    assert "agent candidate" not in t


def test_workflow_map_template_drops_agent_framing():
    t = _read("workflow-map-template.md")
    assert "agent candidate" not in t
    assert "components identified" in t
    assert "operator-assisted judgment" in t
