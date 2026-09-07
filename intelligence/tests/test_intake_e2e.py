"""End-to-end test through FastAPI TestClient with every LLM call mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.models import (
    Classification,
    Decision,
    Extraction,
    GeneratedArtifacts,
    Step,
)


@pytest.fixture
def client(isolated_homebase: Path):  # noqa: ARG001
    # Import after isolated_homebase has set env so settings pick up the temp root
    from app.main import app

    return TestClient(app)


def _stub_llm(*models):
    """Return an object whose .with_structured_output(M).invoke(x) returns the matching stub."""
    queue = list(models)

    class Stub:
        def __init__(self, value):
            self.value = value

        def invoke(self, _rendered):
            return self.value

    class Factory:
        def with_structured_output(self, _schema):
            return Stub(queue.pop(0))

    return Factory()


def test_intake_happy_path(client: TestClient, isolated_homebase: Path):
    classification = Classification(
        deal_type="self storage",
        sub_type="acquisition",
        operator_intent_slug="round-rock-pad-count",
        confidence=0.92,
        rationale="Operator stated self storage acquisition workflow.",
    )
    extraction = Extraction(
        operator_intent="Evaluate pad count feasibility on Round Rock parcel.",
        steps=[Step(order=1, action="Open Snowflake", transcript_span="00:05-00:20")],
        tools_observed=["Snowflake", "Google Maps"],
        decisions=[
            Decision(
                summary="Compared pad count assumptions",
                heuristic="Need at least 50,000 sq ft per pad",
                agent_candidate="Basis",
            )
        ],
        data_sources=["ATTOM"],
        heuristics=["At least 50k sq ft per pad"],
        open_loops=["Verify zoning"],
    )
    generated = GeneratedArtifacts(
        workflow_map_md="# Workflow Map\n",
        prd_md="# PRD\n",
        handoff_md="# Handoff\n",
        pattern_md="# Pattern\n",
    )

    factory = _stub_llm(classification, extraction, generated)

    with patch("app.nodes.classify.get_llm", return_value=factory), \
         patch("app.nodes.extract.get_llm", return_value=factory), \
         patch("app.nodes.generate.get_llm", return_value=factory):
        resp = client.post(
            "/intake",
            json={
                "session_id": "2026-05-25T10-00-00-test",
                "recording_path": str(isolated_homebase / "missing.mp4"),
                "transcript": "operator narration here",
                "keyframe_paths": [],
                "context_cue": "self storage Round Rock",
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["classification"]["deal_type"] == "self storage"
    assert body["library_path"] == "workflows/library/self-storage/acquisition/round-rock-pad-count"
    assert body["pattern_match"]["match"] == "new"
    assert body["low_confidence"] is False

    # Artifacts written
    assert (isolated_homebase / body["outputs"]["prd"]).exists()
    assert (isolated_homebase / body["outputs"]["handoff"]).exists()
    assert (isolated_homebase / body["outputs"]["workflow_map"]).exists()
    assert (isolated_homebase / body["outputs"]["pattern"]).exists()


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_invalid_session_id_rejected(client: TestClient, isolated_homebase: Path):
    resp = client.post(
        "/intake",
        json={
            "session_id": "not-a-valid-id",
            "recording_path": str(isolated_homebase / "x.mp4"),
            "transcript": "x",
        },
    )
    assert resp.status_code == 422
