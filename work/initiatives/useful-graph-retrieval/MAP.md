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
- **Entity identity uses own IDs.** Nodes carry project-minted primary keys.
  External identifiers are recorded alongside them as source/value pairs so
  news-derived nodes can later reconcile against OpenStates, FPPC, and state
  registry keys rather than being rewritten. The ontology's registry-keyed
  primary keys are therefore read as the eventual authority, not as a
  constraint on extraction.
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
- Retrieval spans four orientations named by the roadmap: entity, edge,
  neighborhood, and community.
- The repository's established agent pattern is a Generator/Critic team loop
  (Selector Healing Pipeline, Coreference Critic). Retrieval either extends
  that pattern or departs from it deliberately.

## Decisions so far

<!-- one line per closed ticket; zoom the link for the detail the ticket holds -->

- Graph retrieval patterns and tooling surveyed as facts, not a recommendation: the local Neo4j 2026.05.0 Community server has only a chunk vector index — no full-text index, no APOC, no GDS; `neo4j-graphrag` 1.18.0 is compatible but ships no reranking, community detection, or Cypher repair loop; text2cypher execution accuracy peaks near 60% with temporal and same-name-entity failures; community detection requires a GDS install; Pydantic AI 2.0.0 supplies per-step tool routing, `ModelRetry` repair, and typed output. See [03-survey-graph-retrieval-patterns.md](issues/03-survey-graph-retrieval-patterns.md) and [the findings](research/03-graph-retrieval-patterns-findings.md).

## Not yet specified

- The concrete representation of the external-identifier store and the indexes
  it requires. Neo4j has no map-valued properties, so the shape is parallel
  arrays, prefixed scalar properties, or dedicated `:Identifier` nodes. The
  choice follows from whether retrieval must look a node up by its external
  key, which the modes and index inventory decides.
- Community detection and influence ranking as a retrieval mode, including
  whether communities are precomputed and materialized or derived per query.
- Answer synthesis: model selection, prompt structure, and how the synthesizer
  is constrained to the retrieved evidence.
- Temporal and multi-hop questions spanning redistricting cycles, where
  `District` identity changes across `RedistrictingCycle` and answers must not
  silently conflate cycles.
- Whether retrieval requires a caching or materialization layer, and what
  invalidates it when the graph is re-ingested.

## Out of scope

- Building the chat UI. The contract must make it possible; this map does not
  specify or build it.
- Hosted Neo4j and deployment pipelines; a roadmap "Later consideration".
- The Entity Resolution merge process. This map settles only that news-derived
  nodes record external identifiers so reconciliation stays possible.
- The full outcome-2 write-path migration to the ontology. Only the minimum
  needed to populate a retrievable graph rides on this map's populate task.
- CAL-ACCESS and Open States ingestion; roadmap outcome 5.
- Specifying retrieval and answer evaluation — context relevance, answer
  relevance, groundedness, time to first token. That belongs to the
  [Model Evaluation map](../model-evaluation/MAP.md), whose fog is waiting on
  exactly the contract this map produces.
