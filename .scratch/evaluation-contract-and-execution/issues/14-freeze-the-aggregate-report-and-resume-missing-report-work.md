# Freeze the aggregate report and resume missing report work

Labels: ready-for-agent

## Parent

[Evaluation Contract and Resumable Execution](../PRD.md)

## What to build

After every manifested case has terminal evidence, freeze the exact aggregate Pydantic Evaluation Report as the immutable input to an explicit Evaluation Finalization operation. Finalization is addressed only by Run identity. It loads the frozen Resolved Evaluation Plan, uses its Suite identity, revision, and content hash to retrieve and verify the exact imported Suite from the Evaluation Ledger, resumes only missing report evaluator work, and requests completion only when all expected report evidence is accounted for. A caller-provided Suite object is never authoritative.

## Acceptance criteria

- [ ] A run with any non-terminal manifested case cannot freeze its aggregate report or begin Evaluation Finalization.
- [ ] The complete aggregate Pydantic Evaluation Report is canonically serialized exactly once after all cases become terminal.
- [ ] Report bytes are registered as a content-addressed Evaluation Artifact outside relational rows, with stable identity, metadata, and a resolvable location.
- [ ] Linking the report artifact and moving the run to an explicit finalization-pending state is atomic.
- [ ] Evaluation Finalization is explicitly invoked by run identity and loads the frozen report artifact as its authoritative input.
- [ ] Finalization loads the Resolved Evaluation Plan and retrieves the exact imported Suite by identity and revision through the Evaluation Ledger, rejecting any content-hash mismatch.
- [ ] The finalization API does not accept a caller-provided Evaluation Suite as an authoritative execution input.
- [ ] Expected report evaluators are determined from the ledger-loaded exact Suite revision and Resolved Evaluation Plan rather than mutable authored state.
- [ ] Missing report evaluators execute through the shared engine's report phase against the frozen aggregate report.
- [ ] Only report evaluators lacking terminal execution evidence run; both successful and failed executions are skipped on later invocations.
- [ ] Each new Report Evaluator Execution, its observations, issues, and artifact links commit atomically as it reaches terminal success or failure.
- [ ] Report evaluator failure remains terminal negative evidence and is distinguishable from missing work.
- [ ] Repeated finalization is idempotent and requests guarded completion only after every expected report evaluator has terminal evidence.
- [ ] Finalization is never resumed by an implicit background worker.

## Blocked by

- [Persist a complete run through a decomposed Evaluation Ledger](01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md)
- [Query Metric Observations through producer ownership](05-query-metric-observations-through-producer-ownership.md)
- [Preserve multi-case progress and retry incomplete runs](12-preserve-multi-case-progress-and-retry-incomplete-runs.md)
