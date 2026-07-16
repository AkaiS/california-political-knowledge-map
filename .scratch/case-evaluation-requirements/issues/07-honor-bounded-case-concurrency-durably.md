# Honor bounded case concurrency durably

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Allow operators to run manifested cases concurrently up to the immutable bound recorded in Evaluation Run Configuration while retaining exactly-once, atomic case checkpoint behavior in the SQLite ledger.

## Acceptance criteria

- [ ] Omitted case concurrency executes conservatively with a bound of one.
- [ ] Explicit positive bounds are passed to the shared Pydantic Evals execution path.
- [ ] Observed task concurrency never exceeds the configured bound.
- [ ] Concurrent case completions are serialized through safe ledger transactions.
- [ ] Every terminal case produces exactly one atomic Evaluation Checkpoint with its evaluator evidence.
- [ ] Concurrent execution preserves the same case population, evaluator assignments, failures, observations, and aggregate report semantics as single-case concurrency.

## Blocked by

- [Preserve multi-case progress and retry incomplete runs](06-preserve-multi-case-progress-and-retry-incomplete-runs.md)
