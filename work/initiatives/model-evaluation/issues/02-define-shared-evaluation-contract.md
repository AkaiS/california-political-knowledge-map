# Define the shared evaluation contract and record model

Labels: wayfinder:grilling, completed
Parent: [Repository-Wide Model Evaluation Strategy](../MAP.md)
Blocked by: [Validate the shared evaluation runtime](01-validate-shared-evaluation-runtime.md)

## Question

What common case, suite, Evaluation Run, Evaluation Case Result, metric, artifact-reference, and relational persistence contracts should every component use, while allowing task-specific metric payloads and scoring?

## Blocking

- Blocks: Specify the Relevance Filter evaluation and comparison report.

## Outcome

The shared evaluation contract and relational record model were resolved through a grilling and domain-modeling session, then published as the ready-for-agent [Shared Evaluation Contract and Record Model](../../../projects/shared-evaluation-contract/PRD.md).

The contract establishes immutable authored definition revisions, suite-owned evaluator configuration with mandatory report evaluation, frozen per-run case manifests, typed task and evaluator outcomes, case/run Metric Observations, versioned comparison operations, content-addressed artifacts, and an incremental relational execution ledger.
