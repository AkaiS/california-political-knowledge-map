#!/usr/bin/env bash
set -e

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <iteration-limit> <queue-file>"
  exit 1
fi

limit=$1
queue=$2

if ! [[ "$limit" =~ ^[1-9][0-9]*$ ]]; then
  echo "Iteration limit must be a positive integer."
  exit 1
fi

repo_root=$(git rev-parse --show-toplevel)
queue=${queue#"$repo_root"/}

if [ ! -f "$repo_root/$queue" ]; then
  echo "Queue file not found: $queue"
  exit 1
fi

run_id=$(date -u +%Y%m%d-%H%M%S)-$$
workspace=$(mktemp -d "${TMPDIR:-/tmp}/ralph-$run_id.XXXXXX")/repo
sandbox_name="ralph-$run_id"
branch="codex/ralph-$run_id"

echo "Cloning..."
git clone --quiet --local --no-hardlinks "$repo_root" "$workspace"
echo "Copying agents..."
cp -R "$repo_root/.agents" "$workspace/.agents"
echo "Copying queue file..."
mkdir -p "$(dirname "$workspace/$queue")"
cp "$repo_root/$queue" "$workspace/$queue"
echo "Switching to new branch..."
git -C "$workspace" switch --quiet -c "$branch"

echo "Ralph workspace: $workspace"

sbx create --name "$sandbox_name" codex "$workspace"

for ((iteration = 1; iteration <= limit; iteration++)); do
  echo
  echo "Iteration $iteration/$limit"

  if result=$(sbx run --name "$sandbox_name" codex -- \
    exec \
    --model "gpt-5.6-luna" \
    -c 'model_reasoning_effort="high"' \
    --dangerously-bypass-approvals-and-sandbox \
    --ephemeral \
    "/implement the next issue in \"$queue\".

The file is a stack with '# Completed' and '# Queue' sections. Ignore blank
lines and comments. The bottommost issue path below '# Queue' is the only issue
to implement this iteration. Queue order is authoritative: do not inspect other
issues or their blockers to choose work. If '# Queue' contains no issue paths,
make no changes and emit the completion promise below.

Before implementation, record the current HEAD. Use that commit as the fixed
point when /implement invokes /code-review.

If code review reports actionable findings, invoke /to-tickets once with all of
them. Hard Standards violations and missing or incorrect Spec behavior are
actionable; advisory code-smell observations are not. The user pre-approves the
ticket breakdown, so skip /to-tickets' approval interview. Publish one Markdown
issue per ticket in the current feature's issues directory, assign each the next
unused numeric prefix and Labels: ready-for-agent. Use only the current issue,
its parent specification, and the review findings as ticket context; do not scan
the rest of the queue. Make the first review ticket blocked by the current issue
and chain later review tickets in execution order. Retain their paths and order
for the queue update below. Do not modify the parent PRD.

When finished, check the satisfied acceptance criteria and set the current
issue's Labels value to completed. First remove its path from the bottom of
'# Queue' and append it to the end of '# Completed', immediately above
'# Queue'. Then push any review-ticket paths onto the bottom of '# Queue' in
reverse execution order, so the first review ticket is bottommost and runs next.
Commit the implementation, issue update, queue update, and review tickets
together.

After committing, inspect only the '# Queue' section. If it contains no issue
paths, end your final response with exactly:
<promise>ALL_ISSUES_COMPLETE</promise>

Otherwise end it with exactly:
<promise>CONTINUE</promise>" 2>&1); then
    run_status=0
  else
    run_status=$?
  fi

  printf '%s\n' "$result"

  if ((run_status != 0)); then
    echo "Ralph iteration failed with exit code $run_status" >&2
    exit "$run_status"
  fi

  if grep -Fxq '<promise>ALL_ISSUES_COMPLETE</promise>' <<<"$result"; then
    git -C "$repo_root" fetch "$workspace" "HEAD:refs/heads/$branch"
    echo
    echo "Done. Results are on $branch"
    exit 0
  fi
done

git -C "$repo_root" fetch "$workspace" "HEAD:refs/heads/$branch"

echo
echo "Iteration limit reached. Partial results are on $branch"
exit 1
