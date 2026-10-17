# 01: Record Headline Metrics end to end for Relevance

**What to build:** A completed Relevance Evaluation Run records its Headline
Metrics in its Evaluation Report, and the evaluation summary reads them back.
This ticket creates both modules from the PRD's Modules section, at the
smallest size Relevance needs:

- **The headline module:** `HeadlineRow` and `Headline` with their validators
  and the `to_table` / `from_analyses` codec; `HeadlineDefinition` and its one
  `ReportEvaluator` adapter; the run population; and the `Counts`,
  `SetAgreement`, `Rate` and `Unavailable` measures.
- **The run report module:** `ReportDocument.load`, the `NoHeadline` reasons,
  population accounting, today's diagnostic output, and a JSON-only
  `Scorecard` with `exit_code` and the baseline fixed at `none`.

The summary script and `ca-map eval run` become callers of these modules.
Relevance, the only Gold Set, is the first task through them. See the
[Evaluation headline metrics PRD](../PRD.md) and ADR 0026.

**Blocked by:** None (can start immediately).

Labels: ready-for-agent

- [ ] The evaluation task registry gains an optional `headline` field. When a
  task declares one, `ca-map eval run` passes its evaluator to the engine and
  records its version beside the prompt digests.
- [ ] The rule for a failed outcome moves out of `ca-map eval run` into the
  headline module, and the run's exit code uses it. A failed outcome is a
  framework failure, or a completed case whose output records a failure.
- [ ] Relevance declares `relevance-v1`. Its primary row is pooled RELEVANT
  F1. Its headline rows are RELEVANT precision and recall, accuracy, the four
  confusion-matrix cells as `Rate.quality` count rows, and the automatic
  `execution_failure_rate`.
- [ ] `detection_counts` returns `Counts`. `detection_scores` is rewritten on
  top of it, and every existing per-case score is unchanged.
- [ ] A failed case completes the run, counts toward `execution_failure_rate`,
  and adds nothing to quality rows.
- [ ] An incomplete run summarizes with `NoHeadline` reason `incomplete_run`.
  A report from before headlines summarizes with `predates_headline_metrics`.
- [ ] A raising headline evaluator is recorded as a report evaluator failure.
  Its serialization is the same on every run, the summary shows
  `headline_evaluator_failed`, and the exit code is nonzero.
- [ ] The summary script's `--report` output comes from `Scorecard.to_json`,
  with existing summary keys kept and the headline added. Its exit code is
  `Scorecard.exit_code`.
- [ ] Planned runs keep working through a thin wrapper over a single-axis
  `Scorecard`.
- [ ] Engine-run tests cover a stub Relevance task with authored outputs,
  including failed, both-negative and evaluator-error cases. `Scorecard` tests
  load saved documents for each `NoHeadline` reason. The existing tests that
  summarize saved and historical documents move to the `Scorecard` interface.
- [ ] The summary script gets its one smoke test. `--report` on a saved
  document prints the `Scorecard`'s JSON and exits with its `exit_code`.
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
