# Prototype query construction and validation against the ontology

Labels: wayfinder:prototype, ready-for-agent
Parent: [Useful Graph Retrieval](../MAP.md)
Inputs: [Target question set](02-target-question-set.md), [Retrievable scope and answer policy](04-retrievable-subgraph-now.md), [Current graph inventory](../research/04-graph-inventory-2026-09-08.md)

## Question

Can an LLM construct correct Cypher against this ontology, and does a validating
critic earn its cost?

This is the central architectural choice of the retrieval layer and it is
empirical, not arguable: generated Cypher over the ontology, versus a fixed set
of typed parameterized retrieval primitives the model selects among. Build
throwaway code against the real populated graph and run the target question set
through both.

Probe the indirections most likely to break generation:

- News Ontology Shortcut Rules: news connects `Politician` directly to a
  `LegislativeEvent` for votes and to a `Committee` for membership. The primary
  ontology routes those relationships through `LegislativeTenure`, which the
  current graph excludes. Queries must use the available news shape.
- The sub-label convention, where a node carries `:Organization` plus one or
  more of `:PAC`, `:LaborUnion`, and the rest.
- Relationships whose target is a union, such as `CAMPAIGN_FOR` reaching either
  a `Prop` or a `Politician`.
- Deferred questions requiring `District` and `RedistrictingCycle`, which the
  current graph excludes. Recognize the coverage limit and find partial news
  evidence where possible. Full event-time and redistricting semantics remain
  future work under issue 04.

Then answer the validation half: what classes of error appear, whether a critic
detects them, whether bounded repair converges, and whether validation is better
served by a model critic or by deterministic checks against the schema.

Link the prototype as an asset. Record the observed error classes — the agent
topology and the contract's failure states both depend on them.

## Starting conditions, 2026-09-08

The inventory provides a populated graph suitable for this experiment: 98
Source Articles and 2,407 embedded Article Chunks. Completing the remaining
population work is not a prerequisite for comparing query construction methods.
Use read-only queries against the observed graph; do not repair or reingest it
as part of this prototype.

Both approaches must receive the same available ontology and coverage context.
Their job is to retrieve Grounding Evidence for the librarian-style Retrieval
Answer agreed in issue 04. Keep query-construction failures separate from
coverage limits and defects already present in the data:

- All 174 stance edges lack alignment, and all 12 funding edges lack amount and
  date. Their chunks may still supply those details. Do not score missing graph
  properties as generation errors or treat shared stance topology as same-side
  evidence.
- Thirty-four Organization IDs are duplicated across 70 nodes, and 22 Bills
  lack sessions. Raw node counts and ambiguous cross-article joins do not
  establish real-world identities or exhaustive totals.
- The full M4 influence-chain path and the joined Bill–event–Committee path are
  empty. Some individual vote paths and committee referrals exist. Distinguish
  valid empty results from incorrect Cypher, and preserve Deferred coverage.
- Topic discovery uses `PolicyArea <- DISCUSSES_TOPIC - NewsArticle
  - HAS_CHUNK -> Chunk`, not a chunk-level topic edge.

The target questions remain unchanged. Label what each experiment can establish
from current evidence, including cases where only partial reporting is available.

## Blocking

- Blocks: Decide the retrieval agent topology and orchestration.
