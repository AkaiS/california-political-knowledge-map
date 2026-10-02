# 01 Concentrate Evaluation Case review editing

Labels: completed

## Parent

[Evaluation Case review editing](../PRD.md)

## What to build

Move the reviewer's editing and ordering rules behind one DOM-free,
dependency-free JavaScript interface and use it from the existing page. A
reviewer can edit, recover drafts, save, navigate, and Undo with the same
behavior, while deterministic tests exercise those operations without a browser.
Ship the module's exact HTTP route and page integration together so the new
interface has a real caller from the first completed ticket.

## Acceptance criteria

- [x] One module owns current reviews, selection, revisions, drafts, Undo history,
      note debounce, serialized and deduplicated saves, and navigation
      invalidation. The page uses commands and observable state rather than
      reaching into those mechanisms.
- [x] The construction dependencies are limited to loaded case/review identity,
      persistence, synchronous draft storage, controlled scheduling, and state
      notification. The module imports without a DOM or browser globals and
      adds no third-party dependency or package manifest.
- [x] Note edits synchronously preserve a browser draft and save after 350
      milliseconds without another edit. Verdict changes, Undo, and explicit
      saves flush immediately. Clear verdict retains the note, and unchanged
      values create no Undo entry.
- [x] Saves are serialized and deduplicated for the same case revision. Public
      flush includes edits made during an in-flight save. An older success or
      failure cannot clear a newer draft or replace its save status.
- [x] Failed saves retain selection, in-memory reviews, and recoverable drafts.
      Explicit retry can finish the write. A 409 retains the edits and existing
      report-changed guidance without changing the Python review contract.
- [x] Absolute selection, filter-triggered movement, and relative navigation
      flush before moving. Rapid relative commands each execute in order and
      calculate their destination when execution begins. A final-case
      save-and-advance still saves without changing selection.
- [x] Undo restores and selects the affected case immediately, invalidates every
      earlier pending navigation command, and saves the restored value. Pending
      saves may finish without moving away, and later navigation still works.
- [x] Recovery accepts only same-report drafts for known cases with valid verdict
      and string note values. It preserves the existing key and envelope,
      ignores malformed/unknown entries, retries recovered drafts, and leaves
      unrelated and legacy keys untouched.
- [x] Storage failures preserve edits in memory and the current keep-open and
      unload guidance. Before-unload backup, online retry, and All Runs use
      public commands; All Runs leaves only after successful flush.
- [x] The page keeps filter matching, keyboard handling, trace rendering, and
      DOM work. Note entry and save-status notifications preserve the note's
      focus, caret, and trace view. Save-blocked movement retains the selected
      case's outside-filter row. Empty reports still load without editing errors.
- [x] One exact module asset route returns the intended local file with a
      JavaScript content type after trusted-Host validation. Unknown asset paths
      and wrong Hosts are rejected; no directory hosting is introduced.
- [x] Node's built-in runner deterministically covers every editing-interface
      behavior in the parent testing table using controlled persistence and
      scheduling. Tests assert commands' public outcomes and real draft/payload
      effects, never revisions, internal maps, history, or promise chains.
- [x] Python HTTP tests cover asset delivery and validation, and the focused
      reviewer server/task checks pass. Existing report, review-file, and safe
      rendering tests remain intact.
- [x] Retained browser workflows no longer call private save functions or await
      private navigation chains. Any necessary waits use visible UI state and
      persisted output. They remain opt-in and are not executed for this task.

## Blocked by

None. Can start immediately.

## Verification

Run the new Node test command and focused deterministic reviewer pytest through
uv. Review the adapter diff for focus, caret, filter, shortcut, and trace
preservation; do not claim browser verification. Record commands and results in
the completion comment. The PRD's behavioral table is the acceptance contract,
and the implementation may choose concise method names without exposing internals.

## Comments

2026-10-02: Completed implementation `bfa00d6` and reviewed the three-dot diff
from `b7dc72476a52ae40c4acc5ea912d0ea6dba33de1` with separate Standards and Spec
agents. Standards found no documented violations and one P3 Duplicated Code
judgement call: button availability repeated the module's navigation rule. The
review fix adds a read-only `canNavigate` query sharing the destination calculation
with navigation, removes the page's duplicate algorithm, and checks the public
query against selection, filters, and empty reports. The Standards agent confirmed
the finding resolved with no new findings. Spec found no gaps or scope creep.
No valid finding remains unresolved.

All acceptance criteria are supported by the module's public-command tests,
exact-route HTTP tests, and page-adapter review. The adapter keeps typing and
save-status updates away from the note value and trace content; selection and
Undo can redraw. Browser workflows retain observable waits and remain opt-in.
They were not executed, so these checks do not establish visual or caret behavior
in a browser. Ticket 02 retains CI and documentation work.

Verification used `UV_CACHE_DIR=/private/tmp/ca-map-review-uv-cache` with each uv
command because the sandbox could not initialize the default cache:

- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs`: 22 passed.
- `uv run --no-sync pytest -q tests/test_chat_eval_review.py tests/test_chat_eval_task.py`:
  29 passed, one existing event-loop deprecation warning. Loopback tests used
  approved sandbox escalation after the Spec agent's socket-bind permission failures.
- `RUN_REVIEW_BROWSER_TESTS=0 uv run --no-sync pytest -q tests`: 1409 passed,
  61 skipped, one existing provider sampling warning. Ran once after the fix with
  loopback permission.
- Changed Python files passed Ruff and `python -m py_compile` through uv. The
  module and extracted page adapter passed Node syntax checks, and `git diff
  --check` passed. No Python type checker is configured; lint and compilation
  are not typing checks.

The acceptance checkboxes and `completed` label reflect this evidence.
