# Case Evaluation Requirements and Resumable Evaluation Execution

Labels: ready-for-agent

## Problem Statement

An Evaluation Suite currently applies every configured case evaluator to every selected Evaluation Case. This is too coarse for cases that implement the same Evaluation Task Contract but require different kinds of judgment. Putting evaluator implementations, rubrics, models, or revisions directly on Evaluation Cases would solve the immediate selection problem, but it would couple the Evaluation Gold Set to the mechanism used to judge it. Iterating on a judge or rubric would then force unrelated case and Gold Set revisions.

The current execution paths also do not share one resolved representation of the intended evaluation. The simple suite path builds one Pydantic Evals Dataset, while the durable runner builds and executes a separate one-case Dataset for each case, accumulates report inputs in memory, and invokes report evaluators afterward. This makes it harder to prove that in-memory and durable execution mean the same thing. Although durable case commits preserve completed work, report evaluation cannot be resumed on the same run after every case has finished, so an interruption near the end can waste a complete aggregate report input.

The project needs a model in which Evaluation Cases express what special evaluation they require, Evaluation Suites retain ownership of how those requirements are satisfied, every run freezes the exact resolved evaluator assignment before execution, and durable execution preserves completed case and report work without introducing persistence side effects into evaluators.

## Solution

Allow each Evaluation Case to declare zero or more stable semantic Evaluation Requirements from a component-owned Evaluation Requirement Catalog. An Evaluation Suite continues to evaluate exactly one component operation through one exact Evaluation Task Contract. It owns all Configured Evaluators and maps each supported Evaluation Requirement to a non-empty set of case evaluators through Evaluation Requirement Bindings. Suite-wide Case Evaluators remain available for judgments that apply to every selected case.

Before creating an Evaluation Run, resolve the selected Evaluation Case revisions against the Suite. Reject the pairing if any selected case has an unknown or unbound requirement. Produce a canonical, immutable Resolved Evaluation Plan that records each case's declared requirements, its effective Configured Evaluators, deduplication, and assignment provenance. Persist that plan atomically with the run, Evaluation Case Manifest, and pending Evaluation Case Results.

Use one shared execution engine and one multi-case Pydantic Evals Dataset for both in-memory and durable execution. Attach Suite-wide Case Evaluators at Dataset scope and requirement-selected evaluators at Case scope, omitting duplicates already applied Suite-wide. The in-memory path uses a no-op checkpoint sink; the durable path uses runner-owned Pydantic lifecycle hooks to commit each terminal case and its evaluator evidence atomically. Evaluators remain deterministic producers of evaluation evidence and never write to the database.

After all manifested cases have terminal checkpoints, freeze the exact aggregate Pydantic Evaluation Report as a content-addressed Evaluation Artifact and move the run into finalization-pending. Report evaluator executions are independently checkpointed. An explicit, idempotent Evaluation Finalization operation resumes only missing report evaluator work on the same run under a lease or compare-and-set guard. Interrupted case execution still creates a distinct linked retry run because its manifested execution attempt is incomplete.

## User Stories

1. As an evaluation case author, I want a case to declare zero or more Evaluation Requirements, so that it can state every special kind of judgment needed without choosing evaluator machinery.
2. As an evaluation case author, I want requirement keys to express semantic needs such as contextual relevance judgment, so that case intent remains understandable independently of a particular judge or rubric.
3. As an evaluation case author, I want Evaluation Requirements drawn from a closed component-owned Evaluation Requirement Catalog, so that typos and ad hoc vocabulary cannot silently change evaluation behavior.
4. As a component maintainer, I want each catalog key to have one stable semantic meaning, so that Suites can implement the same requirement consistently over time.
5. As a component maintainer, I want a fundamentally changed requirement meaning to receive a new key, so that historical cases are not reinterpreted.
6. As an evaluation case author, I want evaluator names, evaluator revisions, rubric revisions, metrics, providers, and models excluded from Evaluation Requirements, so that judging implementation can evolve without revising the case.
7. As an evaluation case author, I want adding or removing an Evaluation Requirement to create a new Evaluation Case revision, so that changes in authored case intent remain reproducible.
8. As an Evaluation Gold Set maintainer, I want Gold Set versions to continue selecting exact Evaluation Case revisions without evaluator bindings, so that corpus ownership stays separate from evaluation mechanism ownership.
9. As an Evaluation Suite maintainer, I want a Suite to retain one exact Evaluation Task Contract for one component operation, so that the Pydantic Evals Dataset evaluates one coherent callable.
10. As an Evaluation Suite maintainer, I want heterogeneous inputs and outputs represented as explicit variants inside the shared contract, so that case-specific evaluation does not weaken task compatibility.
11. As an Evaluation Suite maintainer, I want to declare Suite-wide Case Evaluators, so that universally applicable judgments need not be repeated in every requirement binding.
12. As an Evaluation Suite maintainer, I want to bind each supported Evaluation Requirement to one or more Configured Evaluators, so that multiple complementary judgments can collectively satisfy one semantic need.
13. As an Evaluation Suite maintainer, I want every evaluator in a requirement binding to run, so that bindings are deterministic sets rather than ambiguous alternatives or fallbacks.
14. As an Evaluation Suite maintainer, I want one Configured Evaluator declaration referenced from multiple scopes or bindings, so that its configuration has one suite-local source of truth.
15. As an Evaluation Suite maintainer, I want evaluator configurations with materially different settings to use different suite-local names, so that their execution provenance is unambiguous.
16. As an Evaluation Suite maintainer, I want case and report Configured Evaluators held in separate typed collections while their names remain unique across the Suite, so that evaluator role mistakes are rejected early.
17. As an Evaluation Suite maintainer, I want every configured case evaluator referenced Suite-wide or by at least one binding, so that dead configuration cannot masquerade as active coverage.
18. As an Evaluation Suite maintainer, I want bindings that are unused by a particular Gold Set selection to remain valid, so that one Suite can support several compatible populations without revision churn.
19. As an Evaluation Suite maintainer, I want to revise a contextual judge, rubric, or evaluator configuration without revising Evaluation Cases or the Gold Set, so that mechanism iteration remains Suite-owned.
20. As an evaluation runner, I want selected cases with unknown requirement keys rejected before run creation, so that authored data cannot enter an undefined evaluation state.
21. As an evaluation runner, I want selected cases with requirements the Suite cannot bind rejected before run creation, so that mandatory judgments are never silently omitted.
22. As an evaluation runner, I want compatibility checked against only the cases selected for a run, so that unsupported unselected cases do not block a valid subset evaluation.
23. As an evaluation operator, I want a full-run preflight to report every incompatible selected case and requirement, so that Suite coverage gaps can be corrected before spending provider resources.
24. As an evaluation runner, I want Suite-wide and requirement-selected evaluators combined additively for each case, so that both common and special judgments are applied.
25. As an evaluation runner, I want the same Configured Evaluator applied at most once to a case even when several requirements or Suite-wide scope select it, so that overlap cannot double-weight or duplicate work.
26. As an evaluation investigator, I want deduplicated evaluator assignments to retain all selecting requirements and Suite-wide provenance, so that I can explain why each evaluator ran.
27. As an evaluation investigator, I want a Resolved Evaluation Plan containing exact manifested case revisions and evaluator assignments, so that the intended evaluation can be reconstructed independently of later authored-definition changes.
28. As an evaluation investigator, I want the canonical plan persisted as compact JSON in the relational ledger, so that the authoritative plan is transactional and queryable with the run.
29. As an evaluation operator, I want an optional readable JSON or YAML projection of the plan, so that humans and CI can inspect it without making that projection authoritative.
30. As an evaluation runner, I want run creation, manifest creation, pending result creation, and Resolved Evaluation Plan persistence to be atomic, so that a run never exists with an ambiguous intended evaluation.
31. As an evaluation maintainer, I want in-memory and durable execution to consume the same Resolved Evaluation Plan and shared engine, so that convenience execution and recorded execution have identical evaluator semantics.
32. As an evaluation maintainer, I want both execution paths to build one multi-case Pydantic Evals Dataset, so that report behavior and framework lifecycle semantics match Pydantic Evals.
33. As an evaluation runner, I want Suite-wide Case Evaluators attached at Dataset scope and special evaluators attached at Case scope, so that the resolved plan maps directly onto Pydantic Evals concepts.
34. As an evaluation operator, I want bounded case concurrency recorded in the Evaluation Run Configuration, so that execution behavior is reproducible and resource usage is controlled.
35. As an evaluation operator, I want case concurrency to default to one, so that durable execution remains conservative unless parallelism is explicitly selected.
36. As a persistence maintainer, I want concurrent case completion serialized through safe ledger transactions, so that higher task concurrency does not compromise checkpoint integrity.
37. As an evaluation operator, I want each terminal case and its case-evaluator evidence committed atomically as it finishes, so that completed work survives later task, evaluator, orchestration, or process failure.
38. As an evaluator author, I want evaluators to return evidence without writing to the ledger, so that evaluator logic remains portable, testable, and free of duplicate persistence concerns.
39. As an evaluation maintainer, I want runner-owned Pydantic case lifecycle hooks to translate completed framework results into checkpoints, so that persistence behavior is consistent across evaluator implementations.
40. As an evaluation maintainer, I want the in-memory path to use a no-op checkpoint sink, so that it exercises the same engine without requiring a database.
41. As an evaluation operator, I want interruption before every case is terminal to leave completed checkpoints intact while requiring a new linked Evaluation Run for retry, so that immutable execution attempts are not partially replayed in place.
42. As an evaluation operator, I want the complete aggregate Pydantic Evaluation Report frozen after all cases become terminal, so that report evaluators always consume the exact same case population and evidence.
43. As an evaluation investigator, I want that aggregate report stored as a content-addressed Evaluation Artifact, so that large or sensitive report input stays outside relational rows while remaining immutable and reproducible.
44. As a persistence maintainer, I want the report artifact identity and finalization-pending state recorded atomically, so that resumable report work never lacks an authoritative input.
45. As an evaluation operator, I want report evaluators checkpointed independently, so that failure or interruption in one report evaluator does not erase completed report analyses.
46. As an evaluation operator, I want an explicit Evaluation Finalization operation that resumes missing report evaluator work on the same run, so that a complete case phase is not wasted.
47. As an evaluation operator, I want Evaluation Finalization to skip report evaluator executions that already have terminal success or failure evidence, so that finalization is idempotent and does not rewrite history.
48. As an evaluation investigator, I want a report evaluator failure retained as terminal evidence, so that a failed judgment is distinguishable from work that never ran.
49. As an evaluation operator, I want Evaluation Finalization protected by a lease or compare-and-set guard, so that two workers cannot execute the same missing report evaluator concurrently.
50. As an evaluation operator, I want finalization invoked explicitly rather than resumed by an implicit background worker, so that operational control remains visible and predictable.
51. As an evaluation operator, I want a run marked complete only after every expected report evaluator has terminal evidence, so that completion means the evaluation workflow has been fully accounted for.
52. As an evaluation investigator, I want task failures, case evaluator failures, missing report work, report evaluator failures, and orchestration failures represented separately, so that incomplete work and negative evidence are never conflated.
53. As a future component author, I want to define a task contract, requirement catalog, cases, Suite bindings, and evaluator resolvers, so that the shared runtime handles plan resolution, Pydantic Evals composition, checkpointing, and finalization.

## Implementation Decisions

- Preserve the Evaluation Suite boundary as one component operation or callable with one exact Evaluation Task Contract. Do not introduce multiple task contracts per Suite. Input, output, or metadata heterogeneity must be modeled as explicit variants in the shared schemas.
- Add zero or more distinct Evaluation Requirement keys to each immutable Evaluation Case revision. Requirements are mandatory semantic capabilities, not evaluator preferences.
- Define an Evaluation Requirement Catalog per component as a closed vocabulary of stable keys and immutable semantic descriptions. Catalog entries do not have an independent revision lifecycle. A meaning change introduces a new key.
- Keep evaluator implementation names, evaluator revisions, configuration, rubric revisions, metric definitions, provider selection, and model selection out of Evaluation Requirements and the Evaluation Gold Set.
- Preserve normal authored-definition revision semantics: changing a case's requirement set changes the Evaluation Case and therefore requires a new case revision; changing how a Suite satisfies an unchanged requirement changes only the Evaluation Suite revision.
- Keep case and report Configured Evaluators in separate typed Suite collections. Require Suite-local evaluator names to be unique across both collections.
- Represent Suite-wide Case Evaluators as references to declared case Configured Evaluators.
- Represent each Evaluation Requirement Binding as one requirement key mapped to a non-empty set of declared case Configured Evaluator references. Every referenced evaluator runs; bindings do not encode alternatives, ordering fallback, or provider selection.
- Reject duplicate configured references within a scope or binding. Reject configured case evaluators that are referenced neither Suite-wide nor by any binding. Permit bindings that no selected case uses.
- Continue requiring at least one configured report evaluator in every Evaluation Suite.
- Resolve compatibility only after the Evaluation Case Manifest selection is known. Validate the selected cases' exact task schemas and requirement keys. Reject run creation when any selected requirement is absent from the component catalog or lacks a Suite binding. Unselected cases do not affect subset-run compatibility.
- Introduce a Resolved Evaluation Plan as immutable per-run data. It contains the exact Suite revision, exact manifested Evaluation Case revisions, each case's declared requirements, each effective Configured Evaluator reference, evaluator scope, all requirement provenance, and the result of deduplication.
- Resolve effective evaluators as the union of Suite-wide Case Evaluators and every Configured Evaluator selected by every requirement on the case. Apply a Configured Evaluator once per case while retaining all reasons it was selected.
- Serialize the Resolved Evaluation Plan as canonical, compact JSON and include it in the same ledger transaction that creates the Evaluation Run, Evaluation Case Manifest, and pending Evaluation Case Result envelopes. The relational copy is authoritative. Human-readable JSON or YAML may be emitted as a derived artifact.
- Use one shared execution engine for in-memory and durable evaluation. Both paths accept the same Resolved Evaluation Plan, construct the same Pydantic Evals Cases, use the same evaluator resolver, and produce the same report and failure semantics.
- Build one multi-case Pydantic Evals Dataset per Evaluation Run. Attach Suite-wide Case Evaluators to the Dataset. Attach only the remaining requirement-selected Configured Evaluators to each Pydantic Evals Case, omitting anything already applied at Dataset scope.
- Add bounded case concurrency to the immutable Evaluation Run Configuration and its canonical fingerprint. Default it to one and accept explicitly selected higher positive bounds. Serialize durable persistence transactions even when task evaluation is concurrent.
- Introduce a checkpoint sink abstraction at the shared engine boundary. The in-memory path uses a no-op implementation. The durable path uses a ledger-backed implementation.
- Use runner-owned Pydantic CaseLifecycle teardown hooks to convert each completed or failed framework case into one atomic Evaluation Checkpoint containing the terminal Evaluation Case Result, its Case Evaluator Executions, observations, issues, and artifact links.
- Keep all persistence out of task callables, case evaluators, and report evaluators. Evaluators return framework values or failures; the runner and checkpoint sink own translation and storage.
- Preserve completed case checkpoints on cancellation, orchestration failure, or process interruption. If any manifested case lacks a terminal checkpoint, retry by creating a distinct Evaluation Run linked through the existing retry relationship. Do not replay missing cases into the original run.
- Once every manifested case is terminal, construct and serialize the canonical aggregate Pydantic Evaluation Report exactly once. Register its bytes as a content-addressed Evaluation Artifact outside the relational ledger.
- Atomically link the aggregate report artifact to the Evaluation Run and transition the run to an explicit finalization-pending state. This artifact is the authoritative input for all report evaluators and for resumed Evaluation Finalization.
- Treat report evaluation as a separately checkpointed aggregate phase. Persist each Report Evaluator Execution, its observations, issues, and artifact links atomically as it reaches terminal success or failure.
- Provide an explicit, idempotent Evaluation Finalization operation addressed by run identity. It requires all cases to be terminal, loads the frozen report artifact, determines expected report evaluators from the frozen Suite/plan, and executes only evaluators without a terminal execution record.
- Treat both completed and failed Report Evaluator Executions as terminal evidence. Evaluation Finalization must not rerun either. Missing execution records are resumable work.
- Guard Evaluation Finalization with a lease or compare-and-set claim that has clear acquisition, expiry, and release behavior. Concurrent finalizers must not produce duplicate Report Evaluator Executions.
- Do not add implicit background resumption. Callers and operators explicitly invoke Evaluation Finalization after a finalization-pending result or later recovery.
- Complete the Evaluation Run only after every expected report evaluator has terminal evidence. Preserve quality outcomes, task failures, evaluator failures, missing metrics, and release gates independently from workflow status.
- Make a clean schema and API cutover. There are no authored production Evaluation Cases or Evaluation Suites to migrate, so no data migration or backwards-compatibility shim is required.
- This specification refines the earlier shared evaluation contract. Where that specification suggests representing case-specific criteria only as typed metadata or direct rubric references, Evaluation Requirements and Suite-owned bindings supersede that choice. The earlier decisions that evaluator configuration remains Suite-owned, authored revisions remain immutable, and evidence is persisted incrementally remain in force.

## Testing Decisions

- Prefer one highest-level behavioral seam: resolve and execute a typed Evaluation Suite plus selected Evaluation Gold Set through the shared engine using deterministic task/evaluator doubles, then assert the returned report for in-memory execution or the complete persisted Evaluation Run aggregate for durable execution. This seam should cover plan resolution, Pydantic Evals composition, evaluator selection, checkpointing, and finalization without asserting private helper structure.
- Test external behavior and durable invariants rather than internal resolver methods, lifecycle callback ordering, generated SQL, or the exact arrangement of implementation classes.
- Use the existing Suite execution tests, Evaluation Runner lifecycle tests, and temporary real SQLiteEvaluationLedger tests as prior art. Extend those seams instead of introducing a parallel test-only runner.
- Add authored-model contract tests proving cases accept zero or multiple distinct valid requirements, reject duplicates and unknown catalog keys, include requirements in semantic content hashes, and require a new case revision when intent changes.
- Add Suite contract tests proving case/report evaluator name uniqueness, binding type correctness, non-empty binding sets, reference validity, dead case-evaluator rejection, Suite-wide reference validity, and acceptance of dormant bindings.
- Add compatibility tests proving exact Evaluation Task Contract enforcement remains unchanged, selected unbound requirements reject run creation, unsupported unselected cases do not block subset runs, and full-run preflight identifies all coverage gaps.
- Add Resolved Evaluation Plan tests proving deterministic canonical serialization, exact case-revision capture, additive Suite-wide and requirement scopes, union across multiple requirements, deduplication, and preservation of all assignment provenance.
- Add Pydantic Evals composition tests proving Suite-wide evaluators run for every selected case, requirement evaluators run only for matching cases, overlapping evaluator references execute once, and report evaluators receive the complete multi-case report.
- Add execution-path parity tests that run the same frozen plan through no-op and durable checkpoint sinks and compare task outputs, evaluator applications, failures, observations, and aggregate report semantics.
- Add atomic run-creation tests proving the run, plan, manifest, and pending result envelopes all commit or all roll back.
- Add lifecycle checkpoint tests proving each terminal case and all evidence from that case commit atomically, later cancellation or orchestration failure preserves earlier checkpoints, evaluator failures remain evidence, and persistence failures do not leave partial producer records.
- Add bounded-concurrency tests proving the default is one, explicit bounds are fingerprinted, task execution does not exceed the configured bound, and concurrent completion still produces exactly one atomic checkpoint per case.
- Add interruption tests proving missing case work is not resumed into the original run and a retry creates a distinct linked Evaluation Run.
- Add report artifact tests proving the aggregate report is frozen only after all cases are terminal, content identity is stable, artifact metadata and location are recorded, and the run cannot enter finalization-pending without an atomically linked artifact.
- Add Evaluation Finalization tests proving it loads the frozen report, runs only missing report evaluators, skips both successful and failed terminal executions, records each new execution atomically, tolerates repeated invocation, and completes the run only when all expected report evidence is terminal.
- Add finalizer concurrency tests proving one lease holder performs work, competing claims do not duplicate executions, and expired claims can be safely recovered.
- Add independence tests proving a Suite judge/rubric/configuration revision does not require a case or Gold Set revision, while changing a case's requirement set changes its case revision without forcing a Suite revision when the existing binding already supports it.
- Keep all shared-contract tests offline and deterministic. Live provider quality tests remain component-specific and outside this feature's acceptance criteria.

## Out of Scope

- Allowing one Evaluation Suite to evaluate multiple component operations or unrelated callables.
- Allowing cases in one Suite to bypass exact input, output, or metadata schema compatibility.
- Storing evaluator implementations, configurations, rubric revisions, metric definitions, providers, or models on Evaluation Cases or Evaluation Gold Sets.
- Treating Evaluation Requirements as advisory preferences, ordered alternatives, evaluator fallbacks, or dynamic evaluator discovery.
- Creating an independently versioned universal requirement registry or universal evaluator registry.
- Automatically inferring requirements from case metadata, tags, expected outputs, or artifacts.
- Changing the semantics of existing Evaluation Metric Definitions, comparison operations, release gates, or provider-neutral task outcomes beyond what finalization requires.
- Building an authoring UI for catalogs, cases, Suites, bindings, or Resolved Evaluation Plans.
- Implementing implicit background workers for case retry or report finalization.
- Resuming incomplete case execution within the same Evaluation Run.
- Persisting large aggregate report bodies directly in relational columns.
- Writing persistence logic inside custom Pydantic Evals evaluators.
- Migrating existing authored definitions or execution history; no migration is needed because there are no production definitions to preserve.
- Defining component-specific requirement keys, rubrics, evaluator implementations, or quality thresholds as part of the shared framework work.

## Further Notes

- The ownership split is deliberate: an Evaluation Case owns the semantic statement that a special judgment is required; an Evaluation Suite owns the current best mechanism for satisfying it. This permits independent Gold Set and judge iteration while ensuring case intent affects evaluation.
- Evaluation Requirements complement rather than replace Suite-wide Case Evaluators. Requirements should be used only when a judgment is not universally applicable to every case selected by the Suite.
- The Resolved Evaluation Plan is the ground truth for what the run intended to execute. The Pydantic Evals Dataset is its executable projection, and the aggregate Evaluation Report artifact is the immutable input to report finalization.
- Pydantic Evals already supports additive Dataset-wide and Case-specific evaluators. This design maps Suite-wide Case Evaluators to Dataset evaluators and requirement-selected evaluators to per-Case evaluators while retaining the project's stronger provenance and durability rules.
- A report evaluator that raises an error has run and produced terminal failure evidence; it is not missing work. Operational retry of a failed evaluator with changed behavior or infrastructure requires a new Suite/run decision rather than silently rewriting the existing execution.
- The domain terminology and architectural summary for this feature are recorded in the project context and the ADR titled "Resolve case evaluation requirements before execution."
