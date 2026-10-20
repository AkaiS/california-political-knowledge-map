# 05: Record Retrieval Headline Metrics and show them in the RAG reviewer

**What to build:** A completed retrieval run records its Headline Metrics,
which survive report compaction unchanged. The RAG reviewer takes its
run-level values from that table through `Headline.from_analyses`, so the
reviewer and the report agree.

**Blocked by:** 02, Record Extraction Headline Metrics.

Labels: completed

- [x] Retrieval's headline version comes from a literal lookup keyed by the
  retrieval metric version that compaction records. A new metric version fails
  at import until a new headline version is added.
- [x] The primary row is fused Recall@10, as a `CaseMean` of the recorded
  score.
- [x] The headline rows are:
  - the completed-answer rate, by the rule Chat uses;
  - fused Recall@5;
  - fused reciprocal rank;
  - fused complete evidence@10;
  - final-context recall;
  - final-context complete evidence;
  - the automatic `execution_failure_rate`.
- [x] Retrieval has no diagnostic rows.
- [x] Compaction leaves the report's headline table byte-for-byte unchanged.
- [x] The RAG reviewer calls only `Headline.from_analyses`. The mapping from
  its metric names to case score names moves out of the summary script and
  into the reviewer. Case-level views and reviewer-only measurements are
  unchanged.
- [x] An engine-run test proves the table survives compaction. A reviewer test
  proves the reviewer shows the table's fused Recall@10 for a fixture report.
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
  outcomes a user would observe, never pipeline structure. `retrieval-v1` was
  trimmed in place: each branch's completion rate, every per-branch and
  Precision@k diagnostic row, and the unavailable NDCG@10 row are gone. No
  real run had recorded `retrieval-v1`, so the version name stays. The RAG
  reviewer's case-level branch views are unchanged and serve error analysis.
- 2026-10-19, user decision after ticket 06: every end-to-end run ends in a
  plain pass/fail. Ticket 06 moved the completed-answer rule from the summary
  script into Chat's headline, which left a retrieval run's summary with
  `completed_answers: null`. `retrieval-v1` now records
  `completed_answer_rate` right after the primary row, as an operational rate
  by the same rule Chat uses, shared rather than copied. It is not the
  complement of `execution_failure_rate`: a question whose Evidence Assembly
  failed is neither a failed case nor an answer. No real run had recorded
  `retrieval-v1`, so the version name stays.
