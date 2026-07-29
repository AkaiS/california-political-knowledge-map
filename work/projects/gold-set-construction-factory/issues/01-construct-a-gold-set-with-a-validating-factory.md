# Construct an Evaluation Gold Set with a validating factory

Labels: ready-for-agent

Part of [Evaluation Gold Set Construction and Revisioning](../PRD.md). This is the
supported construction path the rest of the project builds on.

## What to build

An evaluation author calls one function to build an Evaluation Gold Set. They
supply the Gold Set identity, description, Evaluation Task Contract, tags,
declared Evaluation Artifacts, a plain collection of Evaluation Cases, the split
ratio they want, and optionally a map pinning particular cases to particular
splits. They get back a frozen `EvaluationGoldSet` with a stable content hash,
alongside the realized split counts so they can see how a small population
actually divided.

The author never derives a case revision reference and never pairs a case with a
split by hand. Every case is validated against the Evaluation Task Contract
before anything is built, using the shared compatibility predicate rather than a
comparison written here, so a Gold Set that constructs successfully cannot be
rejected later at preflight. When cases are incompatible the factory raises once
with every problem it found, each naming the case and the specific schema that
mismatched. A case that declares no expected output is accepted, because
rubric-judged operations need Gold Sets too.

Split assignment is a function of the case's stable business identity and the
requested ratio, and of nothing else. Reordering the input cannot change the
population's meaning, and adding a case cannot move a case that was already
there — that property is what makes revisioning safe, so it is asserted directly
rather than left implied. Explicitly pinned cases take their pinned split and
leave the pool before ratio assignment, so pinning does not distort the division
of everything else. The ratio covers all three splits and must sum to one; a
split may be given a zero share and simply ends up empty.

The factory lives in its own module dedicated to Gold Set assembly — not in the
definitions module, and not as a classmethod. It is a function, not a mutable
builder, so there is no partially built Gold Set to reason about. It performs no
I/O, does not touch the Evaluation Ledger, and executes nothing. Declared
artifacts are carried through unresolved; their existence keeps being checked at
ledger import, where that check already lives. `EvaluationGoldSet`'s own
validators are untouched and direct construction keeps working, so stored Gold
Sets still deserialize.

Be aware of what those validators now cover. The Unified Evaluation Execution
project slimmed `EvaluationCaseRevisionReference` to identity fields, which made a
construction-time member-versus-contract check impossible and removed it. The only
model validator left is `does_not_repeat_a_case_revision`. So a directly
constructed Gold Set can hold members that are schema-incompatible with its
Evaluation Task Contract, and nothing objects until `validate_cases` or preflight.
This factory is the first construction-time schema check to exist since that
change — it is closing a real gap, not adding sugar over an existing guarantee.

## Acceptance criteria

- [ ] A public factory function in a new module dedicated to Gold Set assembly returns a frozen `EvaluationGoldSet` from identity, description, Evaluation Task Contract, tags, declared Evaluation Artifacts, Evaluation Cases, a split ratio, and an optional pinned case-to-split map.
- [ ] The factory derives every case revision reference itself; the caller passes plain Evaluation Cases.
- [ ] The factory reports the realized split counts alongside the constructed Gold Set, and those counts match the actual memberships.
- [ ] Case-versus-contract validation delegates to the shared compatibility predicate; no schema comparison is implemented in this module.
- [ ] Every incompatible case is reported in a single raise, each identifying the case and the mismatching schema; the mismatch is covered for input, expected-output, and metadata schemas.
- [ ] A case declaring no expected-output schema is accepted.
- [ ] Split assignment is derived from each case's stable business identity and the requested ratio, and depends on neither iteration order nor population membership.
- [ ] Shuffling the input cases leaves the resulting memberships and split assignments unchanged.
- [ ] Constructing with N cases and then with those N plus one more leaves every original case's split unchanged.
- [ ] Realized proportions approximate the requested ratio on a population large enough for the claim to be meaningful.
- [ ] A ratio that does not sum to one is rejected; a ratio with a zero share yields an empty split rather than an error.
- [ ] Pinned cases receive their pinned split and are excluded from ratio-based assignment.
- [ ] Two constructions with identical inputs produce identical content hashes.
- [ ] Declared Evaluation Artifacts pass through unresolved, and a factory-built Gold Set with declared artifacts still fails ledger import when an artifact is absent from the catalog.
- [ ] A factory-built Gold Set imports cleanly into a `SQLiteEvaluationLedger` and produces the expected membership rows.
- [ ] The factory performs no I/O, takes no Evaluation Ledger, and executes nothing.
- [ ] `EvaluationGoldSet`'s existing validators are unchanged and direct construction still works. Do not attempt to restore a member-versus-contract `model_validator`; the slimmed reference carries no schemas and it cannot work.
- [ ] The full deterministic test suite passes.

## Blocked by

- [Decide Suite, Gold Set, and Case compatibility in one place](../../unified-evaluation-execution/issues/01-shared-suite-gold-set-case-compatibility-predicate.md), in the Unified Evaluation Execution Path project. The predicate must exist exactly once; it must not be implemented a second time here.
