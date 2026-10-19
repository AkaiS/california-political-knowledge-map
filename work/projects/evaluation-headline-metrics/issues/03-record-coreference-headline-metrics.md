# 03: Record Coreference and Coreference annotator Headline Metrics

**What to build:** Completed Coreference and Coreference annotator runs record
the same agreement Headline Metrics, so their reports subtract. This ticket
adds the headline module's `Pooled` measure. B³ cluster
scores use the four-field `Counts`, whose precision and recall numerators
differ.

**Blocked by:** 02, Record Extraction Headline Metrics.

Labels: completed

- [x] Both tasks declare their own `-v1` headline versions. The primary row for
  each is pooled mention-span F1.
- [x] Both tasks' headline rows are:
  - mention-span precision and recall;
  - B³ cluster precision, recall and F1, pooled over every mention span both
    sides found, through `SetAgreement` with `Counts`;
  - canonical-entity accuracy, through `Pooled` over the same shared spans;
  - mention-span F1 as a per-case mean;
  - the automatic `execution_failure_rate`.
- [x] Neither task has diagnostic rows.
- [x] Engine-run tests cover both tasks on shared fixtures, including a failed
  case, cases with no shared mention spans, and a B³ case where pooled
  precision and recall differ.
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

- 2026-10-19, user decision during ticket 06: headline tables record only
  outcomes a user would observe, never pipeline structure. The Coreference
  Critic is a stage inside the loop, so coreference-v1 lost its three Critic
  diagnostic rows and coreference_annotator-v1 lost the matching
  `Unavailable` rows. No real run had recorded either version, so the version
  names stay. The per-case Critic scores the case evaluators record are
  unchanged and serve error analysis.
