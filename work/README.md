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

- [News Ontology and Graph Population](projects/news-ontology-graph-population/PRD.md), specifying [Useful Graph Retrieval issue 01](initiatives/useful-graph-retrieval/issues/01-populate-graph-with-settled-ontology.md). Broken into eight issues on 2026-08-05; the frontier is below.

### News Ontology and Graph Population frontier

Issue 01 is complete. Two issues are takeable now; the rest declare their
blockers.

- [01 Author and review the Policy Area vocabulary](projects/news-ontology-graph-population/issues/01-author-policy-area-vocabulary.md), `completed` on 2026-08-06. Its deliverable is [the Policy Area vocabulary](projects/news-ontology-graph-population/policy-area-vocabulary.md): 27 topic slugs derived from the Assembly and Senate subject-matter standing committees, reviewed and accepted.
- [05 Write-path ontology vocabulary rename](projects/news-ontology-graph-population/issues/05-write-path-ontology-vocabulary-rename.md), takeable. A mechanical prefactor: `:Article` becomes `:NewsArticle` and `BELONGS_TO` becomes `HAS_CHUNK`.
- [02 Ontology package and conformance check](projects/news-ontology-graph-population/issues/02-ontology-package-and-conformance-check.md), takeable — unblocked by 01. Everything else in the project reads the News Ontology it introduces.
- [03 Extraction Prompt generated from the News Ontology](projects/news-ontology-graph-population/issues/03-generate-extraction-prompt-from-news-ontology.md), blocked by 02.
- [04 Sub-labels and extraction conformance](projects/news-ontology-graph-population/issues/04-sub-labels-and-extraction-conformance.md), blocked by 02.
- [06 Node identity, provenance, and topic edges](projects/news-ontology-graph-population/issues/06-node-identity-provenance-and-topic-edges.md), blocked by 02, 04, and 05.
- [07 Bill session resolution](projects/news-ontology-graph-population/issues/07-bill-session-resolution.md), blocked by 06.
- [Code review of issues 02–07](projects/news-ontology-graph-population/code-review/README.md), `ready-for-agent` as of 2026-08-07. Eighteen findings from a standards-and-spec review of the six completed issues. Three would corrupt the graph 08 builds, and two acceptance criteria are ticked for work that was not done. Broken into [fourteen tickets](projects/news-ontology-graph-population/code-review/issues/) on 2026-08-08; tickets 01, 03, 04, 05, and 07 are takeable now and the rest declare their blockers.
- [08 Rebuild the graph and record the label inventory](projects/news-ontology-graph-population/issues/08-rebuild-graph-and-record-label-inventory.md), blocked by 03, 04, 06, 07, and the code review. Produces the label and relationship counts the Useful Graph Retrieval map waits on.

### Useful Graph Retrieval frontier

The [Useful Graph Retrieval map](initiatives/useful-graph-retrieval/MAP.md) was
charted on 2026-07-29 and holds ten tickets. Two are takeable now; the rest
declare their blockers.

- [Update the extraction prompt to the settled ontology and populate the graph](initiatives/useful-graph-retrieval/issues/01-populate-graph-with-settled-ontology.md), `ready-for-agent` as of 2026-08-05, specified by the [News Ontology and Graph Population PRD](projects/news-ontology-graph-population/PRD.md). Every other retrieval decision waits on it.
- [Decide the target question set for California political retrieval](initiatives/useful-graph-retrieval/issues/02-target-question-set.md), `ready-for-human`.
- [Survey graph retrieval patterns and available tooling](initiatives/useful-graph-retrieval/issues/03-survey-graph-retrieval-patterns.md), `completed` on 2026-08-05; facts live in [the findings](initiatives/useful-graph-retrieval/research/03-graph-retrieval-patterns-findings.md).

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
| `ready-for-agent` | [News Ontology and Graph Population](projects/news-ontology-graph-population/PRD.md) |
| `ready-for-human` | [Scraping Pipeline](projects/scraping-pipeline/PRD.md); [Unified Evaluation Execution Path](projects/unified-evaluation-execution/PRD.md) |
| `completed` | [Article Chunking and Coreference Resolution](projects/article-chunking-coreference/PRD.md); [Batch Ingestion Orchestration](projects/batch-ingestion-orchestration/PRD.md); [Case Evaluation Requirements](projects/case-evaluation-requirements/PRD.md); [Coreference Reliability](projects/coreference-reliability/PRD.md); [Evaluation Contract Hardening](projects/evaluation-contract-hardening/PRD.md); [Evaluation Gold Set Construction and Revisioning](projects/gold-set-construction-factory/PRD.md); [Flexible Category Filtering](projects/flexible-category-filtering/PRD.md); [Influence Graph Playground](projects/influence-graph-playground/PRD.md); [Pipeline Stage Ownership](projects/pipeline-stage-ownership/PRD.md); [Relevance Classification](projects/relevance-classification/PRD.md); [Renewable Evaluation Finalization Authority](projects/renewable-evaluation-finalization-authority/PRD.md); [Shared Evaluation Contract](projects/shared-evaluation-contract/PRD.md); [Story Pipeline Coordinator](projects/story-pipeline-coordinator/PRD.md); [Structured Metric Observation Materialization](projects/structured-metric-observation-materialization/PRD.md) |

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

On 2026-07-29, after the Unified Evaluation Execution Path collapsed to a single
runner-only execution seam:

- The full deterministic suite passed: `489 passed`.
- The per-issue counts in that project's issues 10, 14, and 15 (`482`, `493`,
  `489`) are dated observations of the suite at those moments. They are a
  before-and-after record, not invariants: each is left as measured, and an
  unexplained movement between them is the signal to investigate.

On 2026-08-05, the `ready-for-agent` queue was reconciled against the issue
files and the code:

- The four issues listed under "Ready for agent" were already labeled
  `completed` in their own files; the README listing was stale, as were both
  "gated" paragraphs — Pipeline Stage Ownership 04–10 and Gold Set Construction
  01–03 are all `completed`.
- [Bound transient renewal contention](projects/renewable-evaluation-finalization-authority/issues/01-bound-transient-renewal-contention-by-confirmed-authority.md)
  was implemented but never relabeled. The heartbeat compares the ledger clock
  against the last confirmed expiry with strict inequality, before and after the
  ownership query, and
  `test_transient_renewal_and_ownership_contention_stop_at_confirmed_expiry`
  covers the contended-through-expiry case. Relabeled `completed`, and the
  parent PRD with it.
- Pipeline Stage Ownership and Evaluation Gold Set Construction were relabeled
  `completed`; every child of both is complete. No project is `ready-for-agent`.
- The only remaining agent-takeable ticket is the Useful Graph Retrieval survey,
  which has produced no `research/` output yet.
- The full deterministic suite passed: `544 passed`.

## Information model

| Level | Purpose | Location |
| --- | --- | --- |
| Roadmap | Product outcomes and strategic sequence | `roadmap.md` |
| Initiative | A large uncertain area that needs investigation | `initiatives/<slug>/` |
| Project | A bounded deliverable described by a PRD | `projects/<slug>/` |
| Issue | An independently completable change or investigation | A project's `issues/` directory or `issues/` |
| Code review | Whether a project's build matched its PRD | `projects/<slug>/code-review/` |
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
