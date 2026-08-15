Labels: completed

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

Relationship properties stop being silently overwritten. Today only two
relationship types declare identifying properties, so every other type merges on
its endpoints alone and the write path ends with an unconditional property
assignment. Two articles asserting the same relationship with different detail
produce one edge holding whichever was ingested last, with no record that they
differed.

The fix is a decision about what a relationship means. **A News Ontology
relationship asserts that a claim exists and what identifies it — nothing more.
Its declared properties, and only those, form its Claim Key.** Anything else an
article said about the relationship stays in the Article Chunk the edge points
back to, where it remains retrievable.

The separate identifying-property table is deleted. The rule that replaces it:
if two different values mean two different claims, the property is declared and
therefore identifying; if they do not, the property does not belong on the edge.

An edge carries exactly its Claim Key, the chunk list, `skips` where it is a
shortcut, and `needs_review` where an article asserted the claim without a value
the key depends on. The unconditional property assignment at the end of the
relationship query is removed — there is no free payload left for it to write.

Property normalization survives, scoped to Claim Key properties. Making two
articles' claims comparable is now its only job.

The relationship-query docstring is corrected while here: key names do come from
the ontology, but the relationship type is interpolated from conformed model
output, so the claim that input never reaches the query is false as written.

## Acceptance criteria

- [x] Two extractions asserting one relationship at equal Claim Key values
      produce one edge accumulating both chunks.
- [x] Two extractions asserting one relationship at differing Claim Key values
      produce two edges.
- [x] No property outside the Claim Key, the chunk list, `skips`, and
      `needs_review` reaches an edge.
- [x] The identifying-property table is gone; the declared property set is the
      only source of edge identity.
- [x] The unconditional property assignment is gone from the relationship query.
- [x] Property normalization runs on Claim Key properties.
- [x] The relationship-query docstring states what is and is not ontology-derived.
- [x] The suite is green.

## Blocked by

- [04 Unify the two relationship write paths](04-unify-relationship-write-paths.md)
- [05 Move `sequence_number` onto `LegislativeEvent`](05-move-sequence-number-onto-legislative-event.md)
