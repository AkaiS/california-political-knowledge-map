# Reduce the case revision reference to identity and rebuild the evaluation database

Labels: completed

Part of the [Unified Evaluation Execution Path](../PRD.md). Breaking change to
persisted canonical JSON; no migration is written.

## What to build

An Evaluation Gold Set membership references an exact Evaluation Case revision by
identity and content hash alone. It stops carrying copies of the case's input,
expected-output, and metadata schemas.

Those copies are redundant. Per ADR 0006 a Gold Set binds exactly one Evaluation
Task Contract, so the contract already fixes the schemas for the whole
population; and gold-set import already re-derives the schemas from the stored
case record to check them. The copy is also the mechanism by which a missing
expected-output schema leaks into places that cannot represent its absence.

Everything that validated before still validates. Authoring a Gold Set with an
incompatible member fails immediately, decided by the shared compatibility
predicate against full Evaluation Case objects where the information to judge
actually exists. Gold-set import still rejects a reference whose underlying case
content changed, which is where forgery detection lives and which the slimming
does not touch.

Because this changes canonical JSON and content fingerprints for gold-set
memberships and Frozen Aggregate Manifests, the evaluation database is dropped
and recreated rather than migrated. `document_store.db` is not touched. The
evidence contract version stays at 1 — nothing has consumed this evidence in
production, so there is no compatibility break to signal.

## Acceptance criteria

- [x] The case revision reference carries only record identity, business identity, revision, and content hash.
- [x] Its input, expected-output, and metadata schema fields are removed, and the factory that derives a reference from a case no longer copies them.
- [x] Reconstruction of a reference from stored rows no longer reads or requires schema columns.
- [x] Authoring an Evaluation Gold Set whose member is incompatible with its Evaluation Task Contract still fails at construction.
- [x] Gold-set import still rejects a reference whose underlying Evaluation Case content changed.
- [x] Schema compatibility is decided where full Evaluation Case objects are available, via the shared predicate.
- [x] The evaluation database schema is regenerated; the database is dropped and recreated rather than migrated.
- [x] `document_store.db` is untouched by this change.
- [x] The evidence contract version remains 1.
- [x] Content-hash assertions on gold-set memberships and Frozen Aggregate Manifests are updated to their new values; the updates are recorded as expected consequences, not as behaviour changes.
- [x] The full deterministic test suite passes.

## Blocked by

- 01 — Decide Suite, Gold Set, and Case compatibility in one place.
