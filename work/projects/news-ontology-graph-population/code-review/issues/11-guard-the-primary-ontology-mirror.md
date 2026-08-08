Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

The hand-copied mirror of `ontology.md` cannot drift from the document it
mirrors. The ontology package exists to prevent exactly this kind of drift, and
its own root is currently the one place left unguarded — the primary ontology
module is a manual transcription with nothing checking it.

A test parses `ontology.md` and asserts that the primary ontology module's
labels, per-label property names, and relationship table match it. The document
stays the authored source and the module stays its mirror; the test is what makes
the mirror trustworthy.

Editing either artifact alone now fails loudly.

## Acceptance criteria

- [x] A test parses `ontology.md` rather than restating its contents.
- [x] Labels match between document and module.
- [x] Per-label property names match.
- [x] The relationship table matches, including source and target labels.
- [x] Editing one artifact without the other fails the test.
- [x] The suite is green.

## Blocked by

- [05 Move `sequence_number` onto `LegislativeEvent`](05-move-sequence-number-onto-legislative-event.md)
