# Propagate Configured Case Evaluator Identity into All ReportCase Evidence

Labels: ready-for-agent

## What to build

Make the Configured Evaluator's revision and configuration fingerprint the authoritative behavioral identity attached to every Pydantic Evals result or failure produced by a case evaluator. Expose the deterministic evaluator-version tag to Pydantic Evals before evaluator execution so the framework propagates it uniformly to scalar results, every result emitted by a mapping-valued evaluator, evaluator failures, and evaluation telemetry.

Stop relying on post-execution result-name matching to infer the producing Configured Evaluator. A scalar result may share its evaluator's name, while mapping-valued results use their individual output names; both forms must retain the same configured evaluator version without special-case reconstruction. Preserve that version through checkpoint persistence, typed ReportCase materialization, and frozen aggregate-report materialization.

This ticket covers case evaluators and their ReportCase evidence. It does not expand the Report Evaluator Execution contract or introduce a separately managed evaluator-version source.

## Acceptance criteria

- [ ] Each resolved case evaluator exposes an evaluator-version tag deterministically derived from its Configured Evaluator revision and configuration fingerprint before Pydantic Evals executes it.
- [ ] The configured identity remains authoritative even when the resolved evaluator supplies its own implementation version; no second independently managed behavioral version is persisted.
- [ ] Scalar Evaluation Results receive the exact deterministic evaluator-version tag without depending on a post-execution name lookup.
- [ ] Every Evaluation Result emitted by a mapping-valued evaluator receives the same exact deterministic tag even though its result name differs from the Configured Evaluator name.
- [ ] EvaluatorFailure values receive the same exact deterministic tag when case evaluation raises or returns invalid output.
- [ ] Evaluation telemetry emitted during evaluator execution contains the same evaluator-version value as the corresponding persisted result or failure; checkpoint-time mutation is not used to repair already-emitted telemetry.
- [ ] Checkpoint persistence and frozen aggregate materialization preserve the exact evaluator-version value for scalar results, mapping-valued results, and evaluator failures.
- [ ] ReportCase materialization returns concrete typed EvaluatorFailure values, including their source, error details, error type, and evaluator version, rather than failure dictionaries or evidence-model projections.
- [ ] The runner no longer depends on matching score, label, or assertion names back to Configured Evaluator names to establish evaluator-version provenance.
- [ ] Deterministic end-to-end tests cover a scalar evaluator, a mapping-valued evaluator with output names different from its configured name, and a failing evaluator, asserting exact version equality before and after checkpoint reload and aggregate materialization.
- [ ] Existing durable Evaluation Run lifecycle and ReportCase evidence-contract tests continue to pass without changing the evidence-contract version.

## Blocked by

- [Validate ReportCase Evidence at Evaluation Checkpoints](./01-validate-report-case-evidence-at-evaluation-checkpoints.md)
