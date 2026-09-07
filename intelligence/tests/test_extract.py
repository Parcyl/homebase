"""Tests for extract_node multimodal behavior.

The extract node must pass keyframes to Claude as actual image blocks
(base64 data URIs), not as plain-text file paths. This is the visual layer
that lets Claude see what was on the operator's screen during the recording.
"""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from app.models import Extraction
from app.nodes.extract import (
    MAX_KEYFRAMES,
    _read_image_b64,
    extract_node,
    select_keyframes,
)


def _fake_jpeg_bytes(token: bytes = b"FAKE") -> bytes:
    return b"\xff\xd8\xff\xe0" + token + b"\xff\xd9"


def _make_keyframes(tmp_path: Path, n: int) -> list[str]:
    paths: list[str] = []
    for i in range(n):
        p = tmp_path / f"kf_{i:04d}.jpg"
        p.write_bytes(_fake_jpeg_bytes(f"frame{i}".encode()))
        paths.append(str(p))
    return paths


def _stub_factory(extraction: Extraction):
    """Returns (factory, captured) where factory mimics get_llm()'s return type
    and captured["messages"] holds whatever was passed to invoke()."""
    captured: dict = {"messages": None}

    class StructuredLLM:
        def invoke(self, messages):
            captured["messages"] = messages
            return extraction

    class Factory:
        def with_structured_output(self, _schema):
            return StructuredLLM()

    return Factory(), captured


# ── select_keyframes ────────────────────────────────────────────────────────


def test_select_keyframes_returns_input_when_under_max(tmp_path: Path):
    paths = _make_keyframes(tmp_path, 5)
    assert select_keyframes(paths, max_count=10) == paths


def test_select_keyframes_returns_empty_for_empty_input():
    assert select_keyframes([], max_count=10) == []


def test_select_keyframes_returns_evenly_spaced_first_and_last_included(tmp_path: Path):
    paths = _make_keyframes(tmp_path, 25)
    result = select_keyframes(paths, max_count=10)
    assert len(result) == 10
    assert result[0] == paths[0]
    assert result[-1] == paths[-1]
    assert len(set(result)) == 10


def test_select_keyframes_at_exact_max(tmp_path: Path):
    paths = _make_keyframes(tmp_path, 10)
    assert select_keyframes(paths, max_count=10) == paths


# ── _read_image_b64 ─────────────────────────────────────────────────────────


def test_read_image_b64_encodes_file_content(tmp_path: Path):
    p = tmp_path / "img.jpg"
    p.write_bytes(b"hello")
    encoded = _read_image_b64(str(p))
    assert encoded == base64.b64encode(b"hello").decode("ascii")


def test_read_image_b64_returns_none_for_missing(tmp_path: Path):
    assert _read_image_b64(str(tmp_path / "nope.jpg")) is None


# ── extract_node multimodal ─────────────────────────────────────────────────


def test_extract_node_builds_multimodal_message_with_keyframes(
    isolated_homebase: Path, tmp_path: Path
):
    paths = _make_keyframes(tmp_path, 2)
    factory, captured = _stub_factory(Extraction(operator_intent="x"))

    state = {
        "session_id": "2026-05-27T10-00-00-test",
        "transcript": "hello operator",
        "keyframe_paths": paths,
    }

    with patch("app.nodes.extract.get_llm", return_value=factory):
        extract_node(state)

    msg = captured["messages"]
    assert isinstance(msg, list), "extract_node must pass a list of messages to invoke"
    assert len(msg) == 1
    assert isinstance(msg[0], HumanMessage)

    content = msg[0].content
    assert isinstance(content, list)
    text_blocks = [b for b in content if b.get("type") == "text"]
    image_blocks = [b for b in content if b.get("type") == "image_url"]

    assert len(text_blocks) >= 1
    assert "operator" in text_blocks[0]["text"]
    assert len(image_blocks) == 2
    for block in image_blocks:
        url = block["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        b64_part = url.split(",", 1)[1]
        assert base64.b64decode(b64_part).startswith(b"\xff\xd8\xff")


def test_extract_node_caps_keyframes_at_max(isolated_homebase: Path, tmp_path: Path):
    paths = _make_keyframes(tmp_path, 25)
    factory, captured = _stub_factory(Extraction(operator_intent="x"))

    state = {
        "session_id": "2026-05-27T10-00-00-test",
        "transcript": "x",
        "keyframe_paths": paths,
    }

    with patch("app.nodes.extract.get_llm", return_value=factory):
        extract_node(state)

    image_blocks = [b for b in captured["messages"][0].content if b.get("type") == "image_url"]
    assert len(image_blocks) == MAX_KEYFRAMES == 10


def test_extract_node_no_keyframes_sends_text_only(isolated_homebase: Path):
    factory, captured = _stub_factory(Extraction(operator_intent="x"))

    state = {
        "session_id": "2026-05-27T10-00-00-test",
        "transcript": "x",
        "keyframe_paths": [],
    }

    with patch("app.nodes.extract.get_llm", return_value=factory):
        extract_node(state)

    content = captured["messages"][0].content
    text_blocks = [b for b in content if b.get("type") == "text"]
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    assert len(text_blocks) >= 1
    assert image_blocks == []


def test_extract_node_skips_unreadable_keyframes(isolated_homebase: Path, tmp_path: Path):
    paths = _make_keyframes(tmp_path, 2)
    paths.append(str(tmp_path / "missing.jpg"))  # third path does not exist on disk
    factory, captured = _stub_factory(Extraction(operator_intent="x"))

    state = {
        "session_id": "2026-05-27T10-00-00-test",
        "transcript": "x",
        "keyframe_paths": paths,
    }

    with patch("app.nodes.extract.get_llm", return_value=factory):
        extract_node(state)

    image_blocks = [b for b in captured["messages"][0].content if b.get("type") == "image_url"]
    assert len(image_blocks) == 2  # missing one is skipped, not raised
