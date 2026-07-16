# Preserve multi-case progress and retry incomplete runs

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Extend durable shared-engine execution across the complete manifested population so every terminal case survives failures that occur later in the same attempt. Preserve the Evaluation Run as an immutable execution attempt and require a distinct linked retry whenever any manifested case lacks a terminal checkpoint.

## Acceptance criteria

- [ ] Each terminal case is checkpointed as it finishes rather than accumulated in memory until the case phase ends.
- [ ] Cancellation, task failure, evaluator failure, orchestration failure, or process interruption does not erase earlier terminal case checkpoints.
- [ ] Pending or otherwise non-terminal manifested cases remain visibly distinct from completed and failed cases.
- [ ] Missing case work is never resumed or replayed into the original Evaluation Run.
- [ ] A retry creates a distinct Evaluation Run linked through the existing retry relationship and freezes its own plan and manifest.
- [ ] Task failures, evaluator failures, missing work, and orchestration failures remain separately queryable.
- [ ] Durable multi-case behavior is covered through the highest-level runner and a temporary real SQLite evaluation ledger.

## Blocked by

- [Checkpoint one durable case through the shared engine](05-checkpoint-one-durable-case-through-the-shared-engine.md)
