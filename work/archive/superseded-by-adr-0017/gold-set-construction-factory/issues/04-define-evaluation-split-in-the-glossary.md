# Define Evaluation Split in the glossary and describe the construction flow

Labels: completed

Part of [Evaluation Gold Set Construction and Revisioning](../PRD.md). Independent of
the code tickets; can start immediately.

## What to build

A reader of `CONTEXT.md` can learn what an Evaluation Split is and what each of
the three splits means, without inferring it from the enum. Today the word
appears only in passing inside the Evaluation Case entry, which leaves
`calibration` entirely to interpretation.

The three splits correspond to three distinct adaptation loops. `training`
supplies material for tuning agent behaviour. `held-out` is the reserved evidence
set that confirms tuned behaviour generalizes. `calibration` marks cases reserved
from the agent-tuning loop so judge behaviour can be observed against them
without those cases feeding agent iteration — reservation semantics only; it does
not mean stored expected judgments. The glossary should also record that exactly
one split is assigned per case revision, so a case cannot sit in a tuning loop
and the held-out set at the same time.

The Evaluation Gold Set entry is extended so the domain language matches what the
code supports: a Gold Set is constructed by declaring its identity, description,
Evaluation Task Contract, and tags, populating it with validated cases and
declared artifacts, and locking it into an immutable revision; and revision N+1
is derived from revision N by adding or removing cases while preserving the split
of everything that survived. The Evaluation Task Contract is fixed for the life of
the identity — changing it means a different operation and a new business
identity.

## Acceptance criteria

- [x] `CONTEXT.md` has an Evaluation Split glossary entry defining all three splits.
- [x] The entry documents `calibration` as reservation from the agent-tuning loop for observing judge behaviour, and explicitly not as stored expected judgments.
- [x] The entry records that exactly one split is assigned per Evaluation Case revision.
- [x] The Evaluation Gold Set entry describes the construction flow and the revisioning flow, including that revisioning preserves surviving cases' splits.
- [x] The Evaluation Gold Set entry records that the Evaluation Task Contract cannot change across revisions and that a different contract requires a new business identity.
- [x] Both entries follow the existing glossary entry format, including the _Avoid_ line convention.

## Blocked by

None — can start immediately.
