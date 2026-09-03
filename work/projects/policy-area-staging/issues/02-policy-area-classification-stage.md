# 02 — Policy Area Classification, once per Source Article

Labels: completed

## Parent

[Policy Area Staging](../PRD.md)

## What to build

A Source Article's Policy Areas are decided once, for the article, before it is
ever cut into chunks. Classification reads the coreference-resolved text — the
same canonical names every later stage sees — and returns the areas the article
discusses, chosen from the closed vocabulary. The areas reach the write path
built in 01, so an ingested article carries the `DISCUSSES_TOPIC` edges the
ontology declares. Two Article Chunks of one article can no longer disagree
about what the article is about, because neither is asked.

The stage sits behind a new adapter Protocol on the Story Pipeline, beside the
Coreference and Entity Extraction Protocols it already declares. That Protocol
is where Topic Assignment lands in 04: one seam for both stages, so the pipeline
gains one collaborator and one fake covers both in tests. In this ticket it
exposes classification and the health check the other adapters carry.

The concrete adapter is a Pydantic AI implementation shaped like the extraction
adapter: an agent built from an explicit Model Deployment, structured output, and
failures raised as one stage-specific exception the pipeline maps into its own
vocabulary. The stage owns the vocabulary — the schema admits the vocabulary's
members and nothing else, so an id and its canonical name stop being two answers
a model can pick between.

Classification runs after Coreference Resolution and before chunking, because it
reads resolved text and nothing earlier needs its result. An article the
vocabulary does not cover returns no areas and completes normally, reaching the
graph with its entities. A failure routes to the Dead Letter Queue and sets
Article Status the way a coreference failure does, so the pipeline keeps one
vocabulary of failure.

No maximum number of areas is set. The Gold Set in 05 records the distribution
first, following the precedent set for the coreference discard threshold: no
untested threshold blocks ingestion before there is data to set it from.

## Acceptance criteria

- [x] The Story Pipeline declares one new adapter Protocol exposing
      classification over an article's resolved text and a health check.
- [x] A Pydantic AI adapter implements it, building its agent from an explicit
      Model Deployment and returning structured output.
- [x] The output schema admits only members of the Policy Area vocabulary, and
      an answer naming anything else does not become an area.
- [x] The pipeline runs classification after Coreference Resolution and before
      chunking, on the resolved text.
- [x] The classified areas reach the database through the article-level topic
      method from 01, with no assignments.
- [x] An article classified with no areas completes, is persisted, and reaches
      `COMPLETED`.
- [x] A classification failure raises one stage-specific exception; the pipeline
      logs it to the Dead Letter Queue under its own error category and sets
      Article Status as a coreference failure does.
- [x] A transport failure in the stage is classified by the same connectivity and
      rate-limit handling every other stage call uses.
- [x] Pipeline tests drive a fake classification adapter and assert what reached
      the database, not how the stage arrived there.

## Blocked by

- [01 — The article-level topic write path](01-article-level-topic-write-path.md)
