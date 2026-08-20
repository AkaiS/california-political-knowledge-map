# Decide Suite, Gold Set, and Case compatibility in one place

Labels: completed

Prefactor for the [Unified Evaluation Execution Path](../PRD.md). Nothing else in
this project is safe to move until compatibility has exactly one definition.

## What to build

An author can ask whether an Evaluation Suite, an Evaluation Gold Set, and a set
of Evaluation Cases are compatible, and get back a structured list of everything
wrong with the pairing. The question is answerable on its own — no Resolved
Evaluation Plan, no Evaluation Run, no Evaluation Ledger, no I/O — so it can be
asked from a test, a tool, or a script while a Suite is still being drafted.

Every existing place that decides compatibility today answers by calling this
predicate. Suite-level case validation, preflight's issue accumulation, and the
Gold Set's own member-versus-contract validation stop carrying their own
comparisons. Observable behaviour does not change in this ticket; what changes is
that the four copies become one, so they can no longer drift apart.

**Correction.** Two of those four copies did not resolve the way this ticket
described. The Gold Set's `members_match_task_contract` validator was not
converted to delegate — issue 04 deleted it, because the slimmed
`EvaluationCaseRevisionReference` carries no schemas for a validator to compare.
The aggregate's remaining author-invoked check, `EvaluationGoldSet.validate_cases`,
does delegate to the predicate, and construction-time enforcement moves to the
Gold Set construction factory, which is specified separately and is not yet
implemented. Separately, gold-set import in the ledger still re-derives each
member's schemas from the stored case record and compares them itself, so a
second independent implementation survives at the persistence boundary. See the
amended [ADR 0006](../../../../docs/adr/0006-bind-evaluation-gold-sets-to-one-task-contract.md).

The predicate distinguishes the kinds of problem it finds, at minimum an
Evaluation Task Contract schema mismatch from an unknown Evaluation Requirement,
and names the specific case and the specific schema involved in each.

## Acceptance criteria

- [x] A public predicate decides compatibility between an Evaluation Suite, an Evaluation Gold Set, and Evaluation Cases, and returns a structured collection of issues rather than a boolean.
- [x] The predicate is a pure function over authored definitions: it performs no I/O, takes no Evaluation Ledger, and does not construct a Resolved Evaluation Plan or an Evaluation Run.
- [x] Each issue identifies the Evaluation Case it concerns and the specific mismatch, and distinguishes a contract schema mismatch from an unknown Evaluation Requirement.
- [x] Input, expected-output, and metadata schema mismatches are each detected and reported distinctly.
- [x] A case that declares no expected-output schema is not reported as an issue on that basis alone.
- [x] Suite-level case validation delegates to the predicate instead of comparing schemas itself.
- [x] Preflight delegates to the predicate instead of comparing schemas itself.
- [x] The Gold Set's author-invoked `validate_cases` delegates to the predicate instead of comparing schemas itself. Its `members_match_task_contract` **model validator** does not delegate — issue 04 removed it, because the slimmed case revision reference carries no schemas to compare. Construction-time enforcement moves to the Gold Set construction factory, which uses this predicate and is specified by the Gold Set Construction and Revisioning project; it is unimplemented, so no construction-time check exists today.
- [x] The predicate is unit tested directly as a pure function, with the schema mismatch cases parametrized across input, output, and metadata.
- [x] Every existing test asserting a compatibility rejection still passes, with the same error surfaced from the same seam it is raised from today.
- [x] The full deterministic test suite passes.

## Blocked by

None — can start immediately.
