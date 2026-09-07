"""Proves ScreenStudioRecorder and FileRecorder both satisfy the RecorderAdapter Protocol
-- the whole point of the seam (see design.md section 1).
"""
from __future__ import annotations

import pytest

from providers.recorder.adapter import RecorderAdapter
from providers.recorder.file import FileRecorder
from providers.recorder.screen_studio import ScreenStudioRecorder

ALL_RECORDERS = [ScreenStudioRecorder, FileRecorder]


@pytest.mark.parametrize("cls", ALL_RECORDERS)
def test_recorder_satisfies_protocol_at_runtime(cls):
    recorder = cls()
    assert isinstance(recorder, RecorderAdapter)


@pytest.mark.parametrize("cls", ALL_RECORDERS)
def test_recorder_has_a_name(cls):
    recorder = cls()
    assert isinstance(recorder.name, str) and recorder.name


@pytest.mark.parametrize("cls", ALL_RECORDERS)
def test_start_and_stop_are_best_effort_and_never_raise(cls, tmp_path):
    recorder = cls(runner=lambda *_: None) if cls is ScreenStudioRecorder else cls()
    recorder.start(tmp_path)
    recorder.stop(tmp_path)


@pytest.mark.parametrize("cls", ALL_RECORDERS)
def test_resolve_master_on_empty_session_is_none_not_error(cls, tmp_path):
    recorder = cls(ss_dir=tmp_path / "nope") if cls is ScreenStudioRecorder else cls()
    assert recorder.resolve_master(0.0, tmp_path) is None
