# 05 — Zero-survivor failures and Dead Letter Queue payload

**What to build:** An article that ends with no surviving Mention Spans fails and
reaches `FAILED_DLQ`, carrying a record that says which of three defects caused
it. A Source Article of California political reporting with no resolvable
reference in it is a broken annotator, not a valid outcome, and it should be
readable rather than silently ingested unresolved.

Three failure types separate three different diagnoses. The annotator returning
an empty list indicts the prompt or the model. Every returned Mention Span
failing validation indicts mention matching or the sentence splitter. Every
Mention Span being rejected by the Coreference Critic is a disagreement between
the two models. Collapsing these into one type would force reading the payload to
tell them apart.

The Dead Letter Queue record carries the numbered sentences the annotator was
shown, alongside the Mention Spans and each one's outcome. For the all-discarded
case the sentence table is the only thing that answers what the model was looking
at when it named a mention that could not be found.

A partial discard completes normally however large the discarded proportion. No
threshold is imposed — any number chosen now would have no evidence behind it.
The proportion is recorded on every run so a threshold can be set later from real
distributions.

**Blocked by:** 04 — Per-Mention-Span Critic verdicts and targeted retry.

**Status:** ready-for-agent

- [ ] An annotator returning no Mention Spans fails the article with a failure type distinct from the other two.
- [ ] An article whose Mention Spans are all discarded by validation fails with its own failure type.
- [ ] An article whose Mention Spans are all rejected by the Coreference Critic fails with its own failure type.
- [ ] Each of the three failures writes a Dead Letter Queue record and sets the Article Status to `FAILED_DLQ`.
- [ ] The Dead Letter Queue record carries the numbered sentences the annotator was shown, the Mention Spans, and each Mention Span's outcome, in place of a failed annotated article.
- [ ] An article with at least one surviving Mention Span completes, whatever proportion of its Mention Spans were discarded.
- [ ] The proportion of discarded Mention Spans is recorded on every resolution run, including successful ones.
- [ ] Per-Mention-Span outcomes are available from a resolution run, so a future evaluation can score references individually.
- [ ] Existing Article Status transitions in the Story Pipeline are otherwise unchanged, and the Story Pipeline tests still pass without modification.
- [ ] Parse failures and transport failures keep their existing handling.
