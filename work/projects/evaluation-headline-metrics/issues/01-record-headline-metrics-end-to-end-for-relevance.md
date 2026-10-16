# 01: Record Headline Metrics end to end for Relevance

**What to build:** A completed Relevance Evaluation Run records its Headline
Metrics in its Evaluation Report, and the evaluation summary reads them from
there. This ticket builds the shared contract every later task uses:

- a headline report evaluator and an immutable headline version on each task;
- the run passing that evaluator to the engine;
- the headline version recorded in provenance;
- the summary reading headline rows instead of re-averaging case scores.

Relevance is the first task through it, because it is the only Gold Set and its
outputs are the simplest. See the
[Evaluation headline metrics PRD](../PRD.md) and ADR 0026.

**Blocked by:** None (can start immediately).

Labels: ready-for-agent

- [ ] Every task can declare a headline report evaluator and an immutable
  headline version. Relevance declares `relevance-v1`.
- [ ] A completed Relevance run's report contains one table titled
  `Headline metrics`. Its columns are metric, role, value, numerator,
  denominator, aggregation, scored cases, selected cases and unavailable
  reason.
- [ ] Relevance's primary row is pooled RELEVANT F1. Its headline rows are
  RELEVANT precision and recall, accuracy, the confusion-matrix counts and
  `execution_failure_rate`.
- [ ] The run population is the completed cases plus the failed cases, and it
  depends on no experiment metadata. A direct `ca-map eval run` and a run
  started by the summary script give the same table.
- [ ] A failed case completes the run, counts toward `execution_failure_rate`
  and adds no value to a quality metric.
- [ ] An incomplete run keeps its saved results, has no headline table, and
  its summary says it is incomplete.
- [ ] A failure inside the headline report evaluator is preserved in the final
  snapshot, counted as an evaluator error, and gives a nonzero exit.
- [ ] The headline version appears in the report's provenance beside the Data
  Set hash and the prompt digests.
- [ ] The summary reads headline rows from the report. Its generic per-score
  means move to diagnostic output, and its population accounting is
  unchanged. A report without a headline table summarizes as predating
  Headline Metrics.
- [ ] Tests run a Data Set through the engine and report checkpoint with a stub
  task, and assert only on the saved report and the summary's output. No test
  calls a model.
