# 05 — Record the Bill Designation vocabulary

Labels: completed

## Parent

[Bill Designation Recovery](../PRD.md)

## What to build

`GLOSSARY.md` gains **Bill Designation**: the chamber and number of a California
bill together, normalized to the initials form — `SB 623`, `AB 1751`. It is what
qualifies a `Bill`'s identity alongside its Bill Session Resolution, it is the
`Bill` node's `name`, and it is supplied by resolution rather than by
extraction. Its _Avoid_ line rules out "bill number" used alone,
which is the phrasing that let a chamber-less `9` pass as an identifier.

The primary ontology's `Bill` documentation is reconciled to that form. It
currently gives `number` the example `SB-32` and the primary key
`20252026_SB32`, neither of which matches the `SB 623` the write path now
produces. One form wins and both places say it, so the legislative ingester that
arrives later writes the same string the news pipeline wrote.

No new ADR. Nothing here supersedes a decision — [ADR 0015](../../../docs/adr/0015-resolve-identity-bearing-values-once-per-source-article.md)
already places this resolution at article scope, and this project moves the write
decision into that resolution rather than changing where it lives.

`ontology.md` is corrected rather than merely reconciled. `:Bill` declared
`number` alone, and a bill number without its chamber cannot identify the bill it
keys, so `:Bill` now declares `name` holding the Bill Designation and `number` is
gone. That clears the bar [ADR 0014](../../../docs/adr/0014-the-primary-ontology-is-authored-not-frozen.md)
sets for editing the authored ontology, and the reason is recorded at the change
site in `ontology.md`. This issue originally called the change a reconciliation
of an example and a key; the criteria below are corrected to match what the
history shows.

## Acceptance criteria

- [x] `GLOSSARY.md` defines Bill Designation, with an _Avoid_ line covering "bill
      number" used without a chamber.
- [x] The Bill Session Resolution entry in `GLOSSARY.md` names the Bill
      Designation as the value it resolves against.
- [x] The primary ontology's `Bill` declares `name` holding the Bill
      Designation, drops `number`, and its example and primary key use the same
      normalized form as the write path.
- [x] The ADR 0014 justification for correcting `ontology.md` is recorded at the
      change site.
- [x] No ADR is added.

## Blocked by

- [04 — Recover a Bill Designation from the Source Article](04-recover-designation-from-article.md)
