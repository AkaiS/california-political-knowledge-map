# 01 — Numbered sentence splitter

**What to build:** A utility that takes a Source Article's content and returns its
sentences as an ordered, addressable list — each sentence carrying a label, its
text, and its character range in the content. This is the addressing scheme the
annotator prompt will use, so the model can name a location by copying a visible
label instead of counting.

The splitter uses the sentence splitting already available through `chonkie`, an
existing dependency that reports contiguous, exact character ranges. Two
post-processing rules apply, both preserving contiguity: a whitespace-only
fragment folds into the preceding sentence, and a fragment shorter than a
configured minimum folds into the preceding sentence. The second rule absorbs
most abbreviation splits such as a title ending in a period.

Nothing consumes this yet. It is a pure module, verifiable on its own.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Given a Source Article's content, the utility returns sentences in document order, each with a label, its text, and its start and end character positions in the content.
- [ ] Concatenating every returned sentence's text reproduces the input content exactly, character for character. This is asserted in the code, not only in tests.
- [ ] Each returned sentence's text equals the content sliced by that sentence's recorded range.
- [ ] A whitespace-only fragment does not appear as its own sentence; its characters belong to the preceding sentence.
- [ ] A fragment shorter than the configured minimum does not appear as its own sentence; its characters belong to the preceding sentence.
- [ ] The first sentence starts at position zero and the last ends at the length of the content, with no gaps between consecutive sentences.
- [ ] The concatenation invariant holds over content containing newlines, blank lines, abbreviations such as a title ending in a period, quotation marks, and parentheses.
- [ ] Empty content returns an empty list rather than raising.
- [ ] Content with no sentence delimiter at all returns exactly one sentence spanning the whole content.
