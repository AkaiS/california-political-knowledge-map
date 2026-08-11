Labels: completed

## Parent

[News Ontology and Graph Population](../PRD.md)

## What to build

Bills stop colliding across sessions. Bill numbers recycle every two years, and
the gathered Source Articles already demonstrate the problem: a 2026 article links
`201920200AB218` and another links `201720180SB54`. Merging those with
current-session bills of the same number silently conflates distinct bills, which
is disqualifying for the historical retrieval this map exists to serve.

The session is resolved from the hyperlinks the article actually contains rather
than guessed from prose. The `Story` domain model already carries the links found
in an article's body; `SourceArticle` gains the same links, and the batch
ingestion service populates them when building it. A pure URL parser recognizes
the two known bill URL schemes — `.../bills/ca_202520260ab1776` and
`...bill_id=201920200AB218`, both encoding the same session/chamber/number triple.

Matching is on the **parsed bill number**, never the link's anchor text. Anchor
text in the gathered articles is largely unusable — "June budget", "with a bill",
"sanctuary law." — while the number is exact and present in every case.

Three resolution tiers:

1. A link whose parsed number matches an extracted `Bill`'s number supplies the
   session authoritatively; the node is flagged session-verified.
2. No matching link: the session is derived from the article's publication date
   under California's two-year, odd-year-start convention; the node is flagged
   session-inferred. Dropping unlinked bills would discard the majority of bill
   mentions, and leaving them session-less would create a second identity shape a
   later correct-session ingest could not find in order to fix.
3. Two links in one article resolving the same number to different sessions: no
   session is assigned and the node is flagged for review, so the ambiguity is
   visible rather than arbitrarily decided.

The flag distinguishing verified from inferred is what makes it measurable how
much of the bill layer is guessing. The session participates in the `Bill`
primary key.

Known error mode, accepted and recorded: an article discussing a prior-session
bill without linking it is mis-sessioned by tier 2. This is rarer than the
collisions tiers 1 and 2 together prevent, and is detectable later by joining
against authoritative bill data.

Resolution runs **once per Source Article** in the Story Pipeline, not once per
chunk, so the same links are not parsed repeatedly. The database adapter's
chunk-extraction ingestion signature gains the resolved session map as plain
data, keeping the Graph Database Adapter free of any SQLite dependency and
testable without either database.

Article content in the document store is plain prose with no inline links, which
is why resolution reads the stored link table rather than asking the model to
report URLs it never sees.

## Acceptance criteria

- [x] `SourceArticle` carries the article's links, populated by the batch
      ingestion service.
- [x] Both bill URL schemes parse to session, chamber and number.
- [x] Matching is on the parsed number; anchor text is not consulted.
- [x] Tier 1 produces a session-verified `Bill`; tier 2 a session-inferred one
      from the publication date; tier 3 leaves the session unset and flags the
      node for review.
- [x] The session participates in the `Bill` primary key, so same-numbered bills
      from different sessions are distinct nodes.
- [x] Resolution runs once per Source Article, observably not once per chunk.
- [x] The resolved session map reaches the database adapter as plain data, and the
      Graph Database Adapter acquires no dependency on the document store.
- [x] Covered through the Story Pipeline with mock adapters — no dedicated unit
      test for the parser is required, since all of the above is observable there.

## Blocked by

- [06 — Node identity, provenance, and topic edges](06-node-identity-provenance-and-topic-edges.md)
