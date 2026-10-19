# 06: Record chat operational Headline Metrics

**What to build:** A completed chat run on an Unlabeled Set records
operational Headline Metrics and says plainly that it has no quality metric.
Declined, Deferred and needs-edit questions are reported separately, and
latency is reported without a one-off script. This ticket adds the headline
module's `Quantile` measure. The table records only outcomes a user would
observe, so it has no per-stage, per-branch or per-cohort rows.

**Blocked by:** 01, Record Headline Metrics end to end for Relevance.

Labels: completed

- [x] Chat declares `chat-v1`. Its primary row is `Unavailable` with the
  reason "Unlabeled Set: no quality metric".
- [x] The headline rows are:
  - completed-answer rate;
  - Declined, Deferred and needs-edit rates;
  - p50 and p95 task duration;
  - the automatic `execution_failure_rate`.
- [x] Chat has no diagnostic rows.
- [x] Completed-answer and question-status tests are `Rate.operational`, so
  they count over the whole run population. A stage failure recorded in a
  case's output counts toward `execution_failure_rate` and adds no row of its
  own; no row names a stage. An answer rendered before a later stage failed
  still counts as a completed answer, as the summary's rule does today.
- [x] The completed-answer rule reproduces the summary's current rule,
  including an answer whose introduction is null.
- [x] Question status comes from the recorded question preparation or
  assessment status, using the glossary's distinction between Declined and
  Deferred.
- [x] Task duration covers only cases that completed without a recorded
  failure. Pydantic Evals records no duration for a case whose task raised.
  The rows' scored counts show the gap.
- [x] The summary script's own chat completed-answer and decline rules are
  deleted. The run report module takes those counts from the table.
- [x] Engine-run tests cover each question status, a stage failure recorded in
  output, a framework failure, a null answer introduction, and a headline
  evaluator that raises.
- [x] Depth rule, tasks declare: every task touched supplies only a
  `HeadlineDefinition` built from the closed measure set and functions over a
  single case. No task defines a `ReportEvaluator`, builds table rows, or
  computes a population or failure rate.
- [x] Depth rule, readers call: only the run report module classifies reports,
  accounts for the population, compares or renders. The summary script and
  the RAG reviewer gain none of that logic, and nothing outside the headline
  and run report modules parses table rows.
- [x] Depth rule, two seams: tests cross only the engine-run seam and the run
  report module's interface (`ReportDocument.load` and `Scorecard.build`). The
  summary script's command line keeps its single smoke test and gains no other
  test. No test imports a measure's internals or adds a module-level test
  seam.

## Comments

- 2026-10-19, review: the summary's `completed_answers` and `declined` counts
  are now the numerators of the table's `completed_answer_rate` and
  `declined_rate` rows. A report without those rows gives null: historical and
  incomplete chat runs, a failed headline evaluator, and every non-chat task.
  Retrieval runs counted completed answers before this change and now give
  null, because `retrieval-v1` has no completed-answer row. Whether retrieval
  should keep that count is open for the user.
