"""Tests for filesystem helpers."""

from __future__ import annotations

from pathlib import Path

from app.io import atomic_append, atomic_write, library_path, slugify


def test_slugify_basic():
    assert slugify("Self Storage") == "self-storage"
    assert slugify("Round Rock, TX") == "round-rock-tx"
    assert slugify("  spaces  ") == "spaces"
    assert slugify("Café") == "cafe"
    assert slugify("---weird---") == "weird"
    assert slugify("") == "untitled"
    assert slugify("///") == "untitled"


def test_slugify_collapses_repeats():
    assert slugify("a    b") == "a-b"
    assert slugify("a---b") == "a-b"


def test_atomic_write_creates_parents(tmp_path: Path):
    target = tmp_path / "a" / "b" / "c.md"
    atomic_write(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_overwrites(tmp_path: Path):
    target = tmp_path / "x.md"
    atomic_write(target, "first")
    atomic_write(target, "second")
    assert target.read_text() == "second"


def test_atomic_write_no_tmp_leftover(tmp_path: Path):
    target = tmp_path / "y.md"
    atomic_write(target, "x")
    leftovers = list(tmp_path.glob(".y.md.*.tmp"))
    assert leftovers == []


def test_atomic_append(tmp_path: Path):
    target = tmp_path / "log.md"
    atomic_append(target, "one\n")
    atomic_append(target, "two\n")
    assert target.read_text() == "one\ntwo\n"


def test_library_path_is_dynamic(tmp_path: Path):
    p = library_path(tmp_path, "Self Storage", "Acquisition", "Round Rock Pad Count")
    assert p == tmp_path / "workflows" / "library" / "self-storage" / "acquisition" / "round-rock-pad-count"


def test_library_path_never_hardcodes_asset_class(tmp_path: Path):
    # Any deal_type string yields a slug. The function holds no allow-list.
    p = library_path(tmp_path, "Truck Stop", "Underwriting", "Diesel Volume Check")
    assert "truck-stop" in p.parts
    assert "underwriting" in p.parts
    assert "diesel-volume-check" in p.parts
