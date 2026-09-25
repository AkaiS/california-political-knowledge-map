# 02 — Trace question preparation and approval

Labels: completed

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Let a maintainer follow one original question through successive Query Rewrite Proposals, question-policy and coverage assessments, a person's correction, and the approved Query Rewrite in Logfire. The observations remain joined to the Chat Session across separate browser requests. A Declined question or unavailable rewrite leaves its observed preparation stages without an invented closing outcome.

## Acceptance criteria

- [x] Each Query Rewrite Proposal records its text, relational route, result status, and one-based attempt number within the Chat Session. Other stages do not receive proposal attempt numbers as their own sequence.
- [x] Each question assessment records its result and refers to the proposal it assessed, including Declined and Deferred explanations when present.
- [x] A correction and an approval each refer to the applicable proposal. The approved wording is explicit, and retrieval continues to use only that approved Query Rewrite.
- [x] Preparation, correction, and approval operations have separate bounded spans with the same Chat Session ID. Model calls appear beneath the application operation that invoked them; no span covers the person's waiting time.
- [x] Returned unavailability and safe failure kinds are recorded even when no exception escapes. Custom attributes do not duplicate model content, retries, or token details; Pydantic AI content capture is disabled.
- [x] ASGI-level tests exercise an initial proposal, correction, second proposal, approval, Declined assessment, unavailable rewrite, and abandoned approval. Captured spans agree with browser outcomes without relying on a live Logfire project or a particular exporter schedule.

## Blocked by

- [01 — Start a searchable Chat Session trail](01-start-a-searchable-chat-session-trail.md).

## Comments

2026-09-24: Implemented proposal and assessment stage spans beneath bounded
`chat_session.prepare` and `chat_session.correct` operations. The correction
operation records `chat_session.rewrite_corrected` before preparing the next
proposal. `chat_session.approve` records `chat_session.rewrite_approved` with
the approved wording before retrieval. Every observation carries
`chat_session_id` and `audit_schema_version=1`.

`chat_session.query_rewrite` records `question`, `relational`, `status`, and
`proposal_attempt`. Assessment, correction, and approval refer to that proposal
attempt; operation spans have no attempt sequence. Successful assessment spans
retain the allowed, Declined, or Deferred result and any explanation and
recoverable portion. An unavailable rewrite records `status=unavailable`,
`failure_kind=transport`, and the safe browser explanation. Failed proposal or
assessment stages record `status=failed` and a fixed failure kind (`transport`,
`provider`, `model_output`, or `unexpected`) without copying exception messages
into application attributes.

The tests use `POST /api/chat` with real Chat Session coordination and retrieval,
scripted Pydantic AI models or HTTP responses, and a fake Neo4j driver. An
in-process Logfire TestExporter captures observations synchronously with the
production scrubber. Tests verify that the second approved wording reaches the
embedding request, stale approvals are refused, model spans nest beneath their
application stages, and separate request traces share the Chat Session ID.
Declined, unavailable, failed, and abandoned requests retain only their observed
stages. The later PR review narrowed the scrubber exception to the generated
Chat Session ID, so legislative-session wording may be redacted in audit fields.

Validation: 115 focused chat and preparation tests and 13 agent observability
tests passed. Changed-file Ruff, formatting, `ty 0.0.83`, and `git diff --check`
passed. The single final `uv run --no-sync pytest -q` run passed with 1,284
tests, 47 skips, and the existing Pydantic AI sampling warning. All `uv` commands
used the writable `/tmp/codex-uv-cache` cache. No live Logfire, model, Neo4j, or
browser check was needed.
