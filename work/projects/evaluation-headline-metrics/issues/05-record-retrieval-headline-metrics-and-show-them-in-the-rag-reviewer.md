# 05: Record Retrieval Headline Metrics and show them in the RAG reviewer

**What to build:** A completed retrieval run records its Headline Metrics,
which survive report compaction unchanged. The RAG reviewer takes its
run-level values from that table through `Headline.from_analyses`, so the
reviewer and the report agree.

**Blocked by:** 02, Record Extraction Headline Metrics.

Labels: ready-for-agent

- [ ] Retrieval's headline version comes from a literal lookup keyed by the
  retrieval metric version that compaction records. A new metric version fails
  at import until a new headline version is added.
- [ ] The primary row is fused Recall@10, as a `CaseMean` of the recorded
  score.
- [ ] The headline rows are:
  - fused Recall@5;
  - fused reciprocal rank;
  - fused complete evidence@10;
  - final-context recall;
  - final-context complete evidence;
  - each branch's completion rate;
  - the automatic `execution_failure_rate`.
- [ ] The diagnostic rows are:
  - each branch's Recall@1/5/10/50, reciprocal rank and complete
    evidence@5/10;
  - Precision@k;
  - NDCG@10, declared as `Unavailable` until relevance grades exist.
- [ ] Compaction leaves the report's headline table byte-for-byte unchanged.
- [ ] The RAG reviewer calls only `Headline.from_analyses`. The mapping from
  its metric names to case score names moves out of the summary script and
  into the reviewer. Case-level views and reviewer-only measurements are
  unchanged.
- [ ] An engine-run test proves the table survives compaction. A reviewer test
  proves the reviewer shows the table's fused Recall@10 for a fixture report.
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
