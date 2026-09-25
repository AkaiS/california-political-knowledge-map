# 03 — Trace retrieval branch outcomes

Labels: completed

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

After a person approves a Query Rewrite, show how full-text, dense, and structural retrieval each ran under the shared deadline. A maintainer can distinguish a successful empty branch, a branch failure, and a structural branch skipped because the question was not relational. Parallel branches have separate spans and actual timing, with no fabricated order.

## Acceptance criteria

- [x] Each enabled retrieval branch has a span beneath approval work with the Chat Session ID, branch name, actual start and end times, result status, and returned candidate count.
- [x] Full-text search records its prepared search terms. Retrieval records index identity and observed state when an existing lookup supplied those facts, without a new audit-only index query.
- [x] A non-relational question emits an explicit skipped structural observation with a reason and zero candidates.
- [x] A failed branch records a stable failure stage and kind with a safe diagnostic. Completed sibling branch results remain inspectable.
- [x] Custom branch attributes exclude embedding vectors, raw branch scores, per-candidate routes, and a copy of every returned candidate.
- [x] ASGI-level tests drive real Chat Session coordination with fake retrievers through concurrent completion, an empty result, a branch failure, a deadline, and a skipped branch. Captured branch results match the typed retrieval outcomes without asserting completion order.

## Blocked by

- [02 — Trace question preparation and approval](02-trace-question-preparation-and-approval.md).

## Comments

2026-09-24: Enabled branches now run in independent
`chat_session.retrieval_branch` spans beneath approval. Each carries
`chat_session_id`, `audit_schema_version=1`, `branch`, `status`, and
`candidate_count`. Native span timestamps measure the concurrent work.
Non-relational retrieval emits an event with the same name and identity,
`branch=structural`, `status=skipped`, `reason=non_relational`, and zero candidates.

Full-text spans record the prepared `search_terms`. The existing full-text and
dense index lookups add `database` and an `indexes` mapping from requested index
names to observed state. A null value means the lookup returned no such index;
absent index attributes mean no lookup supplied an observation. These reads
introduce no additional database calls.

The coordinator and concrete retrievers attach their existing safe diagnostics
as `failure_stage`, `failure_kind`, and `diagnostic`. Unexpected exceptions and
deadline exhaustion retain the coordinator's stable classifications. A custom
retriever that returns only `FailedBranch` records `failure_stage=unavailable`
and `failure_kind=unspecified`, with a fixed explanation that no diagnostic was
provided. The typed retrieval outcomes and browser presentation are unchanged.

The public test seam is `POST /api/chat` through preparation and approval, with
real Chat Session and retrieval coordination, scripted agents, fake retrieval
dependencies, and an offline Logfire exporter. Thirteen ASGI cases cover two
concurrent completion orders, empty success, skipped structural retrieval,
raised and returned failures, each concrete retriever's failure diagnostic,
online, populating, and missing indexes, legislative-session search terms, and
a shared deadline. Captured statuses and counts agree with browser Search
details. Barriers and an injected clock control concurrency and the deadline
without timing sleeps. Tests also verify span parenting and overlap, unchanged
index query counts, and exclusion of candidate IDs, routes, and scores from
custom branch attributes.

Validation: 165 focused tests passed. Changed-file Ruff, formatting, `ty 0.0.83`,
and `git diff --check` passed. The single final `uv run --no-sync pytest -q`
run passed with 1,297 tests, 47 skips, and the existing Pydantic AI sampling
warning. All commands used `uv` with the writable
`/private/tmp/ca-map-uv-cache` cache.
