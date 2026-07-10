# Shared Evaluation Contract and Record Model

Status: ready-for-agent
Labels: ready-for-agent
Source: [Define the shared evaluation contract and record model](../model-evaluation-wayfinder/issues/02-define-shared-evaluation-contract.md)

## Problem Statement

Model-backed components currently lack a shared, durable contract for authored evaluation definitions, execution attempts, case outcomes, evaluator activity, metrics, artifacts, and relational persistence. Without that contract, each component can represent cases, failures, scores, configuration, and provenance differently, making regressions difficult to compare, incomplete runs easy to misread, and evaluation evidence hard to query or reproduce.

The project needs one provider-neutral evaluation foundation that works with `pydantic-evals`, Pydantic AI, Logfire, CI artifacts, and a relational evaluation store while still allowing each component to use typed inputs, outputs, metadata, metric values, rubrics, and scoring logic appropriate to its task.

## Solution

Create shared Pydantic contracts and a relational execution ledger for repository-wide evaluation.

Authored Evaluation Cases, Evaluation Gold Sets, Evaluation Suites, Evaluation Rubrics, and Evaluation Metric Definitions remain authoritative in version-controlled files or code. Before execution, the evaluation runtime validates and imports immutable identity, revision, content hash, schema identity, and queryable metadata for every referenced definition.

An Evaluation Run freezes the exact Evaluation Suite revision, Evaluation Gold Set version, Evaluation Case Manifest, and secret-free Evaluation Run Configuration before case execution begins. It records every manifested case, typed task outcome, Case Evaluator Execution, Report Evaluator Execution, Evaluation Metric Observation, and Evaluation Artifact incrementally so partial evidence survives failures.

The runtime uses `pydantic-evals` for case and report evaluation, a provider-neutral component task protocol for model-backed execution, the existing Logfire instrumentation for traces, relational persistence for durable queryable records, and content-addressed external storage for large or sensitive artifacts.

## User Stories

1. As an evaluation author, I want every Evaluation Case to have a stable identity and immutable revisions, so that corrected or relabeled cases do not rewrite historical evidence.
2. As an evaluation author, I want changes to case input, expected output, rubric, or authoritative artifacts to create a new case revision, so that semantic changes remain reproducible.
3. As an evaluation author, I want Evaluation Gold Set versions to reference exact case revisions, so that each run can reconstruct the examples it evaluated.
4. As an evaluation author, I want Gold Set membership to own split assignment, so that a stable case can move between training, calibration, and held-out test splits without losing its identity.
5. As an evaluation author, I want Evaluation Cases to use component-specific Pydantic models for input, expected output, and metadata, so that task-specific data remains strongly typed.
6. As an evaluation author, I want case evaluator configuration excluded from Evaluation Cases, so that cases in one suite cannot silently use inconsistent scoring implementations.
7. As an evaluation author, I want case-specific criteria represented as typed metadata or an exact Evaluation Rubric revision, so that special cases remain data rather than executable configuration.
8. As an evaluation author, I want large or sensitive case material represented by Evaluation Artifact links, so that relational tables do not become an uncontrolled raw-content store.
9. As an evaluation maintainer, I want each Evaluation Suite to be immutable and revisioned, so that task and evaluator behavior can be reproduced across runs.
10. As an evaluation maintainer, I want an Evaluation Suite to bind a typed task contract, compatible case schemas, serialized case evaluators, at least one serialized report evaluator, and metric semantics, so that each suite is complete and executable.
11. As an evaluation maintainer, I want provider and model selection excluded from the Evaluation Suite, so that identical cases and evaluators can compare different model configurations.
12. As an evaluation maintainer, I want evaluator configurations owned by the Evaluation Suite revision rather than a universal evaluator registry, so that deterministic configuration changes do not require standalone evaluator records.
13. As an evaluation maintainer, I want configured evaluators to have suite-local names and configuration fingerprints, so that executions retain exact provenance without a separate evaluator lifecycle.
14. As an LLM-judge author, I want Evaluation Rubrics to be human-authored, immutable, and revisioned, so that I can iterate on criteria and assertions without losing prior judging semantics.
15. As an LLM-judge author, I want Suite evaluator configurations to reference exact Evaluation Rubric revisions, so that judge results can be reproduced.
16. As an evaluation maintainer, I want a rubric semantic change to require a new relevant Metric Definition revision, so that scores with different meanings are never silently compared.
17. As an evaluation runner, I want exact versioned schema identities and fingerprints for case input, expected output, metadata, and task output, so that incompatible Suites and Gold Sets are rejected before execution.
18. As an evaluation runner, I want compatibility to require exact schema identity and revision initially, so that structural guesses cannot corrupt a run.
19. As an evaluation runner, I want a run to freeze an explicit Evaluation Case Manifest, so that aggregate metrics have an exact population and denominator.
20. As an evaluation runner, I want subset execution with recorded selection provenance, so that pull-request suites can run targeted cases without pretending they ran the full Gold Set.
21. As an evaluation runner, I want the resolved manifest rather than the selection expression to be authoritative, so that tag, path, or sampling changes cannot alter historical membership.
22. As an evaluation runner, I want every manifested case to receive exactly one Evaluation Case Result envelope, so that absent results are distinguishable from unselected cases.
23. As an evaluation runner, I want each Evaluation Run to represent one immutable execution attempt, so that retries never overwrite earlier evidence.
24. As an evaluation runner, I want retries linked to prior runs, so that transient failures and repeated attempts can be analyzed.
25. As an evaluation runner, I want an Evaluation Run Configuration to contain a canonical, secret-free effective configuration snapshot and content fingerprint, so that materially equivalent runs can be identified.
26. As a component maintainer, I want the Validated Component Configuration represented by the component's Pydantic configuration model, so that the recorded configuration matches what constructed the evaluated component.
27. As a security-conscious maintainer, I want credentials removed before configuration serialization and fingerprinting, so that secrets are neither persisted nor treated as meaningful experimental differences.
28. As an evaluation runner, I want provider/model identity, model parameters, execution mode, and random seed normalized in shared configuration fields, so that common run dimensions are queryable.
29. As an evaluation runner, I want prompts and other large or sensitive configuration material referenced as Evaluation Artifacts, so that configuration remains safe and compact.
30. As an evaluation runner, I want task outcomes represented as a typed success-or-failure union, so that task failure is data rather than an unrecorded exception.
31. As an evaluation runner, I want successful task outcomes to preserve typed component output and output artifacts, so that evaluators and investigators can use exact results.
32. As an evaluation runner, I want failed task outcomes to preserve a provider-neutral category, exception type, safe message, retryability, and failure artifacts, so that failures can be analyzed without coupling to a provider SDK.
33. As an evaluation runner, I want task failures to remain separate from evaluator failures, so that scoring infrastructure does not misrepresent component behavior.
34. As an evaluation runner, I want execution disposition, task outcome, and evaluator outcomes modeled separately in an Evaluation Case Result, so that partial evidence is retained.
35. As an evaluation runner, I want one Case Evaluator Execution for each actual application of a configured case evaluator, so that evaluator failures are visible even when no metric is emitted.
36. As an evaluation runner, I want every Evaluation Suite to configure at least one report evaluator, so that all run-level analyses have explicit execution provenance.
37. As an evaluation runner, I want Report Evaluator Executions to run after case evaluation and receive the complete manifest and all corresponding results, so that task failures and exclusions cannot silently disappear.
38. As a metric author, I want report evaluators to declare how failed, skipped, or cancelled cases affect each calculation, so that denominators and exclusions are explicit.
39. As a metric author, I want ordinary deterministic aggregation implemented as a report evaluator, so that run-level observations do not require a second derivation model.
40. As an evaluation investigator, I want Case Evaluator Executions and Report Evaluator Executions to record terminal success or failure, duration, and failure evidence, so that missing observations are explainable.
41. As an evaluation investigator, I want case-level observations linked to their Case Evaluator Execution, so that each score has exact producer provenance.
42. As an evaluation investigator, I want run-level observations linked to their Report Evaluator Execution, so that each aggregate or report analysis has exact producer provenance.
43. As a metric author, I want an Evaluation Metric Definition to contain a namespaced name, evaluator revision, value type, comparison operation, and semantic description, so that metric meaning is explicit.
44. As a metric author, I want `(namespaced name, evaluator revision)` to define metric identity, so that unrelated metrics do not collide and semantic changes create new identities.
45. As a metric author, I want value types to support number, integer, boolean, string, and evaluator-owned structured Pydantic values, so that simple metrics and rich report analyses share one contract.
46. As a metric author, I want structured metric values validated against an exact schema revision, so that arbitrary JSON cannot bypass the contract.
47. As a metric author, I want comparison represented by a versioned operation rather than only a direction, so that structured values can define meaningful comparisons.
48. As a metric author, I want comparison operations to return better, equivalent, worse, or incomparable, so that scalar and custom comparisons share a common result.
49. As a metric author, I want shared ordered comparisons for scalar values and evaluator-owned custom comparisons for structured values, so that common cases remain simple without excluding task-specific analysis.
50. As a release owner, I want release thresholds and tolerated regression margins kept outside Metric Definitions, so that gates can be calibrated from baseline runs without changing metric meaning.
51. As a database user, I want scalar observation values stored in typed relational columns, so that numeric, integer, boolean, and string metrics are directly queryable and sortable.
52. As a database user, I want structured observation values stored as validated JSON in a dedicated nullable column, so that rich analyses do not require a schema migration per shape.
53. As a database user, I want each observation row constrained to exactly one populated value column, so that its persisted representation is unambiguous.
54. As an evaluation investigator, I want Evaluation Artifacts identified by content hash rather than location, so that expiring CI URLs or moved files do not alter historical identity.
55. As an evaluation investigator, I want artifact kind, media type, byte size, retention class, and sensitivity/redaction classification recorded, so that artifacts can be handled safely.
56. As an evaluation investigator, I want Evaluation Artifacts to have multiple replaceable locations, so that content can move between local, CI, and long-term storage.
57. As a privacy-conscious maintainer, I want redacted bytes to create a distinct artifact linked to their source, so that redaction never silently replaces historical content.
58. As an evaluation investigator, I want artifacts linked to the smallest responsible producer, so that task output, evaluator rationale, report analysis, and failure evidence retain exact provenance.
59. As an evaluation investigator, I want separate produced-artifact and consumed-artifact queries for a run, so that inputs and rubrics are not confused with generated evidence.
60. As an evaluation investigator, I want one query to retrieve all artifacts produced across a run through its case results and evaluator executions, so that distributed ownership does not impede investigation.
61. As a persistence maintainer, I want application-generated UUIDv7 identifiers, so that local and CI records can be imported or merged without database-local ID allocation.
62. As a persistence maintainer, I want explicit unique business identities and revisions alongside opaque IDs, so that foreign keys stay compact while domain meaning remains enforced.
63. As a persistence maintainer, I want one immutable row per authored definition revision, so that empty stable-identity tables and unnecessary joins are avoided.
64. As a persistence maintainer, I want content hashes to prevent reuse of one business revision for different authored bytes, so that revision identities remain trustworthy.
65. As a persistence maintainer, I want separate case- and run-observation tables, so that ordinary foreign keys enforce each observation's subject type.
66. As a persistence maintainer, I want subject-specific artifact link tables with extensible namespaced roles, so that artifact ownership remains enforceable without polymorphic foreign keys.
67. As a persistence maintainer, I want the relational store to index authored identities and hashes but remain authoritative only for execution history and artifact locations, so that SQLite does not become an evaluation authoring system.
68. As a persistence maintainer, I want the run, manifest, and pending case-result envelopes created atomically, so that a run never exists with an ambiguous intended population.
69. As a persistence maintainer, I want each completed case and evaluator producer persisted atomically, so that a crash cannot leave half-written outcomes.
70. As a persistence maintainer, I want evidence committed incrementally rather than in one run-wide transaction, so that partial results survive process failure.
71. As an evaluation operator, I want `COMPLETED` to mean the workflow reached terminal outcomes, so that execution status is not confused with task quality or release policy.
72. As an evaluation operator, I want `FAILED` reserved for run-level orchestration or infrastructure that prevented complete terminal outcomes, so that case failures do not falsely describe the whole run as missing.
73. As an evaluation operator, I want task failures, evaluator failures, missing required metrics, and gate failures reported independently, so that each problem has a precise remediation path.
74. As an evaluation operator, I want cancelled runs and partial report evaluation retained, so that deliberate stops do not erase completed evidence.
75. As a CI owner, I want deterministic task and evaluator doubles to execute through the same coordinator and persistence seam as real suites, so that pull-request tests remain offline and provider-independent.
76. As a future component author, I want to implement only typed component contracts, suite configuration, Gold Set data, and task-specific evaluators, so that new model-backed components inherit the same provenance and persistence behavior.

## Implementation Decisions

- Use `pydantic-evals` `Dataset` and `Case` execution as the runtime case/report evaluation engine. A provider-neutral task callable delegates model-backed work to the component's injected Pydantic AI adapter.
- Keep authored Evaluation Case revisions, Evaluation Gold Set versions, Evaluation Suite revisions, Evaluation Rubric revisions, and Evaluation Metric Definitions authoritative in version-controlled files or code.
- Import immutable authored-definition identity, revision, content hash, schema references, and queryable metadata into the relational store before a run. Reject an existing business identity whose stored content hash differs.
- Represent every persisted entity with an application-generated UUIDv7. Preserve explicit unique business identities for immutable revisions.
- Store each immutable definition revision in one row rather than introducing separate unversioned identity tables.
- An Evaluation Case revision contains stable case identity, revision, typed input, optional typed expected output, typed metadata, human-facing description/tags, and artifact links. It never contains evaluator configuration.
- An Evaluation Gold Set version owns exact case-revision membership and split assignment through a relational membership table.
- An Evaluation Suite revision contains the typed task contract, exact schema references, serialized case-evaluator configurations, at least one serialized report-evaluator configuration, declared Metric Definitions, and exact Evaluation Rubric references. Provider/model execution configuration is excluded.
- Evaluators are suite-owned configured implementations, not standalone persisted definitions. Each configured evaluator has a suite-local name and canonical configuration fingerprint.
- An Evaluation Rubric is an independently revisioned human-authored policy used by model-based evaluators. A rubric semantic change requires a new rubric revision and suite revision; revise affected Metric Definitions when metric meaning changes.
- Require exact schema identity and revision compatibility for case input, expected output, metadata, and task output. Reject incompatible Suite/Gold Set combinations before case execution.
- Create an Evaluation Run before work begins. Freeze its Suite revision, Gold Set version, Evaluation Run Configuration, code/config/model fingerprints, execution mode, retry relationship, and Evaluation Case Manifest.
- Allow full or subset runs. Persist the resolved case manifest as authoritative and selection criteria as provenance. Aggregate observations use this manifest as their population.
- Represent task outcome as a discriminated success/failure union. Normalize shared failures without persisting provider SDK objects.
- Create exactly one Evaluation Case Result per manifested case. Separate execution disposition, task outcome, and evaluator outcomes.
- Persist one Case Evaluator Execution for every actual application of a configured case evaluator. An execution may emit zero or more case Metric Observations and remains recorded when it fails.
- Invoke configured Report Evaluators after case evaluation. Every suite has at least one report evaluator, including when run-level analysis is a simple deterministic aggregation.
- Give every Report Evaluator the complete case manifest and corresponding case results. Each evaluator defines the treatment of unsuccessful outcomes and exposes exclusions/denominators in its observations where applicable.
- Persist one Report Evaluator Execution per invocation. It may emit zero or more run Metric Observations and remains recorded when it fails.
- An Evaluation Metric Definition consists of a namespaced name, evaluator revision, value type, versioned comparison operation, and semantic description. Its business identity is `(namespaced name, evaluator revision)`.
- Support number, integer, boolean, string, and structured Pydantic metric values. Structured values carry exact schema identity/revision and persist as validated JSON.
- A comparison operation is `none`, shared ordered comparison, or evaluator-owned custom comparison. It produces better, equivalent, worse, or incomparable. Release thresholds are separate gate configuration.
- Expose one shared Metric Observation Pydantic contract but persist case- and run-subject observations in separate tables for foreign-key integrity.
- Store observation values in nullable typed columns for number, integer, boolean, string, and structured JSON, with exactly-one-value constraints and adapter validation against the Metric Definition.
- Identify an Evaluation Artifact by content hash. Record kind, media type, size, retention class, and sensitivity/redaction classification separately from one or more replaceable Artifact Locations.
- Use subject-specific artifact link tables with extensible namespaced roles. Attach artifacts to their smallest responsible producer: authored definition revision, Evaluation Case Result, Case Evaluator Execution, Report Evaluator Execution, or Evaluation Run.
- Expose separate read models for artifacts consumed by a run and artifacts produced by a run. Produced-artifact traversal includes run artifacts, report evaluator artifacts, case-result artifacts, and case-evaluator artifacts.
- Use relational tables for: definition revision indexes; Gold Set membership; Runs; manifest entries; Case Results; Case and Report Evaluator Executions; case and run Metric Observations; Evaluation Artifacts; Artifact Locations; and subject-specific artifact links.
- Avoid generic polymorphic subject identifiers. Use separate subject-specific observation and artifact-link tables so relational foreign keys remain enforceable.
- Persist the run, frozen manifest, and pending result envelopes in one transaction. Persist each case producer and report evaluator producer atomically as it finishes. Finalize run status after expected records reach terminal outcomes.
- Define run lifecycle independently from quality. `COMPLETED` means the workflow reached complete terminal evidence; `FAILED` means run-level orchestration prevented that; `CANCELLED` means deliberately stopped. Individual task/evaluator/gate outcomes remain separate.
- Keep Logfire responsible for traces and model telemetry, with trace/span identities normalized into execution records where available. The relational record and serialized report remain authoritative for CI outcomes.
- Keep large or sensitive raw inputs, prompts, outputs, rationales, trace exports, and reports outside relational tables by default as content-addressed Evaluation Artifacts.

## Testing Decisions

- Prefer one highest-level contract seam: execute a typed Evaluation Suite through the provider-neutral task protocol using deterministic task/evaluator doubles and a real temporary SQLite evaluation store, then assert the complete persisted Evaluation Run aggregate and artifact read models.
- Test external behavior and durable invariants rather than private model methods or SQL statement structure.
- Add contract tests for authored-definition import, content-hash collision rejection, exact schema compatibility, manifest freezing, subset provenance, and secret-free configuration fingerprints.
- Add lifecycle tests for successful, task-failed, evaluator-failed, cancelled, orchestration-failed, partial, and retried runs. Verify `COMPLETED` remains independent from quality and gate success.
- Add persistence tests that terminate execution after selected producer commits and verify already committed evidence survives while the run remains incomplete.
- Add case-result tests proving task failure, case evaluator failure, and report evaluator failure remain distinguishable.
- Add report-evaluator tests proving every manifested case is visible, exclusions are explicit, and failed cases cannot silently improve aggregate metrics.
- Add Metric Definition and Observation tests for all scalar types, structured Pydantic values, exactly-one-value constraints, comparison operation dispatch, and incompatible metric revisions.
- Add relational-integrity tests for subject-specific observation tables, exact producer links, Gold Set memberships, manifest uniqueness, and retry relationships.
- Add artifact tests for content deduplication, multiple locations, redacted derivative identity, smallest-producer ownership, and complete consumed/produced run traversal.
- Add serialization round-trip tests for Evaluation Cases, Suites, Rubrics, Metric Definitions, Evaluation Run Configuration, and structured observation values.
- Use existing repository patterns as prior art: protocol-based pipeline tests with deterministic adapters, temporary real SQLite stores in database tests, Pydantic schema validation tests, and telemetry tests that disable remote export.
- Do not require live LLM providers for shared-contract tests. Component-specific release suites may separately test configured live providers.

## Out of Scope

- Implementing component-specific Relevance Filter, selector healing, Coreference Resolution, Entity Extraction, embedding, or GraphRAG metrics and quality floors.
- Creating or labeling the initial Relevance Filter Evaluation Gold Set.
- Calibrating release thresholds or tolerated regression margins before baseline runs exist.
- Defining a general evaluation authoring UI or making SQLite the authored-definition system of record.
- Persisting provider-specific SDK response or exception objects.
- Storing large or sensitive raw content directly in relational tables by default.
- Building a universal standalone evaluator registry.
- Inferring compatibility between structurally similar but differently versioned Pydantic schemas.
- Implementing cross-backend replication beyond using backend-neutral contracts and UUIDv7 identities.
- Defining CI workflow files, artifact retention durations, or long-term storage infrastructure beyond the shared contracts they must consume.

## Further Notes

- The validated runtime composition is documented in the predecessor wayfinder issue: `pydantic-evals` for execution/scoring, Pydantic AI for provider-neutral task execution, existing Logfire instrumentation for telemetry, relational persistence for durable metadata/outcomes, and external CI/file storage for artifacts.
- Pydantic report evaluators run after case evaluation and receive the full evaluation report. This specification deliberately requires every Evaluation Suite to configure at least one report evaluator so all run-level Metric Observations have explicit producer provenance.
- Direct run comparison should require equivalent Metric Definitions and compatible case manifests. Intersection- or stratum-based comparison must be explicit rather than silently comparing different populations.
- An ADR is not required for evaluator ownership: the Suite-owned evaluator decision is fully captured here and can be revisited without migrating an established standalone evaluator subsystem.

