# Evaluation Case review editing

Labels: completed

## Problem statement

Reviewing an Evaluation Case combines note entry, verdict changes, local draft
recovery, file saves, navigation, and Undo. Their ordering rules currently live
among the page's rendering and event handlers. Recent changes separately fixed
stale save status, navigation during a save, and Undo while navigation was
pending. Another change to one handler can break a rule owned by several others.

The browser workflow tests cover these failures, but normal CI skips those tests.
Maintainers need a way to verify edit durability and ordering without a browser,
a model service, or a live Evaluation Run.

## Solution

Put Evaluation Case review editing behind one dependency-free JavaScript
interface. The module owns review values, local drafts, save ordering, selection,
and Undo. The page renders observable state and translates user actions into
commands. Deterministic tests drive that same interface with controlled save
completion, draft storage, and timers, and run on every pull request.

This preserves the current reviewer workflow and its JSON files. Reviewers keep
the same controls, shortcuts, recovery behavior, and trace presentation.

## User stories

1. As a reviewer, I want to mark an Evaluation Case Pass, Fail, or Defer, so that
   my judgement remains attached to the case I read.
2. As a reviewer, I want to clear a verdict without clearing my note, so that I
   can reconsider a judgement without losing its explanation.
3. As a reviewer, I want notes to save after 350 milliseconds without another
   edit, so that writing does not require a manual save for each keystroke.
4. As a reviewer, I want verdict changes and explicit saves to start saving
   immediately, so that those actions do not wait for the note timer.
5. As a reviewer, I want each edit backed up synchronously in this browser, so
   that reloading before a file save completes retains my work.
6. As a reviewer, I want to recover valid drafts for the same report, so that I
   can continue reviewing after an interrupted save.
7. As a reviewer, I want another report's drafts to remain separate, so that
   replacing a report or changing report directories cannot overwrite its reviews.
8. As a reviewer, I want older saves to leave newer edits and their status alone,
   so that the page never calls an unsaved edit saved.
9. As a reviewer, I want edits made during a save included before navigation
   completes, so that I do not leave a case with its latest note unsaved.
10. As a reviewer, I want failed saves to retain my selection and drafts, so that
    I can retry without reconstructing my work.
11. As a reviewer, I want a changed report to reject old-page saves while keeping
    my edits recoverable, so that my review cannot attach to different content.
12. As a reviewer, I want a browser storage failure to tell me to keep the page
    open until the review file saves, so that I understand when a reload risks
    losing an edit.
13. As a reviewer, I want repeated navigation actions to run in order, so that
    two presses of Next advance twice after the pending save completes.
14. As a reviewer, I want filter changes and case selection to save before
    moving, so that filtering does not bypass save protection.
15. As a reviewer, I want the selected case to remain visible outside the filter
    while a save blocks navigation, so that I can inspect and retry its edit.
16. As a reviewer, I want Undo to restore the last changed verdict or note and
    select its Evaluation Case, so that I can see what was restored.
17. As a reviewer, I want Undo to cancel navigation requested before it, so that
    a delayed save cannot move away from the restored case.
18. As a reviewer, I want an unchanged review to create no Undo entry, so that
    Undo continues to mean the last annotation change.
19. As a reviewer, I want All Runs to wait for a successful save, so that leaving
    the reviewer follows the same durability rule as changing cases.
20. As a reviewer, I want save status updates to preserve my note's focus and
    caret, so that typing can continue while a file write completes.
21. As a reviewer, I want the current shortcuts and trace views preserved, so
    that this maintenance change does not require learning a new workflow.
22. As a maintainer, I want deterministic checks for delayed saves, failures,
    recovery, and Undo on every pull request, so that ordering regressions fail CI.
23. As a maintainer, I want tests to use the page's editing interface and HTTP
    routes, so that internal revisions and promise chains can change safely.

## Implementation decisions

- Introduce one DOM-free JavaScript module for Evaluation Case review editing.
  Use native ES modules and Node's built-in test runner. Add no npm dependency,
  package manifest, bundler, UI framework, or general state-machine framework.
- Construct the module with the ordered known case names, loaded reviews, run
  ID, report identity, and small injected collaborators for review persistence,
  synchronous draft storage, and cancellable scheduling. Keep fetch and browser
  APIs in the page adapter. No new domain term or architectural decision record
  is needed for this extraction.
- Expose commands for note edits, verdict changes, absolute case selection,
  relative navigation, Undo, save/retry, and preparing for unload. Expose copied
  or read-only observable state and change notification for the page. The state
  includes selected case, current review values, visible save status, pending
  draft count, Undo availability, and whether an unload warning is needed.
  Do not expose mutable drafts, revision counters, Undo history, deduplication
  maps, navigation generations, or promise chains.
- Note edits and verdict changes target the selected case. A no-op review change
  creates no history entry. Clear verdict keeps the note. Undo restores the
  prior value, selects that case immediately, invalidates earlier queued
  navigation, and saves the restored value through the same save mechanism.
- The module owns the 350-millisecond note debounce and cancels it when a flush
  begins. Verdict changes, explicit saves, and Undo request an immediate flush.
  Each edit writes its local draft before returning control to the caller.
- A flush reports success only after all drafts, including edits made while a
  save is pending, have been saved. Writes are serialized. Concurrent requests
  to save the same case revision reuse one write. A stale completion cannot
  clear a newer draft or replace its current status, whether the old write
  succeeds or fails. A failed flush returns failure and keeps retryable edits.
- The page provides current filter membership when a relative navigation action
  begins execution. The module calculates the destination against the then
  current selection and processes every navigation action in request order.
  Absolute selection retains its requested destination. Both flush before
  changing selection, including a save-and-advance at the final case. Undo
  invalidates navigation queued before it without cancelling required saves.
- Keep search, cohort and verdict filter matching in the page. A filter-triggered
  selection uses the same save-before-move command. If it cannot move, the page
  retains the selected case's existing outside-filter row.
- Keep the current draft key based on run ID and report identity, and retain the
  current stored envelope containing report identity and reviews. Recover only
  matching-report drafts for known cases with an accepted verdict and string
  note. Unknown cases and malformed entries are ignored. Unrelated and legacy
  storage keys remain untouched. Recovered drafts are retried on initial load.
- Preserve report identity and the Python JSON review request and response
  contract. A 409 is a report-changed failure, retains edits, and asks the
  reviewer to reload. Other write failures retain per-case failure guidance and
  retry. Storage failures retain edits in memory and preserve keep-open and
  unload guidance until the review file is saved.
- All Runs leaves only after a successful public flush. The online event retries
  through that command. Before unload invokes the synchronous draft-storage
  command and uses its public warning result.
- DOM updates for typing and save status must not replace the note value or
  rebuild trace content. Selection and Undo can redraw the selected case. Keep
  keyboard interpretation, trace rendering, Markdown presentation, and focus
  handling in the page.
- Serve the module through one exact asset route with a JavaScript content type
  and the review server's existing trusted-Host check. Load only the intended
  local asset. Do not add generic directory hosting or change existing routes'
  validation and cache behavior.
- Add an explicit supported Node runtime and test command to normal CI alongside
  deterministic pytest. Use Node 22, matching the available local runtime. Python
  commands continue to use uv. Browser workflow tests remain opt-in.
- Preserve ADR 0017. Committed reports and review files remain the evaluation
  artifacts; there is no ledger, new database, remote run identity, or report
  migration.

## Testing decisions

The primary seam is the editing interface used by the real page. Tests issue
reviewer commands and observe public state, returned completion results, draft
storage writes, and persisted review payloads. They never inspect internal
revisions, queues, timers, history arrays, or maps. Controlled persistence
promises and a controlled scheduler make interleavings explicit without sleeps.

| Observable behavior | Required deterministic evidence |
| --- | --- |
| Notes, verdicts, and Undo | Defaults, immediate draft storage, 350-millisecond debounce, immediate verdict save, clear-verdict preservation, no-op history, and Undo across cases |
| Save ordering | One write at a time; repeated flushes deduplicate a revision; edits during a write are included before flush succeeds |
| Stale completion | Older success and failure cannot erase a newer draft or replace its current save status |
| Failed writes | Failed flush retains selection and edits; retry saves them; report-changed failure retains recovery data and reload guidance |
| Navigation | Rapid relative actions each advance; destination uses selection and filters at execution; failed saves prevent movement; final-case advance still flushes |
| Undo during navigation | Undo restores and selects its case immediately; completing the earlier save cannot execute old navigation; later navigation works |
| Recovery | Same-report known valid drafts recover and retry; malformed and unknown entries do not; other report and legacy keys survive |
| Storage failure | Read/write failure does not lose in-memory edits; public keep-open and unload guidance reflects unsaved edits |
| Leaving the page | Public flush stays pending for edits made during save and reports failure rather than authorizing departure |
| Module delivery | Real HTTP request returns the intended asset with JavaScript content type; wrong Host and unregistered asset paths are rejected |

Existing Python review-server tests are the prior art for report identity,
request validation, concurrent file writes, atomic replacement, and safe
presentation. Keep them and extend their HTTP seam for asset delivery. The
opt-in browser workflows are prior art for user action ordering, focus,
filtering, and trace rendering. Preserve them, replacing their private save and
navigation waits with observable UI waits where extraction removes globals.

Verify the module with Node's built-in runner and run focused reviewer pytest
checks plus the full deterministic suite. Do not launch a browser or run browser
automation for this project. Record browser tests as retained but not executed;
deterministic module checks do not establish visual or caret behavior by
themselves. Review the page adapter changes for those preserved behaviors.

## Out of scope

- New reviewer controls, shortcuts, filters, review values, or visual redesign.
- Changes to review-file schema, report identity, server persistence semantics,
  Evaluation Data Sets, Evaluation Runs, prompts, Model Deployments, or telemetry.
- A second module for the Python review store or browser Chat Session lifecycle.
- Cross-tab coordination, collaborative review, authentication, draft expiry,
  background workers, automatic report migration, or new retry policies.
- Browser installation or browser verification, and a general JavaScript build
  system.

## Further notes

The architecture investigation selected this work after reviewing 55 recent
commits at baseline `5db95fd`. The relevant fixes are `2c127e3`, which tied save
status to the current edit; `73c4e0e`, which bound drafts to report identity and
ordered navigation; and `d34960f`, which made Undo invalidate pending navigation.
Their behavior is part of the acceptance contract, not a request to redesign it.

The user delegated selection, specification, ticket sizing, implementation, and
review. The chosen seams and two-ticket breakdown therefore use that existing
authorization rather than introducing another approval checkpoint.

1. [Concentrate Evaluation Case review editing](issues/01-concentrate-review-editing.md)
   integrates the module, delivery route, page adapter, and deterministic checks.
2. [Run review editing checks on every pull request](issues/02-enforce-review-editing-checks.md)
   adds CI enforcement and documents verification after issue 01 is complete.

## Comments

2026-10-02: Both tickets are complete. Ticket 01 concentrated review editing
behind the public module and deterministic tests, and its independent Standards
and Spec reviews resolved the navigation-rule duplication. Ticket 02 added
required Node 22 checks to normal pull-request CI and documented module ownership,
local commands, and the limits of deterministic verification. Its independent
Standards and Spec reviews found no issues. Each ticket records its verification
evidence. The parent label and work index now reflect the completed project.

Browser workflows were retained and not executed. Local passing checks do not
establish browser focus, caret, or visual behavior. The conductor will record
actual pull-request CI evidence after the final sequence review and PR creation;
no remote CI result is claimed here.
