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

Labels: completed

- [x] The evaluation task registry gains an optional `headline` field. When a
  task declares one, `ca-map eval run` passes its evaluator to the engine and
  records its version beside the prompt digests.
- [x] The rule for a failed outcome moves out of `ca-map eval run` into the
  headline module, and the run's exit code uses it. A failed outcome is a
  framework failure, or a completed case whose output records a failure.
- [x] Relevance declares `relevance-v1`. Its primary row is pooled RELEVANT
  F1. Its headline rows are RELEVANT precision and recall, accuracy, the four
  confusion-matrix cells as `Rate.quality` count rows, and the automatic
  `execution_failure_rate`.
- [x] `detection_counts` returns `Counts`. `detection_scores` is rewritten on
  top of it, and every existing per-case score is unchanged.
- [x] A failed case completes the run, counts toward `execution_failure_rate`,
  and adds nothing to quality rows.
- [x] An incomplete run summarizes with `NoHeadline` reason `incomplete_run`.
  A report from before headlines summarizes with `predates_headline_metrics`.
- [x] A raising headline evaluator is recorded as a report evaluator failure.
  Its serialization is the same on every run, the summary shows
  `headline_evaluator_failed`, and the exit code is nonzero.
- [x] The summary script's `--report` output comes from `Scorecard.to_json`,
  with existing summary keys kept and the headline added. Its exit code is
  `Scorecard.exit_code`.
- [x] Planned runs keep working through a thin wrapper over a single-axis
  `Scorecard`.
- [x] Engine-run tests cover a stub Relevance task with authored outputs,
  including failed, both-negative and evaluator-error cases. `Scorecard` tests
  load saved documents for each `NoHeadline` reason. The existing tests that
  summarize saved and historical documents move to the `Scorecard` interface.
- [x] The summary script gets its one smoke test. `--report` on a saved
  document prints the `Scorecard`'s JSON and exits with its `exit_code`.
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

- 2026-10-17, review: every acceptance criterion is met (d61edd42 plus the
  review fixes). The label stays `ready-for-agent` for one open question:
  `ReportDocument.load` takes an added `expected_case_ids` keyword (the
  planned run's check against the selection manifest), and `Scorecard.build`
  takes an added `reviewer_port` keyword (the reviewer link). The PRD fixes
  `load(path)` and `build(documents, baseline)`. The maintainer decides
  whether to keep these options or move them.
- 2026-10-18, resolution (maintainer approved): `ReportDocument.load(path)`
  now matches the PRD. A report that records its selection
  (`experiment_metadata.selection.case_ids`) is checked against its own
  `evaluation_run.selected_case_ids` and outcomes on every load, so a
  disagreement reads as `selection_manifest_mismatch` with a nonzero exit.
  `Scorecard.build` keeps `reviewer_port`, and the PRD's Modules section now
  lists it. Label set to `completed`.
