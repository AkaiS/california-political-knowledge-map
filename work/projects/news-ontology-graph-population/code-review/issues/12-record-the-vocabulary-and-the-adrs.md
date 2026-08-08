Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

The durable decisions this review took become lookups instead of things a future
reader re-derives from a diff.

**The domain glossary** gains the vocabulary this project introduced and never
defined: **News Ontology**, **Shortcut Rule**, **Divergence**, **Bill Session
Resolution**, **Adherence Report**, **Claim Key**, and **Policy Area**. Glossary
entries only — no implementation detail.

**ADR — a news-derived relationship asserts existence and identity, not
payload.** Records the Claim Key rule: a relationship's declared properties, and
only those, identify it, and everything else an article said stays in the Article
Chunk. Its consequences are the shared node key minting contract and the
`LegislativeEvent` key decision.

**ADR — the primary ontology is authored, not frozen.** Correcting `ontology.md`
is a last resort, not a first move. The default is to work around it; correction
requires a fundamental flaw — a property on the wrong entity, or a key that
cannot identify — never a naming preference or convenience. Both corrections made
during this review are cited as the worked examples: the article property
alignment, and `sequence_number` sitting on a relationship when it describes an
event.

## Acceptance criteria

- [x] Seven glossary terms are defined in the domain glossary.
- [x] The relationship-meaning ADR exists, naming the minting contract and the
      `LegislativeEvent` key as consequences.
- [x] The authored-not-frozen ADR exists, stating the bar for correction and
      citing both worked examples.
- [x] Both ADRs follow the existing `docs/adr/` numbering and format.

## Blocked by

- [06 The declared property set is the Claim Key](06-declared-properties-are-the-claim-key.md)
- [07 Export node primary key minting as an ontology contract](07-export-node-key-minting-contract.md)
- [08 A `LegislativeEvent` date outside the key](08-legislative-event-date-outside-the-key.md)
