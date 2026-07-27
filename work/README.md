# Work

This directory is the authoritative home for planned, active, and completed work
on the California Political Knowledge Map.

Start here when deciding what to work on. Use [roadmap.md](roadmap.md) for the
direction of the product and [inbox.md](inbox.md) for ideas and problems that
have not yet been shaped into executable work.

## Current attention

### Ready for human

- [Build the initial relevance Evaluation Gold Set](initiatives/model-evaluation/issues/03-build-initial-relevance-evaluation-gold-set.md)
- [Review Relevance Filter evaluations](projects/scraping-pipeline/issues/13-relevance-evals.md)
- [Review Selector Healing evaluations](projects/scraping-pipeline/issues/14-healer-evals.md)

### Ready for agent

- [Create the Neo4j schema and vector index](projects/article-chunking-coreference/issues/03-neo4j-schema-vector-index.md)
- [Integrate chunking and Coreference Resolution into the pipeline](projects/article-chunking-coreference/issues/04-pipeline-integration.md)
- [Bound transient finalization-renewal contention by confirmed authority](projects/renewable-evaluation-finalization-authority/issues/01-bound-transient-renewal-contention-by-confirmed-authority.md)
- [Decide Suite, Gold Set, and Case compatibility in one place](projects/unified-evaluation-execution/issues/01-shared-suite-gold-set-case-compatibility-predicate.md)
- [Evaluate Evaluation Cases that declare no expected output](projects/unified-evaluation-execution/issues/03-evaluate-cases-without-an-expected-output.md)
- [Declare the full evidence sink protocol](projects/unified-evaluation-execution/issues/05-declare-the-full-evidence-sink-protocol.md)
- [Define Evaluation Split in the glossary and describe the construction flow](projects/gold-set-construction-factory/issues/04-define-evaluation-split-in-the-glossary.md)

The remaining [Unified Evaluation Execution Path](projects/unified-evaluation-execution/PRD.md)
issues (02, 04, 06–10) are `ready-for-agent` but gated; each declares its blockers.
Work the frontier: any issue whose blockers are all complete.

The [Evaluation Gold Set Construction and Revisioning](projects/gold-set-construction-factory/PRD.md)
issues 01–03 are `ready-for-agent` but gated. Issue 01, the validating factory,
is blocked by the Unified Evaluation Execution Path's shared compatibility
predicate, and issues 02 and 03 are blocked by 01. Its glossary issue 04 is
listed above because it has no blockers.

### Blocked initiative chain

The [Model Evaluation map](initiatives/model-evaluation/MAP.md) is the current
large-scale investigation. Its remaining specification branches are ordered,
not parallel:

1. [Specify Relevance Filter evaluation](initiatives/model-evaluation/issues/04-specify-relevance-filter-evaluation.md), blocked by the human Gold Set work.
2. [Specify Selector Healing evaluation](initiatives/model-evaluation/issues/05-specify-selector-healing-evaluation.md), blocked by the Relevance Filter specification.
3. [Specify Coreference Resolution evaluation](initiatives/model-evaluation/issues/06-specify-coreference-evaluation.md), blocked by the Selector Healing specification.
4. [Specify Entity Extraction evaluation](initiatives/model-evaluation/issues/07-specify-entity-extraction-evaluation.md), blocked by the Coreference Resolution specification.

These retain `needs-triage` until their blockers are resolved; they are not
currently executable.

## Project state

| Triage state | Projects |
| --- | --- |
| `ready-for-agent` | [Article Chunking and Coreference Resolution](projects/article-chunking-coreference/PRD.md); [Evaluation Gold Set Construction and Revisioning](projects/gold-set-construction-factory/PRD.md); [Renewable Evaluation Finalization Authority](projects/renewable-evaluation-finalization-authority/PRD.md); [Unified Evaluation Execution Path](projects/unified-evaluation-execution/PRD.md) |
| `ready-for-human` | [Scraping Pipeline](projects/scraping-pipeline/PRD.md) |
| `completed` | [Batch Ingestion Orchestration](projects/batch-ingestion-orchestration/PRD.md); [Case Evaluation Requirements](projects/case-evaluation-requirements/PRD.md); [Coreference Reliability](projects/coreference-reliability/PRD.md); [Evaluation Contract Hardening](projects/evaluation-contract-hardening/PRD.md); [Flexible Category Filtering](projects/flexible-category-filtering/PRD.md); [Influence Graph Playground](projects/influence-graph-playground/PRD.md); [Relevance Classification](projects/relevance-classification/PRD.md); [Shared Evaluation Contract](projects/shared-evaluation-contract/PRD.md); [Story Pipeline Coordinator](projects/story-pipeline-coordinator/PRD.md); [Structured Metric Observation Materialization](projects/structured-metric-observation-materialization/PRD.md) |

The completed [ReportCase Evidence Contract](projects/report-case-evidence-contract/)
contains two issue records but no parent PRD.

## Reconciliation record

On 2026-07-24, project labels were reconciled with child acceptance criteria
and the current test suite:

- Stale parent labels were closed when every child issue was complete.
- Checked Case Evaluation Requirements issues 10–12 and all Structured Metric
  Observation tickets were relabeled `completed`.
- The checked Scraping Pipeline Relevance Filter ticket was relabeled
  `completed`; the project remains `ready-for-human` for its two evaluation
  datasets.
- Renewable Evaluation Finalization remains `ready-for-agent` because its
  focused contention-boundary follow-up is unchecked.
- The full deterministic suite passed: `453 passed`.
- Historical observations in [inbox.md](inbox.md) remain untriaged candidates,
  not executable tickets.

## Information model

| Level | Purpose | Location |
| --- | --- | --- |
| Roadmap | Product outcomes and strategic sequence | `roadmap.md` |
| Initiative | A large uncertain area that needs investigation | `initiatives/<slug>/` |
| Project | A bounded deliverable described by a PRD | `projects/<slug>/` |
| Issue | An independently completable change or investigation | A project's `issues/` directory or `issues/` |
| Inbox | Unshaped ideas, defects, questions, and observations | `inbox.md` |
| Archive | Superseded plans and immutable imported source notes | `archive/` |

Supporting knowledge remains outside this hierarchy:

- [`CONTEXT.md`](../CONTEXT.md) defines the domain language.
- [`docs/adr/`](../docs/adr/) records durable architectural decisions.
- `.scratch/` contains disposable runtime output, not project plans.

## Label convention

`Labels:` is the only state header. Do not add a separate `Status:` field.

Each work item should have exactly one triage-state label:

- `needs-triage`
- `needs-info`
- `ready-for-agent`
- `ready-for-human`
- `completed`
- `wontfix`

Additional descriptive labels may share the same comma-separated line. For
example:

```text
Labels: wayfinder:research, ready-for-human
```

The triage-state label says what should happen next. Other labels describe the
kind of work.

## Archive

- `archive/imports/` contains verbatim snapshots of the two Obsidian notes used
  to seed this structure.
- `archive/legacy-plans/` contains completed or superseded standalone plans
  formerly located at the repository root.
