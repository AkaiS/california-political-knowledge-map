#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <issue-file> [<issue-file> ...]"
  exit 1
fi

repo_root=$(git rev-parse --show-toplevel)
issues=()

for issue_arg in "$@"; do
  if [[ "$issue_arg" = /* ]]; then
    issue_path=$issue_arg
  else
    issue_path=$repo_root/$issue_arg
  fi

  if [ ! -f "$issue_path" ]; then
    echo "Issue file not found: $issue_arg" >&2
    exit 1
  fi

  issue_path=$(realpath "$issue_path")
  if [[ "$issue_path" != "$repo_root"/* ]]; then
    echo "Issue file must be inside the repository: $issue_arg" >&2
    exit 1
  fi

  issue=${issue_path#"$repo_root"/}
  issues+=("$issue")
done

printf -v batch_issues -- '- %s\n' "${issues[@]}"

run_id=$(date -u +%Y%m%d-%H%M%S)-$$
workspace=$(mktemp -d "${TMPDIR:-/tmp}/ralph-$run_id.XXXXXX")/repo
sandbox_name="ralph-$run_id"
branch="codex/ralph-$run_id"

echo "Cloning..."
git clone --quiet --local --no-hardlinks "$repo_root" "$workspace"
echo "Copying agents..."
cp -R "$repo_root/.agents" "$workspace/.agents"

# An issue may be ignored or contain uncommitted edits, so copy the exact input
# that the caller selected into the otherwise clean workspace.
echo "Copying issue files..."
for issue in "${issues[@]}"; do
  mkdir -p "$(dirname "$workspace/$issue")"
  cp "$repo_root/$issue" "$workspace/$issue"
done

echo "Switching to new branch..."
git -C "$workspace" switch --quiet -c "$branch"
base_commit=$(git -C "$workspace" rev-parse HEAD)

echo "Ralph workspace: $workspace"

sbx create --name "$sandbox_name" codex "$workspace"

for index in "${!issues[@]}"; do
  issue=${issues[$index]}
  issue_number=$((index + 1))
  before_commit=$(git -C "$workspace" rev-parse HEAD)

  echo
  echo "Issue $issue_number/${#issues[@]}: $issue"

  if result=$(sbx run --name "$sandbox_name" codex -- \
    exec \
    --model "gpt-5.6-sol" \
    -c 'model_reasoning_effort="low"' \
    --dangerously-bypass-approvals-and-sandbox \
    --ephemeral \
    "Implement the issue at \"$issue\" in the current repository.

This issue is one item in the following caller-selected ordered batch:
$batch_issues
Work only on the current issue, while preserving the implementations already
committed for earlier batch items and leaving later batch items for their turns.
Read its parent specification and directly relevant repository guidance as
needed. Do not invoke /implement, /code-review, or /to-tickets, and do not
create review follow-up issues.

Implement the requested behavior, run proportionate verification, check the
satisfied acceptance criteria, and set the issue's Labels value to completed.
Commit the implementation and issue update together as one commit before
finishing. Do not amend or rewrite commits from earlier batch items." 2>&1); then
    run_status=0
  else
    run_status=$?
  fi

  printf '%s\n' "$result"

  if ((run_status != 0)); then
    echo "Ralph failed on $issue with exit code $run_status" >&2
    exit "$run_status"
  fi

  after_commit=$(git -C "$workspace" rev-parse HEAD)
  if [ "$after_commit" = "$before_commit" ]; then
    echo "Ralph did not commit a result for $issue" >&2
    exit 1
  fi
done

git -C "$repo_root" fetch "$workspace" "HEAD:refs/heads/$branch"

echo
echo "Done. Aggregate results are on $branch"
echo "Commits:"
git -C "$workspace" log --reverse --format='%H %s' "$base_commit..HEAD"
