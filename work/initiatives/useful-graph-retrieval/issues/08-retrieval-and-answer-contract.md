# Define the retrieval and answer contract

Labels: wayfinder:grilling, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Decide the retrieval agent topology and orchestration](07-retrieval-agent-topology.md)

## Question

What is the typed boundary of the retrieval and answering layer — what goes in,
what comes out, and what are its explicit failure states?

The contract must cover:

- The question input, including any scope or filter a caller may supply.
- The retrieval result: the evidence set, its ranking, and the graph elements
  and Article Chunks that support each item.
- The answer, with citations and evidence as first-class typed output rather
  than prose the caller must parse. Provenance runs from every asserted claim
  back to a Source Article or public record.
- Explicit failure states, drawn from the topology decision and the retrievable
  subgraph decision: no evidence found, question reaches an unpopulated region,
  query could not be constructed or validated, orchestration bound exhausted.
- The distinction between a declined question and a failed one.

This is the artifact that graduates the parked fog on the
[Model Evaluation map](../../model-evaluation/MAP.md), which is waiting on "a
defined retrieval and answering contract" before retrieval and answer evaluation
can be specified. Specifying that evaluation stays with that map; this ticket
delivers what it needs.

The contract must be renderable by a chat UI with citations without altering the
retrieval layer beneath it.

## Blocking

- Blocks: Prototype graph-aware reranking.
- Blocks: Decide the developer retrieval surface.
