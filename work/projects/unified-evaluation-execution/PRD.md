# Unified Evaluation Execution Path

Labels: ready-for-human

## Problem Statement

There are three public ways to execute an evaluation today — `EvaluationSuite.execute`,
`EvaluationEngine.execute`, and `EvaluationRunner.run` — and they do not agree with each
other. `EvaluationSuite.execute` branches internally on whether a Resolved Evaluation Plan
was supplied, so the same call can either consume a frozen plan or derive evaluator
assignments on the fly. `EvaluationRunner.run` derives its own assignments again on the
durable path. The result is that the Resolved Evaluation Plan, which the glossary describes
as the thing "every execution path consumes," is in practice advisory.

The consequences are already visible. Case-versus-Suite compatibility is checked in at least
four places with subtly different predicates, so the checks can drift. Report evaluators run
one way in memory, through the `pydantic_evals` report-evaluator hook wrapped in two
compatibility shims, and a completely different way durably, through a claim-fenced
finalization phase that iterates evaluators by hand. An author cannot trust that an in-memory
run tells them anything about what the durable run will produce, and the single test that
asserts parity between the two compares a handful of semantic fields rather than the whole
result.

Underneath this sits a defect that makes a documented, supported case unusable. An Evaluation
Case may legitimately omit its expected output — `expected_output_schema` is optional, and
`pydantic_evals` treats `expected_output` as optional throughout. But when the ledger
reconstructs a `ReportCase` from terminal checkpoints, it validates the task's *actual* output
against the case's *expected output* schema, and raises when that schema is absent. Any run
containing a case without an expected output succeeds through execution and checkpointing and
then fails at finalization, discarding the expensive part of the work.

A related modelling wart makes the contract harder to reason about. `EvaluationCaseRevisionReference`
carries copies of the case's input, output, and metadata schemas even though the Gold Set it
belongs to already binds exactly one Evaluation Task Contract, and even though gold-set import
independently re-derives and re-checks those schemas from the case record. The copy is the
only reason the reference model needs to know anything about schemas at all, and it is the
mechanism by which a missing expected-output schema propagates into places that cannot
represent its absence.

## Solution

There is one way to execute an evaluation: `EvaluationRunner.run`. It always consumes a
Resolved Evaluation Plan and writes Evaluation Checkpoints to an Evaluation Ledger. Authors
who do not want a database file use the ledger's named in-memory constructor; this changes
SQLite's transport, not the store type or the execution path. The runner materializes the
Evaluation Report from ledger evidence and runs report evaluators in the claim-fenced
finalization phase. Parity is therefore structural rather than a property a test needs to
assert: there are not two implementations that can diverge.

`EvaluationSuite` goes back to being a definition. It answers questions about its evaluators,
metrics, contract, and requirement bindings, and it no longer executes anything.
`EvaluationEngine` survives as the internal case-execution mechanism but is no longer a public
entry point, and the two report-evaluator wrapper classes disappear along with the
`pydantic_evals` report-evaluator hook they existed to accommodate.

Compatibility between an Evaluation Suite, an Evaluation Gold Set, and a set of Evaluation
Cases is decided by one shared predicate, callable on its own so an author can ask "will this
pair compile?" without starting a run. Preflight accumulates every issue that predicate finds
into a list and raises once with all of them, rather than failing on the first.

Report case materialization validates the task's actual output against the Evaluation Task
Contract's output schema, which is always present, and treats a missing expected output as the
ordinary, supported condition it is. `EvaluationCaseRevisionReference` becomes identity-only.

## User Stories

1. As an evaluation author, I want exactly one documented way to execute an evaluation, so that I do not have to learn which of three entry points has the semantics I need.
2. As an evaluation author, I want an in-memory run and a durable run of the same plan to produce the same report, so that I can iterate cheaply and trust the result. **Satisfied structurally:** both use the same Evaluation Ledger and execution path; only SQLite's transport differs.
3. ~~As an evaluation author, I want to run an evaluation without a ledger, so that I can try a suite against a handful of cases while I am still drafting it.~~ **Retracted:** the implementation never ran without a ledger; the former buffer wrapped an in-memory Evaluation Ledger. The authoring affordance survives as the ledger's named in-memory constructor.
4. As an evaluation author, I want the in-memory path to still produce canonical evidence, so that what I see while drafting is the same shape that will later be persisted. **Satisfied structurally:** in-memory and file-backed operation are configurations of the same ledger.
5. As an evaluation operator, I want durable execution to consume the Resolved Evaluation Plan produced by preflight, so that the plan I inspected is the plan that ran.
6. As an evaluation operator, I want execution to refuse to start without a Resolved Evaluation Plan, so that no run can silently derive its own evaluator assignments.
7. As an evaluation operator, I want the plan recorded on the run to be byte-identical to the plan preflight returned, so that I can prove after the fact what was executed.
8. As an evaluation author, I want to author an Evaluation Case with no expected output, so that I can evaluate operations whose correctness is judged by rubric rather than by exact match.
9. As an evaluation author, I want a run containing cases without expected outputs to finalize successfully, so that I do not lose the expensive case-execution work at the last step.
10. As an evaluation author, I want the actual task output validated against the Evaluation Task Contract's output schema, so that validation checks the thing it claims to check.
11. As an evaluation author, I want a case whose expected output is present to still be validated against its declared expected-output schema, so that removing the conflation does not remove real checking.
12. As an evaluation maintainer, I want one shared compatibility predicate between Suite, Gold Set, and Case, so that two call sites cannot disagree about whether a pairing is valid.
13. As an evaluation maintainer, I want to call that compatibility predicate independently of preflight, so that I can validate a Suite and Gold Set pairing in a tool or a test without executing anything.
14. As an evaluation author, I want preflight to report every compatibility issue at once, so that I can fix them in one pass instead of discovering them one run at a time.
15. As an evaluation author, I want preflight issues raised as a single typed error carrying the full list, so that a caller can catch it and present all of them.
16. As an evaluation operator, I want the runner to catch preflight failure before creating an Evaluation Run, so that the ledger does not accumulate runs that never had a chance of executing.
17. As an evaluation maintainer, I want redundant case validation removed from Suite execution, evaluator resolution, and durable execution, so that validation happens once at a known point.
18. As an evaluation maintainer, I want `EvaluationSuite` to stop executing, so that the definition model has one responsibility.
19. As an evaluation maintainer, I want `EvaluationEngine` to become internal, so that the number of supported execution seams is one.
20. As an evaluation maintainer, I want the report-evaluator wrapper classes removed, so that there is no None-tolerance or deferral behaviour that exists only for one of the two paths.
21. As an evaluation maintainer, I want the `pydantic_evals` report-evaluator hook bypassed on the shared path, so that report evaluation semantics are ours.
22. As an evaluation operator, I want a report evaluator that raises to be recorded as a failed execution rather than aborting the run, so that one bad judge does not destroy the whole report.
23. As an evaluation operator, I want a report evaluator that returns nothing to produce no observations rather than an error, so that conditional evaluators are expressible.
24. As an evaluation operator, I want report evaluators to run against a materialized Evaluation Report on the shared path, so that every judge sees the same input.
25. As an evaluation operator, I want durable report evaluation to stay inside its claim-fenced finalization phase, so that ADR 0012's fencing guarantees are preserved.
26. As an evaluation operator, I want durable finalization to remain resumable after a report-evaluator failure, so that ADR 0011's terminal-checkpoint recovery story still holds.
27. As an evaluation operator, I want the Evaluation Report to remain a derived projection, so that it is never independently authoritative.
28. As a persistence maintainer, I want the evidence sink to be a declared protocol, so that every method the executor calls is part of the contract.
29. As a persistence maintainer, I want task-outcome recording declared on the sink protocol rather than reached for dynamically, so that a sink implementation can be checked statically.
30. ~~As a persistence maintainer, I want case lifecycle notification declared on the sink protocol, so that the in-memory sink is a complete implementation rather than a partial one.~~ **Retracted in part:** the method remains declared for the engine's checkpoint sink, but the second-implementation justification was false; the buffer only forwarded to a ledger.
31. ~~As a persistence maintainer, I want partial report-evidence checkpointing declared on the sink protocol, so that the durable and ephemeral sinks can be substituted for one another.~~ **Retracted in part:** the method remains part of the engine's checkpoint-sink contract, but there are no two sink implementations to substitute.
32. ~~As a persistence maintainer, I want the in-memory sink to validate evidence exactly as the durable sink does, so that invalid evidence fails in both modes.~~ **Retracted:** the buffer performed ledger validation by forwarding to an in-memory ledger; a second implementation never existed.
33. ~~As a persistence maintainer, I want the in-memory sink to compute checkpoint identity and content hashes, so that ephemeral evidence is indistinguishable in shape from durable evidence.~~ **Retracted:** the ledger computed these values on both transports; this was not independent sink behavior.
34. ~~As an evaluation maintainer, I want report materialization to read from a sink-agnostic evidence source, so that the same materialization code serves the ledger and the buffer.~~ **Retracted:** the evidence-source protocol had no consumers, and one ledger now owns report materialization on both transports.
35. As an evaluation maintainer, I want `EvaluationCaseRevisionReference` reduced to identity fields, so that it does not duplicate what the Evaluation Task Contract already binds.
36. As an evaluation maintainer, I want schema compatibility checked where full Evaluation Case objects are available, so that the check has enough information to be meaningful.
37. As an evaluation maintainer, I want gold-set import to keep rejecting a reference whose underlying case content changed, so that slimming the reference does not weaken forgery detection.
38. As an evaluation author, I want an incompatible Gold Set member rejected at every seam that holds full Evaluation Cases — `EvaluationGoldSet.validate_cases` and preflight — so that slimming the reference relocates the check rather than removing it.
39. As a database user, I want the evaluation database rebuilt rather than migrated, so that we do not carry a migration for evidence that has never been produced in anger.
40. As a database user, I want `document_store.db` left untouched, so that scraped content survives the rebuild.
41. As a release owner, I want the evidence contract version left at 1, so that we do not signal a compatibility break to consumers that do not exist.
42. As a test maintainer, I want the existing durable runner tests to keep working unchanged, so that consolidation does not require rewriting the bulk of the suite.
43. As a test maintainer, I want the seven `EvaluationSuite.execute` call sites migrated to the runner seam, so that no test depends on a removed entry point.
44. As a test maintainer, I want a happy-path test of plan-driven execution, so that the executor is not covered only by a rejection test.
45. ~~As a test maintainer, I want the in-memory versus durable parity test strengthened to compare canonical report bytes, so that parity is asserted on the whole result rather than a few fields.~~ **Retracted:** issue 15 removed the test after the buffer was deleted. With one store and one execution path, parity is structural and comparing the path with itself cannot detect a divergence.
46. As a test maintainer, I want a test that a case with no expected output survives execution, checkpointing, and finalization, so that the defect cannot regress.
47. As a test maintainer, I want a test that mixes cases with and without expected outputs in one run, so that the two are proven to coexist.
48. As an evaluation investigator, I want the failure mode when a case is genuinely incompatible to name the case and the specific mismatch, so that I can fix the right thing.
49. As an evaluation investigator, I want the preflight issue list to distinguish contract mismatches from unknown requirements, so that I can tell an authoring error from a catalog gap.
50. As a CI maintainer, I want the full deterministic suite to pass after consolidation, so that the change is provably behaviour-preserving where it claims to be.

## Implementation Decisions

- `EvaluationRunner.run` becomes the single public execution entry point. It requires a Resolved Evaluation Plan; there is no plan-less branch.
- Persistence is selected when constructing the Evaluation Ledger. Its named in-memory constructor preserves the authoring affordance without introducing another store type or a branch inside the executor.
- `EvaluationSuite.execute` is removed. `EvaluationSuite` retains its definition responsibilities: resolving case evaluators, exposing report evaluators, metrics, requirement bindings, and its Evaluation Task Contract.
- `EvaluationEngine` remains as the internal case-execution mechanism driving `pydantic_evals`, but is no longer exported as a public seam.
- The engine's checkpoint sink remains a fully declared protocol. Task-outcome recording, case lifecycle notification, and partial report-evidence checkpointing move from dynamically probed attributes onto that protocol. The original justification based on two substitutable sink implementations is retracted: the buffer was only a façade over the ledger.
- The executor projects each completed case into canonical evidence, validates it, computes its checkpoint identity and content hash, and hands it to the Evaluation Ledger.
- The sink-agnostic evidence-source abstraction is retracted. It never had a consumer; report materialization reads from the one Evaluation Ledger on both SQLite transports.
- Report evaluators run after report materialization on the shared path. The `pydantic_evals` report-evaluator hook is not used. `_NoneSafeReportEvaluator` and `_DeferredReportEvaluator` are deleted.
- Report-evaluator semantics adopt the claim-fenced behaviour: a raising evaluator is recorded as a failed execution and does not abort the run; an evaluator returning nothing yields no observations and is not an error.
- Report evaluation stays inside the existing claim-fenced finalization phase and remains replay-tolerant on every path, per ADR 0011 and ADR 0012. The former no-claim ephemeral exception is retracted because the executor always uses the ledger.
- Suite/Gold Set/Case compatibility moves into one shared predicate module. It is a pure function over definitions, returns a structured list of issues, and takes no ledger.
- Preflight calls that predicate, accumulates all issues, and raises a single typed error carrying the whole list when any are present. It does not fail on the first issue.
- The compatibility predicate is public so that a caller can validate a Suite and Gold Set pairing without constructing a plan or a run.
- Redundant case validation is removed from evaluator resolution and from durable execution. Validation happens once, at preflight.
- Report case materialization validates the task's actual output against the Evaluation Task Contract's output schema taken from the frozen Suite, not against the case's expected-output schema.
- A case's `expected_output_schema`, when present, continues to validate that case's `expected_output`. When absent, materialization proceeds without an expected output rather than raising.
- `EvaluationCaseRevisionReference` is reduced to `record_id`, `business_id`, `revision`, and `content_hash`. Its input, output, and metadata schema fields are removed, and `from_case` stops copying them.
- Gold-set import continues to re-derive schemas from the stored case record and check them against the Gold Set's Evaluation Task Contract, which is where forgery detection already lives and is unaffected by the slimming.
- `EvaluationGoldSet`'s member-versus-contract validator is removed, because the slimmed reference makes it impossible: `memberships` holds `EvaluationCaseRevisionReference` objects, which after slimming carry no schemas, so a `model_validator` has nothing to compare. Schema compatibility is therefore decided only where full Evaluation Case objects are in hand — `EvaluationGoldSet.validate_cases`, called explicitly by an author, and preflight, which every run passes through. Construction-time validation of `EvaluationGoldSet` is limited to identity-level invariants, principally the rejection of a duplicate case revision.
- A directly constructed `EvaluationGoldSet` is therefore not self-validating against its Evaluation Task Contract. This is the accepted consequence of slimming the reference, not an oversight: an author who bypasses `validate_cases` is caught at preflight before a run is created.
- This is a breaking change to persisted canonical JSON and content fingerprints for gold-set memberships and Frozen Aggregate Manifests. No migration is written. The evaluation database is dropped and recreated. `document_store.db` is not touched.
- The evidence contract version stays at 1.

## Testing Decisions

- A good test here exercises a public seam with real definitions and asserts on the observable result — the Evaluation Report, the recorded Evaluation Checkpoints, or the raised error. It does not assert on which internal function was called or on the presence of a branch.
- The primary seam under test is `EvaluationRunner.run` over an Evaluation Ledger. Tests use its file-backed or named in-memory construction as appropriate.
- Prior art for durable runs is the existing pattern of a file-backed `SQLiteEvaluationLedger` under `tmp_path`, a lifecycle fixture producing cases, gold set, and suite, and a `run` followed by `finalize`. Reuse it.
- Prior art for plan-driven execution is the existing test that executes a frozen plan as one multi-case report; migrate it to the runner seam rather than deleting it.
- The seven tests calling `EvaluationSuite.execute` migrate to an `EvaluationRunner` over an in-memory Evaluation Ledger. Their assertions should survive the migration unchanged; if one does not, that is a semantic change worth surfacing rather than papering over.
- Add a happy-path test of plan-driven execution. The engine currently has only a task-binding rejection test.
- ~~Strengthen the in-memory versus durable parity test to compare canonical report bytes rather than selected semantic fields.~~ **Retracted:** issue 15 deleted this self-comparison after issue 14 removed the buffer. Parity is structural because only one store and execution path remain.
- Add coverage for canonical report serialization and deserialization round-tripping, which is currently untested despite now sitting on the shared path.
- Add a test that a run whose cases have no expected output completes execution, checkpointing, and finalization, and produces a report. Add a companion test mixing cases with and without expected outputs in a single run.
- Add a test that a case with an expected output still fails when that output does not match its declared expected-output schema, proving the conflation was removed without removing the check.
- Test the compatibility predicate directly as a pure function over definitions, with no ledger and no run.
- Test that preflight accumulates multiple distinct issues and reports all of them in one raise, rather than only the first.
- Keep the existing test that the runner rejects an incompatible preflight before creating a run.
- ~~Test the evidence sink protocol by substituting the in-memory sink for the durable one in an otherwise identical run and asserting the evidence produced is equivalent.~~ **Retracted:** there is no second sink implementation to substitute.
- Test that a raising report evaluator is recorded as a failed execution and the run still produces a report on the shared, claim-fenced path.
- Test that a report evaluator returning nothing produces no observations and no error on the shared path.
- Keep the existing gold-set import test that rejects a reference whose case contract changed, and confirm it still passes with the slimmed reference.
- There is no shared `conftest.py` today and helpers are module-local. Where migrated tests need the same in-memory-ledger runner setup across files, extract it; otherwise leave the module-local convention alone.
- The full deterministic suite must pass. Content-hash assertions on gold-set memberships and manifests will need updating for the slimmed reference; those updates are expected and are not evidence of a behaviour change.

## Out of Scope

- Judge calibration as a data model. Expected judgments keyed by rubric and candidate output are a separate population with a different task contract, and are not addressed here.
- Any change to Evaluation Rubric. It remains human-authored criteria and assertions.
- Gold Set construction ergonomics. A validating factory is specified separately; this project only slims `EvaluationCaseRevisionReference` and leaves construction as it is.
- Changing the meaning of Evaluation Splits, or how cases are assigned to them.
- Any migration path for existing evaluation databases. They are dropped and recreated.
- Raising the evidence contract version.
- Changing the claim, heartbeat, or fencing mechanics of Evaluation Finalization. ADR 0012's behaviour is preserved as-is, not revised.
- Changing what the Frozen Aggregate Manifest contains, beyond the consequences of slimming the case revision reference.
- On-disk authoring of Evaluation Suites or Gold Sets. There is no YAML or JSON loader today and none is added.
- Performance work on case execution or concurrency bounds.

## Further Notes

- This project closes inbox items EP-01 through EP-05, which together describe exactly this consolidation: requiring a plan at the execution boundary, centralizing compatibility predicates, eliminating redundant validation, making durable execution consume the preflight plan, and constructing runs from the plan rather than from duplicated plan-derived fields.
- ADR 0005 requires case evaluation requirements to be resolved before execution; making the plan mandatory strengthens rather than changes that.
- ADR 0006 binds a Gold Set to one Evaluation Task Contract. That ADR is the reason the schema copies on `EvaluationCaseRevisionReference` are redundant.
- ADR 0007 puts task outcome validation at the Task Binding. The output-schema fix is consistent with it: the binding validates the outcome against the contract, and materialization should check against the same contract rather than against a case's expected value.
- **Retraction of the original ADR 0010 note:** the ephemeral sink was a second façade over the same store. It wrapped an Evaluation Ledger using SQLite's in-memory transport and forwarded calls to it. Issues 12–15 removed the false run-mode distinction while preserving in-memory authoring.
- The order of work matters. The compatibility predicate and the output-schema fix are independently valuable and unblock the rest. The reference slimming forces the database rebuild. The executor consolidation is the largest change and should land last, when the smaller changes have already stabilized the seams it depends on.
- **Retraction of the original buffer note:** evidence was never stored independently in a buffer; it was projected, validated, hashed, and stored by an in-memory Evaluation Ledger. Byte-level parity no longer needs a test because one implementation serves both persistence choices.
