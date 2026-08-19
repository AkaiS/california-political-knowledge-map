# 01 — Chunk text excludes the overlap

Labels: ready-for-agent

## Parent

[Bill Designation Recovery](../PRD.md)

## What to build

An Article Chunk's text is the chunk's own body and nothing else. The overlap
stops being prepended to it and travels only in the chunk's context field, where
it is already carried and where nothing currently reads it.

Today the overlap refinery slices the previous chunk's trailing characters at a
character offset and prepends them to the next chunk's text. In the Uber
ballot-measure article that slice landed inside `Senate Bill 623`, the chunk
began `ll 623 would also prohibit the sale of such liens`, and the extraction
model claimed a `Bill` named `ll 623` — correctly, because that is what its
chunk said. Every chunk in that article begins mid-word; this one begins mid-word
inside something that mattered.

The overlap is retained. What changes is which consumers see it as part of the
text they are working on. The context is snapped outward to a word start, so
concatenating context with text reproduces a contiguous span of the article. The
Embedding Adapter and the Graph Database Adapter's chunk write consume that
concatenation, which is byte-identical to the text they receive today, so
retrieval behaviour and stored Retrieval Evidence do not change.

The Entity Extraction Adapter receives the text only. Coreference Resolution
already runs on the whole Source Article before chunking, so canonical names are
substituted throughout and the overlap is not what carries entity identity across
a boundary. The accepted cost is claims stated across a chunk boundary. Measured
across the 73 stories in the document store at the current chunk size, 1613
boundaries fall as 91.1% at a paragraph end, 8.6% at a sentence end, and 0.3%
mid-sentence — five boundaries, four at a comma or before a closing quote and one
inside the hyphenated `cross-collaboration`. That 0.3% is the recorded cost of
extracting from the body alone.

## Acceptance criteria

- [ ] An Article Chunk's text is the recursive chunker's output, unmodified; no
      chunk's text begins with characters belonging to the previous chunk.
- [ ] The chunk's context holds the overlap and begins at a word boundary.
- [ ] Concatenating a chunk's context with its text reproduces a contiguous span
      of the Source Article.
- [ ] The Embedding Adapter embeds context concatenated with text.
- [ ] The chunk write stores context concatenated with text, so stored Retrieval
      Evidence is unchanged from today.
- [ ] The Entity Extraction Adapter is called with the text alone.
- [ ] Re-chunking the Uber ballot-measure article produces no chunk beginning
      `ll 623`, covered as a regression test written from the real article text.
- [ ] The existing chunking tests asserting context length and its relationship
      to the previous chunk's text are updated to the new contract.

## Blocked by

- None — can start immediately.
