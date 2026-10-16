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

The scorecard layout is defined in the
[skill design](skill-design.md#scorecard-layout). A reporting skill for agents
is deferred; see Out of Scope.

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
29. As the maintainer, I want retrieval's branch completion rates in the headline, so that a failing branch is visible next to recall.
30. As the maintainer, I want NDCG shown as unavailable, with its reason, until relevance grades exist, so that its absence is explained rather than silent.
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

### Headline Metric contract

- The evaluation task registry gains two fields per task: a headline report
  evaluator and an immutable headline version string, such as `relevance-v1`.
- The headline report evaluator returns one Pydantic Evals `TableResult` titled
  `Headline metrics`.
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
- `ca-map eval run` passes the task's headline report evaluator to the
  evaluation engine. No other run path is added.

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

- The set-agreement scoring helpers gain a count form alongside the existing
  ratio form. Case evaluators and headline report evaluators call the same
  identity functions, so a pooled count and a case score always agree on what
  matched.
- Per-case score names in reports are unchanged.
- A case where both sides are empty keeps each task's documented per-case pass.
  It contributes zero to every pooled count.

### Version 1 headline sets

| Task | Label quality | Primary | Headline rows | Diagnostic rows |
| --- | --- | --- | --- | --- |
| Relevance | Gold | RELEVANT F1 (pooled) | RELEVANT precision and recall; accuracy; confusion-matrix counts | none |
| Extraction | Silver | node F1 (pooled) | node precision and recall; relationship precision, recall and F1 (pooled); node and relationship F1 (per-case mean); ontology conformance rate | sub-label, node-property, claim-property and stance-alignment accuracy |
| Coreference | Silver | mention-span F1 (pooled) | mention-span precision and recall; B³ cluster F1 and canonical-entity accuracy, both pooled over mention spans both sides found; mention-span F1 (per-case mean) | Coreference Critic rejection precision, rejection recall and kept-correct rate |
| Coreference annotator | Silver | mention-span F1 (pooled) | as Coreference | none |
| Policy Area Classification | Silver | Policy Area F1 (pooled) | Policy Area precision and recall (pooled); label-macro F1; per-case mean F1 | per-area precision, recall and F1 |
| Topic Assignment | Silver | assignment F1 (pooled) | assignment precision and recall (pooled); per-case mean F1 | none |
| Retrieval | Silver | fused Recall@10 (per-case mean) | fused Recall@5; fused reciprocal rank; fused complete evidence@10; final-context recall; final-context complete evidence; completion rate for each branch | each branch's Recall@1/5/10/50, reciprocal rank and complete evidence@5/10; Precision@k; NDCG@10, unavailable until relevance grades exist |
| Chat | Unlabeled | none, with the reason "Unlabeled Set: no quality metric" | completed-answer rate; Declined, Deferred and needs-edit rates; failure rate for each stage; p50 and p95 task duration | question-status rates by authored cohort; branch outcomes by status |

Definitions that the table doesn't settle:

- **B³ cluster scores and canonical-entity accuracy** are pooled over every
  mention span both sides found, across all cases. That weights each mention
  equally.
- **Coreference Critic rows** are pooled over every judged critic decision
  across cases. Rejection precision is wrong spans rejected over all rejections.
  Rejection recall is wrong spans rejected over all wrong spans. The
  kept-correct rate is correct spans kept over all correct spans. The rows are
  unavailable on the annotator task, which makes no critic decisions.
- **Label-macro F1** is the mean F1 over the Policy Areas present in the
  selected cases' reference labels. Areas the model predicted but the
  reference never used appear only in pooled precision and in the per-area
  diagnostic rows.
- **Retrieval** keeps the per-question mean because each question is one
  information need. Precision@k stays diagnostic because unlisted chunks may be
  relevant against provisional labels.
- **The retrieval headline version** changes whenever the retrieval metric
  version recorded by compaction changes.
- **Chat's completed-answer rule** is the one the summary script applies today.
  Question status comes from the recorded question preparation or assessment
  status: Declined, Deferred or needs edit, using the glossary's distinction
  between Declined and Deferred. Today's summary counts only declines. Both
  rules move into the chat headline evaluator, and the summary reads the table.
- **Chat's question-status rates by cohort** use the cohort each case's
  authors recorded. This shows whether declined and deferred controls were
  handled as intended without claiming answer quality.
- **Chat's task duration** is the duration Pydantic Evals records for each
  completed and failed case.

### Comparable Run and baseline

- Baseline selection applies the glossary's Comparable Run. A report matches
  on task, Data Set hash, the set of selected case IDs and headline version.
  Model Deployment, prompt digests and commit are the system under test and may
  differ.
- The evaluation summary script gains `--baseline auto|PATH|none`, defaulting
  to `auto`. `auto` selects the newest Comparable Run among that task's
  committed reports.
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
- Passing `--report` more than once renders a multi-axis scorecard.
- The scorecard layout section of the skill design defines the layout. The
  script renders every number in it.
- Diagnostic rows render in a collapsed section.

### Existing readers

- **The evaluation summary script** reads headline rows from the report's
  analyses. It keeps its population accounting. Its generic per-score means
  become diagnostic output.
- **The RAG reviewer** takes its run-level metric values from the headline
  table when the report has one. Its case-level views and its reviewer-only
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
seam produces: a saved report document or the summary script's output. It
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
  final snapshot;
- for retrieval, a table that survives compaction unchanged.

Prior art: the persistence tests that run Data Sets through the engine with stub
tasks and checkpoints, including their preservation of report evaluator errors.
Prior art for fixtures: the per-task evaluation tests for extraction,
coreference, Policy Area Classification, Topic Assignment and retrieval.

### Seam 2: the evaluation summary script

The script's command-line entry point runs against saved report documents.

- **Baseline selection:** each non-matching condition is rejected on its own
  (Data Set hash, selected case IDs, headline version, task and incomplete
  status). Model Deployment and prompt digests may differ.
- **Explicit baselines** that aren't comparable produce no deltas.
- **Dirty worktrees** produce the caveat.
- **Reports without a headline table** summarize as predating Headline Metrics, or as an incomplete run, whichever applies.
- **The markdown scorecard** is snapshot-stable for one axis and for three
  axes, including a chat axis.

Prior art: the run-evaluation tests that summarize saved and historical
documents and drive the script's entry point without model calls.

### Reviewer agreement

The reviewer's existing JavaScript tests gain a fixture whose run-level metrics
come from a headline table.

## Out of Scope

- Recomputing headline tables for historical reports.
- Implementation tickets. Breaking this spec into tickets is a separate request.
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
