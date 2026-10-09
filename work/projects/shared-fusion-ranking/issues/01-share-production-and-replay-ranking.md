# 01 Share ranking across production and report replay

Labels: completed

## Parent

[Shared fusion ranking](../PRD.md)

## What to build

Production retrieval and compact-report replay use one fusion policy and return
the same chunk ordering and scores as before. Preserve the existing interfaces
and keep representation-specific provenance in their adapters. A completed
ticket is verifiable through both interfaces without a model or live graph.

## Acceptance criteria

- [x] Characterize uncovered ranking rules through independent expected outputs
      before changing ownership; retain existing expected outcomes and parity
      checks rather than duplicating checks already present.
- [x] One private implementation owns best branch ranks, unique-chunk nomination,
      eligibility, reciprocal-rank arithmetic, deterministic ties, and final
      truncation for production fusion and compact-report replay.
- [x] Existing interfaces and return types remain compatible. Replay consumes
      retained ranks and recorded eligibility without fabricated provenance.
- [x] Production and replay return unchanged chunk identities, ranks, and numeric
      scores for default and nondefault configurations. Exact adapter parity
      covers branch limits 2, 50, and 75, ties, duplicates, and deep cross-branch
      contributions.
- [x] Production preserves all original contributions, their ordering, source
      identity validation, routes, branch scores, graph claims, and distinct graph
      identities. Input records remain unchanged.
- [x] Configuration validation, defaults, and the production unweighted baseline
      retain their existing behavior. Raw scores cannot affect ranking.
- [x] Failed, skipped, successful-empty, and entirely empty outcomes remain
      unchanged. Production selection observations remain accurate; replay
      introduces no production observation side effects.
- [x] Existing compact reports replay without mutation or migration, honoring
      explicit eligibility when present and current derivation when absent.
- [x] Focused fusion and retrieval-report behavior checks pass through uv.
      Inspect that both adapters use one ranking implementation. Record commands,
      outcomes, and material limitations in the completion comment.

## Blocked by

None. Can start immediately.

## Scope of this slice

Compact-report retention remains behaviorally compatible during this ticket.
Its separate eligibility calculation is replaced in ticket 02; it must not
grow a second shared policy or change the report format in the meantime.

## Comments

2026-10-08: Published after the user approved the two-ticket breakdown and
the dependency from ticket 02 to ticket 01. Implementation has not started.

2026-10-09: Implementation prepared for independent review. The fusion module's
private preparation and scoring functions now serve both production and replay.
Production still builds `FusedCandidate` values, validates Source Article
identity, preserves contributions in their original branch order, and records
nominations before score calculation. Replay adapts retained ranks, nomination
pools and recorded eligibility, then reconstructs Source Article identities.
Its computation has no production selection observation side effects.
`compact_branches` and its separate retention eligibility calculation are
unchanged for ticket 02.

The confirmed seams used were `fuse_candidates(execution, config=...,
unweighted_baseline=...)`, `replay_fusion(branches, config)`, and
`compact_branches(outcomes, config)`. No test imports private ranking helpers.
Existing production outcomes and the exact parity checks at nomination limits
2, 50 and 75 remain intact. Seven added characterization cases pass against the
original implementation at `0b180fd77df13e9aaae3e70678732827ea81a616` and the
shared implementation. They cover independently specified nondefault scores,
final limits, input order and immutability, recorded and absent eligibility,
and selection observations. Temporary weight-removal and tail-nomination
mutations caused the expected failures and were restored. A failing test also
caught and corrected an extraction regression that lost nomination observations
when arithmetic overflowed.

Verification used `UV_CACHE_DIR=/private/tmp/shared-fusion-uv-cache` with uv:

- `uv run --no-sync pytest -q tests/test_fusion.py tests/test_fusion_replay.py tests/test_retrieval_report.py tests/test_rag_review.py tests/test_chunk_review.py tests/test_chat_evidence_trail.py`: 114 passed.
- `uv run --no-sync /private/tmp/source-guides-uv/archive-v0/t8HMQ3-8mvMjzC03/bin/ty check src/knowledge_map/core/fusion.py src/knowledge_map/evaluation/retrieval_report.py tests/test_fusion_replay.py`: passed with cached ty 0.0.85.
- `uv run --no-sync ruff check src/knowledge_map/core/fusion.py src/knowledge_map/evaluation/retrieval_report.py tests/test_fusion_replay.py` and the same files with `ruff format --check`: passed.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`: 31 passed on Node 22.23.1.
- `uv run --no-sync pytest -q tests`: 1611 passed, 61 skipped. One existing provider warning reports ignored temperature while reasoning is enabled.
- A read-only `uv run --no-sync python` comparison checked every replayable case in the five committed retrieval reports against outputs captured before replacing replay: all 101 cases retained exact identities, Source Article IDs, ranks and floating-point scores. Both in-memory inputs and report bytes stayed unchanged.
- `git diff --check` passed. Direct inspection confirms that production and replay share best-rank selection, nomination, eligibility, scoring, ties and truncation. The report adapter's remaining eligibility calculation belongs to retention and ticket 02.

The focused reviewer tests required loopback socket access outside the sandbox;
they passed after that access was granted. An initial sandboxed full-suite
attempt was stopped during collection before the final run. Changed-file type
checks pass; the untouched `tests/test_retrieval_report.py` has two pre-existing
type diagnostics, for Evidence Package narrowing and its evaluator context.
No model calls, live graph queries or browser verification were performed.
This verifies compatibility, not retrieval quality or weight calibration.

2026-10-09: Independent two-axis review of implementation commit
`77485f73af64d3446f1e676a234e4f9edc0c808f` used
`git diff 0b180fd77df13e9aaae3e70678732827ea81a616...HEAD`.
The Standards reviewer found zero documented-standard violations or actionable
baseline smells. The Spec reviewer found zero missing requirements, scope
additions, or incorrect implementations. There are no findings to fix or
unresolved questions. Both reviewers confirmed that retention's separate
eligibility calculation belongs to ticket 02.

Independent review verification used the same temporary uv cache:

- `uv run --no-sync pytest -q tests/test_fusion.py tests/test_fusion_replay.py`: 51 passed.
- All seven characterization cases passed against baseline functions loaded read-only with `git show`. A separate baseline comparison matched every identity, Source Article ID, rank and floating-point score in all 101 cases across the five historical reports; inputs and report bytes remained unchanged.
- The wider focused command recorded above passed 111 tests in the sandbox; three existing reviewer API checks required loopback binding. The final full suite ran with that access and covered those checks successfully.
- `uv run --no-sync pytest -q tests`: 1611 passed, 61 skipped, with the existing ignored-temperature provider warning. This was the final deterministic regression run after review.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`: 31 passed on Node 22.23.1.
- The same changed-file `ty check`, `ruff check` and `ruff format --check` commands recorded above passed again. `git diff --check` passed.

All nine acceptance criteria are satisfied. No code fixes were required by
review. The completed label and checked criteria record that evidence; the
parent project remains open for ticket 02. No model calls, live graph queries
or browser verification were performed.
