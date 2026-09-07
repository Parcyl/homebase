#!/usr/bin/env bash
# Open the latest prds/<session>/PRD.md in HOMEBASE_EDITOR_APP (default VS Code), not the
# system .md default. Written by intelligence/app/io.py. See open_in_editor in lib/state.sh.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../lib/state.sh"

PRD="$(latest_prd || true)"
if [[ -z "$PRD" || ! -f "$PRD" ]]; then
    notify "Homebase" "No PRD yet"
    echo "no prd found"
    exit 1
fi

open_in_editor "$PRD"
