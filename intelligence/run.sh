#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3.11 || command -v python3)}"

if [ ! -d ".venv" ]; then
  echo "Creating venv with $PYTHON_BIN ..."
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev]"

if [ ! -f ".env" ]; then
  echo "ERROR: .env missing. Copy .env.example to .env and fill in ANTHROPIC_API_KEY."
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

# uvicorn requires lowercase log levels (info, warning, error, ...).
# The app code uses Python's logging module with uppercase names, so LOG_LEVEL in
# the .env stays uppercase; we lowercase only for the uvicorn flag.
UVICORN_LOG_LEVEL=$(printf '%s' "${LOG_LEVEL:-info}" | /usr/bin/tr '[:upper:]' '[:lower:]')

exec uvicorn app.main:app \
  --host "${LANGGRAPH_HOST:-127.0.0.1}" \
  --port "${LANGGRAPH_PORT:-8080}" \
  --workers 1 \
  --log-level "$UVICORN_LOG_LEVEL"
