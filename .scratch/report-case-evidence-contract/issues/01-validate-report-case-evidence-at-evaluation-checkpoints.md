# Validate ReportCase Evidence at Evaluation Checkpoints

Labels: ready-for-agent

## What to build

Make the Evaluation Ledger accept and materialize only ReportCase evidence that conforms to evidence contract version 1. Represent the persisted successful and failed ReportCase projections as immutable, extra-forbidding Pydantic models in a discriminated union with an explicit `kind`, while continuing to source authored inputs, metadata, and expected outputs from their immutable Evaluation Case definitions.

Validate supplied ReportCase evidence before it contributes to checkpoint identity or enters durable storage, and use only its canonical validated representation for hashing, serialization, replay comparison, and persistence. Validate stored evidence again before materialization, then combine the typed evidence with schema-validated authored values to reconstruct the appropriate Pydantic Evals ReportCase or ReportCaseFailure.

Keep `EVIDENCE_CONTRACT_VERSION` at version 1. This work establishes the first enforced definition of that contract; it does not introduce a Pydantic Evals version registry, upstream-shape compatibility table, historical version dispatch, or a migration for disposable prototype ledgers.

## Acceptance criteria

- [ ] Evidence contract version 1 defines distinct successful and failed ReportCase evidence models selected by an explicit `kind` discriminator; the models are immutable, reject unknown fields, and validate nested evaluator results and failures rather than retaining arbitrary mappings.
- [ ] Successful evidence preserves the run-specific output, metrics, attributes, score, label, assertion, evaluator-failure, duration, source-case, and trace fields required to reconstruct its evaluator-visible ReportCase semantics.
- [ ] Failed evidence preserves the error, source-case, and trace fields required to reconstruct its evaluator-visible ReportCaseFailure semantics.
- [ ] Authored inputs, metadata, and expected outputs remain excluded from checkpoint evidence and continue to be loaded and schema-validated from the exact immutable Evaluation Case definition during materialization.
- [ ] The Evaluation Ledger validates supplied ReportCase evidence before calculating the checkpoint content hash or beginning persistence and uses the validated canonical JSON representation consistently for hashing, storage, idempotent replay comparison, and aggregate-manifest integrity verification.
- [ ] Checkpoint validation rejects a mismatch between the evidence variant, Evaluation Case disposition, and Evaluation Task Outcome, including successful evidence paired with a failed case or failed evidence paired with a completed case.
- [ ] Successful evidence cannot disagree with the persisted successful task output, and its durations satisfy `total_duration >= task_duration >= 0`.
- [ ] Stored ReportCase evidence is parsed and validated against evidence contract version 1 before materialization; malformed, incomplete, mismatched, or unknown evidence fails at that boundary instead of being interpreted through permissive dictionary defaults.
- [ ] Existing support for recording a terminal low-level checkpoint without ReportCase evidence remains unchanged, while such a checkpoint remains ineligible for ReportCase materialization or a frozen aggregate manifest.
- [ ] Deterministic tests cover successful and failed checkpoint round trips, nested evaluator evidence, canonical replay, malformed and extra fields, variant and outcome mismatches, output and duration inconsistencies, and validation of corrupted stored evidence.
- [ ] Existing successful and failed durable Evaluation Run lifecycle tests continue to reconstruct typed Pydantic Evals report cases and complete finalization without changing the evidence-contract version.

## Blocked by

None — can start immediately.
