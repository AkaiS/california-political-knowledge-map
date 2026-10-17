# 03: Record Coreference and Coreference annotator Headline Metrics

**What to build:** Completed Coreference and Coreference annotator runs record
the same agreement Headline Metrics, so their reports subtract. The full loop
also reports what the Coreference Critic's decisions were worth. This ticket
adds the headline module's `Pooled` measure. B³ cluster
scores use the four-field `Counts`, whose precision and recall numerators
differ.

**Blocked by:** 02, Record Extraction Headline Metrics.

Labels: ready-for-agent

- [ ] Both tasks declare their own `-v1` headline versions. The primary row for
  each is pooled mention-span F1.
- [ ] Both tasks' headline rows are:
  - mention-span precision and recall;
  - B³ cluster precision, recall and F1, pooled over every mention span both
    sides found, through `SetAgreement` with `Counts`;
  - canonical-entity accuracy, through `Pooled` over the same shared spans;
  - mention-span F1 as a per-case mean;
  - the automatic `execution_failure_rate`.
- [ ] Coreference's diagnostic rows are Critic rejection precision, rejection
  recall and kept-correct rate. Each is a `Pooled` row over every judged
  critic decision across cases.
- [ ] The annotator task declares the same critic rows as `Unavailable`, with
  the reason that it makes no critic decisions.
- [ ] Engine-run tests cover both tasks on shared fixtures, including a failed
  case, cases with no shared mention spans, and a B³ case where pooled
  precision and recall differ.
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
