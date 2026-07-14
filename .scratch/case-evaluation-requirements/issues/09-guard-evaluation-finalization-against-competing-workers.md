# Guard Evaluation Finalization against competing workers

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Protect explicit Evaluation Finalization with a lease or compare-and-set claim so only one worker can perform missing report evaluator work for a run at a time. Make ownership, expiry, release, and recovery visible and deterministic without changing already checkpointed report evidence.

## Acceptance criteria

- [ ] A finalizer must atomically acquire the run's finalization claim before executing missing report evaluators.
- [ ] A competing worker cannot acquire a live claim or produce duplicate Report Evaluator Executions.
- [ ] Claim ownership and expiry are represented explicitly enough to diagnose who may finalize and when recovery is allowed.
- [ ] Successful completion and controlled failure have clear claim release behavior.
- [ ] An expired claim can be safely recovered without rerunning terminal successful or failed report evaluator executions.
- [ ] Concurrency tests demonstrate one active worker, no duplicate executions under competing claims, and safe expired-claim recovery.

## Blocked by

- [Freeze the aggregate report and resume missing report work](08-freeze-the-aggregate-report-and-resume-missing-report-work.md)
