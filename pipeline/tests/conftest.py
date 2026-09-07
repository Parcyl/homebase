"""Puts the repo root (for `import providers...`) and pipeline/ itself (for `import
record_session` etc., which import each other as plain top-level modules, matching how
they're actually run: `python3 pipeline/record_session.py`) on sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

_PIPELINE_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PIPELINE_DIR.parent
for p in (_REPO_ROOT, _PIPELINE_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
