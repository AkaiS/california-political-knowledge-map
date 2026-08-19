# 04 — Recover a Bill Designation from the Source Article

Labels: ready-for-agent

## Parent

[Bill Designation Recovery](../PRD.md)

## What to build

A `Bill` name that yields no Bill Designation on its own is matched against the
Bill Designations the rest of its Source Article did yield, before any key is
minted.

The digits in the unparsed name are compared against the designations resolved
elsewhere in the article. Exactly one match adopts that designation: `ll 623` in
an article that also named `Senate Bill 623` five times adopts `SB 623`, resolves
to the same session, and mints the same key. Two or more matches adopt none and
set `needs_review`, so an article naming both `SB 623` and `AB 623` does not
resolve the ambiguity by iteration order. A name with no digits attempts no
recovery and keeps the flagged-nothing resolution from ticket 03.

Recovery runs inside Bill Session Resolution, which already reads every chunk's
extraction at once, so it does not depend on chunk order — resolving the same
extractions in either order yields an equal map, as [ADR 0015](../../../docs/adr/0015-resolve-identity-bearing-values-once-per-source-article.md)
requires. Running it before keys are minted is what prevents the duplicate node
rather than repairing it: `Senate Bill 623` and `ll 623` become one node instead
of two that a later pass has to merge.

Ticket 01 removes the chunk boundary that produced `ll 623`, so that exact name
will not recur from chunking. Recovery covers the class rather than the instance
— a name the model shortened or abbreviated on its own reaches the same node as
the article's full form.

## Acceptance criteria

- [ ] A name yielding no Bill Designation but containing digits matching exactly
      one article-level Bill Designation adopts it.
- [ ] `ll 623` in the Uber ballot-measure extractions mints the same key as
      `Senate Bill 623`, producing one node rather than two.
- [ ] Digits matching two or more article-level Bill Designations adopt none and
      set `needs_review`.
- [ ] A name with no digits attempts no recovery.
- [ ] Recovery happens before any key is minted; no duplicate node is written and
      merged afterwards.
- [ ] Resolving one article's extractions in reversed chunk order yields an equal
      resolution map.

## Blocked by

- [03 — Every extracted Bill gets a resolution](03-resolution-covers-every-bill.md)
