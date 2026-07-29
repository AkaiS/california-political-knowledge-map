# Decide the retrieval agent topology and orchestration

Labels: wayfinder:grilling, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Prototype query construction and validation against the ontology](05-prototype-query-construction-and-validation.md), [Decide the retrieval modes and the index inventory they require](06-retrieval-modes-and-index-inventory.md)

## Question

What agent topology executes retrieval, and who decides that retrieval is
sufficient?

The modes inventory says what retrieval can do and the query-construction
prototype says whether generation needs a critic. Neither answers control flow.
Candidate topologies:

- A single agent holding the retrieval modes as tools, selecting among them.
- A Generator/Critic team loop with bounded query repair, extending the pattern
  already used by the Selector Healing Pipeline and the Coreference Critic.
- A planner that decomposes a question into several retrievals and composes the
  results.

Settle alongside it: what bounds the loop — hop budget, repair attempts, wall
clock, token spend — what happens when a bound is exhausted, and whether the
sufficiency judgement is made by a model or by a deterministic predicate over
retrieved evidence.

Whether this extends the repository's established Generator/Critic pattern or
departs from it should be stated as a decision rather than left for a PRD author
to infer.

This ticket blocks the contract deliberately: failure states such as a rejected
query after bounded repair, or an exhausted hop budget, are contract surface and
cannot be enumerated before the topology is known.

## Blocking

- Blocks: Define the retrieval and answer contract.
