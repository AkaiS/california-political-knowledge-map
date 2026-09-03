# 04 — Topic Assignment, measures to areas

Labels: completed

## Parent

[Policy Area Staging](../PRD.md)

## What to build

After extraction has discovered every measure the article names, one stage
decides which of the article's Policy Areas each Bill and Prop is about. It is
given the article, the areas 02 classified, and every Bill and Prop extraction
the chunks produced — the only place in the pipeline that sees every measure and
every area at once, which is what the judgement needs, and it cannot run earlier
because extraction is what discovers the measures. Its assignments reach the
graph as the `ABOUT_TOPIC` edges the write path in 01 already knows how to write.

The standard is that the **article** connects the measure to the area, not the
chunk. A chunk that never states a bill's subject no longer prevents the claim.
An area the article never connects to a measure is a hallucination to be scored
down, not a second kind of edge — inferred assignments are not marked with a
property, because a declared relationship property joins that relationship's
Claim Key, and two edges differing only in how they were arrived at would become
two claims about one pair.

Assignment names measures by the surface strings extraction produced, so it
cannot invent a Bill the article never mentioned. Two drops enforce that in code
rather than in the prompt: an assignment naming a measure extraction did not
produce is dropped before persistence, so a hallucinated endpoint cannot mint a
node behind the write path's back; and an assignment naming an area outside the
article's classified set is dropped, so the two stages cannot contradict each
other in the graph.

The stage joins the adapter Protocol 02 introduced rather than adding a second
one, and runs in the same position Bill Session Resolution and Legislative Event
dating already occupy — after the extraction loop, with its result travelling to
persistence the way theirs do. A failure routes to the Dead Letter Queue and
Article Status the way a coreference or extraction failure does.

This is the first stage in the pipeline that asserts a claim with no Article
Chunk behind it. That is deliberate, and it means the Grounding Evidence for a
topic edge is the Source Article rather than a chunk.

## Acceptance criteria

- [x] The adapter Protocol introduced in 02 gains assignment over a Source
      Article, its Policy Areas, and its extractions, and the Pydantic AI adapter
      implements it with its own agent and Model Deployment.
- [x] The pipeline runs assignment after the extraction loop, in the position
      Bill Session Resolution occupies, and passes it every Bill and Prop the
      article's extractions produced.
- [x] Assignments reach the database through the article-level topic method from
      01, alongside the article's areas.
- [x] An assignment naming a measure no extraction produced is dropped before
      persistence.
- [x] An assignment naming an area outside the article's classified set is
      dropped before persistence.
- [x] An article with no areas, or with no extracted measures, completes without
      calling the assignment stage or with an empty result, and reaches
      `COMPLETED`.
- [x] An assignment failure raises one stage-specific exception; the pipeline
      logs it to the Dead Letter Queue and sets Article Status as a coreference
      failure does.
- [x] Pipeline tests extend the fake from 02 to cover both stages and assert what
      reached the database.

## Blocked by

- [01 — The article-level topic write path](01-article-level-topic-write-path.md)
- [03 — Policy Area leaves Entity Extraction](03-policy-area-leaves-entity-extraction.md)
