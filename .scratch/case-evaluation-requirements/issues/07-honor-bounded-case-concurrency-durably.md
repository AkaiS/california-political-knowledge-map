# Honor bounded case concurrency durably

Status: completed
Labels: completed

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Allow operators to run manifested cases concurrently up to the immutable bound recorded in Evaluation Run Configuration while retaining exactly-once, atomic case checkpoint behavior in the SQLite ledger.

## Acceptance criteria

- [x] Omitted case concurrency executes conservatively with a bound of one.
- [x] Explicit positive bounds are passed to the shared Pydantic Evals execution path.
- [x] Observed task concurrency never exceeds the configured bound.
- [x] Concurrent case completions are serialized through safe ledger transactions.
- [x] Every terminal case produces exactly one atomic Evaluation Checkpoint with its evaluator evidence.
- [x] Concurrent execution preserves the same case population, evaluator assignments, failures, observations, and aggregate report semantics as single-case concurrency.

## Blocked by

- [Preserve multi-case progress and retry incomplete runs](06-preserve-multi-case-progress-and-retry-incomplete-runs.md)
