"""Tests for the providers.recorder.get_recorder() factory."""
from __future__ import annotations

import pytest

from providers.recorder import FileRecorder, ScreenStudioRecorder, get_recorder


def test_default_is_file_when_unset(monkeypatch):
    monkeypatch.delenv("RECORDER", raising=False)
    assert isinstance(get_recorder(), FileRecorder)


def test_explicit_name_overrides_env(monkeypatch):
    monkeypatch.setenv("RECORDER", "screen-studio")
    assert isinstance(get_recorder("file"), FileRecorder)


def test_env_selects_screen_studio(monkeypatch):
    monkeypatch.setenv("RECORDER", "screen-studio")
    assert isinstance(get_recorder(), ScreenStudioRecorder)


def test_unknown_recorder_raises(monkeypatch):
    monkeypatch.delenv("RECORDER", raising=False)
    with pytest.raises(ValueError):
        get_recorder("not-a-real-recorder")


def test_is_case_insensitive(monkeypatch):
    monkeypatch.delenv("RECORDER", raising=False)
    assert isinstance(get_recorder("SCREEN-STUDIO"), ScreenStudioRecorder)
