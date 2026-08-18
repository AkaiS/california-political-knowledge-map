# 05 — Record the Bill Designation vocabulary

Labels: ready-for-agent

## Parent

[Bill Designation Recovery](../PRD.md)

## What to build

`CONTEXT.md` gains **Bill Designation**: the chamber and number of a California
bill together, normalized to the initials form — `SB 623`, `AB 1751`. It is what
qualifies a `Bill`'s identity alongside its Bill Session Resolution, it is
written to the `Bill` node's `number` property, and it is supplied by resolution
rather than by extraction. Its _Avoid_ line rules out "bill number" used alone,
which is the phrasing that let a chamber-less `9` pass as an identifier.

The primary ontology's `Bill` documentation is reconciled to that form. It
currently gives `number` the example `SB-32` and the primary key
`20252026_SB32`, neither of which matches the `SB 623` the write path now
produces. One form wins and both places say it, so the legislative ingester that
arrives later writes the same string the news pipeline wrote.

No new ADR. Nothing here supersedes a decision — [ADR 0015](../../../docs/adr/0015-resolve-identity-bearing-values-once-per-source-article.md)
already places this resolution at article scope, and this project moves the write
decision into that resolution rather than changing where it lives.

## Acceptance criteria

- [ ] `CONTEXT.md` defines Bill Designation, with an _Avoid_ line covering "bill
      number" used without a chamber.
- [ ] The Bill Session Resolution entry in `CONTEXT.md` names the Bill
      Designation as the value it resolves against.
- [ ] The primary ontology's `Bill` example and primary key use the same
      normalized Bill Designation form as the write path.
- [ ] No ADR is added.

## Blocked by

- [04 — Recover a Bill Designation from the Source Article](04-recover-designation-from-article.md)
