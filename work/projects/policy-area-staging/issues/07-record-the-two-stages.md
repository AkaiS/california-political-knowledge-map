# 07 — Record both stages in the domain vocabulary

Labels: completed

## Parent

[Policy Area Staging](../PRD.md)

## What to build

`CONTEXT.md` describes the pipeline that exists. It gains **Policy Area
Classification** — the article-level choice of Policy Areas from the closed
vocabulary, run on resolved text before chunking — and **Topic Assignment** — the
article-level pass after extraction that connects the article's measures to its
areas. Both entries name the Story Pipeline stage they are, as the existing
stage entries do.

Three existing entries are reconciled rather than left contradicting them. The
**Policy Area** entry says which stage writes the node and that its edge from a
Source Article is article-level. The **Entity Extraction** and **News Ontology**
entries stop implying that the chunk extractor is responsible for Policy Areas.
The **Grounding Evidence** entry records that a topic edge's evidence is the
Source Article rather than a chunk, which is what retiring the chunk-level edge
made true.

No ADR unless the build turned up a decision that supersedes a recorded one. The
staging decision itself is a change of which stage answers a question, not a
reversal of a decision `docs/adr/` holds.

## Acceptance criteria

- [x] `CONTEXT.md` defines Policy Area Classification and Topic Assignment, each
      with an _Avoid_ line separating it from the other and from Entity
      Extraction.
- [x] The Policy Area entry names the stage that writes the node and the level its
      article edge sits at.
- [x] The Entity Extraction and News Ontology entries no longer attribute Policy
      Areas to the chunk extractor.
- [x] The Grounding Evidence entry records that a topic edge is grounded in the
      Source Article.
- [x] Either no ADR is added, or one is added and names the decision it
      supersedes.

## Blocked by

- [04 — Topic Assignment, measures to areas](04-topic-assignment-stage.md)
