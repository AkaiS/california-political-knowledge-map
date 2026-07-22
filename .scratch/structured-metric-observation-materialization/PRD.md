# Schema-Tagged Structured Metric Observations

Status: ready-for-agent
Labels: ready-for-agent

## Problem Statement

Evaluation Metric Definitions already declare exact schemas for evaluator-owned structured values, but durable Evaluation Metric Observations erase those concrete values into untagged JSON objects. After an observation is fetched, the runtime cannot prove which schema governed the persisted object or reconstruct the evaluator-owned Pydantic model safely. The observation contract exposes this data as arbitrary structured JSON, and the Suite's derived schema inventory omits schemas owned by its structured Metric Definitions.

This leaves scalar metrics trustworthy and directly usable while structured metrics lose the contract that gives their named fields meaning. It also permits a fetched dictionary to be mistaken for a materialized evaluator result even though no allowlisted runtime model has validated it.

## Solution

Represent every structured Evaluation Metric Observation with a schema-tagged value envelope. The envelope carries the exact Schema Reference owned by the applicable Evaluation Metric Definition and a strict JSON object payload. Evaluators continue to return concrete Pydantic models; the evaluation runner validates those models against their Metric Definitions and creates the envelopes before persistence.

Rename the structured observation field to describe its domain meaning rather than its database encoding. Persist the complete envelope in the existing structured JSON database column, and return that durable envelope unchanged when observations are fetched.

Materialization remains an explicit operation after fetching. A coordinator resolves each structured observation's exact Metric Definition, confirms that its schema is registered, associates the observation with a resolved binding containing the expected Schema Reference and concrete Pydantic model type, and passes that pair to a persistence-free materializer. The materializer verifies the persisted tag and validates the payload into the concrete evaluator-owned model.

Extend the Suite's derived schema inventory to include the schemas already owned by its structured Metric Definitions. The Metric Definition remains the single authoritative source; the inventory is a deterministic projection rather than a duplicate authored declaration.

## User Stories

1. As a metric author, I want a structured Metric Definition to remain the authority for its value schema, so that persisted observations cannot select their own contracts.
2. As an evaluator author, I want to return my concrete Pydantic result model, so that evaluator code remains independent of persistence envelopes.
3. As an evaluation runner, I want to resolve an evaluator output to its exact Metric Definition before persistence, so that metric identity determines the governing contract.
4. As an evaluation runner, I want to reject a structured evaluator value whose model schema fingerprint differs from the Metric Definition, so that incompatible values never become observations.
5. As an evaluation runner, I want to require structured values to serialize as JSON objects with named fields, so that each constituent value has explicit semantic meaning.
6. As a metric author, I want arrays to appear only beneath named fields, so that an unlabelled root collection cannot masquerade as a meaningful structured metric.
7. As a persistence maintainer, I want every structured observation to carry its exact schema identity, revision, and fingerprint, so that durable evidence is self-describing and verifiable.
8. As a persistence maintainer, I want the schema tag copied from the Metric Definition rather than supplied by evaluator output, so that untrusted values cannot choose a model type.
9. As a persistence maintainer, I want structured payloads restricted to strict JSON values, so that evidence remains portable across compliant serializers.
10. As a persistence maintainer, I want non-finite floating-point values rejected, so that NaN and infinities cannot enter supposedly canonical JSON evidence.
11. As a persistence maintainer, I want object keys to be strings, so that structured payloads have unambiguous JSON semantics.
12. As a database user, I want scalar observations to remain in their existing typed relational columns, so that they stay directly queryable and sortable.
13. As a database user, I want structured envelopes stored in the existing dedicated JSON column, so that rich metric shapes do not require a relational schema migration per evaluator.
14. As an evaluation investigator, I want fetched structured observations to remain durable envelopes until explicitly materialized, so that a dictionary is never confused with a concrete evaluator-owned value.
15. As an evaluation investigator, I want fetched scalar observations to remain immediately usable, so that serializable values do not require unnecessary reconstruction.
16. As an evaluation investigator, I want the public observation field to describe a structured value rather than a storage encoding, so that the domain API communicates its contract.
17. As an Evaluation Suite maintainer, I want the Suite's schema inventory to include schemas owned by its structured Metric Definitions, so that all required runtime contracts are discoverable before materialization.
18. As an Evaluation Suite maintainer, I want that inventory derived from existing Metric Definitions, so that the Suite does not gain a second independently maintained schema list.
19. As an Evaluation Suite maintainer, I want repeated schema references deduplicated deterministically, so that equivalent Suites retain stable persisted representations.
20. As a runtime maintainer, I want schema references kept separate from executable Python model classes, so that authored Suites remain serializable and provider-neutral.
21. As a security-conscious maintainer, I want concrete models resolved only through an explicit allowlisted registry, so that persisted evidence cannot trigger arbitrary Python imports.
22. As a runtime maintainer, I want schema resolution completed before individual materialization calls, so that each materializer receives one exact expected contract.
23. As a runtime maintainer, I want a resolved schema binding to contain both the Schema Reference and concrete model type, so that tag verification and model reconstruction use the same association.
24. As an evaluation investigator, I want materialization to reject an envelope whose tag differs from the resolved schema, so that mismatched evidence never falls back to an untyped dictionary.
25. As an evaluation investigator, I want materialization to reject a payload that fails concrete model validation, so that a correct tag cannot conceal malformed data.
26. As an evaluation investigator, I want each structured observation materialized independently, so that one unresolved schema does not invalidate unrelated observations.
27. As an evaluation operator, I want missing Metric Observations to remain diagnostics, so that quality evidence does not become confused with workflow completion evidence.
28. As an evaluation operator, I want failed structured-value validation recorded through the existing evaluator-failure path, so that the rest of the Evaluation Run can retain its terminal evidence.
29. As a runtime maintainer, I want metric-observation writes to remain internal to the evaluation runner, so that the ledger does not repeat semantic Metric Definition resolution on every insert.
30. As a runtime maintainer, I want fetching to remain a storage operation and materialization to remain a runtime reconstruction operation, so that durable and executable representations have clear boundaries.
31. As a project maintainer, I want this contract treated as greenfield evidence-contract version 1, so that disposable prototype formats do not create migration machinery.
32. As a project maintainer, I want concrete type preservation limited to known structured metric locations, so that arbitrary framework extension fields do not require a recursive serialization system.
33. As a CI maintainer, I want the full structured-observation round trip tested offline with deterministic evaluator models, so that contract regressions are caught without live providers.

## Implementation Decisions

- Introduce an immutable schema-tagged structured metric value containing one exact Schema Reference and one strict JSON object payload.
- Define strict recursive JSON values as objects, arrays, strings, booleans, integers, finite floats, and null. Require the envelope's root payload to be an object with string keys. Reject root arrays, primitive roots, arbitrary runtime containers, NaN, and infinities.
- Rename the Evaluation Metric Observation's structured field from a storage-oriented JSON name to `structured_value`. Retain the existing database column name as an internal storage detail.
- Keep the observation invariant that exactly one scalar field or the structured-value field is populated.
- Continue accepting raw concrete Pydantic models from evaluators. Evaluators do not construct envelopes and cannot supply schema tags.
- Keep semantic write validation in the evaluation runner. Resolve each evaluator output to its exact Metric Definition, validate the runtime model's JSON Schema fingerprint, require a strict object-shaped dump, and create the envelope using the definition's own structured schema.
- Preserve the existing runner behavior for invalid evaluator output: mark the evaluator execution failed, emit no invalid observation, and report the missing metric as a diagnostic.
- Treat metric-observation writes as runner-internal. The ledger validates the envelope's storage shape through the observation model but does not look up the frozen Suite and repeat Metric Definition validation at insertion time.
- Serialize and fetch the complete envelope through the existing structured JSON column. A fetch returns the schema-tagged durable representation and never imports or reconstructs a Python class.
- Extend the derived schema-reference inventory for an Evaluation Suite to include the structured schemas declared by its Metric Definitions. Preserve deterministic order and deduplicate exact references. Do not add a second authored schema field to the Suite.
- Add a resolved schema binding that contains the expected Schema Reference and the allowlisted concrete Pydantic model type.
- Have the runner or reconstruction coordinator iterate over fetched observations, resolve each singular metric reference through the frozen Suite, check that the definition's structured schema is registered, and associate the observation with its resolved schema binding.
- Keep the individual materializer persistence-free. It accepts one fetched structured observation and one resolved schema binding, verifies that the envelope tag equals the expected reference, validates the object payload with the concrete model type, and returns the concrete evaluator-owned model.
- Materialize structured observations independently. Scalars bypass schema resolution and remain directly usable after fetch. Missing schema registrations or invalid structured payloads fail only the affected materialization operation.
- Preserve the existing contract that missing metrics are diagnostics independent from Evaluation Run completion. Terminal evaluator evidence, not successful production of every declared metric, governs workflow completion.
- Keep `EVIDENCE_CONTRACT_VERSION` at 1. Add no migration, legacy reader, compatibility alias, or patching path for previously shaped structured observations.
- Do not introduce recursive schema tagging for arbitrary framework fields. Task-run attributes and other open-ended Pydantic Evals values retain the framework's ordinary JSON round-trip behavior.
- Record the broader separation of existing report-case fetch operations from pure materializers as deferred cleanup rather than expanding this feature.
- Update the domain glossary to state that structured Metric Definitions own exact object-shaped value schemas and that structured observations must conform to them.

## Testing Decisions

- Use the public durable evaluation flow as the primary behavioral seam: execute deterministic case and report evaluators through the evaluation runner, fetch observations through the Evaluation Ledger, resolve registered schemas, and materialize concrete structured values.
- Assert external contracts through returned Evaluation Run aggregates, fetched observations, Suite definition records, and materialized models. Avoid assertions about private helper calls or individual SQL statements.
- Extend the existing deterministic complete-run test that already produces scalar and structured case/report observations. Prove that scalar values remain unchanged while the structured observation round-trips as an envelope and materializes to its original concrete model.
- Use temporary real SQLite Evaluation Ledgers for persistence scenarios so JSON serialization, row mapping, and the unchanged structured column are exercised together.
- Add Metric Definition contract tests for raw concrete model acceptance, schema-fingerprint mismatch, object-root enforcement, strict nested JSON values, root-array rejection, primitive-root rejection, non-string keys, NaN, and infinities.
- Add Suite import tests proving that structured metric schemas appear in the derived schema inventory, scalar metrics add no schema, shared references are deterministically deduplicated, and task-contract schemas remain present.
- Add storage round-trip tests proving the full schema identity, revision, fingerprint, and object payload survive case-level and run-level observation persistence.
- Add materialization tests for successful concrete-model reconstruction, envelope-tag mismatch, unknown registry entries, incompatible registered model fingerprints, and payload validation failures.
- Add mixed-observation tests proving valid scalars and other structured observations remain usable when one structured observation cannot be materialized.
- Preserve and extend the existing missing-metric diagnostic test to prove missing observations still do not block report production or Evaluation Run completion.
- Keep all tests deterministic and offline; use evaluator-owned Pydantic doubles rather than live LLM judges.

## Out of Scope

- Recursive schema tagging or concrete-type reconstruction for task-run attributes, evaluator constructor arguments, experiment metadata, or other arbitrary framework extension fields.
- Changing Pydantic Evals' scalar ReportCase metrics, scores, labels, or assertions.
- Splitting the existing report-case materializers from the database fetches they currently perform.
- Requiring all declared metrics to be produced before freezing a report or completing an Evaluation Run.
- Treating missing metrics, failed evaluators, or failed release gates as incomplete workflow evidence.
- Moving Metric Definition validation into the Evaluation Ledger's insertion methods.
- Persisting Python import paths, dynamically importing model classes from evidence, or storing executable model types in authored Suites.
- Adding a universal runtime type serializer or recursively scanning arbitrary values for Pydantic models.
- Supporting root-list or scalar-root structured Metric Definitions.
- Changing comparison semantics, custom comparator resolution, release gates, or Metric Definition identity.
- Changing the relational observation-table layout or adding separate schema columns.
- Incrementing or dispatching on a new Evidence Contract Version.
- Migrating, rewriting, or reading any earlier prototype structured-observation shape.
- Creating a backwards-compatible alias for the previous public structured observation field.

## Further Notes

- This specification narrows the broader schema-tagged extensible-evidence concern to the locations whose contracts and semantics are explicitly known: structured Evaluation Metric Observations.
- Evaluation Metric Definitions remain repository-wide immutable definitions under the existing metric-identity decision. The schema envelope records and verifies that owned contract; it does not create a new schema authority.
- The Suite schema inventory contains Schema References only. Concrete Pydantic types remain runtime capabilities supplied by an allowlisted registry.
- Collections remain valid inside named structured fields, such as findings or table rows. Only an unlabelled collection at the root is prohibited.
- The deferred fetch/materializer separation should be handled as a later focused cleanup rather than folded into this change.

