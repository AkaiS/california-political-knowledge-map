# Bind Evaluation Gold Sets to one task contract

The membership portion of this decision is amended below: an expected output is optional, and compatibility is enforced at the construction factory rather than by the aggregate's own validators.

An Evaluation Gold Set version binds one exact Evaluation Task Contract and contains only exact Evaluation Case revisions compatible with it. This keeps the full Gold Set coherent, executable, and aggregatable for one component operation; subset selection may vary splits, tags, and Evaluation Requirement coverage, but cannot conceal task-schema incompatibility. Cases for different component operations belong to distinct Gold Sets even when they share source artifacts or provenance, while legitimate shape variation is modeled explicitly inside the shared schemas.

Compatibility means the case's input and metadata schemas match the contract exactly, and that its expected-output schema, **when the case declares one**, matches the contract's output schema. A case that declares no expected output is a compatible member. The evaluation framework does not require an expected output to score a case — rubric-judged and reference-free operations are evaluated against the case's Evaluation Requirements — so demanding one would exclude those operations from having Gold Sets at all. The contract's output schema governs the task's actual output; a case's expected output, where present, is authored reference material and is validated against the case's own declared expected-output schema.

The Gold Set construction factory is the supported way to build a Gold Set and is where member-versus-contract compatibility is enforced, using the shared compatibility predicate the runner and preflight also use. Authoring a Gold Set anywhere in this repository — in `src/` or in a test — goes through the factory; direct construction of `EvaluationGoldSet` is reserved for deserializing a stored Gold Set and for tests that deliberately build an invalid one in order to assert a rejection from a later seam.

`EvaluationGoldSet` itself cannot re-check compatibility, and this is structural rather than a matter of policy. An `EvaluationGoldSetMembership` references its case by identity and content hash alone — the slimmed `EvaluationCaseRevisionReference` carries no schemas — so a validator on the aggregate has nothing to compare a contract against. Only a seam holding full `EvaluationCase` values can decide compatibility. The factory is such a seam and it runs at construction; `validate_cases`, preflight, and ledger import are the others and they run later. Direct construction must in any case keep working, because that is how a stored Gold Set is deserialized, and its membership was already checked when it was authored.

A Gold Set assembled by any route other than the factory is therefore not compatibility-checked at construction; it is checked when `validate_cases` is called, at preflight before a run, and at ledger import. Incompatibility is caught before anything executes, which is what this decision requires — it is not caught at the moment the object is instantiated.

## Consequences

Rubric-judged operations can have Gold Sets.

The factory is load-bearing rather than a convenience wrapper: for schema compatibility it is the only construction-time check there is, so a hand-built Gold Set can be schema-invalid until a later seam sees it. Every such seam runs strictly before execution, so no incompatible member can reach a run. Note the scope of the preflight check: it validates the Suite-versus-Gold-Set contract for the whole population, but validates individual cases only for the members a run actually selects. An incompatible member excluded by split or selection is not reported — it also does not reach the run.

The factory does not exist yet. It is specified by the [Gold Set Construction and Revisioning](../../work/projects/gold-set-construction-factory/PRD.md) project and is unimplemented as of this amendment, so today there is no construction-time compatibility check at all. Until that project lands, the pre-execution seams above are the whole of the enforcement.

Ledger import does not use the shared predicate. It re-derives each member's schemas from the stored case record and compares them itself, so compatibility has one authoritative definition for authoring, preflight, and the runner, and a second independent implementation at the persistence boundary. Import is the seam that most needs to be right about a hand-built Gold Set, which makes the duplication worth retiring.
