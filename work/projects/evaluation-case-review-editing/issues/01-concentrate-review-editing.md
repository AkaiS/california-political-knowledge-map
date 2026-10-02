# 01 Concentrate Evaluation Case review editing

Labels: ready-for-agent

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

- [ ] One module owns current reviews, selection, revisions, drafts, Undo history,
      note debounce, serialized and deduplicated saves, and navigation
      invalidation. The page uses commands and observable state rather than
      reaching into those mechanisms.
- [ ] The construction dependencies are limited to loaded case/review identity,
      persistence, synchronous draft storage, controlled scheduling, and state
      notification. The module imports without a DOM or browser globals and
      adds no third-party dependency or package manifest.
- [ ] Note edits synchronously preserve a browser draft and save after 350
      milliseconds without another edit. Verdict changes, Undo, and explicit
      saves flush immediately. Clear verdict retains the note, and unchanged
      values create no Undo entry.
- [ ] Saves are serialized and deduplicated for the same case revision. Public
      flush includes edits made during an in-flight save. An older success or
      failure cannot clear a newer draft or replace its save status.
- [ ] Failed saves retain selection, in-memory reviews, and recoverable drafts.
      Explicit retry can finish the write. A 409 retains the edits and existing
      report-changed guidance without changing the Python review contract.
- [ ] Absolute selection, filter-triggered movement, and relative navigation
      flush before moving. Rapid relative commands each execute in order and
      calculate their destination when execution begins. A final-case
      save-and-advance still saves without changing selection.
- [ ] Undo restores and selects the affected case immediately, invalidates every
      earlier pending navigation command, and saves the restored value. Pending
      saves may finish without moving away, and later navigation still works.
- [ ] Recovery accepts only same-report drafts for known cases with valid verdict
      and string note values. It preserves the existing key and envelope,
      ignores malformed/unknown entries, retries recovered drafts, and leaves
      unrelated and legacy keys untouched.
- [ ] Storage failures preserve edits in memory and the current keep-open and
      unload guidance. Before-unload backup, online retry, and All Runs use
      public commands; All Runs leaves only after successful flush.
- [ ] The page keeps filter matching, keyboard handling, trace rendering, and
      DOM work. Note entry and save-status notifications preserve the note's
      focus, caret, and trace view. Save-blocked movement retains the selected
      case's outside-filter row. Empty reports still load without editing errors.
- [ ] One exact module asset route returns the intended local file with a
      JavaScript content type after trusted-Host validation. Unknown asset paths
      and wrong Hosts are rejected; no directory hosting is introduced.
- [ ] Node's built-in runner deterministically covers every editing-interface
      behavior in the parent testing table using controlled persistence and
      scheduling. Tests assert commands' public outcomes and real draft/payload
      effects, never revisions, internal maps, history, or promise chains.
- [ ] Python HTTP tests cover asset delivery and validation, and the focused
      reviewer server/task checks pass. Existing report, review-file, and safe
      rendering tests remain intact.
- [ ] Retained browser workflows no longer call private save functions or await
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
