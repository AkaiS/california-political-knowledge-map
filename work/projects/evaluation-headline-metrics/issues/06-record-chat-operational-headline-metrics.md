# 06: Record chat operational Headline Metrics

**What to build:** A completed chat run on an Unlabeled Set records
operational Headline Metrics and says plainly that it has no quality metric.
Declined, Deferred and needs-edit questions are reported separately, and
latency is reported without a one-off script. This ticket adds the headline
module's `Quantile` measure and the `by=` grouping on `Rate.operational`.

**Blocked by:** 01, Record Headline Metrics end to end for Relevance.

Labels: ready-for-agent

- [ ] Chat declares `chat-v1`. Its primary row is `Unavailable` with the
  reason "Unlabeled Set: no quality metric".
- [ ] The headline rows are:
  - completed-answer rate;
  - Declined, Deferred and needs-edit rates;
  - failure rate for each stage, grouped with `by=`;
  - p50 and p95 task duration;
  - the automatic `execution_failure_rate`.
- [ ] Completed-answer and question-status tests are `Rate.operational`, so
  they count over the whole run population. A stage failure recorded in a
  case's output counts toward its stage's rate.
- [ ] The completed-answer rule reproduces the summary's current rule,
  including an answer whose introduction is null.
- [ ] Question status comes from the recorded question preparation or
  assessment status, using the glossary's distinction between Declined and
  Deferred.
- [ ] Task duration covers only cases that completed without a recorded
  failure. Pydantic Evals records no duration for a case whose task raised.
  The rows' scored counts show the gap.
- [ ] The diagnostic rows are question-status rates by the authored cohort and
  branch outcomes by status, both through `by=`.
- [ ] The summary script's own chat completed-answer and decline rules are
  deleted. The run report module takes those counts from the table.
- [ ] Engine-run tests cover each question status, a stage failure recorded in
  output, a framework failure, and a null answer introduction.
- [ ] Depth rule, tasks declare: every task touched supplies only a
  `HeadlineDefinition` built from the closed measure set and functions over a
  single case. No task defines a `ReportEvaluator`, builds table rows, or
  computes a population or failure rate.
- [ ] Depth rule, readers call: only the run report module classifies reports,
  accounts for the population, compares or renders. The summary script and
  the RAG reviewer gain none of that logic, and nothing outside the headline
  and run report modules parses table rows.
- [ ] Depth rule, two seams: tests cross only the engine-run seam and the run
  report module's interface (`ReportDocument.load` and `Scorecard.build`). The
  summary script's command line keeps its single smoke test and gains no other
  test. No test imports a measure's internals or adds a module-level test
  seam.
