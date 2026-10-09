# 02 Share retention eligibility and preserve review consumers

Labels: ready-for-agent

## Parent

[Shared fusion ranking](../PRD.md)

## What to build

Compact reports retain exactly the ranks needed to reproduce production fusion
using the shared eligibility policy from ticket 01. RAG review and sampled
chunk review recover unchanged rankings and Source Article identities from
those reports. This completes the spec's single ownership of ranking policy
across production, retention, and replay.

## Acceptance criteria

- [ ] Compact-branch retention uses the shared best-rank and nomination policy;
      no independent eligibility or ranking implementation remains across the
      production, retention, and replay adapters.
- [ ] Existing compaction and replay interfaces, serialized fields, counts,
      report versions, and configuration identities remain unchanged.
- [ ] Retention keeps the first 50 unique chunks per branch and only the deeper
      ranks required for eligible chunks, with explicit branch eligibility for
      configured nomination budgets above 50.
- [ ] End-to-end production, compact-retention, and replay checks preserve exact
      identities, ranks, and scores for branch limits 2, 50, and 75, duplicates,
      ties, cross-branch tail contributions, nondefault valid configuration,
      empty branches, and final truncation.
- [ ] Tests use existing interfaces and independent expected results alongside
      parity; private helper calls or intermediate maps are not test contracts.
- [ ] RAG projection and sampled top-ten chunk review preserve their established
      outputs and Source Article identities. Existing historical reports and
      compact inputs remain unmodified.
- [ ] Existing documentation accurately describes shared ownership, preserved
      interfaces, and bounded retention. There is no new dependency, public seam,
      report migration, prompt, model call, or change to measurement definitions.
- [ ] Focused deterministic fusion, retrieval-report, RAG projection, and chunk
      review checks pass through uv, with normal deterministic CI retained.
      Record completion evidence without claiming browser or model verification.

## Blocked by

- [01 Share ranking across production and report replay](01-share-production-and-replay-ranking.md).
  Retention must reuse the policy introduced there rather than create a
  competing implementation.

## Comments

2026-10-08: Published after the user approved the two-ticket breakdown.
Ticket 01 must complete before this ticket starts. Implementation has not started.

2026-10-09: Implementation prepared for independent review. Compact retention
now uses the fusion module's private preparation policy for ordered best branch
ranks and branch nominations. The report adapter attaches Source Article IDs,
keeps the first 50 unique chunks, retains deeper ranks for the eligible union,
and records explicit branch eligibility when a configured limit exceeds 50.
It no longer computes best ranks, tie order or nominations independently.
Production and replay continue to share scoring and final truncation. Public
signatures, return types, serialized fields, counts, versions, configuration
identities and measurement definitions are unchanged.

The confirmed seams used were `fuse_candidates(execution, config=...,
unweighted_baseline=...)`, `compact_branches(outcomes, config)`, and
`replay_fusion(branches, config)`. Six new characterization cases passed against
ticket 01 at `03566c1b0ec7d5c171a6030ac0ce6fa94eab6172` before extraction. They
specify complete compact records at limits 2, 50 and 75, duplicate routes, tied
cutoffs, input reversal, an empty branch, a deeper cross-branch contribution and
explicit eligibility above 50. Nondefault weights and rank constant produce
independent expected scores of 1.02, 0.6 and 0.5 after the final limit of three.
Removing identity tie breaking temporarily made all six cases fail. The mutation
was restored before extracting the shared policy. Existing independent ranking
checks and parity checks remain intact; no test imports the private helpers.

Verification used `UV_CACHE_DIR=/private/tmp/shared-fusion-uv-cache` with uv:

- `uv run --no-sync pytest -q tests/test_fusion.py tests/test_fusion_replay.py tests/test_retrieval_report.py tests/test_rag_review.py tests/test_chunk_review.py tests/test_chat_evidence_trail.py`: 120 passed, including the existing RAG projection and sampled chunk review checks.
- `uv run --no-sync /private/tmp/source-guides-uv/archive-v0/t8HMQ3-8mvMjzC03/bin/ty check src/knowledge_map/core/fusion.py src/knowledge_map/evaluation/retrieval_report.py tests/test_fusion_replay.py`: passed with cached ty 0.0.85.
- `uv run --no-sync ruff check src/knowledge_map/core/fusion.py src/knowledge_map/evaluation/retrieval_report.py tests/test_fusion_replay.py` and the same files with `ruff format --check`: passed.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`: 31 passed on Node 22.23.1.
- `uv run --no-sync pytest -q tests`: 1617 passed, 61 skipped. The existing provider warning reports ignored temperature while reasoning is enabled. This was the final deterministic regression run after the implementation and focused checks.
- A read-only `uv run --no-sync python` comparison checked outputs captured before extraction against all five committed historical retrieval reports. All 101 case replays retained exact chunk identities, Source Article IDs, ranks and floating-point scores. Every RAG projection, all 1,010 top-ten candidate records and 808 seeded sample entries matched. In-memory inputs and report bytes stayed unchanged.
- Direct inspection confirms that best-rank selection, branch ordering, nominations and eligibility are owned by the fusion module. Compaction uses those results for bounded retention. Scoring, fusion ties and final truncation remain shared between production and replay.
- `git diff --check` passed. The retrieval guide now documents shared ownership, preserved interfaces, retained eligibility and historical replay without rewriting reports.

The focused and full reviewer API checks used authorized loopback socket access
outside the sandbox. No model calls, live graph queries or browser verification were
performed. This verifies compatibility, not retrieval quality or calibration.
Completion reconciliation remains with the independent reviewer.
