# 07 — Domain vocabulary and ADR

**What to build:** The written record catching up with the code, so the domain
glossary does not describe a mechanism that no longer exists.

`CONTEXT.md` gains a **Mention Span** entry. **Annotated Article** currently
describes a Source Article marked up with `<ref>` tags — a thing this project
deleted — and is rewritten or removed. **Coreference Critic** currently describes
validating an Annotated Article and is amended to describe per-Mention-Span
verdicts.

ADR 0001 recorded the choice of LLM-based tagging with XML tags and a
self-correcting Critic loop. A new ADR supersedes that portion of it, recording
the move to Mention Spans anchored to numbered sentences, Python-derived
character offsets, and per-reference Critic verdicts, along with the two
alternatives rejected along the way: word-index anchoring, which requires the
model and Python to agree on tokenization, and a sentence-lookup tool, which
still needs a locator to pass it. ADR 0001's chunking and Neo4j decisions stand
unchanged.

**Blocked by:** 06 — Delete the tag machinery.

Labels: completed

- [x] `CONTEXT.md` defines **Mention Span**, with an `_Avoid_` line following the file's existing convention.
- [x] The **Annotated Article** entry no longer describes `<ref>` tag markup.
- [x] The **Coreference Critic** entry describes per-Mention-Span verdicts rather than validating a marked-up article.
- [x] The **Coreference Resolution** and **Coreference Adapter** entries are checked against the shipped behaviour and corrected where they disagree.
- [x] A new ADR records the move to Mention Spans, names the two rejected alternatives and why, and states which part of ADR 0001 it supersedes.
- [x] ADR 0001 is annotated as superseded in the portion covering coreference markup, with its chunking and Neo4j decisions left standing.
- [x] No document in the repository describes current coreference as producing tagged article text. Where a banner-marked historical record or this project's own specification names the retired `<ref>` tag format, it does so in the past tense or as the thing being removed.
