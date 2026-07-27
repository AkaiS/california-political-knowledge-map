# Report every preflight compatibility issue in one raise

Labels: completed

Closes inbox item EP-02's accumulation half for the
[Unified Evaluation Execution Path](../PRD.md).

## What to build

An author who runs preflight against a Gold Set with several problems — two cases
whose metadata schema does not match the Evaluation Task Contract, one case
declaring an Evaluation Requirement absent from the catalog — sees all of them,
once, and can fix them in a single pass. Today preflight surfaces the first
problem and hides the rest, so discovering five issues takes five runs.

Preflight accumulates every issue the shared compatibility predicate finds and,
if any exist, raises a single typed error carrying the whole collection. A caller
can catch that error and present every issue. The runner catches it before
creating an Evaluation Run, so the Evaluation Ledger does not accumulate runs
that never had a chance of executing.

## Acceptance criteria

- [x] Preflight collects every issue the compatibility predicate reports rather than stopping at the first.
- [x] When any issue exists, preflight raises one typed error carrying the full collection.
- [x] The error is catchable by a caller and exposes the issues in a form that can be enumerated and presented.
- [x] A preflight over a Gold Set with multiple distinct problems reports all of them in one raise, proven by a test asserting on the full set rather than on a single message.
- [x] Contract schema mismatches and unknown Evaluation Requirements are distinguishable within the reported collection.
- [x] Preflight over a compatible Suite and Gold Set still returns a Resolved Evaluation Plan and raises nothing.
- [x] The existing test that the runner rejects an incompatible preflight before creating an Evaluation Run still passes.
- [x] No Evaluation Run row is created when preflight fails.
- [x] The existing parametrized preflight mismatch tests still pass.
- [x] The full deterministic test suite passes.

## Blocked by

- 01 — Decide Suite, Gold Set, and Case compatibility in one place.
