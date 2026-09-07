"""Proves VowenProvider, FileProvider, and WisprFlowProvider all satisfy the
TranscriptProvider Protocol -- the whole point of the seam (see design.md section 1).
"""
from __future__ import annotations

import pytest

from providers.transcript.file import FileProvider
from providers.transcript.provider import ProviderHealth, TranscriptEntry, TranscriptProvider
from providers.transcript.vowen import VowenProvider
from providers.transcript.wisprflow import WisprFlowProvider

ALL_PROVIDERS = [VowenProvider, FileProvider, WisprFlowProvider]


@pytest.mark.parametrize("cls", ALL_PROVIDERS)
def test_provider_satisfies_protocol_at_runtime(cls, tmp_path):
    provider = cls(**({"history_path": tmp_path / "nope.json"} if cls is not FileProvider
                      else {"session_dir": tmp_path}))
    assert isinstance(provider, TranscriptProvider)


@pytest.mark.parametrize("cls", ALL_PROVIDERS)
def test_provider_has_a_name(cls, tmp_path):
    provider = cls(**({"history_path": tmp_path / "nope.json"} if cls is not FileProvider
                      else {"session_dir": tmp_path}))
    assert isinstance(provider.name, str) and provider.name


@pytest.mark.parametrize("cls", ALL_PROVIDERS)
def test_health_returns_provider_health(cls, tmp_path):
    provider = cls(**({"history_path": tmp_path / "nope.json"} if cls is not FileProvider
                      else {"session_dir": tmp_path}))
    health = provider.health()
    assert isinstance(health, ProviderHealth)
    assert health.name == provider.name


@pytest.mark.parametrize("cls", ALL_PROVIDERS)
def test_entries_in_window_on_missing_source_is_empty_list_not_error(cls, tmp_path):
    provider = cls(**({"history_path": tmp_path / "nope.json"} if cls is not FileProvider
                      else {"session_dir": tmp_path}))
    entries = provider.entries_in_window(0.0, 100.0)
    assert entries == []


def test_transcript_entry_shape():
    e = TranscriptEntry(epoch=1.0, ts_iso="2026-01-01T00:00:01Z", text="hi", source="test")
    assert e.epoch == 1.0 and e.text == "hi" and e.source == "test"
