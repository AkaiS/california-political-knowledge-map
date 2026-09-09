# Decide the retrieval modes and the index inventory they require

Labels: wayfinder:grilling, completed
Parent: [Useful Graph Retrieval](../MAP.md)
Inputs: [Target question set](02-target-question-set.md), [Retrievable subgraph decision](04-retrievable-subgraph-now.md), [Current graph inventory](../research/04-graph-inventory-2026-09-08.md)

## Question

Which retrieval modes does the layer offer, how are their results combined, and
what indexes must exist in Neo4j to support them?

Modes to rule in or out, each justified by questions from the target set:

- Full-text search. No full-text index exists today.
- Vector similarity. Only `chunk_vector_index` exists, while the ontology also
  gives `:PolicyArea` an embedding with no index behind it.
- Structural traversal over typed relationships.

Then settle the boundary between combining candidates and ranking them, and
whether combination is a mode of its own or a later reranking concern.

Decide which identifier lookups retrieval needs now. The original question
treated external-identifier representation as unresolved; the authored ontology
already declares `ExternalIdentifier` and `HAS_IDENTIFIER`. The answer below
settles whether that future capability belongs in the initial implementation.

## Downstream decisions

- [Topology and orchestration](07-retrieval-agent-topology.md) consumes this
  decision and still requires the issue 05 prototype.
- [Reranking](09-prototype-graph-aware-reranking.md) consumes this decision and
  still requires the issue 08 contract.

## Input from the retrievable subgraph decision

[Ticket 04](04-retrievable-subgraph-now.md)'s grilling on 2026-09-08 accepted
Article Chunk embedding retrieval as a route to source material alongside graph
connections. A missing extracted relationship must not disqualify a relevant
passage found through another route. This ticket decides available modes,
combination, and indexes. Issue 07 owns mode selection during execution;
comparative answer quality belongs to evaluation.

The [2026-09-08 live inventory](../research/04-graph-inventory-2026-09-08.md)
confirms an online 768-dimensional cosine chunk vector index covering 2,407
embedded chunks. Only the two token lookup indexes accompany it; no full-text
or property lookup indexes and no constraints were observed. The report also
records populated and empty target traversals and the missing alignment,
funding properties, and duplicate Organization identities that constrain them.

## Answer

Accepted during grilling on 2026-09-08, with the complete decision and index
inventory confirmed by the maintainer. This closes the decision; implementation
belongs to the retrieval PRD that consumes this initiative's decisions.

### Three retrieval modes

| Mode | Search coverage | Target questions that justify it |
| --- | --- | --- |
| Full-text search | Entity names, Source Article titles, and Article Chunk text | E1 named actors, E2 Bill Designations and named measures, and R1/R2 reporting containing the requested actor or measure wording |
| Vector similarity | Article Chunk embeddings | E2's "HOA fee cap bill" description and other questions whose relevant reporting uses different wording, including passages missing an extracted relationship |
| Typed structural traversal | Available ontology relationships, followed to Grounding Evidence | E3 Policy Area discovery; R1/R2 reported stances and lobbying; M1 policy footprint, M2 shared measures, M3 co-reporting, and supported portions of R3/M4/M5 and committee activity |

Name and title matches lead to candidate Article Chunks. Preserve which field
matched and the route from that match to the passage; a title or entity-name
match alone is not Grounding Evidence for a political claim.

Structural discovery retains issue 04's limits. Shared stance topology does not
establish matching alignment, missing funding properties do not establish an
amount, and an incomplete joined path cannot supply a complete chain. Relevant
passages remain eligible through the other modes. Publication-date scope does
not establish event-time coverage, and an unresolved Bill session remains
ambiguous regardless of which search found it.

This inventory specifies available capabilities, not a requirement to run every
mode on every question. Issue 07 decides mode selection, sequencing, and when
retrieval is sufficient.

### Combine chunks, then rank and present sources

Combine and deduplicate candidate Article Chunks from whichever modes ran.
When several routes reach the same chunk, preserve all of those routes and
their supporting graph claims. Deduplicating candidates does not merge graph
entities or resolve identity uncertainty.

Combination is not a fourth retrieval mode. It gathers the candidate evidence;
issue 09 determines shared ranking through its lexical, vector, and structural
comparisons. This decision prescribes no fusion formula, mode weights, or
structural preference. Issue 08 defines the typed representation of candidates,
their provenance, and ranking.

Group selected passages by Source Article for the librarian's presentation.
Keep useful passages from different parts of an article while presenting that
source once. Issue 04's original-wording verification, partial-evidence policy,
and visible disagreements still apply.

### Required index inventory

These are requirements for implementation, not a claim that the new indexes
already exist. The observed baseline remains the 2026-09-08 inventory above.

| Index | Labels and properties | Requirement |
| --- | --- | --- |
| Existing `chunk_vector_index` | `Chunk.embedding` | Retain the observed 768-dimensional cosine index for Article Chunk retrieval |
| Entity-name full-text index | `name` on `Bill`, `Campaign`, `Committee`, `LegislativeEvent`, `Organization`, `PolicyArea`, `Politician`, and `Prop` | Add one index spanning these eight base labels |
| Article-title full-text index | `NewsArticle.title` | Add |
| Chunk-text full-text index | `Chunk.text` | Add |
| Internal-ID range indexes | `id` on each of the eight labels above, plus `NewsArticle` and `Chunk` | Add one non-unique index per base label, ten total |
| Existing token lookup indexes | Node labels and relationship types | Retain both |

Base-label indexes also cover nodes carrying sub-labels. Traversal uses those
labels and typed relationships; the initial inventory adds no separate index
per relationship type or sub-label.

The internal-ID indexes support entity entry points and access to chunks and
articles referenced by provenance. They do not assert uniqueness. The live
inventory found 34 duplicate Organization IDs across 70 nodes; lookup must
preserve that ambiguity, and index creation must not silently merge the nodes.
Entity Resolution remains separate work.

The stored properties are confirmed by
[the graph writer](../../../../src/knowledge_map/adapters/neo4j_db.py).
`NewsArticle.id` stores the article URL; `Chunk.id` derives from that URL and its
chunk index. `Chunk.text` contains transformed text with overlap, so indexing it
does not change the requirement to verify displayed quotations against the
original Story body.

### Deferred indexes and identifiers

Defer Policy Area embeddings and their vector index until a target question
demonstrates a need. The ontology declares the embedding property, but the
current Policy Area writer supplies only `name` and `id`. The inventory did not
measure stored Policy Area embeddings. Article Chunk vectors, name search, and
article-level Policy Area connections are the initial discovery routes.

Defer external-identifier storage, lookup, and indexes until an actual ingestion
or retrieval need arises. Current retrieval uses internal IDs. Implementing a
future external-key capability now would violate the agreed YAGNI scope.

The authored [primary ontology](../../../../ontology.md) already represents
external identifiers as `ExternalIdentifier` nodes connected by
`HAS_IDENTIFIER`. This decision does not replace that representation with JSON,
parallel arrays, scalar properties, or a new `Identifier` label. The future
consumer owns its concrete lookup and indexing requirements; those are not a
remaining blocker for this initiative.

## Handoff

- Issue 07 receives the three available modes and owns their execution policy.
- Issue 08 represents combined chunk candidates, retained retrieval routes and
  supporting claims, ranking, and grouping by Source Article.
- Issue 09 owns shared ranking of the combined candidates and the comparison
  of lexical, vector, and structural signals. No combination formula is assumed.
- The eventual retrieval PRD must implement the index inventory above and carry
  the existing identity and evidence limitations forward.

## Comments

### 2026-09-08: Grilling and confirmation

The maintainer accepted all three modes and rejected speculative implementation
of external identification while only internal IDs are available. They assigned
mode selection to orchestration, accepted chunk-level combination followed by
source grouping, and assigned shared ranking to issue 09. They accepted
full-text coverage of names, titles, and chunk text, and deferred Policy Area
vectors. The final confirmation accepted the concrete index inventory,
non-unique ID lookups that preserve existing ambiguity, and documentation-only
closure with implementation handed forward.
