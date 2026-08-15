Labels: completed

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

`news-ontology.md` is regenerated so that the generated divergence record
describes the ontology that exists rather than the one that existed before this
review.

Three tickets change what the generator reads: the vote Divergence and the
`sequence_number` relocation, the Claim Key rule, and the Divergence module trim.
This is the last step, taken after all three land.

## Acceptance criteria

- [x] `news-ontology.md` is regenerated from the current ontology.
- [x] The vote Divergence appears in the rendered divergence record.
- [x] No stale relationship property or identifying-property content remains.
- [x] The file is regenerated, not hand-edited.

## Blocked by

- [05 Move `sequence_number` onto `LegislativeEvent`](05-move-sequence-number-onto-legislative-event.md)
- [06 The declared property set is the Claim Key](06-declared-properties-are-the-claim-key.md)
- [10 Trim the Divergence module](10-trim-the-divergence-module.md)
