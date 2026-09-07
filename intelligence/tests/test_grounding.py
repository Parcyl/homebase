"""Tests for the grounding node (PRD rework Story 3).

Grounding is the HF1 kill switch. With no target_repo the pipeline claims
nothing (every integration stays to_investigate downstream). With a named repo,
the node does a REAL read: it greps for each data source and marks it integrated
only when actually found, never by assertion.
"""

from __future__ import annotations

from pathlib import Path

from app.models import (
    Component,
    ComponentCategory,
    DataContract,
    Extraction,
    IntegrationStatus,
)
from app.nodes.grounding import _brand_tokens, _collect_sources, ground_node


def _extraction_with_sources(*sources: str) -> Extraction:
    components = [
        Component(
            name=f"C{i}",
            category=ComponentCategory.DATA_INTEGRATION,
            does="x",
            encoded_logic="x",
            logic_rationale="x",
            data_contract=DataContract(source=s),
        )
        for i, s in enumerate(sources)
    ]
    return Extraction(operator_intent="x", components=components)


# ── helpers ───────────────────────────────────────────────────────────────────


def test_brand_tokens_picks_brand_not_generic_words():
    toks = _brand_tokens("ATTOM property API")
    assert "ATTOM" in toks
    assert "property" not in toks  # generic lowercase word is not a brand token
    assert "API" not in toks  # too generic / common acronym, excluded


def test_collect_sources_dedupes_across_components_and_data_sources():
    ex = _extraction_with_sources("ATTOM property API", "ATTOM property API")
    ex = ex.model_copy(update={"data_sources": ["Perplexity API"]})
    sources = _collect_sources(ex)
    assert "ATTOM property API" in sources
    assert "Perplexity API" in sources
    assert len(sources) == 2  # the duplicate ATTOM collapses


# ── ungrounded path ─────────────────────────────────────────────────────────


def test_ground_node_ungrounded_returns_no_change():
    ex = _extraction_with_sources("ATTOM property API")
    result = ground_node({"extraction": ex})  # no target_repo
    # No grounding asserted: either no update, or grounding left empty.
    updated = result.get("extraction", ex)
    assert updated.grounding.target_repo is None
    assert updated.grounding.existence_claims == []


# ── grounded path (real read) ─────────────────────────────────────────────────


def test_ground_node_marks_found_source_integrated(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "client.py").write_text(
        "class ATTOMClient:\n    base_url = 'https://api.gateway.attomdata.com'\n",
        encoding="utf-8",
    )
    ex = _extraction_with_sources("ATTOM property API")

    result = ground_node({"extraction": ex, "target_repo": str(repo)})
    grounding = result["extraction"].grounding

    assert grounding.target_repo == str(repo)
    attom = [c for c in grounding.existence_claims if "ATTOM" in c.fact]
    assert len(attom) == 1
    assert attom[0].status == IntegrationStatus.INTEGRATED
    assert "client.py" in attom[0].how_to_verify


def test_ground_node_marks_missing_source_to_investigate(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "readme.md").write_text("a project that does nothing relevant\n", encoding="utf-8")
    ex = _extraction_with_sources("Perplexity API")

    result = ground_node({"extraction": ex, "target_repo": str(repo)})
    grounding = result["extraction"].grounding

    assert grounding.target_repo == str(repo)
    perplexity = [c for c in grounding.existence_claims if "Perplexity" in c.fact]
    assert len(perplexity) == 1
    assert perplexity[0].status == IntegrationStatus.TO_INVESTIGATE


def test_ground_node_missing_repo_path_stays_to_investigate(tmp_path: Path):
    ex = _extraction_with_sources("ATTOM property API")
    result = ground_node({"extraction": ex, "target_repo": str(tmp_path / "does-not-exist")})
    grounding = result["extraction"].grounding
    assert grounding.target_repo == str(tmp_path / "does-not-exist")
    assert all(c.status == IntegrationStatus.TO_INVESTIGATE for c in grounding.existence_claims)
