# Query Metric Observations through producer ownership

Status: completed
Labels: completed

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Make the evaluator execution that produced an Evaluation Metric Observation its sole relational owner. A Case Metric Observation derives its Evaluation Case Result and Evaluation Run through its Case Evaluator Execution; a Run Metric Observation derives its Evaluation Run through its Report Evaluator Execution. Preserve separate case- and run-observation tables so subject type remains structurally explicit.

Expose indexed query paths that retrieve case observations, run observations, and comparable metrics across runs through those producer relationships without storing a second independently writable subject identifier.

## Acceptance criteria

- [x] A Case Metric Observation references one Case Evaluator Execution and stores no independently writable Case Result or Run owner.
- [x] A Run Metric Observation references one Report Evaluator Execution and stores no independently writable Evaluation Run owner.
- [x] Separate case- and run-observation tables continue to enforce observation subject type.
- [x] Observation writes cannot attribute a producer's metric to a different case or run.
- [x] Case-result, run-level, and cross-run metric queries traverse indexed producer relationships and return the same complete evidence expected by callers.
- [x] Observation metric identities resolve to canonical Evaluation Metric Definition records.
- [x] Temporary-ledger tests prove exact producer attribution and cross-case or cross-run misattribution is unrepresentable.

## Blocked by

- [Persist a complete run through a decomposed Evaluation Ledger](01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md)
- [Canonicalize Metric Definitions across Suites](04-canonicalize-metric-definitions-across-suites.md)
