# Useful Graph Retrieval

Labels: wayfinder:map, needs-triage

## Destination

Reach a decision-ready Useful Graph Retrieval initiative with ready-for-agent
PRDs specifying the retrieval and answering layer over the settled ontology: its
typed retrieval and answer contract including citations and evidence, its
retrieval modes and index inventory, query construction and validation, the
retrieval agent topology, graph-aware reranking, and the developer surface —
together with a populated graph that those decisions were made against.

This map realizes roadmap outcome 4, [Useful graph retrieval](../../roadmap.md).

## Notes

- Use `/grilling` and `/domain-modeling` when resolving decisions; read
  `CONTEXT.md` before exploration.
- **The ontology is settled.** [`ontology.md`](../../../ontology.md) is a fixed
  input to this map, not a subject of it. Retrieval is designed against the
  whole ontology, including the legislative and campaign-finance layers that
  news ingestion alone cannot populate, so the contract survives roadmap
  outcome 5 without being reopened.
- **Entity identity uses own IDs.** Current retrieval uses internal IDs. The
  authored ontology declares `ExternalIdentifier` nodes and `HAS_IDENTIFIER`
  for eventual reconciliation with authoritative records. Ticket 06 defers
  implementing external-identifier storage, lookup, and indexes until a concrete
  ingestion or retrieval need arises. The ontology's registry-keyed primary keys
  remain the eventual authority rather than a constraint on news extraction.
- **First consumer is the developer** investigating California politics through
  a local surface. The retrieval and answer contract must nonetheless carry
  citations and evidence as first-class typed output, so that adding a chat UI
  is a rendering job rather than a redesign of the retrieval layer. Provenance
  to a Source Article is a product principle and belongs in the contract at
  every audience.
- **This map carries a narrow execution override.** `task` tickets do real work
  where a decision is blocked without it, and `prototype` tickets build
  throwaway retrieval code against the real populated graph. Every other ticket
  resolves as a decision and hands implementation to a PRD.
- Retrieval spans three orientations: **entity lookup**, **relationship
  lookup**, and **multi-hop traversal**. The roadmap originally named four —
  entity, edge, neighborhood, and community — and the
  [target question set](issues/02-target-question-set.md) cut them to three.
- **The corpus grounds the answer.** Full-text search, graph connections, and
  Article Chunk embedding retrieval are routes to that evidence. A missing extracted
  relationship does not exclude a relevant source found through another route,
  as accepted during [ticket 04](issues/04-retrievable-subgraph-now.md)'s grilling.
  See **Grounding Evidence** in `CONTEXT.md`.
- [Ticket 04](issues/04-retrievable-subgraph-now.md)'s coverage and presentation
  policies are settled. A Retrieval Answer presents sources as a librarian would,
  with explicit limits and visible disagreements. The Coverage Description
  supplies overall collection coverage and monthly detail on demand. The
  [2026-09-08 inventory](research/04-graph-inventory-2026-09-08.md) records 98
  articles and 2,407 embedded chunks, with all news base labels present. Missing
  stance alignment, funding properties, and complete joined paths, plus
  duplicated Organization IDs, constrain structural retrieval. Ticket 04 is
  complete, and issue 05 used this observed graph for its query-construction
  prototypes. The parent population task remains open as separate work.
- The repository's established agent pattern is a Generator/Critic team loop
  (Selector Healing Pipeline, Coreference Critic). Retrieval either extends
  that pattern or departs from it deliberately.

## Decisions so far

<!-- one line per closed ticket; zoom the link for the detail the ticket holds -->

- Query construction settled on 2026-09-14: models filter the semantic schema,
  select and wire typed compiler-owned pieces, and bind positional values; code
  owns validation, Cypher, Grounding Evidence traversal, Source Article lookup,
  and result hydration. Bill-name values use the shared Bill Designation parser
  before entity resolution. Do not use free-form model-generated Cypher or a
  general query-construction critic. Prototype source remains on the experiment
  branches and tag; only the findings and decision move into `main`. See
  [05-prototype-query-construction-and-validation.md](issues/05-prototype-query-construction-and-validation.md).

- Retrieval modes and indexes settled on 2026-09-08: full-text over names, titles, and chunk text; Article Chunk vectors; typed traversal. Combine and deduplicate chunks while retaining provenance, then group selected passages by source. Issue 07 owns mode selection and issue 09 owns shared ranking. Add three full-text indexes and ten non-unique base-label ID indexes; retain chunk vector and token lookup indexes. External-identifier implementation and Policy Area vectors are deferred. See [06-retrieval-modes-and-index-inventory.md](issues/06-retrieval-modes-and-index-inventory.md).

- Retrievable scope settled against the 2026-09-08 inventory: source discovery through graph and embeddings, librarian-style source presentation, explicit partial evidence and coverage limits, and collection-level Coverage Descriptions with monthly detail on demand. Missing properties, duplicate identities, and empty joined paths constrain structural answers. See [04-retrievable-subgraph-now.md](issues/04-retrievable-subgraph-now.md).

- Target question set authored: ten families over three orientations — entity lookup, relationship lookup, multi-hop traversal — cutting the roadmap's four; the corpus grounds every answer and the graph only reaches it, so each question terminates in a `Chunk` hop and structure-derived answers ship with the Chunks behind each element counted; Declined (permanent stance) is split from Deferred (coverage state), and negation over a closed universe from absence over an open one; no expected answers are authored here. See [02-target-question-set.md](issues/02-target-question-set.md) and [the set](question-set.md).
- Graph retrieval patterns and tooling surveyed as facts, not a recommendation: the local Neo4j 2026.05.0 Community server has only a chunk vector index — no full-text index, no APOC, no GDS; `neo4j-graphrag` 1.18.0 is compatible but ships no reranking, community detection, or Cypher repair loop; text2cypher execution accuracy peaks near 60% with temporal and same-name-entity failures; community detection requires a GDS install; Pydantic AI 2.0.0 supplies per-step tool routing, `ModelRetry` repair, and typed output. See [03-survey-graph-retrieval-patterns.md](issues/03-survey-graph-retrieval-patterns.md) and [the findings](research/03-graph-retrieval-patterns-findings.md).

## Not yet specified

- Retrieval Answer generation: model selection, prompt structure, and how source
  selection, supporting passages, and brief relevance notes stay grounded in the
  retrieved evidence.
- Temporal and multi-hop questions spanning redistricting cycles, where
  `District` identity changes across `RedistrictingCycle` and answers must not
  silently conflate cycles.
- Whether retrieval requires a caching or materialization layer, and what
  invalidates it when the graph is re-ingested.

## Out of scope

- **Community-oriented retrieval, community detection, and influence ranking.**
  Community detection requires a Graph Data Science install the local Neo4j
  Community server does not have, and there is no in-database alternative — see
  [the survey findings](research/03-graph-retrieval-patterns-findings.md). It is
  therefore not one of this map's retrieval orientations and is not a mode
  ticket 06 rules on. It remains a roadmap Later consideration.
- Building the chat UI. The contract must make it possible; this map does not
  specify or build it.
- Hosted Neo4j and deployment pipelines; a roadmap "Later consideration".
- The Entity Resolution merge process. Internal-ID lookup must preserve the
  current graph's identity ambiguity rather than silently merge nodes.
- External-identifier implementation and indexes, deferred by ticket 06 until
  an actual ingestion or retrieval need arises. The authored ontology already
  declares the future representation.
- Policy Area embeddings and their vector index, deferred by ticket 06 until a
  target question demonstrates a need.
- The full outcome-2 write-path migration to the ontology. Only the minimum
  needed to populate a retrievable graph rides on this map's populate task.
- CAL-ACCESS and Open States ingestion; roadmap outcome 5.
- Specifying retrieval and answer evaluation — context relevance, answer
  relevance, groundedness, time to first token. That belongs to the
  [Model Evaluation map](../model-evaluation/MAP.md), whose fog is waiting on
  exactly the contract this map produces.
