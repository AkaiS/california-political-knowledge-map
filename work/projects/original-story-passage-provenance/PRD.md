# Original Story Passage Provenance

Labels: ready-for-agent

## Problem Statement

A person can find relevant CalMatters reporting through full-text, dense, or
graph retrieval and still receive "Grounding Evidence could not be assembled
and verified." The Story Pipeline resolves Mention Spans before it creates
Article Chunks, then stores the resolved wording with overlap in Neo4j. The
Evidence Assembler currently looks for that stored wording as an exact substring
of the original Story in SQLite. A legitimate replacement such as "she" with a
person's name makes the lookup fail. Repeated wording can also make the first
substring match the wrong occurrence. The Chat Agent must not quote transformed
text as if it appeared in the original Story.

The system knows the original positions of accepted Mention Spans during
Coreference Resolution and the resolved-text positions of each Article Chunk
during chunking. It currently discards the connection between those coordinate
systems. That is why retrieval can identify the right Article Chunk but cannot
reliably provide its original passage to the Chat Agent.

## Solution

Keep coreference-resolved Article Chunks, their overlap, and their embeddings
for retrieval. During the Story Pipeline run, carry the accepted Mention Spans'
original positions through chunking and calculate the smallest contiguous
original Story range represented by each stored Article Chunk. Save that range
and a fingerprint of the original Story content on the Neo4j Chunk node.

When the Evidence Assembler selects Grounding Evidence, it loads the original
Story, checks the fingerprint and range, and takes the passage directly from
the Story body. The Chat Agent receives that original passage, citation, and
retrieval provenance. It never receives coreference-resolved wording as a
quotation. The passage contains the chunk's mapped range only, including the
overlap already stored with the chunk. It does not add neighboring sentences.

A replacement is indivisible for this mapping. If a stored chunk begins or
ends inside the canonical name substituted for an accepted Mention Span, the
mapped range includes the entire original mention. No fractional character
position inside the replacement is claimed to correspond to a fractional
position inside the original mention.

## User Stories

1. As a person asking about California politics, I want relevant reporting to
   reach the Chat Agent even when Coreference Resolution changed a pronoun, so
   that I can inspect the source instead of receiving an avoidable evidence
   failure.
2. As a person reading a Retrieval Answer, I want quoted wording to appear in
   the original Story, so that I can check it against the publication.
3. As a person reading a Retrieval Answer, I want the original pronoun or
   referring expression preserved in a quote, so that a model-written
   canonical name is not presented as the publication's wording.
4. As a person reading a Retrieval Answer, I want the selected passage tied to
   the Source Article that retrieval found, so that the citation points to the
   right reporting.
5. As a person reading several passages from one Source Article, I want each
   passage to come from its own recorded range, so that repeated sentences do
   not silently collapse onto the first occurrence.
6. As a person reading a Retrieval Answer, I want a passage to stop at its
   mapped Article Chunk boundary, so that the system does not add nearby
   sentences I did not ask it to include.
7. As a person reading a passage whose boundary intersects a replacement, I
   want the whole original mention shown, so that the quote is a real
   contiguous excerpt rather than an invented fraction of a word.
8. As a person asking a question found through full-text retrieval, I want the
   same original-wording rule as for other retrieval routes, so that the route
   does not change what counts as a quote.
9. As a person asking a question found through dense retrieval, I want
   coreferenced embeddings to remain available, so that source verification
   does not weaken the search index.
10. As a person asking a Relational Question, I want graph claims to retain
    their Article Chunk provenance when a passage is verified, so that the
    original excerpt does not erase the route that found it.
11. As a person asking a question with partial corpus coverage, I want
    provenance failures to remain distinct from Deferred coverage, so that I
    am not told material is missing merely because a chunk cannot be verified.
12. As a person asking a question, I want a stale or malformed chunk range to
    fail verification, so that the Chat Agent cannot quote unrelated Story
    wording.
13. As a Story Pipeline operator, I want accepted Mention Span positions to
    remain available after Coreference Resolution, so that chunk ranges can be
    mapped without another model call.
14. As a Story Pipeline operator, I want offsets calculated against the full
    Source Article, so that separately numbered sentences and length-changing
    replacements do not shift later passages to the wrong place.
15. As a Story Pipeline operator, I want the stored range to cover the text
    indexed for retrieval, including the chunk's overlap prefix, so that the
    displayed passage corresponds to what retrieval matched.
16. As a Story Pipeline operator, I want malformed or inconsistent replacement
    positions rejected before writing chunks, so that bad provenance does not
    enter the graph.
17. As a maintainer, I want legacy chunks without original ranges to fail
    closed, so that deployment does not silently revive substring guessing.
18. As a maintainer, I want a controlled way to repopulate existing chunks
    with provenance, so that the current corpus can use this behavior.
19. As a maintainer, I want tests that exercise the Story Pipeline and Evidence
    Assembler with ordinary storage fakes, so that the behavior is checked
    without live models, databases, or a browser.
20. As a maintainer, I want the existing retrieval ranking, coverage,
    citations, and context limits to behave as before, so that this change
    stays about passage provenance.

## Implementation Decisions

- Keep the current order: Coreference Resolution, Article Chunking, embedding,
  Entity Extraction, and Neo4j persistence. The stored Chunk text remains the
  coreference-resolved chunk body plus its existing overlap prefix. Full-text
  and dense retrieval continue to use that text and its embedding.
- The Coreference Resolution Run must expose the final accepted, located
  substitutions with half-open original Source Article offsets and their
  replacement text. These are Python-derived positions, not positions supplied
  by the model. Rejected and discarded Mention Spans do not contribute to the
  mapping. The existing outcome audit remains intact.
- Build a resolved-to-original offset map from the accepted substitutions in
  full Source Article coordinates. Numbered sentences locate mentions in the
  original text; replacements may change the lengths of later sentences, so
  sentence-local arithmetic alone is insufficient. Validate nonoverlap,
  original mention text, and that replaying the substitutions produces the
  Coreference Resolution Run's resolved text. Inconsistent input fails the
  Story Pipeline before chunk persistence.
- For each Article Chunk, map the half-open resolved interval from the start
  of its stored overlap prefix to the end of its body. The resulting original
  range is the smallest contiguous Story range covering that interval. With
  no substitutions, this is the identical interval in the original content.
- Treat each replacement as one atomic mapping unit. A boundary strictly
  inside replacement text maps outward to include the whole original mention.
  A boundary exactly at a replacement edge maps to that corresponding
  original edge. If both boundaries lie inside the same replacement, the
  passage is the entire original mention. This is the only boundary widening;
  do not add surrounding sentences or a configurable quote window.
- Store the original start, original end, and a content fingerprint with each
  Neo4j Chunk. Use half-open Python string offsets and a SHA-256 fingerprint of
  the original content encoded as UTF-8. The fingerprint belongs to each
  chunk's provenance so a reprocessed chunk can be checked against the Story
  version it came from. No Mention Span map or additional Story column is
  persisted.
- Grounding Evidence hydration returns the range and fingerprint alongside
  the existing Chunk identity and citation. The Evidence Assembler checks the
  selected Chunk and Source Article identities, the Story URL, exact content
  fingerprint, and `0 <= start < end <= len(Story.content)`. It constructs a
  Verified Passage from `Story.content[start:end]` and those offsets. It does
  not search for Chunk text in the Story, reverse Coreference Resolution at
  read time, or use the resolved text as displayed quotation.
- Preserve the current Evidence Assembly failure behavior when metadata is
  missing, invalid, or stale. Do not classify provenance failure as Deferred,
  a failed retrieval branch, or an empty search. The Chat Agent's existing
  evidence rendering continues to exclude unverified stored Chunk wording.
- Existing graph chunks have no original range. Do not infer one at live
  retrieval time or guess by first substring match. A separate, one-time
  model-free backfill will measure and conditionally restore ranges for chunks
  it can map uniquely. Unresolved legacy chunks fail verification. Selective
  reingestion is a later decision, not the default migration path.
- Update the evidence-storage and retrieval-contract documentation to state
  the new range and fingerprint contract. This change does not alter question
  policy or the Coverage Description.

## Testing Decisions

- Test observable behavior at the existing Story Pipeline and Evidence
  Assembler boundaries. Use the pipeline's injected adapters to capture
  persisted Chunk provenance and the assembler's injected storage functions
  to observe the resulting Verified Passage. Prefer one end-to-end contract
  case connecting those observations over tests of private arithmetic.
- Add a small focused test of the offset mapper for the one rule that is easy
  to hide behind integration setup: a boundary strictly inside a replacement
  includes the entire original mention, while a boundary at either edge maps
  exactly. Cover a chunk whose two boundaries fall inside the same
  replacement.
- Cover no substitutions, multiple length-changing substitutions across
  numbered sentences, repeated original wording, and the existing overlap
  prefix. Assert the returned passage and offsets against the original Story,
  not the internal shape of the map.
- Cover missing, negative, inverted, out-of-bounds, and stale-hash provenance;
  a mismatched Story or Source Article; and resolved Chunk text that differs
  from the original. Each must fail safely rather than produce a quote.
- Cover a valid full-text, dense, and structural candidate through the same
  assembly behavior where those routes affect provenance. Preserve ranking,
  citation, coverage, and context-budget behavior.
- Existing prior art is the Story Pipeline's fake-adapter tests, Article
  Chunking offset tests, the Evidence Assembler's in-memory storage tests,
  and the Evidence Store's hydration tests. Add deterministic adapter coverage
  for the Neo4j Chunk properties and hydration fields. No live-model or
  browser test is required.

## Out of Scope

- Saving the full Mention Span or reverse-coreference map in Neo4j or SQLite.
- Replacing coreference-resolved text or embeddings with original wording.
- Adding neighboring sentences, quote windows, summaries, or a second model
  to choose a better excerpt.
- Proving at read time that the resolved Chunk is a faithful transformation
  of the original Story. The range and fingerprint verify the quoted original
  passage and its source version; they do not independently rejudge the
  Coreference Critic's decision.
- Changing Query Rewrite, Deferred policy, branch fusion, retrieval ranking,
  Chat Session lifecycle, or context limits.
- Solving the separate stale-relationship and orphan-node reprocessing defect.

## Further Notes

ADR 0016 assigns Mention Span location and substitution to Python. ADR 0001
keeps coreference-resolved Article Chunks and embeddings in Neo4j. This spec
uses both decisions and adds provenance to the existing Chunk node. The
original Story in SQLite remains the authority for quoted wording.

The current Evidence Assembler treats an exact first substring match as
verification. This spec replaces that rule. A range and matching fingerprint
establish which characters of the current original Story are being quoted;
they do not establish that the coreferenced search text was semantically
correct. That is the intentional limit of the minimal change.
