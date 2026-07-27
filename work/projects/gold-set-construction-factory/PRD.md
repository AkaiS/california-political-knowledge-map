# Evaluation Gold Set Construction and Revisioning

Labels: ready-for-agent

## Problem Statement

There is no supported way to build an Evaluation Gold Set. The model is frozen and validates
itself on construction, which is correct, but it means an author must assemble the entire
finished object in one expression: derive a case revision reference for every case, pair each
with a split, and hand the whole tuple to the constructor. Every one of the seventeen gold
sets in the repository is built this way, by hand, in a test. Nothing in `src/` builds one at
all.

The immediate cost is that split assignment is meaningless in practice. Because assigning
splits by hand is tedious, essentially every gold set in the repository puts every case in
`held-out`. The split machinery exists, the database enforces one split per case revision, and
nobody uses it — which means the leakage guarantee it was built to provide has never actually
been exercised.

The larger cost is that revisioning is unsupported. An Evaluation Gold Set is versioned
specifically so that revision N+1 can add or remove cases without rewriting earlier
membership, and so that a run against revision N stays reproducible forever. But there is no
operation that derives revision N+1 from revision N. An author has to rebuild the whole
membership tuple by hand and hope they reproduced the previous split assignments exactly. If
they get one wrong, a case silently migrates from `held-out` into a tuning loop, and every
subsequent held-out number is contaminated in a way nothing in the system can detect.

The authoring flow the domain actually wants is: declare the Gold Set's identity, description,
Evaluation Task Contract, and tags; populate it with cases and artifacts, validating each
against the contract as it goes; then lock it into an immutable revision. The current model
supports only the last step.

## Solution

A validating factory, living in its own module, is the supported way to construct an
Evaluation Gold Set. The caller supplies identity, description, Evaluation Task Contract,
tags, declared Evaluation Artifacts, the Evaluation Cases, and the split ratio they want. The
factory validates every case against the contract using the same shared compatibility
predicate the rest of evaluation uses, assigns splits deterministically, derives the case
revision references, and returns a frozen `EvaluationGoldSet`. If any case is incompatible,
the factory raises once with every problem it found, rather than one at a time.

Split assignment is deterministic and derived from the case's stable business identity, not
from a random draw and not from the order cases were passed in. That is what makes revisioning
safe: a case that landed in `held-out` in revision 1 lands in `held-out` in revision 7,
because the assignment is a function of the case's identity and the ratio, not of the
population it happened to be in. Adding or removing cases cannot reshuffle the cases that
stayed.

Revisioning is a first-class operation. Given an existing Gold Set and a set of cases to add
or remove, the factory produces revision N+1 with the same identity, preserving the split of
every case that survived. Changing the Evaluation Task Contract is not a revision — it means
the Gold Set is evaluating a different operation, and it requires a new business identity.
The factory refuses to produce a revision whose contract differs from its predecessor's.

All three splits survive. `training` supplies material for agent tuning, `held-out` is the
reserved evidence set, and `calibration` marks cases reserved from the agent-tuning loop so
judge behaviour can be observed against them without those cases feeding agent iteration. The
factory does not execute anything and does not touch the Evaluation Ledger.

## User Stories

1. As an evaluation author, I want a supported way to construct an Evaluation Gold Set, so that I do not have to assemble membership tuples by hand.
2. As an evaluation author, I want to declare the Gold Set's identity, description, Evaluation Task Contract, and tags up front, so that the contract is fixed before any case is considered.
3. As an evaluation author, I want to hand the factory a plain collection of Evaluation Cases, so that I do not have to derive case revision references myself.
4. As an evaluation author, I want every case validated against the Evaluation Task Contract at construction time, so that an incompatible case cannot enter the population.
5. As an evaluation author, I want all incompatible cases reported at once, so that I can fix them in one pass.
6. As an evaluation author, I want each reported incompatibility to name the case and the specific schema that mismatched, so that I know what to change.
7. As an evaluation author, I want the factory to use the same compatibility predicate the runner uses, so that a Gold Set that constructs successfully cannot be rejected later at preflight.
8. As an evaluation author, I want a case with no expected output to be accepted, so that rubric-judged operations can have Gold Sets.
9. As an evaluation author, I want to specify the split ratio I want, so that the population is divided according to my evaluation strategy rather than a hardcoded default.
10. As an evaluation author, I want split assignment derived from each case's stable business identity, so that the assignment is reproducible.
11. As an evaluation author, I want split assignment independent of the order I pass cases in, so that reordering my authoring code cannot change the population's meaning.
12. As an evaluation author, I want split assignment independent of which other cases are present, so that adding a case does not move an existing one.
13. As an evaluation author, I want the realized split proportions to approximate the ratio I asked for, so that the ratio is meaningful for populations of realistic size.
14. As an evaluation author, I want to see the realized split counts, so that I can tell whether a small population divided sensibly.
15. As an evaluation author, I want to pin a specific case to a specific split explicitly, so that a case I know belongs in held-out cannot drift by hash.
16. As an evaluation author, I want explicitly pinned cases excluded from ratio-based assignment, so that pinning does not skew the remaining division.
17. As an evaluation author, I want to derive revision N+1 from an existing Gold Set by adding cases, so that growing a population does not mean rebuilding it.
18. As an evaluation author, I want to derive revision N+1 by removing cases, so that a case discovered to be mislabelled can be retired.
19. As an evaluation author, I want every surviving case to keep the split it had in the previous revision, so that revisioning cannot contaminate the held-out set.
20. As an evaluation author, I want newly added cases assigned by the same deterministic rule, so that a grown population stays consistent with itself.
21. As an evaluation author, I want the factory to reject a revision whose Evaluation Task Contract differs from its predecessor's, so that a Gold Set cannot silently start evaluating a different operation.
22. As an evaluation author, I want the rejection message to tell me to use a new business identity, so that I know what the intended remedy is.
23. As an evaluation author, I want the revision number incremented for me, so that I cannot accidentally reuse or skip one.
24. As an evaluation author, I want a revision that changes nothing to be rejected, so that the revision history means something.
25. As an evaluation author, I want to attach declared Evaluation Artifacts to a Gold Set, so that population-level source material is recorded by content hash.
26. As an evaluation author, I want the factory to pass declared artifacts through without resolving them, so that construction does not require a populated artifact catalog.
27. As an evaluation author, I want artifact existence checked at ledger import as it is today, so that the existing validation point is preserved.
28. As an evaluation author, I want the factory to return a frozen `EvaluationGoldSet`, so that the result is immutable the moment it exists.
29. As an evaluation author, I want the returned Gold Set to have a stable content hash, so that two identical constructions are recognizably the same.
30. As an evaluation maintainer, I want `EvaluationGoldSet`'s own validators kept, so that a hand-constructed Gold Set still cannot be invalid.
31. As an evaluation maintainer, I want the factory to be the recommended path rather than the only one, so that deserialization from stored JSON keeps working.
32. As an evaluation maintainer, I want the factory in its own module, so that construction logic does not accumulate inside the definitions module.
33. As an evaluation maintainer, I want the factory to be a function rather than a mutable builder, so that there is no partially built Gold Set to reason about.
34. As an evaluation operator, I want `calibration` to mean cases reserved from the agent-tuning loop, so that the split has a documented meaning.
35. As an evaluation operator, I want the one-split-per-case-revision constraint preserved, so that a case cannot be in a tuning loop and the held-out set simultaneously.
36. As an evaluation operator, I want to request a ratio that omits a split entirely, so that a population with no calibration cases is expressible.
37. As an evaluation operator, I want a ratio that does not sum to one rejected, so that a typo does not silently produce a partial population.
38. As an evaluation operator, I want to select cases from a Gold Set by split when running, so that the splits are actually usable, as the runner already supports.
39. As a test maintainer, I want the existing hand-built gold sets in tests migrated to the factory, so that the factory is exercised by the whole suite rather than by its own tests alone.
40. As a test maintainer, I want migrated tests that intentionally build an invalid Gold Set to keep constructing it directly, so that the model's own validators stay covered.
41. As a documentation maintainer, I want the Gold Set glossary entry to describe the construction and revisioning flow, so that the domain language matches what the code supports.
42. As a documentation maintainer, I want Evaluation Split added to the glossary with the meaning of each of the three splits, so that `calibration` is not left to interpretation.

## Implementation Decisions

- Construction lives in a new module dedicated to Gold Set assembly. It does not go into the definitions module, and it is not a classmethod on `EvaluationGoldSet`.
- Construction is a validating factory function, not a mutable builder. There is no intermediate half-built object. A builder may be revisited later if authoring pressure demands incremental population, but the factory is the shape for now.
- The factory takes the Gold Set identity, description, Evaluation Task Contract, tags, declared Evaluation Artifacts, the Evaluation Cases, an optional map of explicitly pinned case-to-split assignments, and a split ratio.
- Case-versus-contract validation uses the shared compatibility predicate introduced by the Unified Evaluation Execution project. The factory does not implement its own comparison. This is the only dependency between the two projects.
- Validation accumulates. Every incompatible case is collected and reported in one raise, identifying the case and the mismatching schema.
- A case with no expected-output schema is valid. The contract's output schema governs actual outputs; a case's expected output is optional.
- Split assignment is deterministic, computed from the case's stable business identity and the requested ratio. It must not depend on iteration order, on the size of the population, or on which other cases are present.
- Explicitly pinned cases take their pinned split and are removed from the pool before ratio-based assignment, so pinning does not distort the remaining division.
- The split ratio is expressed over the three splits and must sum to one. A split may be given a zero share. A ratio that does not sum to one is rejected.
- The factory reports the realized split counts alongside the constructed Gold Set, because for small populations the realized division can differ noticeably from the requested ratio and the author should see that.
- Revisioning is a separate factory operation taking the previous `EvaluationGoldSet`, the cases to add, and the case identities to remove.
- The revision operation preserves the split of every surviving case exactly, reading it from the previous revision's membership rather than recomputing it. Only newly added cases are assigned, by the same deterministic rule.
- The revision operation requires the Evaluation Task Contract to be identical to the previous revision's and rejects any difference, directing the author to a new business identity. This follows ADR 0006, which binds a Gold Set to one contract.
- The revision operation increments the revision number itself and rejects a no-op revision that neither adds nor removes anything.
- Declared Evaluation Artifacts are passed through unresolved. Their existence in the artifact catalog continues to be validated at ledger import, which is where that check already lives.
- The factory does not touch the Evaluation Ledger, does not execute anything, and has no I/O.
- `EvaluationGoldSet`'s existing validators are retained unchanged. The factory is the recommended construction path, not a replacement for the model's own invariants, and direct construction must keep working so stored Gold Sets can be deserialized.
- `EvaluationSplit` keeps all three members. `calibration` is documented as reservation from the agent-tuning loop so judge behaviour can be observed against those cases.
- The `CONTEXT.md` glossary gains an Evaluation Split entry defining all three splits, and the Evaluation Gold Set entry is extended to describe construction and revisioning.

## Testing Decisions

- A good test here calls the factory with real definitions and asserts on the returned `EvaluationGoldSet` or on the raised error. It does not assert on how splits were computed internally, only that the assignment has the properties claimed: deterministic, order-independent, and population-independent.
- The seam under test is the factory module's two public functions: construct and revise. Nothing else needs a new seam.
- Prior art for building the cases, contracts, and suites these tests need is the existing module-local helper pattern in the preflight and definitions test modules.
- Test that a valid population constructs and that the result is frozen with a stable content hash.
- Test that two constructions with identical inputs produce identical content hashes.
- Test order-independence directly: shuffle the input cases and assert the resulting memberships and split assignments are unchanged.
- Test population-independence directly: construct with N cases, then with those N plus one more, and assert every original case kept its split. This is the property that makes revisioning safe and it deserves an explicit test rather than being implied by the revision tests.
- Test that requested ratios produce approximately correct realized proportions on a population large enough for the claim to be meaningful, and that the reported realized counts match the actual memberships.
- Test that a ratio not summing to one is rejected, and that a ratio with a zero share produces an empty split rather than an error.
- Test that explicitly pinned cases receive their pinned split and are excluded from ratio-based assignment.
- Test that an incompatible case is rejected, and separately that multiple incompatible cases are all reported in a single raise. Parametrize the mismatch across input, output, and metadata schemas, following the existing parametrized preflight mismatch test.
- Test that a case with no expected output is accepted.
- Test the revision operation for addition, for removal, and for both at once, asserting in every instance that surviving cases kept their splits.
- Test that a revision with a changed Evaluation Task Contract is rejected and that the message directs the author to a new business identity.
- Test that a no-op revision is rejected and that the revision number increments correctly.
- Test that a Gold Set built by the factory imports cleanly into a `SQLiteEvaluationLedger` and produces the expected membership rows, reusing the existing ledger import test pattern.
- Test that declared artifacts pass through construction unresolved and are still validated at import.
- Migrate the seventeen hand-built gold sets in the existing tests to the factory, except those that deliberately construct an invalid Gold Set to exercise the model's own validators. Those keep constructing directly.
- The migration is where the split machinery finally gets exercised across the suite. Expect some tests that assumed everything was `held-out` to need explicit pinning; pin rather than reshape the test.

## Out of Scope

- A mutable builder with incremental population and a separate lock step. The validating factory covers the current need; a builder is a plausible successor if authoring pressure justifies it.
- Judge calibration data. Expected judgments keyed by rubric and candidate output belong to a separate population with the judge's own task contract, and are not modelled here. The `calibration` split in this project carries reservation semantics only.
- Any change to Evaluation Rubric.
- On-disk authoring formats. There is no YAML or JSON loader for authored definitions today and none is added; the factory is a Python-level API.
- Case authoring. This project constructs Gold Sets from Evaluation Cases that already exist; it does not help create the cases.
- Any change to how the Evaluation Ledger stores or validates Gold Sets, beyond confirming that factory-built Gold Sets import correctly.
- Statistical stratification of splits by case tags, requirements, or any other attribute. Assignment is by identity hash and explicit pinning only.
- Changing `EvaluationCaseRevisionReference`, which is slimmed by the Unified Evaluation Execution project.
- Retiring or renaming any member of `EvaluationSplit`.

## Further Notes

- The only coupling to the Unified Evaluation Execution project is the shared compatibility predicate. If that project has not landed, this one can define the predicate and the other can adopt it; the dependency runs in whichever direction is convenient, but the predicate must not end up implemented twice.
- The reason to insist on deterministic, population-independent split assignment is contamination. If assignment can shift when the population changes, a case can migrate from `held-out` into a tuning loop across revisions, every subsequent held-out measurement is compromised, and nothing in the system would detect it. The database's one-split-per-case-revision constraint protects against overlap within a revision but says nothing across revisions.
- The three splits correspond to three distinct adaptation loops: calibrating judges so they score as intended, tuning agent behaviour, and confirming that tuned behaviour generalizes. They are kept because those loops are genuinely distinct, not because the enum already had three members.
- Evaluation Artifacts on a Gold Set are population-level provenance — content-addressed source material for the population as a whole, distinct from the artifacts a single Evaluation Case declares. The factory's only job with them is to carry them through faithfully.
