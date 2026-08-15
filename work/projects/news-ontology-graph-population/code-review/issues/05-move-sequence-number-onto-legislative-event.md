Labels: completed

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

Roll-call position is recorded once on the Legislative Event rather than
duplicated onto every vote edge into it. `sequence_number` currently sits on the
three vote relationships, where it is identical for every voter at one event —
which means it describes the event's position in the bill's lifecycle, not one
legislator's claim. It belongs beside the event's existing `type` and `date`.

This is a correction to the primary ontology, made under the standing that
ticket 12's second ADR records: a property on the wrong entity is a fundamental
flaw, not a naming preference. The change lands in both `ontology.md` and the
primary ontology module, which must stay in agreement.

The three vote relationships are then left with no declared properties at all.
That is the point: a news-derived vote edge and a later legislative-derived vote
edge share an empty Claim Key and merge instead of duplicating.

The News Ontology declares neither `sequence_number` on events nor any vote
relationship property, because news supplies neither. It declares a
**Divergence** saying so explicitly: a news-derived vote edge carries no
roll-call position and no event discrimination. No claim is made that news
reports only terminal votes — the corpus is too small to support it, and event
discrimination stays on the `LegislativeEvent` sub-label.

## Acceptance criteria

- [x] `ontology.md` puts `sequence_number` on `LegislativeEvent` and off the
      three vote relationships.
- [x] The primary ontology module matches that document exactly.
- [x] `VOTED_AYE`, `VOTED_NO`, and `ABSTAINED` declare no properties.
- [x] The News Ontology declares no `sequence_number` on events and no vote
      relationship property.
- [x] A Divergence is declared for the vote relationships stating that
      news-derived vote edges carry no roll-call position and no event
      discrimination.
- [x] The suite is green.

## Blocked by

- None — can start immediately.
