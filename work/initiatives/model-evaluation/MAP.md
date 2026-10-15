# Repository-Wide Model Evaluation Strategy

Labels: wayfinder:map, needs-triage

## Destination

Reach a decision-ready, repository-wide evaluation strategy and implementation roadmap that makes production regressions visible, compares model trade-offs, and provides a consistent foundation for every current and future model-backed component.

## Notes

- Use `/grilling` and `/domain-modeling` when resolving decisions; read `GLOSSARY.md` before exploration.
- The shared standard must cover all model-backed components, with task-specific scoring on top of common contracts, provenance, run recording, artifacts, and CI integration.
- Evaluation is for regression detection first and model comparison second. Run affected deterministic checks on pull requests; require broad non-deterministic suites before releases.
- Human-labeled, versioned Gold Sets are authoritative. Promote reviewed production failures, ambiguous inputs, and model-disagreement cases into versioned training, calibration, or held-out test splits.
- Relevance human labels are binary. `INCONCLUSIVE` is an automated review-routing status, and relevance release gates prioritize recall of `RELEVANT` articles.
- Evaluation Data Sets and reports are versioned files under `evals/`, as decided in [ADR 0017](../../../docs/adr/0017-git-is-the-evaluation-versioning-system.md).
- Component evaluations cover Relevance Filter, coreference, Entity Extraction, Policy Area Classification, and Topic Assignment. The Chat Session path now has a retrieval and answer contract and an unlabeled training set for error analysis.

## Decisions so far

- Shared evaluation runtime: use `pydantic-evals` for case execution, Pydantic AI as the model task boundary, and Logfire for operational traces. Git versions Data Sets and JSON reports. [ADR 0017](../../../docs/adr/0017-git-is-the-evaluation-versioning-system.md) supersedes the earlier relational-ledger design in issues 01 and 02.
- Chat Session error analysis: run the existing concrete target questions and Declined/Deferred controls as an unlabeled training set. Review preparation, retrieval branches, Grounding Evidence, citations, answer guidance, and failures case by case before defining answer evaluators. See [the review guide](../../../docs/evaluation/chat-answer-review.md).

## Not yet specified

- Review initial Chat Session cases, record observed retrieval, citation, and answer failures, and use those observations to define labels and evaluators. No answer-quality metric exists yet.
- Define embedding evaluation once the downstream retrieval task and ground-truth relevance judgments are available.
- Calibrate component quality floors and tolerated regression margins from baseline runs rather than selecting them in advance.

## Out of scope

- Building or deploying the future GraphRAG agent itself; this effort only prepares its evaluation strategy.
