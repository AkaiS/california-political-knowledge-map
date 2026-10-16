# Product requirements: Evaluation headline metrics

Labels: needs-triage

## Problem Statement

No Evaluation Run records a run-level result. All 42 committed reports under
`evals/reports/` hold per-case scores only; the `analyses` field Pydantic Evals
reserves for experiment-wide results is empty in every one, because no task
registers a `ReportEvaluator` and `ca-map eval run` passes none to
`run_data_set`.

Every aggregate the maintainer has read was therefore computed after the run by
one of five routes:

1. Pydantic Evals' console table, printed by `ca-map eval run` and not saved.
2. `summarize_report` in `scripts/run_evaluation.py`: an unweighted mean of
   recorded case scores, printed and not saved.
3. `project_report` in `rag_review.py`, which overrides route 2 for retrieval
   and chat with the reviewer's own rules.
4. A one-off `measure.py` and `metrics.json` committed beside one chat report.
5. Hand-written tables in `docs/evaluation/retrieval.md`.

Each route chooses its own population, denominator and metric subset. A
retrieval run produces 60 score names, and the `run-evaluation` skill names no
headline among them, so each agent asked for "a report" highlights a different
selection. Two runs of the same task cannot be compared without re-deriving the
comparison by hand.

The per-case scores also cannot support the aggregates people expect.
`detection_scores` records precision, recall and F1 ratios but not the matched,
expected and found counts, so a pooled (micro) F1 cannot be recovered from a
saved report. Population drift compounds this: only the latest retrieval report
records its selected case IDs, chat runs range from 1 to 100 cases, and 24 of
42 reports ran from a dirty worktree.

Coverage is uneven. Chat registers no evaluators. Relevance, the only Gold Set,
records agreement and RELEVANT-recall as booleans, with no precision, F1 or
confusion matrix. Policy Area Classification and Topic Assignment have
evaluators and Silver Sets but no committed report.

## Solution

Each Evaluation Task declares a fixed, versioned set of Headline Metrics. A
`ReportEvaluator` computes them at the end of the run from the in-memory
Pydantic Evals report and returns them as one `TableResult` titled
`Headline metrics`. The existing checkpoint already serializes the whole report,
so the table lands in the committed report file with no new storage.

The headline table is the single source of truth for a run's result. The
summary script, the reviewer and the reporting skill read it; none re-averages
case scores for a metric the table already carries.

A Comparable Run is defined in code: same task, same Data Set hash, same
selected case IDs, same headline metric version. The summary script finds the
most recent Comparable Run as the baseline and reports deltas only against it.
When no Comparable Run exists it says why.

A model-invoked `report-evaluation` skill turns one or more reports into a
fixed-layout report. The script renders every number; the agent fills only
bounded interpretation slots. See [skill-design.md](skill-design.md).

## User Stories

1. As the maintainer, I want every Evaluation Run to record the same headline
   numbers for its task, so that two runs differ only where the system did.
2. As the maintainer, I want one primary metric per task, so that a task's
   trend reads as one line.
3. As the maintainer, I want pooled and per-case aggregates reported side by
   side with their names saying which is which, so that a few large cases cannot
   silently dominate or vanish.
4. As the maintainer, I want the failure rate reported as a headline metric on
   every task, so that a run cannot raise its F1 by failing its hard cases.
5. As the maintainer, I want a delta shown only against a run over the same
   cases, Data Set revision and metric version, so that a changed population is
   never read as a changed system.
6. As the maintainer, I want a run with no comparable baseline to say which
   condition failed, so that I know whether to rerun or re-baseline.
7. As the maintainer, I want a metric that cannot be computed to appear with its
   reason rather than disappear, so that absence is visible.
8. As the maintainer, I want every agent-written evaluation report to follow
   one layout, so that I read results rather than re-learn a format.
9. As the maintainer, I want several axes evaluated together shown as one row
   per axis, never averaged across axes, so that a Silver Set number is never
   blended with a Gold Set number.
10. As the maintainer, I want Unlabeled Set runs to report operational counts
    and state plainly that they carry no quality score.

## Implementation Decisions

### Headline Metric contract

Each `EvaluationTask` gains:

- `headline`: a `ReportEvaluator` returning one `TableResult` titled
  `Headline metrics`.
- `headline_version`: a string such as `relevance-v1`. Any change to a
  definition, aggregation or population rule creates a new version. Versions
  are immutable, following the prompt-version rule in ADR 0022.

Every row has the columns `metric`, `role` (`primary`, `headline` or
`diagnostic`), `value`, `numerator`, `denominator`, `aggregation`
(`pooled`, `per_case_mean`, `rate`, `count`), `scored_cases`,
`selected_cases` and `unavailable_reason`. A metric that cannot be computed
keeps its row with `value` null and a reason.

Each task has exactly one `primary` row. `headline` rows appear in every
report. `diagnostic` rows appear in the report file and in the detailed section
of a rendered report, never in its scorecard.

`ca-map eval run` passes `report_evaluators=(task.headline,)` to
`run_data_set`.

### Population rule

ADR 0024 stands: a failed or unresolved case contributes no value to a quality
metric and is never counted as success or zero. Every task therefore carries
two `rate` headline rows: `execution_failure_rate` and `unresolved_rate`, both
over selected cases. The selection manifest already reaches the report
evaluator through `experiment_metadata["selection"]`.

### Pooled counts

The report evaluator pools counts from `case.output` and
`case.expected_output`, using the same identity functions the case evaluators
use. `detection_scores` gains a sibling that returns the counts, and both case
and report evaluators call the shared identity helper. Committed per-case score
names stay unchanged.

A case where both sides are empty remains a per-case pass, as each task's
evaluator already documents. In pooled metrics it contributes no counts. The
two aggregates are reported side by side, so that convention is visible rather
than hidden in one number.

### Per-task headline sets (version 1)

| Task | Label quality | Primary | Headline | Diagnostic |
| --- | --- | --- | --- | --- |
| `relevance` | Gold | RELEVANT F1 (pooled) | RELEVANT precision, recall; accuracy; confusion-matrix counts | none |
| `extraction` | Silver | node F1 (pooled) | node P/R; relationship P/R/F1 (pooled); node F1 and relationship F1 (per-case mean); ontology conformance rate | sub-label, node-property, claim-property and stance-alignment accuracy |
| `coreference` | Silver | span F1 (pooled) | span P/R; B³ cluster F1 and entity accuracy, both mention-weighted over shared mentions; span F1 (per-case mean) | critic rejection precision and recall; critic kept-correct rate |
| `coreference_annotator` | Silver | span F1 (pooled) | as `coreference`, without critic rows | none |
| `policy_area_classification` | Silver | Policy Area F1 (pooled) | Policy Area P/R (pooled); label-macro F1 over areas with support; per-case mean F1 | per-area P/R/F1 |
| `topic_assignment` | Silver | assignment F1 (pooled) | assignment P/R (pooled); per-case mean F1 | none |
| `retrieval` | Silver | fused Recall@10 (per-case mean) | fused Recall@5; fused MRR; fused complete-evidence@10; context recall; context complete evidence; branch completion rate for each branch | each branch's Recall@{1,5,10,50}, MRR and complete-evidence@{5,10}; Precision@k; NDCG@10 with reason until relevance grades exist |
| `chat` | Unlabeled | none | completed-answer rate; decline rate; failure rate by stage; p50 and p95 case latency | branch outcomes by status |

Retrieval keeps the per-case mean, the standard IR convention, because each
question is one information need. Precision@k stays diagnostic because unlisted
chunks may be relevant against provisional labels.

Chat's primary row is `null`, with the reason "Unlabeled Set: no quality
metric". Its headline rows are operational and never presented as quality.

### Comparable Run and baseline

`scripts/run_evaluation.py` gains:

- `--baseline auto|PATH|none`, defaulting to `auto`. `auto` scans
  `evals/reports/<task>/` for the most recent report that matches on task, Data
  Set hash, sorted selected case IDs and `headline_version`.
- A `comparison` block in the summary: the baseline path, a `comparable`
  boolean, each failed condition, and a per-row delta for `primary` and
  `headline` rows.
- A dirty worktree on either side sets `comparable_with_caveat` and names the
  dirty side. It does not block the comparison.
- `--format markdown` renders the fixed scorecard defined in
  [skill-design.md](skill-design.md). JSON stays the default.
- Repeated `--report` renders one multi-axis scorecard.

### Existing aggregation routes

- `summarize_report` reads headline rows from `report.analyses` and keeps its
  population accounting. Its generic per-score means move under `diagnostic`
  in the summary.
- `project_report` keeps reviewer-only measurements. Where it computes a
  metric the headline table also carries, the reviewer displays the table's
  value. A test pins the two to agree on a fixture report.
- The per-report `measure.py` pattern ends. Latency becomes a chat headline row.

### Historical reports

Committed reports stay unchanged (ADR 0024). A report without a headline table
summarizes as `headline_version: none` and is never a Comparable Run. Each task
is re-baselined with one full run after this lands.

### Glossary

Add these terms:

- **Headline Metric**: one of the fixed, versioned run-level measurements a task
  records in every Evaluation Report, one of which is its primary metric.
- **Comparable Run**: an earlier Evaluation Run of the same task over the same
  selected case IDs, Data Set revision and headline version. It is the only
  baseline a reported delta may use.

### ADR

Record ADR 0026: an Evaluation Report carries its task's versioned headline
table, computed by a Pydantic Evals `ReportEvaluator`, and deltas are reported
only against a Comparable Run. It refines ADR 0024. The archived
metric-canonicalization ticket under `superseded-by-adr-0017` gave metric
identity a database ledger; this decision keeps identity in code and the
report file.

## Testing Decisions

- For each task, a fixture report with known outputs yields the expected
  headline rows. Include an empty-versus-empty case, a failed case and an
  unresolved case, so the pooled, per-case and rate rows each prove their
  population rule.
- Pooled and per-case aggregates disagree on a fixture built to make them
  disagree.
- Baseline selection rejects each non-matching condition in isolation: Data
  Set hash, case IDs, headline version and task.
- The markdown renderer produces a snapshot-stable scorecard for one axis and
  for three axes.
- The reviewer and the headline table agree on fused Recall@10 for a fixture
  retrieval report.
- No test calls a model. The report evaluator runs over a constructed
  `EvaluationReport`.

## Out of Scope

- Recomputing headline tables for historical reports.
- Graded relevance labels, and therefore NDCG values.
- A quality metric for chat. That needs reference answers or a validated judge
  (`validate-evaluator`), and belongs in its own project.
- Running Policy Area Classification and Topic Assignment for the first time.
  Their first runs are the re-baseline, not part of this build.
- Statistical significance testing. With 18 to 73 cases per set, the scorecard
  reports counts beside each rate so the reader can judge the size of a change.
  Confidence intervals are a later version.
- Any persistence beyond the report file.

## Further Notes

The audit behind this PRD was run on 2026-10-16 at `42041c0f`. Extraction's 16
reports are the strongest existing series, with a consistent metric set across
15 of them. Even so, their pooled F1 cannot be recovered without rerunning
them.
