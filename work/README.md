# Work

This directory is the authoritative home for planned, active, and completed work
on the California Political Knowledge Map.

Start here when deciding what to work on. Use [roadmap.md](roadmap.md) for the
direction of the product and [inbox.md](inbox.md) for ideas and problems that
have not yet been shaped into executable work.

## Current attention

### Waiting for human review

- [Build the initial relevance Evaluation Gold Set](initiatives/model-evaluation/issues/03-build-initial-relevance-evaluation-gold-set.md)
- [Review Relevance Filter evaluations](projects/scraping-pipeline/issues/13-relevance-evals.md)
- [Review Selector Healing evaluations](projects/scraping-pipeline/issues/14-healer-evals.md)

### Open initiative branches

The [Model Evaluation map](initiatives/model-evaluation/MAP.md) is the current
large-scale investigation. Its remaining open branches are:

- [Specify Relevance Filter evaluation](initiatives/model-evaluation/issues/04-specify-relevance-filter-evaluation.md)
- [Specify Selector Healing evaluation](initiatives/model-evaluation/issues/05-specify-selector-healing-evaluation.md)
- [Specify Coreference Resolution evaluation](initiatives/model-evaluation/issues/06-specify-coreference-evaluation.md)
- [Specify Entity Extraction evaluation](initiatives/model-evaluation/issues/07-specify-entity-extraction-evaluation.md)

### Reconciliation queue

The migration preserved existing labels rather than guessing at intent.
Before this index can become a reliable generated dashboard, reconcile:

- Parent PRDs still labeled `ready-for-agent` even when all or most child issues
  are complete.
- Projects with completed acceptance criteria but pending human review.
- Open concerns in [inbox.md](inbox.md) that now overlap completed evaluation
  work.

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
