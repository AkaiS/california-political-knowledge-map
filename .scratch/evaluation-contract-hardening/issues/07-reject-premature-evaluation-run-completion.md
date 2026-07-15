# Reject premature Evaluation Run completion

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Make Evaluation Run completion a guarded ledger transition rather than an unconditional status update. Evaluation Finalization may request completion, but the ledger authorizes it transactionally only when the frozen Resolved Evaluation Plan, manifested cases, case-evaluator assignments, aggregate report artifact, and report-evaluator assignments all have the required terminal evidence.

Terminal task or evaluator failures count as completed workflow evidence. Missing metrics, quality failures, and failed release gates remain independently reported outcomes and do not prevent workflow completion.

## Acceptance criteria

- [ ] No public ledger operation can unconditionally mark an Evaluation Run complete.
- [ ] Completion is rejected while any manifested case lacks a terminal task outcome or any planned Case Evaluator application lacks terminal execution evidence.
- [ ] Completion is rejected until the exact aggregate report artifact is frozen and atomically linked to the run.
- [ ] Completion is rejected while any report evaluator expected by the frozen Suite and Resolved Evaluation Plan lacks terminal execution evidence.
- [ ] Successful and failed task or evaluator executions both satisfy terminal-evidence accounting.
- [ ] Missing metrics, quality issues, and release-gate failures remain visible but do not block a fully accounted workflow from completing.
- [ ] The invariant check and status transition execute in one transaction and remain safe under repeated finalization requests.
- [ ] Temporary-ledger lifecycle tests cover pending cases, missing case evaluators, missing reports, missing report evaluators, terminal failures, gate failures, and successful idempotent completion.

## Blocked by

- [Persist a complete run through a decomposed Evaluation Ledger](01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md)
- [Freeze the aggregate report and resume missing report work](../../case-evaluation-requirements/issues/08-freeze-the-aggregate-report-and-resume-missing-report-work.md)
