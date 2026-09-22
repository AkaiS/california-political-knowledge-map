#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)

if ! command -v uv >/dev/null 2>&1; then
  echo "setup-databases: uv is required but was not found on PATH" >&2
  exit 1
fi

cd "$project_root"
exec uv run --project "$project_root" python -m knowledge_map.database_setup
