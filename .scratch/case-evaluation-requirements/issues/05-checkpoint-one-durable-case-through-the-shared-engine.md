# Checkpoint one durable case through the shared engine

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Run one manifested Evaluation Case durably through the shared engine and translate its terminal Pydantic lifecycle result into one atomic Evaluation Checkpoint. Persistence belongs to the runner-owned checkpoint sink; task callables and evaluators remain portable evidence producers.

## Acceptance criteria

- [ ] Durable execution consumes the same Resolved Evaluation Plan and shared engine as in-memory execution.
- [ ] Runner-owned Pydantic case lifecycle integration produces the terminal Evaluation Case Result and its Case Evaluator Executions.
- [ ] The case result, evaluator success or failure evidence, observations, issues, and artifact links commit atomically as one checkpoint.
- [ ] Task failure and case-evaluator failure remain separate terminal evidence and are not conflated with orchestration failure.
- [ ] Task callables and case evaluators perform no ledger writes.
- [ ] A persistence failure leaves no partial producer records or observations.
- [ ] The same deterministic one-case plan produces equivalent task output, evaluator applications, failures, observations, and report semantics with no-op and ledger-backed checkpoint sinks.

## Blocked by

- [Atomically create runs from frozen plans](03-atomically-create-runs-from-frozen-plans.md)
- [Execute frozen plans through one shared multi-case engine](04-execute-frozen-plans-through-one-shared-multi-case-engine.md)
