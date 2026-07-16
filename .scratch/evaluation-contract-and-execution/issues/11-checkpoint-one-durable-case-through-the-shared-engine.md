# Checkpoint one durable case through the shared engine

Labels: ready-for-agent

## Parent

[Evaluation Contract and Resumable Execution](../PRD.md)

## What to build

Run one manifested Evaluation Case durably through the shared engine and translate its terminal Pydantic lifecycle result into one atomic Evaluation Checkpoint. Persistence belongs to the runner-owned checkpoint sink; task callables and evaluators remain portable evidence producers.

## Acceptance criteria

- [ ] Durable execution consumes the same Resolved Evaluation Plan and shared engine as in-memory execution.
- [ ] Runner-owned Pydantic case lifecycle integration produces the terminal Evaluation Case Result and a completed, failed, or explicitly skipped Case Evaluator Execution for every planned application.
- [ ] The case result, evaluator success, failure, or skip evidence, observations, issues, and artifact links commit atomically as one checkpoint.
- [ ] Task failure and case-evaluator failure remain separate terminal evidence and are not conflated with orchestration failure.
- [ ] Task callables and case evaluators perform no ledger writes.
- [ ] A persistence failure leaves no partial producer records or observations.
- [ ] The same deterministic one-case plan produces equivalent task output, evaluator applications, skips, failures, observations, and report semantics with no-op and ledger-backed checkpoint sinks.

## Blocked by

- [Persist a complete run through a decomposed Evaluation Ledger](01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md)
- [Query Metric Observations through producer ownership](05-query-metric-observations-through-producer-ownership.md)
- [Atomically create runs from frozen plans](09-atomically-create-runs-from-frozen-plans.md)
- [Execute frozen plans through one shared multi-case engine](10-execute-frozen-plans-through-one-shared-multi-case-engine.md)
