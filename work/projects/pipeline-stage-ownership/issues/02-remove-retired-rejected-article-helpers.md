# Remove the retired rejected-article helpers

Labels: completed

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

The rejected-article store is dead. Neither its writer nor its reader is called
from application code: the surviving import in the discovery module is unused,
and both discovery call sites already cache articles with `relevance_status =
'PENDING'`. The metadata those helpers once held now lives in the cache's stored
metadata column.

Delete both helpers and the dead import. Update the tests that reference them —
the archive crawl test asserts through the getter and needs a direct cache query
instead.

This is a prefactor. It removes a second, parallel notion of "an article we
decided against" before the relevance writers are reshaped, so those diffs stay
readable.

## Acceptance criteria

- [x] Neither rejected-article helper exists, and no module imports them.
- [x] Discovery continues to cache articles it filters out with `relevance_status = 'PENDING'`, unchanged in behavior.
- [x] Tests previously asserting through the rejected-article getter assert against the cache directly and still prove the same behavior.
- [x] The full deterministic test suite passes.

## Blocked by

None - can start immediately.
