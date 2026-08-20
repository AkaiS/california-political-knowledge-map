# Evaluation Contract and Ledger Hardening

Labels: superseded
Superseded by ADR 0017; see [the archive note](../README.md). Archived on 2026-08-19.

## Problem Statement

The shared evaluation foundation has the right broad concepts but does not yet enforce several of its most important trust boundaries. An Evaluation Gold Set can reference cases with unrelated task schemas, Evaluation Run Configuration accepts untyped component settings, and a component can return a value that violates the Suite's output contract while the run still records a successful Task Outcome. Task-produced artifacts can also be lost between component execution and durable checkpointing.

Metric and persistence integrity have similar gaps. Evaluation Metric Definitions are embedded in Suites without an independently enforced repository-wide identity, so two Suites can assign different meanings to the same apparent metric identity. Evaluation Metric Observations independently store both a subject and a producer, permitting impossible cross-case or cross-run attribution. Evaluation Run completion is an unconditional status update rather than a transactionally guarded conclusion derived from the frozen plan and terminal evidence.

These correctness gaps are concentrated in one large SQLite Evaluation Ledger that currently owns schema installation, authored-definition import, run lifecycle, checkpoint persistence, artifacts, provenance queries, and row mapping. Extending that class directly would deepen coupling and make the new invariants harder to test and maintain. Synchronous and asynchronous evaluator adapters also repeat the same timing and evidence-recording behavior.

The project needs a coherent hardening pass that makes invalid evaluation evidence unrepresentable, preserves one shared execution and transaction boundary, and leaves a future component author with one typed, provider-neutral path from authored definitions to trustworthy persisted results.

## Solution

Harden the authored, runtime, and durable evaluation contracts around one public shared evaluation engine and one Evaluation Ledger facade.

Each Evaluation Gold Set version will bind one exact Evaluation Task Contract, and every member will implement the same input, expected-output, and metadata schemas. A Suite and Gold Set must match exactly before selection or run creation. Legitimate heterogeneous shapes remain explicit variants inside one shared Pydantic schema rather than unrelated case contracts hidden by subset selection.

Each evaluated component operation will be exposed through an Evaluation Task Binding. The Binding associates the synchronous or asynchronous component callable and its Pydantic models with the authored Task Contract, validates every invocation exactly once, and returns a complete Evaluation Task Outcome. Success Outcomes contain validated typed output and output-artifact references; failures contain provider-neutral failure evidence and failure-artifact references. Bindings and evaluators remain persistence-free, while checkpoint sinks atomically persist their evidence.

Evaluation Run Configuration will freeze a schema-identified, secret-free Validated Component Configuration plus normalized shared execution dimensions, including bounded case concurrency. Metric Definitions will become immutable, content-addressed, repository-wide definitions that remain embedded in self-contained authored Suites but normalize into canonical ledger records. Metric Observations will be owned solely by their producer executions, with their case or run subject derived through that relationship.

The SQLite Evaluation Ledger will remain one facade, connection, and transaction owner. Internally it will delegate to an Authored Definition Catalog, Evaluation Execution Store, and Evaluation Artifact Catalog, with schema installation separated as a technical component. Evaluation Finalization may request completion, but the ledger will authorize the transition only after the frozen plan, manifested cases, evaluator assignments, and aggregate report all have terminal evidence.

This is a clean schema and API cutover. There is no production evaluation ledger to migrate and no backwards-compatibility shim is required.

## User Stories

1. As an evaluation author, I want each Evaluation Gold Set version to bind one exact Evaluation Task Contract, so that its population has one coherent typed meaning.
2. As an evaluation author, I want every Gold Set member to match the bound input schema exactly, so that incompatible component inputs cannot enter the population.
3. As an evaluation author, I want every Gold Set member to match the bound expected-output schema exactly, so that authoritative outcomes remain comparable.
4. As an evaluation author, I want every Gold Set member to match the bound metadata schema exactly, so that evaluators can rely on one metadata contract.
5. As an evaluation author, I want incompatible membership rejected while authoring, so that an invalid Gold Set is discovered before execution.
6. As an evaluation investigator, I want Gold Set membership revalidated against exact imported Case revisions, so that a reference cannot resolve to different authored content.
7. As an evaluation maintainer, I want a Gold Set contract change to alter its authored content identity, so that historical populations remain reproducible.
8. As a component author, I want heterogeneous inputs or outputs represented as explicit schema variants, so that flexibility does not weaken exact compatibility.
9. As an evaluation operator, I want subset selection to vary splits, tags, and requirement coverage without concealing schema incompatibility, so that a subset run remains honest about its population.
10. As an evaluation author, I want Cases for different component operations placed in distinct Gold Sets, so that a full Gold Set remains executable by one operation.
11. As an evaluation author, I want distinct Gold Sets to reuse the same source artifacts and provenance, so that contract separation does not duplicate large evidence.
12. As an Evaluation Suite maintainer, I want the Suite and Gold Set contracts compared before selection, so that an incompatible pairing cannot create a run.
13. As an Evaluation Suite maintainer, I want selected Manifest cases checked against the matched contract as defense in depth, so that later orchestration cannot bypass the invariant.
14. As a component author, I want one Evaluation Task Binding to associate my operation and Pydantic models with the Task Contract, so that runtime typing has an explicit boundary.
15. As a component author, I want Binding creation to reject mismatched model schemas, so that a callable cannot merely claim to implement a contract.
16. As a component author, I want synchronous operations supported through the same Task Binding semantics, so that ordinary components require no evaluation-specific wrapper behavior.
17. As a component author, I want asynchronous operations supported through the same Task Binding semantics, so that awaiting a component does not create a second evidence model.
18. As an evaluation runner, I want every returned component value validated once at the Binding boundary, so that Python annotations are not mistaken for runtime guarantees.
19. As an evaluation runner, I want an output-contract violation represented as a terminal `output_validation` Task Failure, so that invalid output is never persisted as success.
20. As an evaluation runner, I want output-validation failures non-retryable within the same attempt by default, so that deterministic contract bugs are not silently replayed.
21. As an evaluation runner, I want component exceptions normalized without provider SDK objects, so that durable evidence stays provider-neutral.
22. As an evaluation investigator, I want successful Task Outcomes to retain exact output-artifact references, so that the evidence behind a result remains discoverable.
23. As an evaluation investigator, I want failed Task Outcomes to retain failure-artifact references, so that negative evidence is not discarded.
24. As a component maintainer, I want the underlying component to remain unaware of the evaluation framework, so that production behavior and evaluation behavior use the same operation.
25. As a persistence maintainer, I want Task Bindings and evaluators to perform no ledger writes, so that checkpoint atomicity remains runner-owned.
26. As an evaluation runner, I want the shared engine to trust a validated Task Outcome without validating it again, so that one boundary has clear responsibility.
27. As an evaluation maintainer, I want synchronous and asynchronous evaluator adapters to share timing and evidence-recording behavior, so that their semantics cannot drift.
28. As an evaluation maintainer, I want sync and async adapters to retain only their invocation-specific call or await behavior, so that deduplication does not obscure asynchronous correctness.
29. As a component maintainer, I want Evaluation Run Configuration to contain my component's validated Pydantic configuration, so that persisted configuration matches what constructed the component.
30. As an evaluation investigator, I want the component configuration's schema identity, revision, and fingerprint recorded, so that its typed meaning is reproducible.
31. As a security-conscious maintainer, I want credentials removed from serialized component configuration, so that the ledger does not become a secret store.
32. As a security-conscious maintainer, I want secrets excluded from configuration fingerprints, so that credentials are not treated as experimental differences.
33. As an evaluation operator, I want provider identity, model identity, model parameters, execution mode, and random seed normalized, so that common run dimensions remain queryable.
34. As an evaluation operator, I want bounded case concurrency represented explicitly, so that execution behavior is reproducible.
35. As an evaluation operator, I want case concurrency to default to one and reject non-positive bounds, so that omitted configuration is conservative and valid.
36. As an evaluation investigator, I want materially equivalent Run Configurations to share a fingerprint, so that equivalent experiments can be identified.
37. As an evaluation investigator, I want any material shared or component setting to change the fingerprint, so that unlike runs are not conflated.
38. As a metric author, I want each Evaluation Metric Definition to have repository-wide identity and immutable semantic content, so that a metric means the same thing wherever it appears.
39. As a metric author, I want value type, structured schema, semantic description, and comparison operation covered by a content hash, so that semantic changes are detectable.
40. As an Evaluation Suite maintainer, I want Suites to remain self-contained by embedding exact Metric Definitions, so that a Suite can be serialized and reviewed without a runtime registry.
41. As a persistence maintainer, I want embedded Metric Definitions normalized into canonical ledger records, so that identical definitions are stored once.
42. As a persistence maintainer, I want identical metric imports to be idempotent, so that multiple Suites can reuse one definition safely.
43. As a persistence maintainer, I want conflicting content for an existing metric identity rejected, so that semantic collisions cannot enter the ledger.
44. As an evaluator author, I want a type-agnostic evaluator to reuse one Metric Definition across Task Contracts, so that task type alone does not create meaningless metric revisions.
45. As an evaluator author, I want a new Metric Definition revision when observation meaning, value schema, or comparison semantics change, so that comparisons remain trustworthy.
46. As an Evaluation Suite maintainer, I want adopting a new metric revision to require a new Suite revision, so that historical Suite behavior remains reproducible.
47. As an Evaluation Suite maintainer, I want Configured Evaluator metric references resolved only against exact definitions declared by the Suite, so that undeclared observations cannot masquerade as supported metrics.
48. As an evaluation investigator, I want every Case Metric Observation owned by its Case Evaluator Execution, so that its producer provenance is exact.
49. As an evaluation investigator, I want every Run Metric Observation owned by its Report Evaluator Execution, so that its producer provenance is exact.
50. As a database user, I want an observation's Case Result or Run derived through its producer, so that duplicated ownership cannot disagree.
51. As a database user, I want separate case- and run-observation tables, so that relational structure preserves subject type.
52. As a database user, I want indexed case, run, and cross-run metric queries through producer relationships, so that normalized provenance remains practical to query.
53. As a persistence maintainer, I want cross-case and cross-run misattribution to be structurally impossible, so that application bugs cannot corrupt provenance.
54. As an evaluation investigator, I want observation identities resolved to canonical Metric Definitions, so that queried values retain exact semantics.
55. As an evaluation runtime maintainer, I want one Evaluation Ledger facade, so that persistence remains a cohesive capability rather than a collection of database objects.
56. As a persistence maintainer, I want one shared SQLite connection and transaction owner, so that cross-capability invariants remain atomic.
57. As a persistence maintainer, I want authored-definition import isolated in an Authored Definition Catalog, so that definition changes do not expand execution lifecycle code.
58. As a persistence maintainer, I want run and checkpoint persistence isolated in an Evaluation Execution Store, so that lifecycle changes have one focused home.
59. As a persistence maintainer, I want artifact identity and provenance isolated in an Evaluation Artifact Catalog, so that artifact policy can evolve independently.
60. As a persistence maintainer, I want schema installation separated from domain stores, so that bootstrapping does not dominate persistence APIs.
61. As an evaluation runner, I want to depend on the Evaluation Ledger abstraction rather than SQLite, so that orchestration does not absorb storage details.
62. As a persistence maintainer, I want the facade to coordinate transactions spanning internal stores, so that decomposition does not weaken run creation or checkpoints.
63. As a project maintainer, I want one clean schema cutover with no migration or compatibility shim, so that prototype constraints do not burden the final model.
64. As an evaluation operator, I want Evaluation Finalization to request rather than dictate completion, so that a stale caller cannot bypass durable invariants.
65. As an evaluation operator, I want completion rejected while any manifested case lacks terminal task evidence, so that absent work is never reported as complete.
66. As an evaluation operator, I want completion rejected while any planned Case Evaluator application lacks terminal evidence, so that required judgments cannot silently disappear.
67. As an evaluation operator, I want completion rejected before the exact aggregate report artifact is frozen and linked, so that report evaluation has an immutable input.
68. As an evaluation operator, I want completion rejected while any expected Report Evaluator lacks terminal evidence, so that finalization accounts for all planned work.
69. As an evaluation operator, I want failed Task and Evaluator executions to count as terminal evidence, so that completion describes workflow accounting rather than quality.
70. As an evaluation operator, I want missing metrics, quality issues, and release-gate failures reported independently, so that they do not falsely make a fully accounted workflow incomplete.
71. As a persistence maintainer, I want the completion check and status transition in one transaction, so that competing or stale finalizers cannot race the invariant.
72. As an evaluation operator, I want repeated completion requests to be safe, so that explicit finalization is idempotent.
73. As a CI maintainer, I want all shared-contract scenarios deterministic and offline, so that pull requests do not depend on live providers.
74. As a CI maintainer, I want in-memory and durable evaluation to consume the same engine seam, so that test doubles exercise production orchestration.
75. As a CI maintainer, I want temporary real SQLite ledgers in durable tests, so that foreign keys, transactions, and query behavior are genuinely verified.
76. As a future component author, I want one typed path from Gold Set and Suite authoring through Task Binding, execution, checkpointing, metrics, and finalization, so that new model-backed components inherit trustworthy behavior.

## Implementation Decisions

- Preserve one shared evaluation engine that consumes a frozen Resolved Evaluation Plan and builds one bounded-concurrency, multi-case Pydantic Evals Dataset for both in-memory and durable execution.
- Use a no-op checkpoint sink for in-memory execution and a ledger-backed checkpoint sink for durable execution. Task Bindings and evaluators never own persistence.
- Bind every Evaluation Gold Set version to one exact Evaluation Task Contract. Include that contract in authored semantic content and require every member's input, expected-output, and metadata schema identity, revision, and fingerprint to match.
- Validate Gold Set membership when authored and when exact Case references are resolved during import. Compare Gold Set and Suite contracts once before selection, then revalidate Manifest cases as defense in depth.
- Permit subset compatibility differences only for splits, tags, and Evaluation Requirement coverage. Selection cannot make a schema-incompatible Gold Set valid.
- Model legitimate heterogeneous inputs, outputs, or metadata as explicit variants inside the shared Pydantic schemas. Do not allow multiple Task Contracts in one Gold Set or Suite.
- Introduce an Evaluation Task Binding as the runtime association among one component operation, its input/output/metadata Pydantic models, and one exact Evaluation Task Contract.
- Keep Python model classes and executable callables in the runtime Task Binding, not in serialized authored definitions and not in a global model registry.
- Make the Task Binding the sole per-invocation output-validation boundary. The shared engine trusts its typed success or provider-neutral failure and does not repeat validation.
- Represent output contract violations as terminal, non-retryable `output_validation` Task Failures for the current attempt. Skip case evaluators that require a successful typed output while retaining the failed case for report evaluation.
- Make the Task Binding produce the complete Evaluation Task Outcome envelope, including output-artifact or failure-artifact references. The Binding describes evidence but never registers artifacts or writes to the ledger.
- Preserve atomic checkpoint ownership in the engine's checkpoint sink. A case checkpoint persists the Task Outcome, Case Evaluator Executions, Metric Observations, issues, and artifact links together.
- Consolidate synchronous and asynchronous evaluator timing, success/failure normalization, and call recording behind shared logic while retaining separate thin call and await operations.
- Replace arbitrary component-configuration mappings with a schema-identified Validated Component Configuration derived from the component's Pydantic configuration model.
- Keep provider, model, model parameters, execution mode, random seed, and bounded case concurrency as normalized shared Run Configuration fields. Avoid the overloaded `model_settings` and component-options vocabulary.
- Canonically serialize a secret-free effective Run Configuration and fingerprint only material non-secret content. Case concurrency defaults to one and must be positive.
- Make every Evaluation Metric Definition an immutable repository-wide authored definition with identity `(namespaced name, evaluator revision)` and a canonical content hash.
- Keep authored Evaluation Suites self-contained by embedding their exact Metric Definitions. Configured Evaluators reference only definitions declared by the Suite.
- During Suite import, normalize embedded Metric Definitions into canonical ledger records and store exact Suite-to-metric relationships. Identical imports are idempotent; conflicting content for one identity is rejected.
- Allow one Metric Definition to be reused across Task Contracts when observation value schema, semantic meaning, and comparison operation are identical. A semantic change requires a new Metric Definition revision and a new revision of each adopting Suite.
- Make evaluator execution the sole relational owner of an Evaluation Metric Observation. Derive a Case Observation's Case Result and Run through its Case Evaluator Execution, and derive a Run Observation's Run through its Report Evaluator Execution.
- Preserve separate case- and run-observation tables and index producer relationships for subject and cross-run queries. Do not store a second independently writable subject owner.
- Retain one Evaluation Ledger facade and one SQLite connection/transaction owner. The evaluation runtime depends on the ledger abstraction rather than the SQLite implementation.
- Delegate immutable definition graphs and references to an Authored Definition Catalog; Runs, plans, manifests, checkpoints, transitions, and execution queries to an Evaluation Execution Store; and artifact identity, locations, derivatives, links, traversal, and provenance to an Evaluation Artifact Catalog.
- Separate clean schema installation from the three domain persistence capabilities. Provide no migration or backwards-compatibility path for the prototype schema because no production evaluation data exists.
- Coordinate cross-capability transactions at the ledger facade so definition import, run creation, case checkpoints, report checkpoints, artifact links, and guarded completion retain atomic invariants.
- Permit Evaluation Finalization to request completion only after the aggregate report is frozen. The ledger authorizes completion transactionally after proving every manifested case and every planned case/report evaluator application has terminal evidence.
- Count successful and failed task or evaluator executions as terminal workflow evidence. Keep missing metrics, quality issues, and release-gate outcomes independent from Evaluation Run completion.
- Preserve explicit finalization and its execution lease. Do not introduce implicit background finalization or resume incomplete case execution within the original Run.
- Treat the unrelated `handoff` skill-lock change as outside this specification.

## Testing Decisions

- Use one primary behavioral seam: the public shared evaluation engine entry point. Each scenario supplies an authored Gold Set, Suite, Metric Definitions, validated Task Binding, and Run Configuration, resolves and executes the evaluation, then reads either the returned in-memory report or complete durable Evaluation Run aggregate.
- Exercise the same engine with a no-op checkpoint sink and a ledger-backed checkpoint sink. Assert equivalent selected populations, evaluator assignments, task outcomes, observations, issues, and aggregate semantics.
- Use temporary real SQLite Evaluation Ledgers for durable scenarios. Verify behavior through the Evaluation Ledger facade rather than internal stores or raw SQL.
- Prefer highest-level contract tests that validate observable behavior and durable invariants. Do not assert internal repository arrangement, private helper calls, callback ordering, or individual SQL statements.
- Add preflight scenarios for Gold Set membership mismatches, imported Case-reference mismatches, Suite-to-Gold-Set contract mismatches, explicit schema variants, full populations, and subsets.
- Add Task Binding scenarios for synchronous success, asynchronous success, output validation failure, normalized component failure, success artifacts, and failure artifacts.
- Add evaluator-adapter scenarios proving sync and async invocation use shared timing and evidence semantics without double execution or double validation.
- Add Run Configuration scenarios for typed component configuration, canonical round trip, schema identity, secret removal, material fingerprint changes, and bounded-concurrency defaults and rejection.
- Add Metric Definition scenarios using two Suites: identical reuse must normalize to one record, while the same identity with different semantic content must reject import.
- Add producer-owned observation scenarios that persist and query case metrics, run metrics, and comparable metrics across runs. Prove cross-case and cross-run attribution cannot be represented.
- Add checkpoint atomicity scenarios that fail after selected writes and verify no partial Task Outcome, Evaluator Execution, Observation, issue, or artifact-link evidence remains.
- Add completion scenarios for pending cases, missing Case Evaluator executions, missing aggregate report artifacts, missing Report Evaluator executions, terminal task/evaluator failures, missing metrics, failed gates, repeated finalization, and successful completion.
- Add one complete-run tracer test that imports the authored definition graph, creates the frozen run, executes and checkpoints evidence, finalizes it, and queries the complete aggregate and artifact provenance through the decomposed ledger facade.
- Keep all shared-contract tests deterministic and offline. Live provider quality tests remain component-specific.
- Use the existing evaluation definition, ledger, and run lifecycle contract tests as prior art, extending their public seams instead of creating parallel test-only orchestration.
- Do not add migration tests for the prototype schema. Every persistence test begins with a fresh ledger using the clean schema.

## Out of Scope

- Migrating or preserving prototype evaluation ledger files.
- Providing backwards-compatible aliases, schema shims, or dual-write behavior for the previous evaluation contracts.
- Allowing one Evaluation Gold Set or Evaluation Suite to contain multiple unrelated Task Contracts.
- Inferring compatibility between structurally similar but differently identified or revisioned schemas.
- Serializing Python model classes or executable component callables into authored definitions.
- Introducing a global runtime model registry or universal evaluator registry.
- Making Task Bindings, evaluators, or component operations responsible for persistence.
- Persisting large artifact bodies directly in relational rows.
- Changing component-specific rubrics, evaluator implementations, Gold Set examples, or quality thresholds.
- Changing the semantics of Evaluation Requirements or Suite-owned Requirement Bindings beyond preserving schema-homogeneous Gold Sets.
- Treating task failure, evaluator failure, missing metrics, or gate failure as equivalent to incomplete workflow evidence.
- Automatically retrying an output-contract violation within the same immutable Evaluation Run attempt.
- Resuming incomplete case execution within an existing Evaluation Run.
- Adding implicit background workers for Evaluation Finalization.
- Building an evaluation authoring UI, artifact browser, or operations dashboard.
- Live-provider quality evaluation as part of shared-contract CI.
- The unrelated `handoff` skill-lock change.

## Further Notes

- This specification hardens and refines the earlier Shared Evaluation Contract and Case Evaluation Requirements work. Where wording conflicts, the accepted architectural decisions in [ADR 0005](../../../docs/adr/0005-resolve-case-evaluation-requirements-before-execution.md), [ADR 0006](../../../docs/adr/0006-bind-evaluation-gold-sets-to-one-task-contract.md), [ADR 0007](../../../docs/adr/0007-validate-task-outcomes-at-the-task-binding.md), [ADR 0008](../../../docs/adr/0008-reuse-repository-wide-metric-definitions.md), [ADR 0009](../../../docs/adr/0009-derive-metric-observation-subjects-from-producers.md), and [ADR 0010](../../../docs/adr/0010-keep-one-evaluation-ledger-transaction-facade.md) govern this hardening pass.
- Implementation is divided into seven ready-for-agent tracer bullets: [decomposed ledger](issues/01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md), [contract-homogeneous Gold Sets](issues/02-bind-every-evaluation-gold-set-to-one-task-contract.md), [typed Run Configuration](issues/03-freeze-typed-component-configuration-in-evaluation-runs.md), [canonical Metric Definitions](issues/04-canonicalize-metric-definitions-across-suites.md), [producer-owned observations](issues/05-query-metric-observations-through-producer-ownership.md), [validated Task Bindings](issues/06-invoke-sync-and-async-tasks-through-validated-task-bindings.md), and [guarded completion](issues/07-reject-premature-evaluation-run-completion.md).
- Existing case-evaluation issues continue to own Resolved Evaluation Plans, atomic run creation, the shared multi-case engine, durable checkpoints, retries, bounded concurrency, aggregate report freezing, and finalizer leasing. Their blocking edges now include the relevant hardening prerequisites.
- The full Gold Set is contract-homogeneous, but Suite support for case-specific Evaluation Requirements may still vary by selected population. Requirement incompatibility in an unselected case does not block a subset; task-schema incompatibility invalidates the Gold Set itself.
- Repository-wide Metric Definition identity does not require one metric per task type. A type-agnostic evaluator can reuse a definition wherever the observation semantics are genuinely identical.
