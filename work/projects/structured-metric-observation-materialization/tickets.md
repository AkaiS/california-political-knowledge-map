# Tickets: Schema-Tagged Structured Metric Observations

These tickets implement the durable structured-metric contract described in [PRD.md](PRD.md): persist self-describing observations, expose their Metric Definition-owned schemas, and safely reconstruct evaluator-owned models.

Work the **frontier**: any ticket whose blockers are all done. The first two tickets can start immediately and independently; the third starts after both are complete.

## Persist schema-tagged structured Metric Observations

Labels: completed

**What to build:** Allow deterministic case and report evaluators to return concrete Pydantic models while the evaluation runner converts valid structured results into durable, schema-tagged object envelopes. Persist and fetch the complete envelope without reconstructing a runtime model, while preserving scalar observation behavior and the existing evaluator-failure path.

**Blocked by:** None — can start immediately.

- [x] A structured Metric Observation exposes its durable envelope as `structured_value`; the previous public storage-oriented field is removed without a compatibility alias.
- [x] The envelope contains the exact schema identity, revision, and fingerprint copied from the governing Metric Definition plus an object-shaped JSON payload.
- [x] Exactly one scalar field or structured-value field may be populated on an observation.
- [x] Case and report evaluator outputs are resolved to their exact Metric Definitions before the runner creates observations.
- [x] A concrete Pydantic result whose schema fingerprint differs from the Metric Definition is rejected through the existing evaluator-failure path and produces no invalid observation.
- [x] Structured payload roots must be objects with string keys; root arrays and primitive roots are rejected.
- [x] Nested payloads accept only strict JSON objects, arrays, strings, booleans, integers, finite floats, and null; arbitrary runtime containers, NaN, and infinities are rejected.
- [x] The full envelope round-trips through the existing structured JSON database column for both case-level and run-level observations.
- [x] Fetching returns the durable envelope unchanged and performs no schema resolution, imports, or model reconstruction.
- [x] Existing scalar observation columns, values, query behavior, and direct usability remain unchanged.
- [x] Invalid structured results continue to be recorded as evaluator failures and missing-metric diagnostics without changing Evaluation Run completion semantics.
- [x] Tests exercise the public runner-to-ledger round trip with deterministic evaluator-owned models and a temporary real SQLite ledger.

## Expose Metric Definition schemas through the Suite inventory

Labels: completed

**What to build:** Make every structured schema already owned by a Suite's Metric Definitions discoverable through the Suite's derived schema inventory. Preserve Metric Definitions as the single authored authority and keep concrete Python model types in the runtime allowlist rather than in serializable Suite records.

**Blocked by:** None — can start immediately.

- [x] The derived schema inventory includes the exact Schema Reference declared by every structured Metric Definition in the Suite.
- [x] Existing task input, output, and metadata Schema References remain present.
- [x] Scalar Metric Definitions add no schema references.
- [x] Repeated exact Schema References are deduplicated deterministically while stable inventory ordering is preserved.
- [x] The Suite gains no second authored field for metric schemas.
- [x] Authored and frozen Suite records contain schema references only and never executable Python model classes or import paths.
- [x] Runtime schema registration rejects a model whose schema fingerprint is incompatible with the registered Schema Reference.
- [x] Tests cover structured and scalar metrics, shared structured schemas, deterministic ordering, exact-reference deduplication, and preservation of task-contract schemas.

## Materialize fetched structured observations into evaluator-owned models

Labels: completed

**What to build:** Resolve each fetched structured observation through its singular Metric Definition and an allowlisted schema binding, then reconstruct the concrete evaluator-owned Pydantic model in an explicit persistence-free materialization step. Keep scalar observations directly usable and isolate materialization failures to the affected structured observation.

**Blocked by:** Persist schema-tagged structured Metric Observations; Expose Metric Definition schemas through the Suite inventory.

- [x] A resolved schema binding associates one expected Schema Reference with one allowlisted concrete Pydantic model type.
- [x] Before materialization, the runtime resolves the observation's metric identity through the frozen Suite and confirms that the definition's structured schema is registered.
- [x] The individual materializer accepts one fetched structured observation and one resolved schema binding and performs no persistence access.
- [x] The materializer rejects an envelope whose schema tag differs from the binding's expected reference.
- [x] The materializer validates the object payload with the bound concrete model and returns an instance of that evaluator-owned model.
- [x] An unknown registry entry, incompatible registered model, malformed payload, or schema-tag mismatch never falls back to an untyped dictionary.
- [x] Scalar observations bypass schema resolution and remain directly usable after fetch.
- [x] Structured observations are materialized independently so one failure does not invalidate unrelated scalar or structured observations.
- [x] The public durable evaluation flow proves successful reconstruction for deterministic case-level and report-level structured metrics after a real SQLite round trip.
- [x] Mixed-observation tests prove unaffected observations remain usable when one structured observation cannot be resolved or validated.
- [x] Missing observations remain diagnostics and do not prevent report production or Evaluation Run completion.
- [x] Evidence contract version remains 1, with no migration, legacy reader, compatibility alias, or previous-shape patching path.
- [x] Materialization remains limited to structured Metric Observations; arbitrary task-run attributes and other framework extension fields retain ordinary JSON round-trip behavior.
