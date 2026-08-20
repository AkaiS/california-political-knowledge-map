# Prototype query construction and validation against the ontology

Labels: wayfinder:prototype, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Update the extraction prompt to the settled ontology and populate the graph](01-populate-graph-with-settled-ontology.md), [Decide the target question set for California political retrieval](02-target-question-set.md)

## Question

Can an LLM construct correct Cypher against this ontology, and does a validating
critic earn its cost?

This is the central architectural choice of the retrieval layer and it is
empirical, not arguable: generated Cypher over the ontology, versus a fixed set
of typed parameterized retrieval primitives the model selects among. Build
throwaway code against the real populated graph and run the target question set
through both.

Probe the indirections most likely to break generation:

- `LegislativeTenure` mediating between `Politician` and every vote, committee
  assignment, and district, so no `Politician` connects directly to a `Vote`.
- The sub-label convention, where a node carries `:Organization` plus one or
  more of `:PAC`, `:LaborUnion`, and the rest.
- Relationships whose target is a union, such as `CAMPAIGN_FOR` reaching either
  a `Prop` or a `Politician`.
- `District` identity varying by `cycle_year`, so cycle-blind matches silently
  conflate redistricting cycles.

Then answer the validation half: what classes of error appear, whether a critic
detects them, whether bounded repair converges, and whether validation is better
served by a model critic or by deterministic checks against the schema.

Link the prototype as an asset. Record the observed error classes — the agent
topology and the contract's failure states both depend on them.

## Blocking

- Blocks: Decide the retrieval agent topology and orchestration.

## Comments

### Previously discussed — 2026-08-19 grilling session

- **Prototype only what is genuinely uncertain; build the rest for keeps.** The
  maintainer's position is that this ticket should not produce throwaway code
  across the board. The uncertain part is whether graph traversal over a corpus
  this small reaches evidence a vector search would not — that is worth a real
  experiment. Everything the retrieval design already settles should be built to
  keep.
