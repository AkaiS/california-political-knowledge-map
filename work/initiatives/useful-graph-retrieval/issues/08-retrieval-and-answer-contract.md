# Define the retrieval and answer contract

Labels: wayfinder:grilling, ready-for-agent
Parent: [Useful Graph Retrieval](../MAP.md)
Inputs: [Accepted retrieval topology and orchestration](07-retrieval-agent-topology.md)
Blocked by: [Graph-Prioritized Retrieval issue 02](../../../projects/graph-prioritized-retrieval/issues/02-retrieval-execution-and-evidence-contracts.md)

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
- Coverage and retrieval outcomes, drawn from the retrievable subgraph decision:
  Deferred coverage and no matching evidence found are distinct.
- Execution failures, drawn from the topology decision: query could not be
  constructed or validated, orchestration bound exhausted.
- The distinction between a declined question and a failed one.

This is the artifact that graduates the parked fog on the
[Model Evaluation map](../../model-evaluation/MAP.md), which is waiting on "a
defined retrieval and answering contract" before retrieval and answer evaluation
can be specified. Specifying that evaluation stays with that map; this ticket
delivers what it needs.

The contract must be renderable by a chat UI with citations without altering the
retrieval layer beneath it.

## Input from the topology decision

[Issue 07](07-retrieval-agent-topology.md) closed on 2026-09-16 and supplies the
following contract requirements:

- Query preparation records a user-approved natural-language Query Rewrite and
  an internal `relational` route. Rejected rewrites retain the proposed question,
  route, and user correction. `rewrite_unavailable` stops before retrieval and
  never falls back to the original wording.
- Every approved rewrite expects full-text and dense branches. A Relational
  Question also expects typed structural retrieval. The contract records the
  expected branches, evidence recovered by each, and failed branches rather
  than requiring a `complete` or `partial` summary.
- Each branch retains its ranked candidates before fusion, including Article
  Chunk identity, branch-local rank and score, route and matched field, and any
  supporting graph claim. Fused candidates retain every contributing route.
- A successful branch returning no candidates is distinct from a failed branch.
  A successful empty structural traversal says that the available graph contains
  no matching connection; a construction or execution failure says that the
  connection could not be searched.
- Every failed branch reaches user-facing disclosure. Structural failure on a
  Relational Question is the prominent limitation; text-branch failures remain
  visible but secondary. Detailed failure stage, kind, attempts, and diagnostics
  stay in logs rather than the answer contract.
- A deterministic Evidence Assembler verifies original wording, groups passages
  by Source Article, attaches relevant Coverage Description entries, and applies
  the context budget. No post-retrieval model or sufficiency loop alters the
  package before it returns to the Chat Agent.
- Deferred coverage is explained before approval and again with any evidence
  recovered. Declined remains a policy outcome, not a retrieval failure.

## Remaining work

The retrievable-scope, retrieval-mode, and topology decisions have settled the
contract's semantics. Graph-Prioritized Retrieval issue 02 owns the remaining
work: encode those decisions as concrete Pydantic types and prove that the
distinct outcomes cannot collapse into one representation. Once those types
exist, record them here as the answer and close this decision.

This ticket no longer blocks retrieval implementation or the reranking
prototype. The developer retrieval surface still waits for the concrete types
because it renders them without defining new behavior.

## Input from the retrievable subgraph decision

[Ticket 04](04-retrievable-subgraph-now.md)'s grilling rounds on 2026-09-08
settled the following policy requirements. Its
[subsequent inventory](../research/04-graph-inventory-2026-09-08.md) qualifies the
intended scope with observed path availability and claim/identity limitations;
the parent population task remains open.

- A Retrieval Answer presents relevant sources for the reader to consult.
  Brief introductions and connections to the question support that selection;
  summarization must not replace the sources.
- Return supported partial evidence automatically while stating the original
  question's unmet coverage requirement. The answering agent needs explicit
  context about relevant coverage limits alongside the evidence. A succinct
  Coverage Description goes to the orchestration agent, and the relevant limits
  must reach the answering agent. Ticket 04 settles the description's
  semantics; this ticket owns its concrete representation in the contract.
- Incomplete graph elements remain eligible for discovery. Their connected
  Grounding Evidence may supply information missing from graph properties.
  Claims still require support for the specific identity, amount, date, or
  other value they depend on.
- Preserve ticket 02's Deferred coverage state. A search finding no matching
  evidence is a separate outcome and does not establish a coverage gap or a
  non-event. Deferred questions may still return useful sources; this ticket
  chooses how to represent both coverage and search outcomes.
- Each selected source includes its title, publication date when available,
  link, a short passage verified against the original extracted wording, and
  a relevance note where useful. Transformed graph chunk text must not be
  silently presented as a verbatim quotation.
- Highlight disagreements between sources without adjudicating them.
- Organize the Coverage Description by Publication or distinct public-record
  collection. Its account of what each collection provides is authored;
  ingestion updates measured availability. A coverage percentage requires a
  known, bounded expected set; otherwise completeness remains unknown and
  observed available-material counts are reported.
- News dates describe Story publication dates supplied by Publications, not
  temporal coverage of events. Event coverage belongs to sources that explicitly
  claim it. Wider temporal reasoning is deferred beyond this decision.
- Reuse discovery and stored article metadata as the basis for observed counts.
  The archive already records candidate-list progress, which includes failed
  fetches and must not be represented as completed ingestion or exhaustive
  Publication coverage.
- Reflect verified currently available material after ingestion, including
  additions from a partially successful refresh. Do not include refresh status,
  retries, or incomplete-refresh warnings in orchestrator context. The primary
  description concerns overall collection coverage.
- Include access to a separate monthly coverage breakdown in the initial
  contract, loaded when the question needs it rather than in every orchestrator
  prompt. Month-specific percentages require month-specific known expected
  totals; otherwise return the month's verified available count and unknown
  completeness. News months use Story publication dates.

## Input from the retrieval modes decision

[Issue 06](06-retrieval-modes-and-index-inventory.md) closed on 2026-09-08 and
settles the following requirements for this contract:

- Full-text search over entity names, Source Article titles, and Article Chunk
  text; Article Chunk vector search; and typed traversal supply candidates.
  Issue 07 decides when and in what order those modes run.
- Combine and deduplicate Article Chunks while retaining every retrieval route
  and supporting graph claim. Name and title hits lead to candidate passages;
  retain which field matched without treating that match alone as grounding.
- Issue 09 determines shared ranking. This contract must represent ranking
  without presupposing a particular fusion formula or structural preference.
- Group selected passages by Source Article for presentation, preserving useful
  passages from different parts of an article while presenting the source once.
- Deduplicating chunks does not merge graph entities or resolve duplicate
  internal IDs. External-identifier lookup and Policy Area vectors are deferred.
