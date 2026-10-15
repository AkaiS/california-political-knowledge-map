# Ticket 04 independent review

Reviewed on 2026-10-09 UTC against fixed point
`487712edcdf7f6ae92748f4279be12143d7ab907` with
`git diff 487712edcdf7f6ae92748f4279be12143d7ab907...HEAD`.
The implementation commit was `65d70ffe6361e597a76308ee114a7f8e9b17f801`.
Separate parallel Standards and Spec reviewers used the repository's code-review
skill. Neither reviewer authored the implementation.

The review read AGENTS.md, GLOSSARY.md, the tracker and domain conventions,
ADRs 0017, 0022, and 0023, the parent PRD, ticket 04, the implementation diff,
and the full [implementation validation](ticket-04.md).

## Standards

No documented-standard violations were found.

One judgment call was reported: possible Duplicated Code in `web.py`.
`update_guide` repeated `submit_question`'s JSON content-type gate and shutdown
guard. Both routes used the same "Expected Content-Type: application/json" and
"The local service is stopping." errors, leaving those shared rules open to
drift. Accepted and fixed by extracting `json_content_type_error(request)` and
`stopping_service_error()`. Route-specific body validation and errors remain
explicit. The order remains content type, awaited body validation, shutdown
check, then execution scheduling. The reviewer confirmed the finding resolved
and found no remaining Standards issue in the correction.

The new tests use HTTP/ASGI, temporary real SQLite, the real Chat Session,
deterministic model/retrieval dependencies, and explicit events. The public
store completion operation is the approved supplemental seam; its effects are
observed through HTTP. No private task registry or SQL assertions and no
independent Chat Session feature-testing seam were introduced. Prompt resources,
historical evaluations, and shared retrieval contracts are unchanged.

## Spec

Zero Spec findings were reported. Stable identity, retained reading and
retrieval dates, successful empty replacement, independent edited questions,
and retired-completion rejection match the requirements. Conflicting updates
admit one running attempt and return HTTP 409 for a second request; another
explicit update succeeds after completion. This implements serialization without
adding a queue. No scope creep was found.

The independent Spec reviewer ran the update, execution, and web tests,
46 passed, then repeated them after the correction with the same result.
The reviewer also confirmed the final ticket state, frontier, and review
record, with zero Spec findings. Existing browser evidence covers Update guide, Edit question, and
visible attempt timing. Cancel remains ticket 05. Startup reconciliation and
Retry, including shutdown before coroutine entry, remain ticket 06.

## Acceptance and verification

All six ticket 04 acceptance criteria are checked, supported by the implementation
validation's criterion-to-test mapping. The review inspected all three saved
browser images and the recorded controlled interaction. They show readable
saved content during Running and Failed updates, separate retrieval and latest
attempt times, and an edited question beside its independent original guide.
The admission-check correction preserves behavior and changes no reader
interaction, so browser verification was not repeated.

The ticket has exactly one triage-state label, `completed`. The parent project
remains `ready-for-agent`. The authoritative work README now lists tickets
01 through 04 as completed and tickets 05 through 09 as takeable.

All commands used uv with `UV_CACHE_DIR=/tmp/source-guides-uv`. Type tooling
also used `UV_TOOL_DIR=/tmp/source-guides-tools` and cached offline execution.

- Focused update, web, execution, lifecycle, and correction tests: 48 passed
  after the correction.
- `uv run --no-sync pytest -q tests`: 1514 passed, 61 skipped, one existing
  OpenRouter reasoning/temperature warning, 50.06 seconds. Existing local HTTP
  tests ran with approved loopback permission.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`: 29 passed.
- `uv tool run --offline --from ty ty check src/knowledge_map/web.py src/knowledge_map/adapters/source_guides.py src/knowledge_map/schemas/source_guides.py`: passed.
- `uv run --no-sync ruff check` over changed Python modules and the new tests: passed.
- `uv run --no-sync node --check src/knowledge_map/resources/source-guides/guide.js`: passed.
- `git diff --check`: passed.

Summary: Standards reported zero hard violations and one maintenance finding,
now fixed. Spec reported zero findings. No valid finding or input question
remains unresolved.
