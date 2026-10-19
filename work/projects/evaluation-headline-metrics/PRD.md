# Product requirements: Evaluation headline metrics

Labels: ready-for-agent

## Problem Statement

The maintainer runs an evaluation, asks an agent for a report, and gets a
different set of numbers each time. Two runs of the same task can't be read side
by side, because nothing fixes what a run's result is.

No Evaluation Run records a run-level result. All 42 committed Evaluation
Reports hold per-case scores only. Every aggregate the maintainer has read was
computed afterwards by one of five readers: the console table, the evaluation
summary script, the RAG reviewer, a one-off script committed beside one chat
report, and hand-written tables in the retrieval guide. Each reader picks its
own population, denominator and metric subset. A retrieval run produces 60
score names and no reader marks any of them as the headline, so each agent
highlights a different selection.

The saved scores also can't support the aggregates the maintainer expects. Set
agreement is stored as per-case precision, recall and F1 ratios without the
counts behind them, so a pooled F1 can't be recovered from a saved report.
Populations drift between runs: chat runs range from 1 to 100 cases, only the
newest retrieval report records its selected case IDs, and 24 of 42 reports
ran from a dirty worktree. Nothing stops a report from presenting a change in
population as a change in the system.

Coverage is uneven:

- **Chat:** has no evaluators.
- **Relevance:** the only Gold Set, but it records agreement and RELEVANT recall
  without precision, F1 or a confusion matrix.
- **Policy Area Classification and Topic Assignment:** have evaluators and
  Silver Sets but no report.

## Solution

Every completed Evaluation Run records its task's Headline Metrics in its
Evaluation Report. They form one fixed, versioned table, and one row in it is
the primary metric. The table is frozen when the run completes, as ADR 0026
decides. Every reader takes its numbers from the table.

When the maintainer asks for a summary, they get a scorecard rendered from that
table. It shows the run's population and provenance. It shows a change only
against a Comparable Run. When none exists, the scorecard names the condition
that failed.

When several axes run together, the scorecard gives one row per axis and never
an overall score.

A reporting skill for agents is deferred; see Out of Scope.

## User Stories

1. As the maintainer, I want every completed Evaluation Run to record its run-level result in its Evaluation Report, so that I don't depend on whoever reads it next.
2. As the maintainer, I want each task to report the same Headline Metrics on every run, so that two runs differ only where the system did.
3. As the maintainer, I want exactly one primary metric per task, so that a task's trend reads as one line.
4. As the maintainer, I want F1 as the primary metric for relevance and coreference, with recall beside it, so that the evaluators' "read recall first" guidance stays visible without changing the headline.
5. As the maintainer, I want each headline row to say how it was aggregated, so that I can tell a pooled number from a per-case mean.
6. As the maintainer, I want pooled and per-case F1 reported side by side for set-agreement tasks, so that a few large cases can't silently dominate or vanish.
7. As the maintainer, I want each pooled metric to show its numerator and denominator, so that I can judge how much evidence a rate rests on.
8. As the maintainer, I want articles where both sides agree on nothing to count as a pass in the per-case mean and to add nothing to pooled counts, so that both conventions stay visible and neither is hidden inside one number.
9. As the maintainer, I want an execution failure rate on every task, so that a run can't raise its F1 by failing its hard cases.
10. As the maintainer, I want failed cases kept out of quality metrics, as ADR 0024 requires, so that a failure never reads as success or as zero.
11. As the maintainer, I want a metric that can't be computed to keep its row, with a null value and a reason, so that absence is visible.
12. As the maintainer, I want a change reported only against a Comparable Run, so that a different population is never read as a different system.
13. As the maintainer, I want runs on different Model Deployments, prompt versions or code to remain Comparable Runs, so that the system under test is exactly what a comparison shows.
14. As the maintainer, I want the newest Comparable Run picked automatically as the baseline, so that I don't have to find it myself.
15. As the maintainer, I want to name a specific baseline when I need one, so that I can compare against a run I trust.
16. As the maintainer, I want a report with no Comparable Run to name every condition that failed, so that I know whether to rerun or to establish a new baseline.
17. As the maintainer, I want a dirty worktree on either side flagged as a caveat rather than blocking the comparison, so that most of the existing history stays usable while the gap stays visible.
18. As the maintainer, I want every headline definition change to produce a new, immutable headline version, so that a changed meaning can't hide behind an unchanged name.
19. As the maintainer, I want reports written before headline metrics to say they predate them and can't be compared, so that I'm not shown numbers computed by hand.
20. As the maintainer, I want a failed case to count as data in the run's report, so that a failure is measured rather than stopping the report.
21. As the maintainer, I want a run whose process stopped before every case finished to keep its saved results and to say it has no Headline Metrics, so that a partial population never becomes a baseline.
22. As the maintainer, I want a failure in the headline computation to count as an evaluator error and give a nonzero exit, so that a missing result can't pass silently.
23. As the maintainer, I want the summary to account for selected, scored, failed and unresolved Evaluation Cases, so that I can see the population behind every number.
24. As the maintainer, I want relevance to report RELEVANT precision, recall and F1, accuracy, and the confusion-matrix counts, so that the one Gold Set gets a complete classification summary.
25. As the maintainer, I want extraction to report pooled node and relationship precision, recall and F1, so that its long series of runs becomes comparable on raw counts.
26. As the maintainer, I want coreference and the coreference annotator scored identically on agreement, so that the two reports subtract.
27. As the maintainer, I want Policy Area Classification to report a macro F1 across areas, so that a common area can't hide failure on rare ones.
28. As the maintainer, I want retrieval to lead with fused Recall@10 averaged per question, so that its headline follows the usual information-retrieval convention.
29. As the maintainer, I want retrieval's headline to hold only outcomes a user would observe, with branch breakdowns left to the RAG reviewer's case views, so that a change to the pipeline's structure never changes what two runs compare.
30. As the maintainer, I want NDCG left out of retrieval's headline until relevance grades exist, so that the table holds only rows a run can compute.
31. As the maintainer, I want an Unlabeled Set run to report operational counts and say plainly that it has no quality metric, so that chat numbers are never read as answer quality.
32. As the maintainer, I want chat to report Declined, Deferred and needs-edit questions as separate rates, so that a policy refusal is never confused with missing coverage.
33. As the maintainer, I want chat's completed-answer and question-status rules defined once, in its headline evaluator, so that the summary and the scorecard can't disagree on them.
34. As the maintainer, I want chat latency reported as p50 and p95 with a case count, so that a slowdown is visible without a one-off script.
35. As the maintainer, I want a scorecard rendered by the evaluation summary script, so that every number in a report comes from code.
36. As the maintainer, I want several reports rendered together as one row per axis, with their label quality, so that Silver and Gold numbers are never blended.
37. As the maintainer, I want diagnostic metrics kept in the report and in a collapsed section of the scorecard, so that the headline stays short and the detail is still there.
38. As the maintainer, I want the RAG reviewer to show the table's value wherever it shows a headline metric, so that the reviewer and the report agree.
39. As the maintainer, I want retrieval report compaction to keep the headline table intact, so that compaction never changes a run's result.

## Implementation Decisions

### Decided elsewhere

- **ADR 0026:** the run result is frozen in the report, computed by the task's
  `ReportEvaluator`, and a change is stated only against a Comparable Run.
- **ADR 0024:** this spec keeps its population accounting, progressive
  snapshots and failure handling.
- **ADR 0022:** headline versions follow the same immutability as prompt
  versions.

### Modules

All of this feature's behaviour lives in two deep modules. Everything else is a
caller. The shape was chosen on 2026-10-16 by a blind comparison of three
independent interface designs. The typed-report design won, and the reviewer's
recommended grafts from the runner-up are included. The type shapes below come
from that comparison and fix the interface, not the implementation.

#### Headline module: the shared value and the writing side

```python
class HeadlineRow(BaseModel, frozen=True):
    metric: str; role: Role; aggregation: Aggregation
    value: float | None; numerator: float | None; denominator: float | None
    scored_cases: int; selected_cases: int; unavailable_reason: str | None

class Headline(BaseModel, frozen=True):
    rows: tuple[HeadlineRow, ...]
    def to_table(self) -> TableResult                       # titled "Headline metrics"
    @classmethod
    def from_analyses(cls, analyses) -> Headline | None     # in-memory or serialized
    primary: HeadlineRow                                     # property
    def row(self, metric: str, aggregation: Aggregation) -> HeadlineRow | None
    def by_role(self, role: Role) -> tuple[HeadlineRow, ...]

class HeadlineDefinition(BaseModel, frozen=True):
    version: str                                             # immutable, e.g. "extraction-v1"
    measures: tuple[Measure, ...]                            # declared order is row order
    def evaluator(self) -> ReportEvaluator

class Counts(BaseModel, frozen=True):                       # one case's contribution
    precision_numerator: float; precision_denominator: int
    recall_numerator: float; recall_denominator: int

# The closed set of measures:
SetAgreement(prefix, counts: Callable[[ReportCase], Counts], roles)   # pooled P/R/F1
Pooled(metric, contribution: Callable[[ReportCase], tuple[float, float] | None], role)
PerLabel(prefix, counts: Callable[[ReportCase], Mapping[str, Counts]], reference_labels)
CaseMean(score: str, role)            # mean of a recorded case score or assertion
Rate.quality(metric, test, role)
Rate.operational(metric, test, role)
Quantile(metric, q, of, role)
Unavailable(metric, aggregation, role, reason)
```

The interface is everything a caller must know:

- **What a `Headline` guarantees.** Its validators enforce:
  - a value is null exactly when a reason is given;
  - a pooled row with a value has a numerator and a denominator;
  - each pair of metric and aggregation is unique;
  - the one primary row comes first, then the headline rows, then the
    diagnostic rows, each in declared order;
  - an `execution_failure_rate` row is present.
- **How the table is read.** `from_analyses` is the only way to read the
  table, on either side. It returns `None` when a report has no table. It
  raises a format error on a duplicate table or on columns that differ from
  the contract.
- **How a definition is checked.** A `HeadlineDefinition` validates at import.
  It needs a non-empty version and exactly one primary row, produced by its
  first measure. It must not name `execution_failure_rate`, which it adds
  itself.
- **What each measure sees.**
  - The quality measures (`SetAgreement`, `Pooled`, `PerLabel`, `CaseMean`,
    `Rate.quality` and `Quantile`) see only cases that succeeded.
  - `Rate.operational` sees the whole run population.

  ADR 0024's exclusion is therefore part of a measure's type, and no task
  restates it.
- **How set agreement is counted.** One identity function,
  `detection_counts(expected, found) -> Counts`, serves both the case
  evaluators and the measures. `detection_scores` is rewritten on top of it,
  and per-case score names are unchanged. The four-field `Counts` covers set
  agreement, Relevance's single-label sets and B³ clusters, whose precision
  and recall have different numerators.
- **The measure set is closed.** Adding a measure requires amending this
  spec.

Hidden behind the module:

- **The run population.** It is built only from the report's completed and
  failed cases, never from experiment metadata. It is split into succeeded
  cases and failed outcomes. Failed outcomes are framework failures plus
  completed cases whose output records a failure. That rule moves out of
  `ca-map eval run`, so the run's exit code and `execution_failure_rate`
  share one definition of a failed case.
- **The arithmetic.** Pooling, per-case means of recorded scores, rates,
  quantiles, and per-label expansion. A zero denominator gives a
  null value with a reason.
- **Assembling the table.** Appending `execution_failure_rate`, ordering rows
  by role, and encoding the `TableResult`.
- **The one `ReportEvaluator` adapter.** It is a plain dataclass, because
  pydantic-evals rejects a frozen subclass. Its serialization arguments are
  only the headline version, so a recorded evaluator failure serializes the
  same way on every run.

#### Run report module: the reading side

```python
class ReportDocument:                                        # lenient over historical shapes
    @classmethod
    def load(cls, path: Path) -> ReportDocument              # raises on an unreadable file

class Scorecard(BaseModel):
    axes: tuple[Axis, ...]                                   # one per report, in argument order
    @classmethod
    def build(cls, documents: Sequence[ReportDocument],
              baseline: Literal["auto", "none"] | Path,
              *, reviewer_port: int = 8766) -> Scorecard   # port in the reviewer link and command
    def to_json(self) -> dict
    def to_markdown(self) -> str
    exit_code: int                                           # property

class NoHeadline(BaseModel):
    reason: Literal["predates_headline_metrics", "incomplete_run", "headline_evaluator_failed"]
```

The interface is everything a caller must know:

- **Every axis carries five things:** a `Headline` or a `NoHeadline` reason,
  its population, its comparison, its provenance, and today's diagnostic
  output.
- **A comparison reports independently** on each of six conditions: task,
  Data Set revision, selected case IDs, headline version, a completed baseline
  with a table, and a selection manifest on both sides. Each failed condition
  is listed. A dirty worktree on either side adds a caveat and never fails a
  condition. Changes are computed for primary and headline rows only, and are
  null when either value is null.
- **`exit_code` is nonzero** when any axis is incomplete or has execution
  failures or evaluator errors, whichever output format is chosen.

Hidden behind the module:

- **Reading historical documents.** It tolerates every historical document
  shape and tells apart reports that predate Headline Metrics, incomplete
  runs, and failed headline evaluators.
- **Population accounting,** moved out of the summary script.
- **Comparison.** The six conditions, the caveat and the changes.
- **Choosing an automatic baseline.** Candidates are only reports beside the
  current one with an earlier `ran_at`. The newest candidate that is
  `comparable` or `comparable_with_caveat` wins, with no preference for clean
  worktrees. With no candidate, the reason is the newest same-task report's
  failed conditions, or "no earlier run".
- **Output.** Assembling several axes without ever producing an overall score,
  and both renderers.

#### Callers

- **`ca-map eval run`** passes `task.headline.evaluator()` to the evaluation
  engine. It records `task.headline.version` beside the prompt digests in the
  experiment metadata, which already reaches the report's provenance. No other
  run path is added.
- **The evaluation task registry** gains one field, `headline`, which holds the
  task's `HeadlineDefinition`. The version and the evaluator come from that one
  value, so they can't disagree. The field stays optional until every task
  declares one, and then becomes required.
- **The evaluation summary script** parses arguments, loads documents, builds a
  `Scorecard`, prints JSON or markdown, and returns `exit_code`. One smoke test
  covers it. Its existing
  summary function for planned runs becomes a thin wrapper over a single-axis
  `Scorecard`.
- **The RAG reviewer** reads run-level values only through
  `Headline.from_analyses`. The mapping from its metric names to case score
  names moves out of the summary script and into the reviewer.

#### Depth rules

These rules hold the shape. Every ticket repeats them as acceptance criteria.

- **Tasks declare; they don't build.** A task supplies a `HeadlineDefinition`
  made from the closed measure set and functions over a single case. It
  defines no `ReportEvaluator`, builds no table rows, and computes no
  population or failure rate.
- **Readers call; they don't compute.** Only the run report module classifies
  reports, accounts for the population, compares or renders. The summary
  script and the RAG reviewer hold none of that logic, and nothing outside the
  two modules parses table rows.
- **Tests cross the two seams.** Tests cross only the engine-run seam and the
  run report module's interface (`ReportDocument.load` and `Scorecard.build`
  with their outputs). The summary script's command line is a caller, not a
  seam, and gets one smoke test. Neither module gets an internal test seam.

### Headline Metric contract

- Each task's `HeadlineDefinition` carries an immutable headline version, such
  as `relevance-v1`. Its evaluator returns one Pydantic Evals `TableResult`
  titled `Headline metrics`.
- Each row has the columns `metric`, `role`, `value`, `numerator`,
  `denominator`, `aggregation`, `scored_cases`, `selected_cases` and
  `unavailable_reason`.
- `role` is `primary`, `headline` or `diagnostic`. Each task has exactly one
  `primary` row.
- `aggregation` is `pooled`, `per_case_mean`, `rate` or `quantile`.
- A metric that can't be computed keeps its row, with a null `value` and a
  reason.
- The headline version is recorded in the report's provenance beside the Data
  Set hash and the prompt digests.

### Failed cases and incomplete runs

- A failed Evaluation Case is data. When a task raises, Pydantic Evals records
  a case failure and the run continues. When a task catches its own failure,
  the failure stays in the case output. Either way the run completes, its
  Headline Metrics are computed, and the case counts toward
  `execution_failure_rate`. Under ADR 0024 it adds no value to a quality
  metric.
- An incomplete run is one whose process stopped before every selected case
  reached a result or a failure. Causes include an interruption, a crash, an
  infrastructure error that escapes the engine, or a returned report whose
  cases don't match the selection. ADR 0024 keeps its saved results and
  unresolved case IDs. Its headline report evaluator never runs, so it has no
  Headline Metrics and is never a Comparable Run. Its scorecard reports the
  population block and says the run is incomplete.
- A failure inside the headline report evaluator is recorded by Pydantic Evals
  as a report evaluator failure. The summary counts it as an evaluator error
  and exits nonzero, as it does today.

### Run population and selected case IDs

"Selected cases" serves two purposes, and the spec keeps them apart:

- **The run population** is the denominator for every rate in one run. Inside
  the headline report evaluator, it is the completed cases plus the failed
  cases. It depends on no experiment metadata, so a direct `ca-map eval run`
  and a run started by the evaluation summary script compute it the same way.
- **The selected case IDs** decide whether two runs are Comparable Runs. The
  report checkpoint records them before any case runs. Reports written before
  that manifest existed have none, so they can't be shown to match and are
  never Comparable Runs.

### Pooled counts

- Pooled counts come from the shared `detection_counts` described under
  Modules, so a pooled count and a case score always agree on what matched.
- Per-case score names in reports are unchanged.
- A case where both sides are empty keeps each task's documented per-case pass.
  It contributes zero to every pooled count.

### Version 1 headline sets

A headline set records only outcomes a user would observe: answered, declined,
deferred or failed, latency, and the task's quality metrics. It never pins the
pipeline's structure, so it has no per-stage, per-branch, per-cohort or
Coreference Critic rows.
Error analysis finds where a run broke.

| Task | Label quality | Primary | Headline rows | Diagnostic rows |
| --- | --- | --- | --- | --- |
| Relevance | Gold | RELEVANT F1 (pooled) | RELEVANT precision and recall; accuracy; confusion-matrix counts | none |
| Extraction | Silver | node F1 (pooled) | node precision and recall; relationship precision, recall and F1 (pooled); node and relationship F1 (per-case mean); ontology conformance rate | sub-label, node-property, claim-property and stance-alignment accuracy |
| Coreference | Silver | mention-span F1 (pooled) | mention-span precision and recall; B³ cluster F1 and canonical-entity accuracy, both pooled over mention spans both sides found; mention-span F1 (per-case mean) | none |
| Coreference annotator | Silver | mention-span F1 (pooled) | as Coreference | none |
| Policy Area Classification | Silver | Policy Area F1 (pooled) | Policy Area precision and recall (pooled); label-macro F1; per-case mean F1 | per-area precision, recall and F1 |
| Topic Assignment | Silver | assignment F1 (pooled) | assignment precision and recall (pooled); per-case mean F1 | none |
| Retrieval | Silver | fused Recall@10 (per-case mean) | fused Recall@5; fused reciprocal rank; fused complete evidence@10; final-context recall; final-context complete evidence | none |
| Chat | Unlabeled | none, with the reason "Unlabeled Set: no quality metric" | completed-answer rate; Declined, Deferred and needs-edit rates; p50 and p95 task duration | none |

Every task's headline rows also include `execution_failure_rate`, which the
table leaves out of each line to keep it readable.

Definitions that the table doesn't settle:

- **B³ cluster scores and canonical-entity accuracy** are pooled over every
  mention span both sides found, across all cases. That weights each mention
  equally.
- **Label-macro F1** is the mean F1 over the Policy Areas present in the
  selected cases' reference labels. Areas the model predicted but the
  reference never used appear only in pooled precision and in the per-area
  diagnostic rows.
- **Retrieval** keeps the per-question mean because each question is one
  information need.
- **The retrieval headline version** changes whenever the retrieval metric
  version recorded by compaction changes.
- **Chat's completed-answer rule** is the one the summary script applies today.
  Question status comes from the recorded question preparation or assessment
  status: Declined, Deferred or needs edit, using the glossary's distinction
  between Declined and Deferred. Today's summary counts only declines. Both
  rules move into the chat headline evaluator, and the summary reads the table.
- **Chat's task duration** covers only cases that completed without a recorded
  failure. Pydantic Evals records no duration for a case whose task raised, so
  a framework failure has none to contribute. The row's scored count, below the
  selected count, shows the gap.
- **Relevance's confusion-matrix counts** are four `Rate.quality` rows, one per
  cell, with the count as the numerator. Pydantic Evals' confusion-matrix
  evaluator isn't used, because the contract fixes a single table.
- **Ontology conformance** reads the recorded `StayedInsideTheNewsOntology`
  assertion instead of re-deriving it.

### Comparable Run and baseline

- Baseline selection applies the glossary's Comparable Run. A report matches
  on task, Data Set revision (compared by its recorded hash), the set of
  selected case IDs and headline version.
  Model Deployment, prompt digests and commit are the system under test and may
  differ.
- The evaluation summary script gains `--baseline auto|PATH|none`, defaulting
  to `auto`. `auto` considers only that task's reports with an earlier
  `ran_at` than the current one, and selects the newest Comparable Run among
  them. A dirty worktree never makes an older clean run win.
- An explicit baseline that isn't comparable is still reported, marked not
  comparable with the failed conditions. No deltas are shown for it.
- The summary gains a comparison block with:
  - the baseline path;
  - one of `comparable`, `comparable_with_caveat` or `not_comparable`;
  - each failed condition;
  - a delta for each primary and headline row.
- A dirty worktree on either side produces `comparable_with_caveat` and names
  which side is dirty.

### Scorecard

- The evaluation summary script gains `--format markdown`. JSON stays the
  default.
- Passing `--report` more than once renders a multi-axis scorecard. It opens
  with one row per axis: axis, label quality, primary metric, value, change,
  scored over selected cases, failure rate and comparison status. It never
  shows an overall score. Each axis's one-axis scorecard follows, in the same
  order. An Unlabeled axis shows "no quality metric" in place of a value.
- The script renders every number in the scorecard. An agent or a person
  copies it as it is.
- A one-axis scorecard has these parts, in order:
  - A heading naming the task, its primary metric and value, and the change
    against the baseline, or "no comparable baseline".
  - A population line: label quality, selection scope, and the selected,
    scored, failed and unresolved counts.
  - A baseline line: the baseline report and its comparison status, naming
    any failed conditions or caveats.
  - A table with the primary row first and then the headline rows in their
    declared order. Its columns are metric, value, baseline value, change,
    scored over selected cases, and aggregation.
  - One line per unavailable headline row, giving the metric and its reason.
  - A provenance line: commit and dirty state, Model Deployment, prompt
    digests, Data Set hash prefix, headline version, and links to the report
    and the trace.
- Diagnostic rows render in a collapsed section.
- The script's exit code is the scorecard's `exit_code` in both formats. A
  `--report` summary of a run with failures now exits nonzero, where today it
  exits 0.

### Existing readers

- **The evaluation summary script** becomes the thin caller described under
  Modules. Its population accounting moves into the run report module, and its
  generic per-score means become diagnostic output.
- **The RAG reviewer** takes its run-level metric values from the headline
  table, through `Headline.from_analyses`, when the report has one. Its case-level views and its reviewer-only
  measurements are unchanged.
- **The one-off chat measurement script pattern** ends. Latency becomes a chat
  headline row.
- **Retrieval report compaction** leaves the report's analyses untouched. It
  already avoids rescoring live runs. Inbox ED-08 removed the spent historical
  rescoring migration, so no tool rewrites a committed report's scores.

### Domain terms

This spec uses Headline Metric and Comparable Run as the glossary defines them.

## Testing Decisions

### What a good test is

A good test drives a seam with authored inputs and asserts only on what the
seam produces: a saved report document, or a `Scorecard`'s JSON, markdown and
exit code. It
never asserts on helper functions or intermediate structures. No test calls a
model; task callables are stubs that return authored outputs.

### Seam 1: the engine run

A Data Set runs through the evaluation engine and the report checkpoint, with a
stub task and the task's real case and headline evaluators. Assertions read the
saved report. Each task gets fixtures covering:

- the expected primary, headline and diagnostic rows;
- a case where both sides are empty, and a failed case that completes the run
  and appears in `execution_failure_rate`;
- for set-agreement tasks, a population where pooled and per-case F1 disagree;
- a headline evaluator that raises, which leaves an evaluator error in the
  final snapshot that serializes the same way on every run;
- for retrieval, a table that survives compaction unchanged.

Prior art: the persistence tests that run Data Sets through the engine with stub
tasks and checkpoints, including their preservation of report evaluator errors.
Prior art for fixtures: the per-task evaluation tests for extraction,
coreference, Policy Area Classification, Topic Assignment and retrieval.

### Seam 2: the run report module's interface

The summary script is one of the readers this spec replaces, so its command
line is not a test seam. Tests load saved report documents written to a
temporary directory with `ReportDocument.load`, build a `Scorecard` with
`Scorecard.build`, and assert only on `to_json()`, `to_markdown()` and
`exit_code`.

- **Baseline selection:** each non-matching condition is rejected on its own
  (Data Set revision, selected case IDs, headline version, task and incomplete
  status). Model Deployment and prompt digests may differ.
- **Explicit baselines** that aren't comparable produce no deltas.
- **Dirty worktrees** produce the caveat, and a newer dirty Comparable Run
  beats an older clean one.
- **Later reports** are never chosen as the automatic baseline.
- **The exit code** is the same in both formats.
- **Reports without a headline table** summarize as predating Headline Metrics, or as an incomplete run, whichever applies.
- **The markdown scorecard** is snapshot-stable for one axis and for three
  axes, including a chat axis.

The summary script gets one smoke test. It runs `--report` against a saved
document and checks that the output and exit code come from the `Scorecard`.
The existing run-evaluation tests that summarize saved and historical
documents move to this seam. The script's plan and execute tests stay where
they are.

Prior art: the run-evaluation tests that summarize saved and historical
documents without model calls.

### Reviewer agreement

The reviewer's existing JavaScript tests gain a fixture whose run-level metrics
come from a headline table.

## Out of Scope

- Recomputing headline tables for historical reports.
- The `report-evaluation` skill and its agent slots. On 2026-10-16 the
  maintainer deferred them until they have seen how evaluations they ask an
  LLM to perform come out once the scorecard exists. The parked design is in
  the [skill design](skill-design.md). The `run-evaluation` skill is unchanged.
- Re-baseline runs for each task. They make model calls and follow
  implementation.
- First runs of Policy Area Classification and Topic Assignment, beyond their
  re-baseline.
- Graded relevance labels, and therefore NDCG values.
- A quality metric for chat. That needs reference answers or a validated judge,
  and belongs in its own project.
- Confidence intervals and significance testing. Until then, the scorecard
  shows numerators and denominators beside every rate.
- Any persistence beyond the Evaluation Report file.

## Further Notes

- The audit behind this spec was run on 2026-10-16 at `42041c0f`.
- Extraction's 16 reports are the strongest existing series. Even so, their
  pooled F1 can't be recovered without rerunning them.
- The archived metric-canonicalization ticket under the ADR 0017 archive gave
  metric identity a database ledger. ADR 0026 keeps identity in code and the
  report file instead.
- The maintainer confirmed three choices on 2026-10-16:
  - F1 is primary for relevance and coreference.
  - Retrieval uses the per-case mean.
  - A dirty worktree is a caveat, not a block.
