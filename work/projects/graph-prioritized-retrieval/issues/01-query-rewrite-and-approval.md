# 01 — Query Rewrite and approval

Labels: ready-for-agent

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

- [ ] The Query Rewriter's Model Deployment is configured separately from the
      downstream construction deployments.
- [ ] A Query Rewrite contains one nonempty natural-language question and one
      internal `relational` boolean.
- [ ] Rewrite instructions target the form of the 25 verified construction
      questions: explicit entities, relationships, dates or sessions, and
      requested result.
- [ ] The rewrite omits a separate request for reporting, citations, or sources
      because retrieval always returns Grounding Evidence.
- [ ] Question policy and coverage receive only the Query Rewrite.
- [ ] A Declined rewrite stops with an explanation before approval or retrieval.
- [ ] A Deferred rewrite explains the unavailable capability and recoverable
      portion before approval.
- [ ] The user sees the rewritten question but not `relational`.
- [ ] Rejection records the proposed question, internal route, and any user
      correction; rejected text never reaches retrieval.
- [ ] Query Rewriter transport exhaustion records `rewrite_unavailable`, reports
      a temporary network problem, and does not use the original wording as a
      fallback.
- [ ] Scripted-model tests cover accepted, rejected, Declined, Deferred, and
      unavailable rewrite behavior without asserting prompt text.

## Blocked by

None. Can start immediately.
