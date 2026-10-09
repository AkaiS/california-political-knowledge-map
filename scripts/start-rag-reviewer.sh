#!/usr/bin/env bash
set -euo pipefail
checkout="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$checkout"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Prepare this checkout first: uv sync --locked --dev' >&2
  exit 1
fi
exec uv run --no-sync python -u scripts/start_rag_reviewer.py "$@"
