# Repository-Wide Model Evaluation Strategy

Labels: wayfinder:map, needs-triage

## Destination

Reach a decision-ready, repository-wide evaluation strategy and implementation roadmap that makes production regressions visible, compares model trade-offs, and provides a consistent foundation for every current and future model-backed component.

## Notes

- Use `/grilling` and `/domain-modeling` when resolving decisions; read `CONTEXT.md` before exploration.
- The shared standard must cover all model-backed components, with task-specific scoring on top of common contracts, provenance, run recording, artifacts, and CI integration.
- Evaluation is for regression detection first and model comparison second. Run affected deterministic checks on pull requests; require broad non-deterministic suites before releases.
- Human-labeled, versioned Evaluation Gold Sets are authoritative. Promote reviewed production failures, ambiguous inputs, and model-disagreement cases into versioned training, calibration, or held-out test splits.
- Relevance human labels are binary. `INCONCLUSIVE` is an automated review-routing status, and relevance release gates prioritize recall of `RELEVANT` articles.
- Evaluation records use relational links between datasets, cases, runs, and controlled artifacts. Raw inputs/outputs stay outside the evaluation database, subject to retention controls.
- Component order: Relevance Filter; selector healing; coreference; Entity Extraction. Embedding and GraphRAG evaluation are in scope but await a defined retrieval/answering contract.

## Decisions so far

- Shared evaluation runtime: use `pydantic-evals` for dataset/case execution and scoring, Pydantic AI as the provider-neutral task seam, existing Logfire instrumentation for traces/LLM telemetry, relational persistence for run metadata and case outcomes, and CI artifacts for serialized reports/raw artifact manifests. See [01-validate-shared-evaluation-runtime.md](issues/01-validate-shared-evaluation-runtime.md).
- Shared evaluation contract: use immutable, versioned authored definitions; suite-owned case/report evaluator configuration; mandatory report evaluation; frozen run manifests and secret-free configuration fingerprints; typed task/evaluator outcomes; versioned Metric Definitions and comparison operations; content-addressed artifacts; and an incremental relational execution ledger. See [the completed contract issue](issues/02-define-shared-evaluation-contract.md) and [ready-for-agent specification](../../projects/shared-evaluation-contract/PRD.md).

## Not yet specified

- Define retrieval and answer evaluation for the future GraphRAG agent, including context relevance, answer relevance, groundedness/faithfulness, and time to first token once its retrieval and response contract exists.
- Define embedding evaluation once the downstream retrieval task and ground-truth relevance judgments are available.
- Calibrate component quality floors and tolerated regression margins from baseline runs rather than selecting them in advance.

## Out of scope

- Building or deploying the future GraphRAG agent itself; this effort only prepares its evaluation strategy.
