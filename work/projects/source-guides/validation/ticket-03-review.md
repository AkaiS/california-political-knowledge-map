# Ticket 03 independent review

Reviewed on 2026-10-09 UTC against fixed point
`f66eccff180123c4d563e1af5782a16a9d0c5e2a` with
`git diff f66eccff180123c4d563e1af5782a16a9d0c5e2a...HEAD`.
The implementation commit was `bf33bdb1ab0c6b4e209c53cad8a29b7a67673203`.
Separate parallel reviewers examined Standards and Spec using the repository's
code-review skill. Neither reviewer authored the implementation.

The review read AGENTS.md, GLOSSARY.md, the tracker and domain conventions,
ADRs 0017, 0022, and 0023, the parent PRD, ticket 03, its implementation diff,
and [implementation validation](ticket-03.md).

## Standards

No documented-standard violations were found. The execution tests use
HTTP/ASGI, temporary real SQLite, the real Chat Session, deterministic injected
model and retrieval activity, and explicit events. They assert saved outcomes
rather than private task containers or SQL layouts. The public store completion
seam matches the approved supplementary validation plan. Existing test migrations
update the submission contract without adding another feature-testing seam.

Shared retrieval remains consistent with ADR 0023. Prompt resources and
historical evaluation records remain consistent with ADRs 0022 and 0017.

One judgment call was reported: possible Duplicated Code in `guide.js`.
`refreshGuides` and `openSelectedGuide` repeated the same detail fetch,
non-success rejection, and JSON decoding. Accepted and fixed by extracting
`readSavedGuide(identity)`. Each caller retains its selection-generation check,
display behavior, and error message. The reviewer confirmed the fix.

The widespread test migrations follow the PRD's change-coordination rule and
were not classified as Shotgun Surgery. The pending ticket label, checkboxes,
and frontier were expected review reconciliation rather than implementation
defects. They are now reconciled.

## Spec

No ticket 03 spec findings were reported. Submission returns a saved identity
promptly. Application-owned tasks survive browser disconnects. List and detail
reads restore status without replay. Completion checks the guide's active
running attempt in the same transaction as content and retrieval-time publication.
Independent searches retain the existing model and retrieval dependencies.
No scope creep was identified. Update, Cancel, Retry, and startup recovery remain
in their assigned tickets.

One additional candidate was reproduced through HTTP/ASGI and real SQLite:
shutdown immediately after acceptance can cancel a task before its coroutine
starts, leaving its persisted attempt running. This is outside ticket 03's
acceptance boundary. Ticket 03 explicitly assigns restart recovery and Retry to
ticket 06, and the PRD assigns unfinished-attempt reconciliation to startup.
The task is still stopped and joined before dependencies close. The existing
shutdown test establishes interruption after model entry, not every shutdown
schedule. Ticket 06 must reconcile all unfinished attempts; this review does
not claim startup recovery is already implemented.

## Acceptance and verification

All six ticket 03 acceptance criteria are checked, supported by the implementation
validation's criterion-to-test mapping and controlled browser evidence. The
ticket has exactly one triage-state label, `completed`. The parent project stays
`ready-for-agent`; tickets 04 and 06 join tickets 07, 08, and 09 on the frontier.
Ticket 05 remains blocked by 04.

The browser evidence was inspected rather than repeated. The review fix changes
only shared detail-request handling and preserves URLs, rendering, polling, and
generation guards. JavaScript syntax validation passed after that refactor.
No new browser behavior or separate Chat Session test seam was introduced.

All implementation checks used uv with `UV_CACHE_DIR=/tmp/source-guides-uv`.
The type check also used `UV_TOOL_DIR=/tmp/source-guides-tools` and cached offline
execution. Final deterministic suites were run once after the review fix.

- Focused web, execution, lifecycle, and correction checks: 43 passed before
  the JavaScript refactor. The independent Spec reviewer also ran the execution
  and lifecycle subset, 6 passed.
- `uv run --no-sync node --check src/knowledge_map/resources/source-guides/guide.js`:
  passed after the refactor.
- `uv run --no-sync pytest -q tests`: 1509 passed, 61 skipped, one existing
  OpenRouter reasoning/temperature warning, 46.53 seconds. Existing loopback
  HTTP tests ran with approved permission.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`:
  29 passed.
- `uv tool run --offline --from ty ty check src/knowledge_map/web.py src/knowledge_map/adapters/source_guides.py src/knowledge_map/schemas/source_guides.py`:
  passed.
- `uv run --no-sync ruff check` across all changed Python modules and tests:
  passed.
- `git diff --check`: passed.

Summary: Standards reported one maintenance finding, now fixed, and no hard
violations. Spec reported zero findings. No valid finding or input question
remains unresolved.
