# 0016. Mention Spans for Coreference Resolution

We decided that Coreference Resolution uses structured Mention Spans anchored
to numbered sentences rather than whole-article markup. The annotator returns
the sentence label, verbatim mention text, occurrence, and canonical entity;
Python derives the character offsets from the Source Article and applies the
accepted substitutions. The Coreference Critic returns one verdict per
Mention Span. This supersedes the coreference-markup and tag-resolution
portions of ADR 0001; its Article Chunking and Neo4j decisions remain in force.

## Considered Options

* **Word-index anchoring**: Rejected because it requires the model and Python
  to agree on tokenization, and disagreements over abbreviations, hyphenation,
  or punctuation can produce plausible but wrong positions.
* **Sentence-lookup tool**: Rejected because the model would still need a
  locator to pass to the tool. Numbered sentences provide that locator without
  an extra round trip.

## Consequences

The model never re-emits the Source Article or calculates a position. Text
outside accepted Mention Spans remains unchanged, and a rejected span can be
discarded without costing its neighbours. Per-Mention-Span verdicts and
outcomes are available for audit and future evaluation. The adapter returns
the resolved text together with each Mention Span's outcome rather than text
alone, so the Story Pipeline and the Dead Letter Queue record what happened to
every reference; nothing downstream of resolution changes.
