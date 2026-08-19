# 02 — Bill Designation parsing, four forms only

Labels: completed

## Parent

[Bill Designation Recovery](../PRD.md)

## What to build

A `Bill`'s identity comes from its Bill Designation — the chamber and number
together, normalized to `SB 623` or `AB 1751` — parsed from the name the article
used. The Entity Extraction Adapter stops being asked for a bill number.

California writes a bill four ways: `SB`, `AB`, `Senate Bill`, `Assembly Bill`,
followed by digits. Parsing accepts exactly those, case-insensitively, with an
optional space or hyphen before the digits, and nothing else. The current rule
accepts any two or three letters before a number, which is why it accepts
`ll 623` and rejects `Senate Bill 9`, `Assembly Bill 1751`, and every other
spelled-out form in the graph — broad where it produces garbage and narrow where
it matters.

`number` leaves the News Ontology's `Bill` properties, so the Extraction Prompt
stops listing it and the conformance gate drops it if a model emits it anyway.
The model reports the name as the article wrote it: `Senate Bill 623`, `SB 623`,
`the bill`. The property is not deleted from the primary ontology — a later
legislative ingester supplies it authoritatively — it stops being something news
extraction is asked for. Bill Session Resolution supplies it instead, writing the
parsed Bill Designation into it.

Bill Session Resolution and `Bill` key minting read the node's name. Neither
reads an extracted `number` property, and the preference for a `number` property
over the name — the reason `Senate Bill 9` normalized `"9"`, failed, and never
tried its own name — is gone.

The three session tiers established by [News Ontology and Graph Population issue
07](../../news-ontology-graph-population/issues/07-bill-session-resolution.md)
are unchanged. Only the value they are keyed on changes.

## Acceptance criteria

- [x] `SB 623`, `sb623`, `Senate Bill 623`, and `senate bill 623` all parse to
      the Bill Designation `SB 623`; the Assembly forms parse to `AB`.
- [x] `ll 623`, `to 5`, and `the bill` parse to no Bill Designation.
- [x] `number` is absent from the News Ontology's `Bill` properties, and the
      regenerated ontology document and Extraction Prompt no longer list it.
- [x] `number` remains declared on `Bill` in the primary ontology.
- [x] The parsed Bill Designation is written to the `Bill` node's `number`
      property by the resolution, not by the extraction.
- [x] No code outside the ontology reads an extracted `number` property.
- [x] A Source Article naming `Senate Bill 623` resolves it to a session under
      the same three tiers as one naming `SB 623`, observable through the Story
      Pipeline with mock adapters.

## Blocked by

- None — can start immediately.
