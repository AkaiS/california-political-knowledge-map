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
can catch that error and present every issue. The Evaluation Ledger does not
accumulate runs that never had a chance of executing.

The runner no longer catches that error, because it no longer calls preflight:
issue 09 made `EvaluationRunner.run` require a Resolved Evaluation Plan. The
fence moved rather than disappeared — a failed preflight raises instead of
returning, so no plan exists and the runner cannot be reached. `ResolvedEvaluationPlan`
is un-constructible outside `preflight_selected_cases` to keep that the only way
in. See the corresponding Implementation Decision in the PRD.

## Acceptance criteria

- [x] Preflight collects every issue the compatibility predicate reports rather than stopping at the first.
- [x] When any issue exists, preflight raises one typed error carrying the full collection.
- [x] The error is catchable by a caller and exposes the issues in a form that can be enumerated and presented.
- [x] A preflight over a Gold Set with multiple distinct problems reports all of them in one raise, proven by a test asserting on the full set rather than on a single message.
- [x] Contract schema mismatches and unknown Evaluation Requirements are distinguishable within the reported collection.
- [x] Preflight over a compatible Suite and Gold Set still returns a Resolved Evaluation Plan and raises nothing.
- [x] An incompatible preflight cannot reach the runner at all. The original criterion — that the runner rejects an incompatible preflight before creating an Evaluation Run — is retracted: after issue 09 the runner does not call preflight, so it has nothing to reject. The test now asserts the guarantee that replaced it, that a raised preflight leaves the Evaluation Ledger empty.
- [x] A Resolved Evaluation Plan cannot be constructed outside `preflight_selected_cases`, so the runner cannot be handed a plan whose cases were never checked. Reading a stored plan back goes through a named rehydration seam that re-verifies its content hash.
- [x] No Evaluation Run row is created when preflight fails.
- [x] The existing parametrized preflight mismatch tests still pass.
- [x] The full deterministic test suite passes.

## Blocked by

- 01 — Decide Suite, Gold Set, and Case compatibility in one place.
