Labels: completed

## Parent

[News Ontology and Graph Population](../PRD.md)

## What to build

A machine-readable statement of what the news extraction pipeline can produce, so
that the answer is a lookup rather than an investigation, and so that it cannot
drift from the primary ontology unnoticed.

An `ontology` package under the knowledge map holds three things:

- A **primary ontology** module mirroring [`ontology.md`](../../../../ontology.md):
  the label set, the sub-label map, per-label property *names* (names only — a
  full property schema with types is explicitly not attempted), and a
  relationship table mapping each relationship type to its permitted source and
  target labels.
- A **News Ontology** module declaring its own label set, relationship set,
  per-label property names, the Policy Area vocabulary from ticket 01, and its
  **shortcut rules**.
- The **conformance check** relating the two.

`ontology.md` is not edited. It remains the destination shape later authoritative
ingestion fills in; the News Ontology is the record of how far short of it news
alone falls.

The News Ontology excludes `LegislativeTenure`, `District` and
`RedistrictingCycle`, whose primary keys need facts news prose does not supply,
and with them `HELD_TENURE`, `REPRESENTS_DISTRICT`, `TRANSITIONED_BY` and
`EVOLVED_INTO`. `LegislativeEvent` and its `ACTION_ON` edge to `Bill` are
retained — a stated event date is the one reliable date news gives, and
flattening votes onto `Bill` would conflate a bill's several votes.
`current_party` stays on `Politician`; the tenure-scoped `party_affiliation` has
no home here. `ExternalIdentifier` and `HAS_IDENTIFIER` are out of scope: external
identifiers are to be derived from structured sources, never extracted from prose.

A shortcut rule names the primary-ontology path it collapses and the direct
relationship it produces. The one family this project introduces collapses the
tenure hop:

```
Politician -HELD_TENURE-> LegislativeTenure -VOTED_NO-> LegislativeEvent
  ⇒ Politician -VOTED_NO-> LegislativeEvent   (skips: LegislativeTenure)
```

applied to `VOTED_AYE`, `VOTED_NO`, `ABSTAINED`, `SERVES_ON`, `CHAIRS` and
`VICE_CHAIRS`. The term for a collapsed path is **shortcut** and the property
recording it is `skips`; "elided" is not used anywhere.

A human-readable `news-ontology.md` is **generated** from the News Ontology
module and never hand-edited — generation is what stops a fourth artifact
becoming a fourth drift risk. That document is also the answer to the parent
ticket's question about where the Extraction Prompt and the ontology disagreed.

## Acceptance criteria

- [x] The primary ontology module carries the label set, sub-label map, per-label
      property names, and the relationship table with permitted endpoint labels,
      mirroring `ontology.md`.
- [x] Any correction to `ontology.md` is a deliberate, recorded last resort rather
      than a convenience. This supersedes the original criterion — "`ontology.md`
      is unmodified" — and the statement to the same effect in the body above:
      the file was in fact corrected twice, once here to align the article
      properties, and once by
      [issue 05 of the code review](../code-review/issues/05-move-sequence-number-onto-legislative-event.md)
      moving `sequence_number` onto `LegislativeEvent`. Both are the worked
      examples in
      [ADR 0014 — The primary ontology is authored, not frozen](../../../../docs/adr/0014-the-primary-ontology-is-authored-not-frozen.md),
      which governs when such a correction is permitted.
- [x] The News Ontology declares its labels, relationships, per-label property
      names, the ticket 01 Policy Area vocabulary, and the six shortcut rules.
- [x] The excluded labels and relationships listed above are absent from the News
      Ontology.
- [x] The conformance check asserts every News Ontology label exists in the
      primary ontology, and every News Ontology relationship either appears in the
      primary relationship table with matching endpoints or is produced by a
      declared shortcut whose collapsed path exists in the primary ontology.
- [x] The conformance check runs in the test suite and fails loudly when either
      ontology is edited out of agreement — this is a test over two data
      structures, not a seam, and is the one non-seam test this project adds.
- [x] `news-ontology.md` is generated from the module, and regenerating it
      produces no diff.

## Blocked by

- [01 — Author and review the Policy Area vocabulary](01-author-policy-area-vocabulary.md)
