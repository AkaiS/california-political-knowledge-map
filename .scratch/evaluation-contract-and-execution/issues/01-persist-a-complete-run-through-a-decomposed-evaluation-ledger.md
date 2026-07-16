# Persist a complete run through a decomposed Evaluation Ledger

Labels: ready-for-agent

## Parent

[Evaluation Contract and Resumable Execution](../PRD.md)

## What to build

Preserve the Evaluation Ledger as one persistence facade and transaction owner while routing a complete deterministic evaluation path through three focused internal capabilities: the Authored Definition Catalog, Evaluation Execution Store, and Evaluation Artifact Catalog. A caller must still be able to import the authored definition graph, create and checkpoint a run, attach evidence, and query the complete result through the existing cohesive ledger boundary.

Use one shared SQLite connection so operations spanning capabilities remain atomic. Install one clean evaluation schema through a separate schema-installation component; there is no production evaluation data to migrate and no backwards-compatibility shim is required.

## Acceptance criteria

- [ ] The public Evaluation Ledger remains the single persistence facade used by the evaluation runtime and owns one shared transaction boundary.
- [ ] Authored definition import and lookup are delegated to an Authored Definition Catalog.
- [ ] The Authored Definition Catalog can retrieve an exact imported Evaluation Suite by identity and revision and rejects a content-hash mismatch.
- [ ] Run creation, manifests, results, checkpoints, lifecycle transitions, and execution queries are delegated to an Evaluation Execution Store.
- [ ] Artifact identity, locations, derivatives, links, traversal, and provenance queries are delegated to an Evaluation Artifact Catalog.
- [ ] Schema installation is separated from the three domain persistence capabilities and creates only the clean current schema.
- [ ] A deterministic contract test imports a complete authored definition graph, creates a run, records case and report evidence with artifacts, and reads back the complete run aggregate through the facade.
- [ ] Run creation and producer checkpoints remain atomic when work crosses internal capability boundaries.
- [ ] The evaluation runtime depends on the Evaluation Ledger abstraction rather than the concrete SQLite implementation.
- [ ] Durable execution and finalization can resolve all authoritative authored inputs through the facade without accepting caller-provided mutable definitions.

## Blocked by

None - can start immediately.
