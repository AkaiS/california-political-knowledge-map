#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/setup-worktree.sh [--source PATH] [--dry-run] [--skip-sync]

Prepare the current Git worktree for local development.

By default, PATH is the primary worktree that owns the repository's common
.git directory. Existing local files are never overwritten.

Options:
  --source PATH  Copy/link local state from PATH instead of the primary worktree
  --dry-run      Print the actions without changing anything
  --skip-sync    Do not run "uv sync --frozen"
  -h, --help     Show this help
EOF
}

source_root=""
dry_run=false
skip_sync=false

while (($#)); do
  case "$1" in
    --source)
      if (($# < 2)); then
        echo "setup-worktree: --source requires a path" >&2
        exit 2
      fi
      source_root=$2
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --skip-sync)
      skip_sync=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "setup-worktree: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

target_root=$(git rev-parse --show-toplevel)

if [[ -z "$source_root" ]]; then
  common_git_dir=$(git rev-parse --path-format=absolute --git-common-dir)
  source_root=$(dirname "$common_git_dir")
fi

if [[ ! -d "$source_root" ]]; then
  echo "setup-worktree: source directory does not exist: $source_root" >&2
  exit 1
fi

source_root=$(cd "$source_root" && pwd -P)
target_root=$(cd "$target_root" && pwd -P)

run() {
  if "$dry_run"; then
    printf 'Would run:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

copy_if_missing() {
  local relative_path=$1
  local source_path="$source_root/$relative_path"
  local target_path="$target_root/$relative_path"

  if [[ ! -e "$source_path" ]]; then
    printf 'Skipping %s (not present in source)\n' "$relative_path"
  elif [[ -e "$target_path" || -L "$target_path" ]]; then
    printf 'Keeping existing %s\n' "$relative_path"
  else
    run mkdir -p "$(dirname "$target_path")"
    run cp -R "$source_path" "$target_path"
  fi
}

link_if_missing() {
  local relative_path=$1
  local source_path="$source_root/$relative_path"
  local target_path="$target_root/$relative_path"

  if [[ ! -e "$source_path" ]]; then
    printf 'Skipping %s (not present in source)\n' "$relative_path"
  elif [[ -e "$target_path" || -L "$target_path" ]]; then
    printf 'Keeping existing %s\n' "$relative_path"
  else
    run ln -s "$source_path" "$target_path"
  fi
}

printf 'Setting up worktree: %s\n' "$target_root"
printf 'Local-state source: %s\n' "$source_root"

if [[ "$source_root" != "$target_root" ]]; then
  # Deliberately allowlisted: do not copy .venv, caches, logs, or DLQ data.
  copy_if_missing ".env"
  copy_if_missing ".agents"
  copy_if_missing ".logfire/logfire_credentials.json"
  link_if_missing "document_store.db"
else
  echo "Current worktree is the local-state source; no files need transferring."
fi

run mkdir -p "$target_root/.scratch/dlq"

if ! "$skip_sync"; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "setup-worktree: uv is required but was not found on PATH" >&2
    exit 1
  fi
  run uv sync --frozen --project "$target_root"
fi

echo "Worktree setup complete."
