# Product Requirements: Coreference Resolution via Mention Spans

Labels: ready-for-agent

## Problem Statement

Coreference Resolution currently asks the annotator model to re-emit the entire
Source Article with `<ref entity="Canonical Name">pronoun</ref>` tags embedded in
it. The model is competent at choosing the entity but unreliable at reproducing
several thousand words verbatim. A single dropped comma, normalized quote mark,
or re-wrapped line fails the Structural Identity Check, which compares the
tag-stripped output against the original text.

Three costs follow from that.

First, failure is all-or-nothing at the article level. One bad character
invalidates every correct annotation in the article, and the retry asks for the
whole article again.

Second, the retry feedback and the Coreference Critic prompt both carry full
copies of the article. The Critic receives the original text and the annotated
text together, so its context is roughly two copies of the article plus tags.
Larger context makes the Critic's judgement worse, not better.

Third, the Coreference Critic returns a single `is_valid` boolean for the whole
article. There is no way to keep the correct annotations and discard only the
wrong ones, and no per-annotation signal to measure against a silver set.

Articles that exhaust the retry budget are written to the Dead Letter Queue with
`failure_type="structural_mismatch"` and their Article Status set to
`FAILED_DLQ`. These are articles the model understood correctly and failed only
at transcription.

## Solution

The annotator stops rewriting the article. It reads the Source Article as
numbered sentences and returns a structured list of Mention Spans, where each
Mention Span names the sentence it occurs in, the pronoun or referring
expression as it appears, which occurrence of that expression it is within the
sentence, and the canonical entity it refers to.

Python owns everything positional. A sentence splitter records each sentence's
character range in the Source Article before the prompt is built, so the model
only copies back a sentence label it can see on the line in front of it. Given a
sentence label and a mention string, Python derives the exact character range by
searching within that sentence's range. The model never emits a character
offset, a word index, or any number it would have to compute.

Because Python performs the substitution against the original string, text
outside the substituted ranges cannot change. The Structural Identity Check, the
tag-stripping helper, the whitespace normalizer, the markdown-fence cleaner, and
the `structural_mismatch` failure type are all deleted rather than fixed.

The Coreference Critic receives the numbered sentences once, plus the list of
Mention Spans, and returns one verdict per Mention Span. Rejected Mention Spans
are discarded individually; accepted ones are applied. An article no longer
fails because one pronoun was misread.

The Coreference Adapter's external contract is unchanged: it still takes the
Source Article's content and returns resolved text for the Story Pipeline to
chunk, embed, and extract from.

## User Stories

1. As an AI engineer, I want the annotator to return structured Mention Spans instead of a rewritten article, so that the model spends its effort on entity judgement rather than transcription.
2. As an AI engineer, I want the annotator prompt to present the Source Article as numbered sentences, so that the model can address a location by copying a visible label rather than by counting.
3. As an AI engineer, I want each Mention Span to carry the mention text exactly as it appears in the sentence, so that Python can locate it without the model reporting a position.
4. As an AI engineer, I want each Mention Span to carry an occurrence number, so that a sentence containing the same pronoun twice can assign each occurrence a different canonical entity.
5. As an AI engineer, I want the occurrence number to default to the first match, so that the common case of a unique mention within a sentence costs the model nothing.
6. As a developer, I want Python to derive every character range from the sentence table and the mention text, so that no offset in the system originates from model arithmetic.
7. As a developer, I want the sentence splitter to record each sentence's character range at split time, so that a sentence label resolves to a range without re-searching the article.
8. As a developer, I want the concatenation of all numbered sentences to reproduce the Source Article's content exactly, so that a split defect is caught by an assertion rather than by a wrong substitution.
9. As a developer, I want substitutions applied in descending start position, so that earlier character ranges remain valid while later ones are rewritten.
10. As a developer, I want the Coreference Adapter to keep returning resolved text from the Source Article's content, so that the Story Pipeline, chunking, embedding, and extraction steps need no change.
11. As an AI engineer, I want a Mention Span whose mention text is absent from its named sentence to be discarded, so that one bad reference does not fail the article.
12. As an AI engineer, I want a Mention Span whose occurrence number exceeds the available matches to be discarded, so that an over-counted repeat does not produce a wrong substitution.
13. As an AI engineer, I want a Mention Span naming a sentence label that does not exist to be discarded, so that a hallucinated label cannot raise an index error mid-pipeline.
14. As an AI engineer, I want two Mention Spans that resolve to overlapping character ranges to be reduced to one, so that substitution cannot corrupt the text.
15. As an AI engineer, I want every discarded Mention Span recorded with the reason it was discarded, so that I can measure which validation rule the model violates most often.
16. As an AI engineer, I want the Coreference Critic to receive the numbered sentences once rather than two copies of the article, so that its context is roughly half its current size.
17. As an AI engineer, I want the Coreference Critic to return a verdict for each Mention Span rather than one boolean for the article, so that correct references survive an incorrect neighbour.
18. As an AI engineer, I want each Critic verdict to carry a short reason when it rejects, so that the rejection can be fed back or audited.
19. As an AI engineer, I want a Critic verdict that names a Mention Span not present in the request to be ignored, so that a hallucinated verdict cannot alter the text.
20. As an AI engineer, I want a Mention Span with no matching Critic verdict to be discarded, so that an incomplete Critic response fails closed rather than open.
21. As an AI engineer, I want the retry to re-ask only the rejected Mention Spans, so that a retry does not re-derive the whole article.
22. As a system operator, I want an article that ends with zero surviving Mention Spans to fail rather than complete, so that a silently broken annotator cannot pass unresolved text into the graph.
23. As an AI engineer, I want an annotator returning no Mention Spans at all to fail with its own failure type, so that a prompt or model defect is distinguishable from a matching defect.
24. As an AI engineer, I want an article whose Mention Spans are all discarded by validation to fail with its own failure type, so that a mention-matching or splitter defect is distinguishable from a Critic disagreement.
25. As an AI engineer, I want an article whose Mention Spans are all rejected by the Coreference Critic to fail with its own failure type, so that a disagreement between the two models is visible as such.
26. As an AI engineer, I want the Dead Letter Queue record to carry the numbered sentences the annotator was shown, so that I can see what the model was looking at when it named a mention that could not be found.
27. As a system operator, I want a partial discard to complete normally regardless of how many Mention Spans were discarded, so that no untested threshold blocks ingestion before we have data to set one.
28. As a system operator, I want the proportion of discarded Mention Spans per article recorded, so that silent quality decay is visible without reading the text.
29. As a system operator, I want no article to reach `FAILED_DLQ` for a transcription defect, so that the queue holds only annotation, matching, and transport failures worth reading.
30. As an AI engineer, I want the Dead Letter Queue record for a coreference failure to carry the Mention Spans and their validation outcomes rather than a failed annotated article, so that a failure record is directly replayable against a new prompt.
31. As an AI engineer, I want the `structural_mismatch` failure type retired, so that the failure vocabulary describes failures that can still occur.
32. As an AI engineer, I want per-Mention-Span outcomes available from the resolution run, so that the future Coreference Resolution evaluation can score references individually against a silver set.
33. As a developer, I want the Article Chunk's text to remain the resolved text, so that embeddings carry the canonical entity names that make a chunk retrievable.
34. As a developer, I want no Mention Span provenance written to the graph, so that the write path gains no new schema and the Source Article remains the source for quotation.
35. As a developer, I want abbreviations and other splitter artefacts to degrade to a mis-numbered line rather than to lost text, so that a splitter weakness costs at most one Mention Span.
36. As a maintainer, I want the deleted tag-handling helpers and their tests removed rather than left unused, so that the module does not carry two coreference mechanisms.
37. As a maintainer, I want `GLOSSARY.md` and the affected ADR updated in the same change, so that the domain vocabulary does not describe a mechanism that no longer exists.

## Implementation Decisions

### Mention Span

The Mention Span is the unit the annotator returns and the Coreference Critic
judges. As requested from the model it carries the sentence label, the mention
text verbatim, the occurrence number within that sentence (defaulting to the
first), and the canonical entity name. Python adds the derived character range
after validation. The derived range is internal to the Coreference Adapter and
is discarded once the substitution is applied.

`CriticValidation`, the current article-level `is_valid` plus `issues` shape, is
replaced by a per-Mention-Span verdict list rather than extended.

### Sentence numbering

A new pure module in the utilities package splits the Source Article's content
into numbered sentences and returns, for each, its label, its text, and its
character range in the content.

The splitter uses the sentence splitting already available through `chonkie`,
which is an existing dependency and reports contiguous, exact character ranges.
Two post-processing rules apply: a fragment consisting only of whitespace folds
into the preceding sentence, and a fragment shorter than a configured minimum
folds into the preceding sentence. Both rules preserve contiguity. The
concatenation of all sentence texts must equal the input content exactly, and
this is asserted, not assumed.

The known weakness is abbreviations — a title such as "Sen." ends a sentence
under the delimiter rules. The minimum-length rule absorbs most of these. Where
it does not, the consequence is a mis-numbered line, not lost text: the
annotator still sees every word in consecutive numbered lines, so the antecedent
remains visible, and validation is per-Mention-Span, so a bad split costs at
most one reference.

Sentence numbering exists only to give the annotator an addressable location. No
sentence label survives into the resolved text, so a chunk boundary falling
inside a sentence is not a concern for this work.

### Deriving the character range

For each returned Mention Span, Python looks up the sentence label's recorded
range, searches within that slice for the mention text on word boundaries,
selects the match indicated by the occurrence number, and offsets the match
position by the sentence's start. Anything that fails — unknown label, no match,
occurrence beyond the available matches — discards that Mention Span with a
recorded reason.

Word-index anchoring was considered and rejected: it requires the model and
Python to agree on tokenization, and disagreements over abbreviations,
hyphenation, and punctuation produce plausible-looking but wrong positions.
Occurrence counting is bounded by the matches of a string the model already
chose, and the matching rule on the Python side admits no interpretation.

A tool call letting the model fetch a sentence was considered and rejected: the
model would still need a locator to pass the tool, which is the problem the
numbering already solves, at the cost of an extra round trip.

### Applying the Mention Spans

Surviving Mention Spans are sorted by descending start position and each range
is replaced with its canonical entity name, producing the resolved text. Text
outside the replaced ranges is not touched, which is why no structural check is
needed. Overlapping ranges are reduced to one before substitution.

`replace_tags_with_entities` is replaced by this substitution function.
`strip_ref_tags`, `normalize_whitespace`, `check_structural_identity`, and
`clean_annotated_text` are deleted, along with the `structural_mismatch` branch
of the retry loop and its `CoreferenceResolutionError` failure type.

### The Coreference Critic

The Critic receives the numbered sentences once and the list of validated
Mention Spans, and returns one verdict per Mention Span, each carrying the
sentence label and mention identity it refers to, an accept or reject decision,
and a short reason when rejecting.

Verdicts naming a Mention Span that was not sent are ignored. A Mention Span
receiving no verdict is discarded. The retry, when the budget allows, re-asks
the annotator for the rejected Mention Spans only, supplying the Critic's
reasons; accepted Mention Spans are not re-derived.

Two model calls per article remain the accepted cost. The judgement being asked
of each call is now narrower than before.

### Failure and degradation

An article that ends with zero surviving Mention Spans fails and reaches
`FAILED_DLQ`. A Source Article of California political reporting with no
resolvable reference in it is a defect in the annotator, not a valid outcome,
and failing loudly puts the case where it can be read.

Three failure types distinguish the ways that happens, because they point at
three different defects: `no_mentions_returned` when the annotator returns an
empty list, which indicts the prompt or the model; `all_mentions_discarded` when
every returned Mention Span fails validation, which indicts mention matching or
the sentence splitter; and `all_mentions_rejected` when the Coreference Critic
rejects every one, which is a disagreement between the two models. Parse
failures and transport failures keep their existing handling.

A partial discard completes normally, however large the discarded proportion.
No threshold is imposed: any number chosen now would have no evidence behind it,
and the recorded discard proportion is what will set one later.

Dead Letter Queue records carry the numbered sentences the annotator was shown,
the Mention Spans, and each one's validation outcome, in place of the failed
annotated article. For `all_mentions_discarded` the sentence table is the only
thing that answers what the model was looking at when it named a mention that
could not be found. Article Status transitions in the Story Pipeline are
otherwise unchanged.

### Adapter contract

`CoreferenceAdapter.resolve`, taking content and returning resolved text, is
unchanged, as is its health check. The Story Pipeline, `chunk_article`,
embedding, extraction, and the Neo4j write path require no modification. No
Mention Span data is persisted to the graph.

### Documentation

`GLOSSARY.md` gains a **Mention Span** entry and loses or rewrites **Annotated
Article**, which describes the `<ref>` tag mechanism being removed. The
**Coreference Critic** entry is amended to describe per-Mention-Span verdicts.

ADR 0001 recorded the choice of XML tag markup with a Critic loop. A new ADR
supersedes that portion of it, recording the move to Mention Spans and the
reasoning above; ADR 0001's chunking and Neo4j decisions stand.

## Testing Decisions

A good test here asserts on the resolved text and on which Mention Spans
survived, both of which are externally observable. It does not assert on prompt
strings, on the order of internal helper calls, or on the derived character
ranges, which are internal bookkeeping.

The primary seam is the Coreference Adapter's `resolve`, driven with both agents
overridden by `FunctionModel`. `tests/test_coreference.py` already establishes
this pattern, and the new tests replace the tag-based ones in place. Cases:
clean resolution; a Mention Span rejected by the Critic while its neighbours
survive; a Mention Span whose mention text is absent from its sentence; an
occurrence number beyond the available matches; a hallucinated sentence label; a
sentence containing the same pronoun twice mapped to two different entities; a
retry that corrects only the rejected Mention Spans; and an article where every
Mention Span is discarded, which must return the original content.

Two pure functions are tested directly because they are the deterministic core
and cheap to exercise: the sentence splitter, whose property that concatenated
sentence texts equal the input is asserted over articles with newlines,
abbreviations, and quotation marks; and the substitution function, given
hand-written Mention Spans covering adjacent ranges, ranges at the start and end
of the content, and overlapping ranges.

The Story Pipeline tests in `tests/test_pipeline.py` use mock adapters and
should need no change, since the adapter contract is unchanged. Confirming that
they pass untouched is part of the acceptance for this work.

Tests covering `strip_ref_tags`, `normalize_whitespace`,
`check_structural_identity`, and `replace_tags_with_entities` are deleted with
the functions.

## Out of Scope

- Persisting Mention Spans to Neo4j or to any node property.
- Marking substituted text in the Article Chunk, whether by brackets or otherwise.
- Embedding the original text instead of the resolved text; the resolved text stays the embedding input.
- Changing `chunk_article`, the overlap refinery, or the Article Chunk schema.
- Building the Coreference Resolution evaluation or its silver set; this work only makes per-reference scoring possible.
- Automatic replay of Dead Letter Queue records.
- Setting a discard-proportion threshold that fails an article on partial discard.
- Splitting the annotator call across sentence ranges for long articles.
- Cross-sentence entity consistency checking beyond what the Critic already judges.

## Further Notes

The occurrence number is expected to be unused in the large majority of Mention
Spans, since distinct mentions in one sentence are usually distinct strings. It
exists for the genuine repeat case, and the discard rules keep an over-counted
occurrence from doing damage.

The proportion of discarded Mention Spans is the metric to watch after this
lands, and it is what a partial-discard threshold should eventually be set
from. If it is high, the next lever is a tool letting the annotator confirm a
sentence's text before committing, which was deliberately deferred here.

## Comments

### Previously discussed — 2026-08-19 grilling session

How this rework gets judged, given that evaluation work is deliberately paused:

- **Ingestion rate is the first signal.** 59 of 73 stories in `document_store.db`
  sat at `FAILED_DLQ` under the tag-reconstruction approach this project replaces.
  Re-run the corpus and read the completion count.
- **Ingestion rate is not sufficient.** It measures that the Structural Identity
  Check passed, not that pronouns resolved to the right people. Wrong coreference
  produces a graph that is confidently wrong rather than empty, which is worse for
  a product whose promise is provenance. **Hand-check ten articles' resolved
  mentions** before trusting a full run.
- **Do not unpause the evaluation framework for this.** The Coreference
  evaluation in the
  [Model Evaluation initiative](../../initiatives/model-evaluation/MAP.md) stays
  frozen; the hand-check is a one-time judgment, not an Evaluation Silver Set.
- Related: the bracketed rendering of substitutions in retrieval answers doubles
  as an ongoing visibility check on coreference quality, since a reader sees every
  alteration. See
  [08-retrieval-and-answer-contract.md](../../initiatives/useful-graph-retrieval/issues/08-retrieval-and-answer-contract.md).
