# Migrate the hand-built gold sets in the test suite to the factory

Labels: ready-for-agent

Part of [Evaluation Gold Set Construction and Revisioning](../PRD.md). This is where
the split machinery finally gets exercised by something other than its own tests.

## What to build

The seventeen Gold Sets assembled by hand across the test suite are built by the
factory instead. Today every one of them puts every case in `held-out` because
assigning splits by hand is tedious, which means the leakage guarantee the split
machinery exists to provide has never been exercised. After this ticket the
factory is exercised by the whole suite rather than by its own tests alone.

The construction sites live in `test_evaluation_runs.py`,
`test_evaluation_definitions.py`, `test_evaluation_preflight.py`,
`test_evaluation_requirements.py`, `test_evaluation_ledger.py`, and
`test_evaluation_task_bindings.py`, several of them behind module-local helpers
that many tests share. Migrating a helper migrates its callers with it.

Three sites deliberately construct an invalid Gold Set to prove the model's own
validators still bite — the mismatched-member rejection in the definitions tests,
the authoring rejection in the preflight tests, and the forged-contract import
rejection in the ledger tests. Those keep constructing directly, because routing
them through the factory would test the wrong seam.

Expect tests that silently assumed everything was `held-out` to need explicit
pinning. Pin them rather than reshaping the test around whatever the ratio
happens to produce.

## Acceptance criteria

- [ ] Every hand-built Gold Set in the test suite is constructed through the factory, except the sites that deliberately build an invalid Gold Set to exercise the model's own validators.
- [ ] The sites that deliberately build an invalid Gold Set still construct `EvaluationGoldSet` directly, and still assert the same rejection from the same seam.
- [ ] Module-local gold-set helpers construct through the factory, so their callers migrate with them.
- [ ] Tests that depend on a specific case being in a specific split pin that case explicitly rather than relying on the ratio.
- [ ] No test asserts on how a split was computed internally; assertions are on the resulting memberships.
- [ ] Content-hash and membership assertions are updated to their new values where migration changes them, and the updates are recorded as expected consequences rather than behaviour changes.
- [ ] The full deterministic test suite passes.

## Blocked by

- 01 — Construct an Evaluation Gold Set with a validating factory.
