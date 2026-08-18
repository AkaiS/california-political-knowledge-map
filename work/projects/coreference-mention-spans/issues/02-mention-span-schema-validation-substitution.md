# 02 — Mention Span schema, validation, and substitution

**What to build:** The Mention Span — the unit the annotator will return and the
Coreference Critic will judge — together with the rules that decide whether one
is usable and the function that applies the usable ones to produce resolved text.

A Mention Span as returned by a model carries the sentence label, the mention
text verbatim, which occurrence of that text within the sentence it refers to
(defaulting to the first), and the canonical entity name. Given the numbered
sentences from ticket 01, the character range is derived in Python: look up the
sentence label's recorded range, search that slice for the mention text on word
boundaries, select the match the occurrence number indicates, and offset it by
the sentence's start. No offset in the system originates from model arithmetic.

Substitution replaces each surviving range with its canonical entity name,
working in descending start position so earlier ranges stay valid as later ones
are rewritten. Text outside the replaced ranges is not touched, which is the
property that makes a structural check unnecessary.

No model is involved. Hand-written Mention Spans in, resolved text plus a list of
discards out.

**Blocked by:** 01 — Numbered sentence splitter.

**Status:** ready-for-agent

- [ ] A Mention Span requested from a model carries a sentence label, mention text, an occurrence number defaulting to the first, and a canonical entity name.
- [ ] Given numbered sentences and a Mention Span, the derived character range locates the mention in the content and is not supplied by the model.
- [ ] Mention text is matched on word boundaries, so a mention of "her" does not match inside "there".
- [ ] A Mention Span naming a sentence label that does not exist is discarded with a recorded reason, and does not raise.
- [ ] A Mention Span whose mention text does not occur in its named sentence is discarded with a recorded reason.
- [ ] A Mention Span whose occurrence number exceeds the matches available in its sentence is discarded with a recorded reason.
- [ ] Two Mention Spans resolving to overlapping character ranges are reduced to one before substitution, with the dropped one recorded as discarded.
- [ ] A sentence containing the same pronoun twice, with two Mention Spans distinguished only by occurrence number, resolves each occurrence to its own canonical entity.
- [ ] Substitution of an empty Mention Span list returns the content unchanged.
- [ ] Substitution leaves every character outside the replaced ranges identical to the input content.
- [ ] Adjacent ranges, a range at position zero, and a range ending at the last character of the content all substitute correctly.
- [ ] Every discard is reported with the Mention Span it came from and the rule that rejected it.
