"""Grounding node. Turns 'what exists' from a guess into a fact.

This is the HF1 kill switch. The generate prompt is forbidden from asserting
that any integration exists; only this node may promote an existence claim to
INTEGRATED, and only by actually finding the source named in a real target repo.

- No target_repo  -> no claims. Downstream labels every integration to_investigate.
- target_repo set  -> for each data source the extraction names, grep the repo
  for the source's brand token. Found -> INTEGRATED (with the file as proof).
  Not found / unreadable repo -> TO_INVESTIGATE (with how to verify).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .. import pipeline_state
from ..models import ExistenceClaim, Extraction, Grounding, IntegrationStatus
from ..state import PipelineState

log = logging.getLogger("homebase.grounding")

# Brand tokens are distinctive: all-caps acronyms (ATTOM) or Capitalized names
# (Perplexity, Mapbox). Generic words and common acronyms are not evidence.
_BRAND_RE = re.compile(r"\b([A-Z][a-zA-Z]{3,}|[A-Z]{4,})\b")
_STOP_BRANDS = {"API", "JSON", "HTTP", "HTTPS", "REST", "GIS", "CRS", "URL"}

# Bound the read so a huge repo cannot stall the pipeline.
_MAX_FILES = 4000
_MAX_BYTES = 200_000
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}
_TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".toml",
    ".yaml", ".yml", ".env", ".cfg", ".ini", ".sql", ".sh", ".rb", ".go",
}


def _brand_tokens(source: str) -> list[str]:
    """Distinctive tokens worth searching for. Empty if the source is all generic."""
    return [t for t in _BRAND_RE.findall(source) if t not in _STOP_BRANDS]


def _collect_sources(extraction: Extraction) -> list[str]:
    """Every distinct data source the extraction names, order-preserving."""
    seen: dict[str, None] = {}
    for comp in extraction.components:
        if comp.data_contract and comp.data_contract.source:
            seen.setdefault(comp.data_contract.source, None)
    for src in extraction.data_sources:
        seen.setdefault(src, None)
    return list(seen.keys())


def _search_repo(repo: Path, tokens: list[str]) -> str | None:
    """Return a 'token in relpath' proof string if any token is found, else None."""
    if not tokens:
        return None
    scanned = 0
    for path in repo.rglob("*"):
        if scanned >= _MAX_FILES:
            break
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:_MAX_BYTES]
        except OSError:
            continue
        for tok in tokens:
            if tok in text:
                return f"found '{tok}' in {path.relative_to(repo)}"
    return None


def _claim_for(source: str, repo: Path | None) -> ExistenceClaim:
    tokens = _brand_tokens(source)
    proof = _search_repo(repo, tokens) if repo and repo.is_dir() else None
    if proof:
        return ExistenceClaim(
            fact=f"{source} integration", status=IntegrationStatus.INTEGRATED, how_to_verify=proof
        )
    return ExistenceClaim(
        fact=f"{source} integration",
        status=IntegrationStatus.TO_INVESTIGATE,
        how_to_verify=f"grep the target repo for {source!r}; none of {tokens or [source]} found",
    )


def ground_node(state: PipelineState) -> dict:
    """Populate extraction.grounding from a real read of target_repo, or leave it
    empty (ungrounded) when no repo is named."""
    target_repo = state.get("target_repo")
    extraction: Extraction = state["extraction"]

    if not target_repo:
        # Ungrounded: claim nothing. Downstream forces to_investigate.
        return {}

    pipeline_state.update("grounding", state.get("session_id"))
    repo = Path(target_repo).expanduser()
    claims = [_claim_for(src, repo) for src in _collect_sources(extraction)]
    grounded = extraction.model_copy(
        update={"grounding": Grounding(target_repo=target_repo, existence_claims=claims)}
    )
    log.info(
        "grounding_complete",
        extra={
            "session_id": state.get("session_id"),
            "target_repo": target_repo,
            "claims": len(claims),
            "integrated": sum(c.status == IntegrationStatus.INTEGRATED for c in claims),
        },
    )
    return {"extraction": grounded}
