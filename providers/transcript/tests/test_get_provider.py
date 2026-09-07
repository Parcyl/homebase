"""Tests for the providers.transcript.get_provider() factory."""
from __future__ import annotations

import pytest

from providers.transcript import FileProvider, VowenProvider, WisprFlowProvider, get_provider


def test_default_is_file_when_unset(monkeypatch):
    monkeypatch.delenv("DICTATION_PROVIDER", raising=False)
    assert isinstance(get_provider(), FileProvider)


def test_explicit_name_overrides_env(monkeypatch):
    monkeypatch.setenv("DICTATION_PROVIDER", "vowen")
    assert isinstance(get_provider("file"), FileProvider)


def test_env_selects_vowen(monkeypatch):
    monkeypatch.setenv("DICTATION_PROVIDER", "vowen")
    assert isinstance(get_provider(), VowenProvider)


def test_env_selects_wisprflow(monkeypatch):
    monkeypatch.setenv("DICTATION_PROVIDER", "wisprflow")
    assert isinstance(get_provider(), WisprFlowProvider)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.delenv("DICTATION_PROVIDER", raising=False)
    with pytest.raises(ValueError):
        get_provider("not-a-real-provider")


def test_file_provider_binds_session_dir(tmp_path):
    provider = get_provider("file", session_dir=tmp_path)
    assert isinstance(provider, FileProvider)
    assert provider.session_dir == tmp_path


def test_is_case_insensitive(monkeypatch):
    monkeypatch.delenv("DICTATION_PROVIDER", raising=False)
    assert isinstance(get_provider("VOWEN"), VowenProvider)
