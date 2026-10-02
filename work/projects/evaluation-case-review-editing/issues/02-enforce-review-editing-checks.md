# 02 Run review editing checks on every pull request

Labels: completed

## Parent

[Evaluation Case review editing](../PRD.md)

## What to build

Make a pull request fail when the review editing module violates its durability
or ordering contract. Normal CI runs its deterministic Node checks alongside
the existing Python checks. Maintainers have documented local commands for both
and can distinguish these checks from the optional browser workflows.

## Acceptance criteria

- [x] Normal pull-request CI explicitly installs Node 22 and runs the review
      editing tests with Node's built-in runner. Tests are required to pass and
      are not conditional on a browser opt-in variable or a preinstalled runtime.
- [x] Existing deterministic pytest still runs through uv. The new checks require
      no browser, npm package installation, model service, or database service.
- [x] Reviewer documentation explains the editing module's ownership and gives
      the exact local Node and uv test commands. It retains the optional browser
      command and states which behaviors still require browser verification.
- [x] The Node review-editing checks, focused reviewer Python checks, and full
      deterministic Python suite pass. Record counts, commands, and any existing
      skips or warnings accurately. Browser tests remain unexecuted.
- [x] The final diff preserves review files, report identity, public review JSON,
      shortcuts, and trace presentation, and contains no new mutable-state access
      from the page into the module. Standards and spec review findings are fixed
      before the implementation is considered complete.
- [x] Ticket completion comments record the evidence, and the parent PRD and
      work index reflect the completed project once all acceptance criteria pass.

## Blocked by

- [01 Concentrate Evaluation Case review editing](01-concentrate-review-editing.md)

## Verification

Run the same Node command used by CI and the repository's full deterministic
pytest command through uv. Inspect the workflow and retained browser tests
without launching a browser. The final green pull request supplies CI evidence;
do not call checks green while required runs are still pending.

## Comments

2026-10-02: Added Node 22 setup and the required review-editing test step to the
normal pull-request workflow. The action is pinned to the commit attached to
the official [setup-node v7.0.0 release](https://github.com/actions/setup-node/releases/tag/v7.0.0).
The workflow retains `uv run --no-sync pytest -q tests` and adds no browser or
npm installation. The reviewer guide now explains editing-module and page
ownership, exact local setup and test commands, and what still needs browser
verification. The optional browser commands remain documented.

Verification used `UV_CACHE_DIR=/private/tmp/ca-map-review-uv-cache` for each uv
command to keep cache writes inside the sandbox's writable paths:

- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs`:
  22 passed, no skips or warnings, with Node v22.23.1. This is the CI command.
- `uv run --no-sync pytest -q tests/test_chat_eval_review.py tests/test_chat_eval_task.py`:
  29 passed, one existing `pydantic_evals` event-loop deprecation warning.
- `RUN_REVIEW_BROWSER_TESTS=0 RUN_NEO4J_INTEGRATION=0 uv run --no-sync pytest -q tests`:
  1409 passed, 61 skipped, one existing OpenRouter sampling-parameter warning.
  The opt-in browser and Neo4j checks remained disabled. Both Python runs used
  approved sandbox escalation for temporary HTTP servers' loopback sockets.
- The workflow parsed as YAML, and `git diff --check` passed. No Python type
  checker is configured in this repository. This ticket changes no Python or
  JavaScript implementation.

Browser workflows were inspected and retained but not executed. The changes
since `4dec0b6a92819a64bc11f1a04652346967d35c51` affect only CI and documentation,
so they introduce no page access to mutable module state and no review-file,
report-identity, JSON, shortcut, or trace-presentation changes.

The final two criteria remain open for Standards and Spec review and the
resulting project reconciliation. The conductor will record final pull-request
CI evidence after opening the PR; local passing checks do not establish that
future CI run's result. The ticket, parent PRD, and work index retain their
current triage state until that handoff is complete.

2026-10-02: Completed the independent Standards and Spec review of
`git diff 4dec0b6a92819a64bc11f1a04652346967d35c51...75c90528c5b1ebb42a2b4f7eeeca4a7b4c17300c`.
Standards found zero documented breaches and zero smell findings. Spec found
zero missing requirements, wrong behavior, or scope creep. No implementation
fix was needed, and no valid finding remains unresolved. Both reviewers also
checked the reconciliation diff and found no introduced issues.

The final diff changes only CI and documentation. Review files, report identity,
public review JSON, shortcuts, trace presentation, and page/module access remain
unchanged. All acceptance criteria are now checked, this ticket and the parent
PRD are `completed`, and the work index lists both completed tickets and removes
the project from the ready queue. This completion supersedes the earlier comment
that review and reconciliation were pending.

Final verification used `UV_CACHE_DIR=/private/tmp/ca-map-review-uv-cache`:

- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs`:
  22 passed, no skips or warnings, Node v22.23.1.
- `RUN_REVIEW_BROWSER_TESTS=0 RUN_NEO4J_INTEGRATION=0 uv run --no-sync pytest -q tests/test_chat_eval_review.py tests/test_chat_eval_task.py`:
  29 passed, one existing event-loop deprecation warning.
- `RUN_REVIEW_BROWSER_TESTS=0 RUN_NEO4J_INTEGRATION=0 uv run --no-sync pytest -q tests`:
  1409 passed, 61 skipped, one existing OpenRouter sampling-parameter warning.
  The full suite ran once after the review and reconciliation changes. Python
  tests used approved loopback-socket permission.
- Workflow YAML parsing and assertions confirmed explicit Node 22, disabled
  package-manager caching, the unconditional required Node command, and the
  retained pytest command. `git diff --check` passed.

Browser tests remain retained and unexecuted. No type-check claim is made; the
repository has no configured Python type checker. Actual pull-request CI
evidence remains the conductor's final handoff after sequence review and PR
creation. These local results do not claim that pending remote checks passed.
