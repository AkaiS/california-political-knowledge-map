# 04: Record Policy Area Classification and Topic Assignment Headline Metrics

**What to build:** Completed Policy Area Classification and Topic Assignment
runs record pooled agreement Headline Metrics. Policy Area Classification also
reports a label-macro F1, so a common area can't hide failure on rare ones.
This ticket adds the headline module's `PerLabel` measure.

**Blocked by:** 02, Record Extraction Headline Metrics.

Labels: ready-for-agent

- [ ] Both tasks declare their own `-v1` headline versions.
- [ ] Policy Area Classification's primary row is pooled Policy Area F1. Its
  headline rows are pooled precision and recall, label-macro F1, per-case mean
  F1 and the automatic `execution_failure_rate`.
- [ ] `PerLabel` produces the label-macro F1 headline row over the Policy Areas
  present in the selected cases' reference labels. It also produces per-area
  precision, recall and F1 as diagnostic rows, including areas that were only
  predicted.
- [ ] Topic Assignment's primary row is pooled assignment F1. Its headline rows
  are pooled precision and recall, per-case mean F1 and the automatic
  `execution_failure_rate`.
- [ ] Both-empty cases add zero to pooled counts. Their recorded per-case pass
  still feeds the per-case mean.
- [ ] Engine-run tests cover both tasks, including a fixture where label-macro
  and pooled F1 disagree.
- [ ] Depth rule, tasks declare: every task touched supplies only a
  `HeadlineDefinition` built from the closed measure set and functions over a
  single case. No task defines a `ReportEvaluator`, builds table rows, or
  computes a population or failure rate.
- [ ] Depth rule, readers call: only the run report module classifies reports,
  accounts for the population, compares or renders. The summary script and
  the RAG reviewer gain none of that logic, and nothing outside the headline
  and run report modules parses table rows.
- [ ] Depth rule, two seams: tests cross only the engine-run seam and the
  summary script's entry point. No test imports a measure's internals or adds
  a module-level test seam.
