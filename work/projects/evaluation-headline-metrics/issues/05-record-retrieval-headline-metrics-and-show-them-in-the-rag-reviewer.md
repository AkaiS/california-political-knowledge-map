# 05: Record Retrieval Headline Metrics and show them in the RAG reviewer

**What to build:** A completed retrieval run records its Headline Metrics,
which survive report compaction unchanged. The RAG reviewer takes its
run-level metric values from that table, so the reviewer and the report agree.

**Blocked by:** 01, Record Headline Metrics end to end for Relevance.

Labels: ready-for-agent

- [ ] Retrieval declares a headline version, which changes whenever the
  retrieval metric version recorded by compaction changes.
- [ ] The primary row is fused Recall@10, as a per-case mean.
- [ ] The headline rows are:
  - fused Recall@5;
  - fused reciprocal rank;
  - fused complete evidence@10;
  - final-context recall;
  - final-context complete evidence;
  - each branch's completion rate;
  - `execution_failure_rate`.
- [ ] The diagnostic rows are:
  - each branch's Recall@1/5/10/50, reciprocal rank and complete
    evidence@5/10;
  - Precision@k;
  - NDCG@10, null with the reason that relevance grades don't exist yet.
- [ ] Compaction leaves the report's headline table byte-for-byte unchanged.
- [ ] When a report has a headline table, the RAG reviewer shows the table's
  run-level values. Case-level views and reviewer-only measurements are
  unchanged.
- [ ] An engine-run test proves the table survives compaction. A reviewer test
  proves the reviewer shows the table's fused Recall@10 for a fixture report.
