# Restrict Consumed Artifact Provenance to Manifested Cases

Status: completed

## Parent

[Query Complete Evaluation Artifact Provenance and Telemetry](../shared-evaluation-contract/issues/06-artifact-provenance-and-telemetry.md)

## What to build

When an Evaluation Run executes a selected subset of a Gold Set, its consumed-artifact read model must include authored artifacts from the exact Evaluation Case revisions in the resolved manifest, not from every case supplied to the runner. Continue to record artifacts belonging to the run's exact Evaluation Suite, Evaluation Gold Set, and Evaluation Rubric revisions as consumed inputs.

The resolved manifest remains authoritative: investigators querying a subset run must not see artifacts from excluded cases represented as inputs to that run. Full-population runs must retain their existing consumed-artifact behavior.

## Acceptance criteria

- [x] A subset Evaluation Run records authored artifacts from every selected, manifested Evaluation Case revision as consumed artifacts.
- [x] Authored artifacts belonging only to excluded Evaluation Case revisions do not appear in the subset run's consumed-artifact read model.
- [x] Artifacts belonging to the run's exact Evaluation Suite, Evaluation Gold Set, and Evaluation Rubric revisions remain included as consumed inputs.
- [x] A full-population Evaluation Run continues to expose all applicable case-definition artifacts as consumed inputs.
- [x] Deterministic SQLite contract coverage exercises a Gold Set containing at least one selected and one excluded case and proves the complete consumed-artifact result.
- [x] Produced-artifact traversal and artifact ownership at the smallest responsible producer remain unchanged.

## Blocked by

None - can start immediately.
