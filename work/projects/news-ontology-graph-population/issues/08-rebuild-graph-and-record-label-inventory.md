Labels: ready-for-agent

## Parent

[News Ontology and Graph Population](../PRD.md)

## What to build

The graph that every other Useful Graph Retrieval ticket is waiting on, plus the
facts they need from it.

There is no migration. The existing Neo4j database was populated under a
superseded ontology and is dropped rather than migrated, so that no node built
against the old shape survives. The gathered Source Articles are re-chunked,
re-embedded and re-ingested from the SQLite document store, which retains their
content, and the run is end-to-end under the new rules.

The parent ticket then gets its answer, produced by hand-run Cypher and recorded
once: which ontology labels and relationship types materialized and at what
counts, and which stayed empty. **Empty labels must be split into two kinds** —
those the News Ontology excludes outright, which are structurally unreachable
from news, and those it includes that simply produced nothing. The corpus is a
thin basis for conclusions about coverage: an included-but-empty label may mean
news cannot reach it, or merely that the gathered articles did not happen to
mention it, and the record should say so rather than imply the stronger claim.

Count the corpus at run time and record that number — do not carry a figure over
from this ticket. The document store held 73 Source Articles as of 2026-08-14,
all `UNPROCESSED`, and the ingestion path applies no relevance filter, so the
run covers all of them.

The adherence report from the run is read alongside the counts — a label the
prompt keeps producing and conformance keeps dropping is a different finding from
a label nobody mentioned.

No reporting CLI command is built. This is a one-time inventory, not a recurring
metric.

## Acceptance criteria

- [ ] The existing Neo4j database is dropped, not migrated.
- [ ] All gathered Source Articles are re-chunked, re-embedded and re-ingested,
      and the run completes.
- [ ] Materialized labels and relationship types are counted by hand-run Cypher
      and recorded on the parent ticket.
- [ ] Empty labels are recorded in two groups: News-Ontology-excluded, and
      included-but-unproduced.
- [ ] The record states the corpus size and does not overclaim from it.
- [ ] The run's adherence report is summarized alongside the counts.
- [ ] The full deterministic suite passes, and the count is recorded as a dated
      observation.

## Blocked by

- [03 — Extraction Prompt generated from the News Ontology](03-generate-extraction-prompt-from-news-ontology.md)
- [04 — Sub-labels and Entity Extraction Adapter conformance](04-sub-labels-and-extraction-conformance.md)
- [06 — Node identity, provenance, and topic edges](06-node-identity-provenance-and-topic-edges.md)
- [07 — Bill session resolution from article links](07-bill-session-resolution.md)
