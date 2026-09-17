# 01 — Query Rewrite and approval

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Build the Query Rewriter as a model-backed component with its own configurable
Model Deployment. It turns the original wording into one natural-language Query
Rewrite shaped like the 25 verified construction cases and returns an internal
`relational` boolean.

The Chat Agent evaluates only the rewrite against question policy and coverage.
It presents only the rewritten question for approval. Rejection records the
proposal, route, and user correction, then permits another rewrite. Transport
exhaustion reports a temporary network failure and never falls back to the
original question.

## Acceptance criteria

- [x] The Query Rewriter's Model Deployment is configured separately from the
      downstream construction deployments.
- [x] A Query Rewrite contains one nonempty natural-language question and one
      internal `relational` boolean.
- [x] Rewrite instructions target the form of the 25 verified construction
      questions: explicit entities, relationships, dates or sessions, and
      requested result.
- [x] The rewrite omits a separate request for reporting, citations, or sources
      because retrieval always returns Grounding Evidence.
- [x] Question policy and coverage receive only the Query Rewrite.
- [x] A Declined rewrite stops with an explanation before approval or retrieval.
- [x] A Deferred rewrite explains the unavailable capability and recoverable
      portion before approval.
- [x] The user sees the rewritten question but not `relational`.
- [x] Rejection records the proposed question, internal route, and any user
      correction; rejected text never reaches retrieval.
- [x] Query Rewriter transport exhaustion records `rewrite_unavailable`, reports
      a temporary network problem, and does not use the original wording as a
      fallback.
- [x] Scripted-model tests cover accepted, rejected, Declined, Deferred, and
      unavailable rewrite behavior without asserting prompt text.

## Blocked by

None. Can start immediately.

## Comments

2026-09-17: Implemented the question-preparation boundary in
`core/question_preparation.py` and its public values in
`schemas/query_preparation.py`. `prepare()` sends only the rewrite to the Chat
Agent's injected policy/coverage assessor. `approve()` releases the sole
retrieval input; `reject()` retains and logs feedback for another proposal.
Approval presentation excludes routing metadata and retains Deferred limits.
Connection failures and exhausted transient provider responses produce
`rewrite_unavailable`, with no approval or original-question fallback.

The Query Rewriter has independent deployment, model, and optional local
endpoint settings. It uses the existing agent factory and transport handling.
Its instructions preserve named entities, relationships, scope, dates, and
sessions using construction-case examples, and omit redundant evidence
requests while preserving source-discovery intent. See
[question preparation](../../../../docs/query-preparation.md) and
[Model Deployments](../../../../docs/model-deployments.md) for use and settings.

Validation used the confirmed public seams. The new preparation and deployment
tests passed 16 cases; the focused run including deployment documentation,
chat configuration, and observability passed 41. The full deterministic suite,
`uv run --no-sync pytest -q`, passed 956 tests with two existing provider
warnings. `ty check` and `ruff check` passed for the changed source and tests.
The type checker was run through `uv` from a temporary tool environment.

Scripted `FunctionModel` responses cover accepted, rejected, Declined, Deferred,
and unavailable outcomes without prompt-text assertions. They establish the
interaction contract, not a real model's rewriting quality. Retrieval invocation
and the Chat Agent's complete conversation remain issue 09's integration work.
