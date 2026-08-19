# 03 — Annotator returns Mention Spans, wired end to end

**What to build:** Coreference Resolution stops rewriting the Source Article. The
annotator reads the article as numbered sentences and returns a structured list
of Mention Spans; the Coreference Adapter validates them, applies the survivors,
and returns the resolved text.

This is the ticket that removes transcription from the model's job. Today the
annotator re-emits several thousand words with `<ref>` tags embedded and a
structural check rejects the whole article over a single changed character.
After this ticket the model emits only its entity judgements, and the text
outside the substituted ranges cannot change because Python never rewrites it.

The Coreference Critic is not called in this ticket. Every Mention Span that
survives validation is applied. That leaves resolution unchecked until ticket 04,
which matters only if ingestion runs between the two.

The adapter's external contract does not change: content in, resolved text out.
The Story Pipeline, chunking, embedding, extraction, and the Neo4j write path are
untouched.

**Blocked by:** 02 — Mention Span schema, validation, and substitution.

Labels: completed

- [x] The annotator prompt presents the Source Article as numbered sentences, one per line, each prefixed with the label the model is to copy back.
- [x] The annotator's output is a list of Mention Spans, not text; a response that does not parse as that list is a failure rather than a silently accepted string.
- [x] The Coreference Adapter's resolve takes a Source Article's content and returns resolved text, unchanged in signature and in health check behaviour.
- [x] Resolution runs splitter, annotator, validation, substitution, in that order, with no structural comparison anywhere in the path.
- [x] A Source Article with pronouns resolvable to canonical entities returns text with those pronouns replaced and every other character identical to the input.
- [x] A Mention Span discarded by validation does not prevent its neighbours in the same article from being applied.
- [x] The Story Pipeline's own behaviour is unchanged. Edits to the Story Pipeline tests are confined to the model-response fixtures that encode the annotator and Coreference Critic contract; no assertion about pipeline behaviour is weakened or removed.
- [x] The annotator no longer receives instructions to reproduce the article text, and its prompt no longer describes `<ref>` tags.
- [x] Tests drive this through the Coreference Adapter's resolve with the annotator agent overridden, following the existing pattern in the coreference tests.
