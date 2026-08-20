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

## Comments

### Previously discussed — 2026-08-19 grilling session

- **An answer directs, it does not reframe.** The maintainer's stated intent is
  the opposite of a Google AI Overview: the answer must not rewrite the reporting
  such that a reader never visits the source. It links, and it says how each
  linked thing bears on the question.
- **One answer element is an Article Chunk plus its Source Article URL plus a
  short relevance statement.** An earlier proposal to narrow the excerpt to the
  specific sentence that produced the connection was considered and set aside:
  Mention Spans are article-scoped and exist only where a pronoun needed
  resolving, while Entity Extraction runs per-Chunk, so there is no general join
  between a graph edge and the sentence that produced it. Revisit only if a
  sentence-level anchor becomes cheap.
- **The relevance statement is generated per Chunk in isolation** — the model
  sees that Chunk and the question, nothing else — so it cannot import a claim
  from another article. Statement generation runs *after* ranking, only for what
  survives.
- **Two distinct refusals, never conflated.** "I lack the corpus material to
  answer that" is decided after retrieval. "That is not something I should be
  answering" is decided before retrieval, by a dedicated scope-classifier agent.
  The maintainer does not want the refusal to enumerate what data is missing.
- **The scope classifier is its own agent**, not the existing Relevance Filter.
  That filter judges whole articles and is becoming a classifier over headline
  and description; judging an incoming query is a different task warranting its
  own prompt and its own evaluation.
- **Coreference substitutions render bracketed in place**, in the convention used
  for altered quotations, so a reader can see what was changed. Chunks are cut
  from resolved text ([pipeline.py:214](../../../../src/knowledge_map/core/pipeline.py:214)),
  so an unmarked excerpt would quote text the publication never printed.
