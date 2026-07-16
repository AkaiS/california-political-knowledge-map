# Evaluation Contract and Resumable Execution

Status: ready-for-agent
Labels: ready-for-agent

## Problem Statement

The shared evaluation foundation has the right broad concepts but does not yet enforce several of its most important trust boundaries. An Evaluation Gold Set can reference cases with unrelated task schemas, Evaluation Run Configuration accepts untyped component settings, and a component can return a value that violates the Suite's output contract while the run still records a successful Task Outcome. Task-produced artifacts can also be lost between component execution and durable checkpointing.

Case-level judging is too coarse. An Evaluation Suite currently applies every configured case evaluator to every selected Evaluation Case. Putting evaluator implementations, rubrics, models, or revisions on Cases would couple the Gold Set to the current judging mechanism and force unrelated authored revisions whenever a judge changes. Cases instead need to express stable semantic requirements while Suites retain ownership of how those requirements are satisfied.

Execution also lacks one frozen representation and one lifecycle across in-memory and durable paths. The convenience path builds one multi-case Pydantic Evals Dataset, while the durable runner builds one-case Datasets, accumulates report input in memory, and invokes report evaluators separately. Report work cannot safely resume from the exact authored Suite and aggregate report after interruption. Output-validation failures can skip typed-output evaluators without leaving the terminal assignment evidence required by guarded completion.

Metric and persistence integrity have similar gaps. Metric Definitions lack independently enforced repository-wide identity, Metric Observations independently store both subjects and producers, and Evaluation Run completion is an unconditional status update. These responsibilities are concentrated in one large SQLite Evaluation Ledger whose public cohesion is useful but whose internal coupling makes new invariants difficult to maintain.

The project needs one coherent contract from authored definitions through planning, task invocation, case execution, checkpointing, report finalization, and completion. Invalid evidence should be unrepresentable, interrupted work should remain recoverable without rewriting an immutable attempt, and finalization must never depend on mutable caller-provided authored objects.

## Solution

Harden authored, runtime, and durable contracts around one public shared evaluation engine and one Evaluation Ledger facade.

Each Evaluation Gold Set version binds one exact Evaluation Task Contract, and every member implements the same input, expected-output, and metadata schemas. Each Evaluation Case may additionally declare stable Evaluation Requirements from a component-owned closed catalog. The Evaluation Suite owns all judging machinery, applies case evaluators Suite-wide where appropriate, and binds supported requirements to configured case evaluators.

Preflight resolves selected exact Case revisions against one exact imported Suite revision. It produces an immutable Resolved Evaluation Plan containing the Suite identity, revision, and content hash; manifested Case revisions; declared requirements; effective case-evaluator assignments; deduplication; and assignment provenance. Run creation persists that plan atomically with the Run, Manifest, pending Case Results, and typed, secret-free Run Configuration.

An Evaluation Task Binding associates one synchronous or asynchronous component operation and its Pydantic models with the authored Task Contract. It validates returned output exactly once and emits a complete provider-neutral Task Outcome with artifact references. Output-contract violations are terminal, non-retryable `output_validation` failures for the attempt. Planned case evaluators that require typed task output receive terminal `skipped` executions with a stable reason such as `task_output_unavailable`; their absence is never mistaken for unfinished work.

The shared engine has two explicit phases. The case phase consumes the frozen plan, builds one bounded-concurrency multi-case Pydantic Evals Dataset, executes tasks and case evaluators, and produces the complete aggregate report input. The report phase consumes that immutable aggregate report plus the exact imported Suite revision resolved by the ledger. In-memory execution runs both phases with a no-op checkpoint sink. Durable execution checkpoints terminal case work, freezes the aggregate report as a content-addressed artifact, and later runs only missing report evaluators under explicit finalization.

Finalization is addressed only by Run identity. It loads the Resolved Evaluation Plan, verifies and loads the exact imported Suite by identity, revision, and content hash from the Authored Definition Catalog, and loads the frozen aggregate report artifact. It never accepts a caller-provided Suite as authoritative. A lease or compare-and-set claim prevents competing finalizers from duplicating report work.

Metric Definitions become immutable, content-addressed, repository-wide definitions embedded in self-contained Suites and normalized during import. Metric Observations are owned solely by their producer executions. The SQLite Evaluation Ledger remains one facade, connection, and transaction owner while delegating authored definitions, execution state, and artifacts to focused internal capabilities.

Evaluation Finalization requests completion; the ledger authorizes it transactionally only when every manifested task, planned case-evaluator application, aggregate report, and expected report evaluator has terminal evidence. `completed`, `failed`, and explicitly justified `skipped` producer executions all count as terminal workflow accounting. Quality failures, missing metrics, and release-gate outcomes remain independent from workflow completion.

This is a clean schema and API cutover. There is no production evaluation ledger to migrate and no backwards-compatibility shim is required.

## User Stories

### Case Requirements and Resumable Execution

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

### Contract and Ledger Hardening

54. As an evaluation author, I want each Evaluation Gold Set version to bind one exact Evaluation Task Contract, so that its population has one coherent typed meaning.
55. As an evaluation author, I want every Gold Set member to match the bound input schema exactly, so that incompatible component inputs cannot enter the population.
56. As an evaluation author, I want every Gold Set member to match the bound expected-output schema exactly, so that authoritative outcomes remain comparable.
57. As an evaluation author, I want every Gold Set member to match the bound metadata schema exactly, so that evaluators can rely on one metadata contract.
58. As an evaluation author, I want incompatible membership rejected while authoring, so that an invalid Gold Set is discovered before execution.
59. As an evaluation investigator, I want Gold Set membership revalidated against exact imported Case revisions, so that a reference cannot resolve to different authored content.
60. As an evaluation maintainer, I want a Gold Set contract change to alter its authored content identity, so that historical populations remain reproducible.
61. As a component author, I want heterogeneous inputs or outputs represented as explicit schema variants, so that flexibility does not weaken exact compatibility.
62. As an evaluation operator, I want subset selection to vary splits, tags, and requirement coverage without concealing schema incompatibility, so that a subset run remains honest about its population.
63. As an evaluation author, I want Cases for different component operations placed in distinct Gold Sets, so that a full Gold Set remains executable by one operation.
64. As an evaluation author, I want distinct Gold Sets to reuse the same source artifacts and provenance, so that contract separation does not duplicate large evidence.
65. As an Evaluation Suite maintainer, I want the Suite and Gold Set contracts compared before selection, so that an incompatible pairing cannot create a run.
66. As an Evaluation Suite maintainer, I want selected Manifest cases checked against the matched contract as defense in depth, so that later orchestration cannot bypass the invariant.
67. As a component author, I want one Evaluation Task Binding to associate my operation and Pydantic models with the Task Contract, so that runtime typing has an explicit boundary.
68. As a component author, I want Binding creation to reject mismatched model schemas, so that a callable cannot merely claim to implement a contract.
69. As a component author, I want synchronous operations supported through the same Task Binding semantics, so that ordinary components require no evaluation-specific wrapper behavior.
70. As a component author, I want asynchronous operations supported through the same Task Binding semantics, so that awaiting a component does not create a second evidence model.
71. As an evaluation runner, I want every returned component value validated once at the Binding boundary, so that Python annotations are not mistaken for runtime guarantees.
72. As an evaluation runner, I want an output-contract violation represented as a terminal `output_validation` Task Failure, so that invalid output is never persisted as success.
73. As an evaluation runner, I want output-validation failures non-retryable within the same attempt by default, so that deterministic contract bugs are not silently replayed.
74. As an evaluation runner, I want component exceptions normalized without provider SDK objects, so that durable evidence stays provider-neutral.
75. As an evaluation investigator, I want successful Task Outcomes to retain exact output-artifact references, so that the evidence behind a result remains discoverable.
76. As an evaluation investigator, I want failed Task Outcomes to retain failure-artifact references, so that negative evidence is not discarded.
77. As a component maintainer, I want the underlying component to remain unaware of the evaluation framework, so that production behavior and evaluation behavior use the same operation.
78. As a persistence maintainer, I want Task Bindings and evaluators to perform no ledger writes, so that checkpoint atomicity remains runner-owned.
79. As an evaluation runner, I want the shared engine to trust a validated Task Outcome without validating it again, so that one boundary has clear responsibility.
80. As an evaluation maintainer, I want synchronous and asynchronous evaluator adapters to share timing and evidence-recording behavior, so that their semantics cannot drift.
81. As an evaluation maintainer, I want sync and async adapters to retain only their invocation-specific call or await behavior, so that deduplication does not obscure asynchronous correctness.
82. As a component maintainer, I want Evaluation Run Configuration to contain my component's validated Pydantic configuration, so that persisted configuration matches what constructed the component.
83. As an evaluation investigator, I want the component configuration's schema identity, revision, and fingerprint recorded, so that its typed meaning is reproducible.
84. As a security-conscious maintainer, I want credentials removed from serialized component configuration, so that the ledger does not become a secret store.
85. As a security-conscious maintainer, I want secrets excluded from configuration fingerprints, so that credentials are not treated as experimental differences.
86. As an evaluation operator, I want provider identity, model identity, model parameters, execution mode, and random seed normalized, so that common run dimensions remain queryable.
87. As an evaluation operator, I want bounded case concurrency represented explicitly, so that execution behavior is reproducible.
88. As an evaluation operator, I want case concurrency to default to one and reject non-positive bounds, so that omitted configuration is conservative and valid.
89. As an evaluation investigator, I want materially equivalent Run Configurations to share a fingerprint, so that equivalent experiments can be identified.
90. As an evaluation investigator, I want any material shared or component setting to change the fingerprint, so that unlike runs are not conflated.
91. As a metric author, I want each Evaluation Metric Definition to have repository-wide identity and immutable semantic content, so that a metric means the same thing wherever it appears.
92. As a metric author, I want value type, structured schema, semantic description, and comparison operation covered by a content hash, so that semantic changes are detectable.
93. As an Evaluation Suite maintainer, I want Suites to remain self-contained by embedding exact Metric Definitions, so that a Suite can be serialized and reviewed without a runtime registry.
94. As a persistence maintainer, I want embedded Metric Definitions normalized into canonical ledger records, so that identical definitions are stored once.
95. As a persistence maintainer, I want identical metric imports to be idempotent, so that multiple Suites can reuse one definition safely.
96. As a persistence maintainer, I want conflicting content for an existing metric identity rejected, so that semantic collisions cannot enter the ledger.
97. As an evaluator author, I want a type-agnostic evaluator to reuse one Metric Definition across Task Contracts, so that task type alone does not create meaningless metric revisions.
98. As an evaluator author, I want a new Metric Definition revision when observation meaning, value schema, or comparison semantics change, so that comparisons remain trustworthy.
99. As an Evaluation Suite maintainer, I want adopting a new metric revision to require a new Suite revision, so that historical Suite behavior remains reproducible.
100. As an Evaluation Suite maintainer, I want Configured Evaluator metric references resolved only against exact definitions declared by the Suite, so that undeclared observations cannot masquerade as supported metrics.
101. As an evaluation investigator, I want every Case Metric Observation owned by its Case Evaluator Execution, so that its producer provenance is exact.
102. As an evaluation investigator, I want every Run Metric Observation owned by its Report Evaluator Execution, so that its producer provenance is exact.
103. As a database user, I want an observation's Case Result or Run derived through its producer, so that duplicated ownership cannot disagree.
104. As a database user, I want separate case- and run-observation tables, so that relational structure preserves subject type.
105. As a database user, I want indexed case, run, and cross-run metric queries through producer relationships, so that normalized provenance remains practical to query.
106. As a persistence maintainer, I want cross-case and cross-run misattribution to be structurally impossible, so that application bugs cannot corrupt provenance.
107. As an evaluation investigator, I want observation identities resolved to canonical Metric Definitions, so that queried values retain exact semantics.
108. As an evaluation runtime maintainer, I want one Evaluation Ledger facade, so that persistence remains a cohesive capability rather than a collection of database objects.
109. As a persistence maintainer, I want one shared SQLite connection and transaction owner, so that cross-capability invariants remain atomic.
110. As a persistence maintainer, I want authored-definition import isolated in an Authored Definition Catalog, so that definition changes do not expand execution lifecycle code.
111. As a persistence maintainer, I want run and checkpoint persistence isolated in an Evaluation Execution Store, so that lifecycle changes have one focused home.
112. As a persistence maintainer, I want artifact identity and provenance isolated in an Evaluation Artifact Catalog, so that artifact policy can evolve independently.
113. As a persistence maintainer, I want schema installation separated from domain stores, so that bootstrapping does not dominate persistence APIs.
114. As an evaluation runner, I want to depend on the Evaluation Ledger abstraction rather than SQLite, so that orchestration does not absorb storage details.
115. As a persistence maintainer, I want the facade to coordinate transactions spanning internal stores, so that decomposition does not weaken run creation or checkpoints.
116. As a project maintainer, I want one clean schema cutover with no migration or compatibility shim, so that prototype constraints do not burden the final model.
117. As an evaluation operator, I want Evaluation Finalization to request rather than dictate completion, so that a stale caller cannot bypass durable invariants.
118. As an evaluation operator, I want completion rejected while any manifested case lacks terminal task evidence, so that absent work is never reported as complete.
119. As an evaluation operator, I want completion rejected while any planned Case Evaluator application lacks terminal evidence, so that required judgments cannot silently disappear.
120. As an evaluation operator, I want completion rejected before the exact aggregate report artifact is frozen and linked, so that report evaluation has an immutable input.
121. As an evaluation operator, I want completion rejected while any expected Report Evaluator lacks terminal evidence, so that finalization accounts for all planned work.
122. As an evaluation operator, I want failed Task and Evaluator executions to count as terminal evidence, so that completion describes workflow accounting rather than quality.
123. As an evaluation operator, I want missing metrics, quality issues, and release-gate failures reported independently, so that they do not falsely make a fully accounted workflow incomplete.
124. As a persistence maintainer, I want the completion check and status transition in one transaction, so that competing or stale finalizers cannot race the invariant.
125. As an evaluation operator, I want repeated completion requests to be safe, so that explicit finalization is idempotent.
126. As a CI maintainer, I want all shared-contract scenarios deterministic and offline, so that pull requests do not depend on live providers.
127. As a CI maintainer, I want in-memory and durable evaluation to consume the same engine seam, so that test doubles exercise production orchestration.
128. As a CI maintainer, I want temporary real SQLite ledgers in durable tests, so that foreign keys, transactions, and query behavior are genuinely verified.
129. As a future component author, I want one typed path from Gold Set and Suite authoring through Task Binding, execution, checkpointing, metrics, and finalization, so that new model-backed components inherit trustworthy behavior.

### Integrated Seam Decisions

130. As an evaluation maintainer, I want explicit case and report execution phases separated by the immutable aggregate report, so that in-memory and durable execution share one resumable lifecycle.
131. As an evaluation investigator, I want finalization to load and hash-verify the exact imported Suite revision from the Evaluation Ledger, so that mutable caller state cannot change historical evaluation behavior.
132. As an evaluation operator, I want every planned case evaluator accounted for as completed, failed, or explicitly skipped with a stable reason, so that inapplicable work is distinguishable from missing work.

## Implementation Decisions

- Preserve one Evaluation Suite boundary per component operation and exact Evaluation Task Contract. Do not permit unrelated Task Contracts in one Suite or Gold Set.
- Bind every Gold Set version to one exact input, expected-output, and metadata schema identity, revision, and fingerprint. Validate members at authoring and exact-reference import.
- Permit subset differences only for splits, tags, and Evaluation Requirement coverage. Selection cannot make a schema-incompatible Gold Set valid.
- Add zero or more distinct Evaluation Requirement keys to immutable Case revisions. Catalog keys have stable semantic descriptions; a meaning change introduces a new key.
- Keep evaluator implementations, revisions, configuration, rubrics, metrics, providers, and models out of Cases, Requirements, and Gold Sets.
- Keep case and report Configured Evaluators in separate typed Suite collections with names unique across both. Continue requiring at least one report evaluator.
- Resolve case evaluators as the union of Suite-wide references and every relevant requirement binding. Execute each configured evaluator once per case while retaining all selection provenance.
- Introduce a canonical Resolved Evaluation Plan containing the exact Suite identity, revision, and content hash; exact manifested Case revisions; requirements; effective case-evaluator references; scopes; deduplication; and provenance.
- Persist the authoritative compact JSON plan in the same transaction as Run, Manifest, and pending Case Results. Human-readable projections are derived and non-authoritative.
- Finalization resolves expected report evaluators by loading the exact imported Suite identified by the frozen plan from the ledger. Do not copy mutable caller state into finalization and do not accept a caller-provided Suite as authority.
- Introduce an Evaluation Task Binding as the runtime association among one operation, its input/output/metadata Pydantic models, and one exact Task Contract. Keep executable classes and callables out of serialized definitions.
- Make the Task Binding the sole per-invocation output-validation boundary. The engine trusts typed success or provider-neutral failure and does not validate output again.
- Represent output-contract violations as terminal, non-retryable `output_validation` Task Failures for the current attempt.
- For every planned case evaluator that cannot run because typed task output is unavailable, persist a terminal `skipped` Case Evaluator Execution with a stable machine-readable reason. Skipping is explicit evidence, not omission.
- Make Task Bindings produce complete Task Outcome envelopes including output- or failure-artifact references without performing persistence.
- Consolidate sync and async evaluator timing and evidence normalization while retaining thin invocation-specific call and await operations.
- Replace arbitrary component settings with a schema-identified Validated Component Configuration derived from the component's Pydantic model.
- Normalize provider, model, model parameters, execution mode, random seed, and bounded case concurrency in Run Configuration. Canonically serialize and fingerprint only material, secret-free content. Concurrency defaults to one and must be positive.
- Make Metric Definitions immutable repository-wide authored definitions with identity `(namespaced name, evaluator revision)` and canonical content hashes.
- Keep Suites self-contained by embedding exact Metric Definitions. Normalize them into canonical ledger records on import and reject conflicting content for one identity.
- Make evaluator execution the sole relational owner of Metric Observations. Derive Case Result and Run subjects through producer relationships using separate case- and run-observation tables.
- Retain one Evaluation Ledger facade, shared SQLite connection, and transaction owner. Delegate authored definitions to an Authored Definition Catalog, lifecycle state to an Evaluation Execution Store, and artifacts to an Evaluation Artifact Catalog; separate schema installation.
- Require the Authored Definition Catalog to retrieve an exact Suite by identity and revision and verify its content hash before returning it for execution or finalization.
- Use one shared engine with explicit case and report phases. The case phase consumes the plan and produces the aggregate report; the report phase consumes the frozen report and exact ledger-loaded Suite.
- Use a no-op checkpoint sink in memory and a ledger-backed sink durably. Both paths execute the same phase contracts and produce equivalent observable semantics.
- Build one multi-case Pydantic Evals Dataset per Run case phase. Attach Suite-wide evaluators at Dataset scope and remaining requirement-selected evaluators at Case scope.
- Checkpoint each terminal case atomically with its Task Outcome, completed/failed/skipped Case Evaluator Executions, Metric Observations, issues, and artifact links.
- Preserve completed case checkpoints on cancellation or interruption. Retry missing case work in a distinct linked Run; never replay it into the original attempt.
- Freeze the canonical aggregate report exactly once after all manifested cases have terminal checkpoints. Store its bytes as a content-addressed artifact outside relational rows and atomically link it while entering finalization-pending.
- Address explicit Evaluation Finalization by Run identity only. Load the frozen plan, exact imported Suite, and frozen aggregate report from the ledger; run only report evaluators lacking terminal records.
- Checkpoint each Report Evaluator Execution and its observations, issues, and artifacts independently. Completed and failed report executions are terminal and are not rerun.
- Guard finalization with a lease or compare-and-set claim having explicit ownership, expiry, release, and recovery semantics.
- Allow finalization to request completion. Authorize the status transition in one ledger transaction only after every manifested task, planned case evaluator, frozen report, and expected report evaluator is terminal.
- Count `completed`, `failed`, and valid `skipped` producer executions as terminal workflow evidence. Keep missing metrics, quality issues, and release-gate failures independent from workflow status.
- Make repeated finalization and completion requests idempotent. Do not add implicit background resumption.
- Make a clean schema and API cutover with no migration or compatibility shim.

## Testing Decisions

- Use one primary behavioral seam: resolve and execute an authored Gold Set and Suite through the public shared engine, then inspect either the in-memory result or complete durable Run aggregate.
- Exercise the same explicit case and report phases with no-op and ledger-backed checkpoint sinks and assert equivalent populations, assignments, outcomes, observations, skips, failures, and aggregate semantics.
- Use temporary real SQLite Evaluation Ledgers for durable tests and verify behavior through the facade rather than internal stores or raw SQL.
- Add authored-contract tests for Gold Set homogeneity, exact imported references, schema variants, Requirement catalogs, Suite bindings, dead references, and authored content hashes.
- Add preflight tests for exact Suite identity/revision/content-hash capture, full coverage-gap reporting, subset requirement compatibility, evaluator union, deduplication, and provenance.
- Add atomic run-creation tests proving Run, plan, Manifest, and pending Results all commit or roll back together.
- Add Task Binding tests for sync and async success, output mismatch, provider-neutral component failure, artifact references, and exactly-once output validation.
- Add explicit skipped-evaluator tests proving output-validation failure creates terminal `task_output_unavailable` evidence for every affected planned assignment and does not block completion.
- Add Run Configuration tests for typed snapshots, canonical round trips, schema identity, secret removal, fingerprints, and bounded concurrency.
- Add Metric Definition tests for idempotent reuse and semantic conflict rejection across Suites.
- Add producer-owned observation tests proving cross-case and cross-run misattribution cannot be represented and indexed queries remain complete.
- Add checkpoint atomicity tests that inject persistence failure and prove no partial outcomes, producer records, observations, issues, or artifact links survive.
- Add durable interruption tests proving terminal cases survive and missing case work requires a distinct retry Run.
- Add report tests proving the aggregate is frozen only after the case phase, content identity is stable, and finalization-pending cannot exist without an atomically linked artifact.
- Add finalization tests proving the operation accepts only Run identity, loads and hash-verifies the exact imported Suite, ignores caller mutations, runs only missing report evaluators, and is idempotent.
- Add completion tests for pending tasks, missing and skipped case evaluators, missing reports, missing report evaluators, terminal failures, quality failures, gate failures, and successful repeated completion.
- Add finalizer concurrency tests proving one live lease holder, no duplicate executions, and safe expired-claim recovery.
- Add a complete tracer test from authored-definition import through planning, execution, report finalization, guarded completion, aggregate query, and artifact provenance.
- Keep shared-contract tests deterministic and offline. Live provider quality tests remain component-specific.

## Out of Scope

- Allowing one Gold Set or Suite to evaluate multiple unrelated component operations or Task Contracts.
- Inferring compatibility between structurally similar but differently identified or revisioned schemas.
- Storing evaluator machinery, providers, models, or Metric Definitions on Cases or Gold Sets.
- Treating Evaluation Requirements as preferences, alternatives, fallbacks, or dynamic evaluator discovery.
- Creating a universal requirement, evaluator, or runtime model registry.
- Making Task Bindings, component operations, or evaluators responsible for persistence.
- Persisting large artifact bodies directly in relational columns.
- Automatically retrying output-contract violations within the same Run.
- Resuming incomplete case execution within an existing Run.
- Accepting mutable caller-provided Suite objects during finalization.
- Adding implicit background workers for retry or finalization.
- Building an authoring UI, artifact browser, or operations dashboard.
- Changing component-specific requirements, rubrics, evaluator implementations, examples, or thresholds.
- Migrating prototype authored definitions, execution history, or ledger files.
- Live-provider quality evaluation in shared-contract CI.

## Further Notes

- The ownership split is deliberate: a Case owns the semantic statement that special judgment is required; a Suite owns the current mechanism for satisfying it.
- The Resolved Evaluation Plan is authoritative for Run intent. The multi-case Dataset is its case-phase executable projection. The aggregate report artifact is the immutable boundary between case and report phases.
- The plan freezes the exact Suite identity, revision, and content hash, but not a serialized executable Suite object. The ledger's imported authored definition is the only finalization authority.
- A terminal `skipped` evaluator execution is appropriate only when a frozen assignment cannot run because a declared prerequisite is unavailable. It must retain the assignment, reason, timestamps, and producer identity needed for workflow accounting.
- A report evaluator that fails has produced terminal negative evidence; it is not missing work. Changed behavior or infrastructure requires a new Suite/Run decision rather than rewriting the execution.
- Architectural decisions are recorded in [ADR 0005](../../docs/adr/0005-resolve-case-evaluation-requirements-before-execution.md), [ADR 0006](../../docs/adr/0006-bind-evaluation-gold-sets-to-one-task-contract.md), [ADR 0007](../../docs/adr/0007-validate-task-outcomes-at-the-task-binding.md), [ADR 0008](../../docs/adr/0008-reuse-repository-wide-metric-definitions.md), [ADR 0009](../../docs/adr/0009-derive-metric-observation-subjects-from-producers.md), and [ADR 0010](../../docs/adr/0010-keep-one-evaluation-ledger-transaction-facade.md).
- Implementation is divided into sixteen dependency-linked tracer bullets: [decomposed ledger](issues/01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md), [Gold Set Task Contracts](issues/02-bind-every-evaluation-gold-set-to-one-task-contract.md), [typed Run Configuration](issues/03-freeze-typed-component-configuration-in-evaluation-runs.md), [canonical Metric Definitions](issues/04-canonicalize-metric-definitions-across-suites.md), [producer-owned observations](issues/05-query-metric-observations-through-producer-ownership.md), [validated Task Bindings](issues/06-invoke-sync-and-async-tasks-through-validated-task-bindings.md), [Evaluation Requirements](issues/07-author-evaluation-requirements-and-suite-bindings.md), [preflight plans](issues/08-preflight-selected-cases-into-a-resolved-evaluation-plan.md), [atomic run creation](issues/09-atomically-create-runs-from-frozen-plans.md), [shared engine](issues/10-execute-frozen-plans-through-one-shared-multi-case-engine.md), [durable checkpoints](issues/11-checkpoint-one-durable-case-through-the-shared-engine.md), [retry behavior](issues/12-preserve-multi-case-progress-and-retry-incomplete-runs.md), [bounded concurrency](issues/13-honor-bounded-case-concurrency-durably.md), [report finalization](issues/14-freeze-the-aggregate-report-and-resume-missing-report-work.md), [guarded completion](issues/15-reject-premature-evaluation-run-completion.md), and [finalizer leasing](issues/16-guard-evaluation-finalization-against-competing-workers.md).
