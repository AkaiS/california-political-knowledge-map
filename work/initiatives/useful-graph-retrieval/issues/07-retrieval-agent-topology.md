# Decide the retrieval agent topology and orchestration

Labels: wayfinder:grilling, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Prototype query construction and validation against the ontology](05-prototype-query-construction-and-validation.md)
Inputs: [Accepted retrieval modes and index inventory](06-retrieval-modes-and-index-inventory.md)

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

## Input from the retrieval modes decision

[Issue 06](06-retrieval-modes-and-index-inventory.md) closed on 2026-09-08. The
available modes are full-text search over names, article titles, and chunk text;
Article Chunk vector search; and typed structural traversal. This ticket owns
which modes run, their order, and the sufficiency judgement. There is no accepted
rule requiring all three modes for every question.

Combine and deduplicate the chunks reached by whichever modes run, preserving
their retrieval routes and supporting graph claims. Combination is not another
mode, and issue 09 owns shared ranking. Source discovery does not require a
matching extracted relationship. Internal-ID lookup must preserve existing
identity ambiguity; external-identifier implementation and Policy Area vectors
are deferred.
