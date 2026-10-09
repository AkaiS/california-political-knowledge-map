# Shared fusion ranking

Labels: completed

## Problem Statement

Maintainers need retrieval measurements to describe the ordering production
actually used. Production fusion and compact-report replay currently implement
eligibility, weighted reciprocal-rank scoring, tie breaking, and final truncation
separately. A change to either implementation can make a saved Evaluation Run
describe different Grounding Evidence from production, even when both still run
successfully.

This duplication also makes maintenance require understanding two representations
and updating the same policy twice. Existing parity checks catch several such
differences, but they do not remove the duplicate ownership.

## Solution

Concentrate ranking policy in the fusion module. Production candidate records
and retained report ranks use that same implementation through their existing
interfaces. Their adapters keep representation-specific provenance, report
retention, and output formatting.

The change preserves current behavior. People asking political questions receive
the same ranked Grounding Evidence, and reviewers recover the same ordering and
scores from existing compact reports. Maintainers change ranking policy in one
place and verify it through the interfaces callers already use.

## User Stories

1. As a maintainer, I want production fusion and report replay to share ranking
   policy, so that a future ranking change has one implementation to update.
2. As a retrieval reviewer, I want replayed ranks and scores to equal production
   ranks and scores for the same execution and configuration, so that the report
   explains the retrieval I am reviewing.
3. As a person asking a political question, I want this refactor to preserve the
   selected Grounding Evidence, so that maintenance does not change my sources.
4. As a maintainer, I want existing fusion and replay callers to keep their
   interfaces, so that adopting the shared implementation requires no caller
   migration.
5. As a maintainer, I want each branch to nominate unique Article Chunks using
   its configured limit, so that repeated discovery routes consume no extra
   nominations.
6. As a maintainer, I want nomination ties resolved by Article Chunk identity,
   so that input order cannot change which tied chunks become eligible.
7. As a person asking a political question, I want a chunk nominated by any
   successful branch to remain eligible, so that missing graph relationships
   do not exclude useful full-text or dense evidence.
8. As a maintainer, I want each branch to contribute only its best rank for a
   chunk, so that multiple routes do not multiply that branch's influence.
9. As a maintainer, I want eligible chunks to use ranks from every successful
   branch that found them, so that a rank below another branch's nomination
   cutoff still contributes to the existing score.
10. As a maintainer, I want raw branch scores excluded from fusion arithmetic
    and tie breaking, so that incomparable retrieval scores cannot affect order.
11. As a maintainer, I want the existing weighted reciprocal-rank formula and
    numeric results preserved, so that this change is independent of tuning.
12. As a maintainer, I want final ties resolved by Article Chunk identity and
    ranks to remain consecutive and one-based, so that output is deterministic.
13. As a maintainer, I want the fused-candidate limit applied after scoring the
    eligible union, so that a limit change retains its current meaning.
14. As an evaluation author, I want the unweighted measurement baseline retained,
    so that I can compare equal branch contributions without changing configured
    weights or production behavior.
15. As a maintainer, I want current configuration defaults and validation retained,
    so that invalid weights and candidate limits remain rejected.
16. As an evidence reviewer, I want every original contribution retained for an
    admitted production chunk, so that routes, ranks, matched fields, branch
    scores, and supporting graph claims remain inspectable.
17. As an evidence reviewer, I want distinct graph identities and Claim Keys
    preserved, so that ranking cannot silently resolve entity ambiguity.
18. As a maintainer, I want input execution records left unchanged, so that
    ranking cannot discard information needed by later inspection.
19. As a person asking a political question, I want completed sibling evidence
    retained when another branch fails or is skipped, so that partial retrieval
    continues to supply useful sources.
20. As a maintainer, I want empty successful branches and entirely empty retrieval
    to preserve their current outputs, so that no candidates are fabricated.
21. As a retrieval reviewer, I want compact reports to retain the first 50 unique
    chunks per branch and the extra ranks needed for exact fusion, so that
    replay stays accurate without restoring full candidate records.
22. As a retrieval reviewer, I want configured nomination budgets above 50 to
    retain their explicit eligibility, so that larger production budgets do not
    change the 50-chunk measurement budget.
23. As a retrieval reviewer, I want historical compact reports to replay without
    rewriting them, so that their committed evidence remains unchanged.
24. As a chunk reviewer, I want sampled top-ten chunks to keep their ordering and
    Source Article identity, so that the shared policy preserves review inputs.
25. As a maintainer, I want independent expected-result checks alongside parity
    checks, so that two adapters agreeing on a shared bug cannot establish
    correctness.
26. As a maintainer, I want deterministic verification without model calls, a
    live graph, or browser control, so that this bounded refactor is inexpensive
    to verify through the existing interfaces.

## Implementation Decisions

- Deepen the existing fusion module. It owns best-rank selection, branch
  nominations, eligibility, weighted reciprocal-rank arithmetic, deterministic
  ordering, and final truncation. Production and compact-report replay must not
  retain independent implementations of those rules.
- Preserve the existing production-fusion, compact-branch retention, and
  compact-report replay interfaces and their return types. Shared ranking
  internals stay private; add no new public test seam or general ranking framework.
- Treat live candidate records and retained report ranks as two real adapters
  to the shared policy. The shared implementation needs chunk identity, branch,
  rank, eligibility information, and configuration; replay must not construct
  fabricated production provenance just to invoke it.
- Apply each branch's nomination limit to unique chunks ordered by their best
  branch rank and chunk identity. Rank the union of those nominations. For each
  admitted chunk, score the best rank from every branch that found it, including
  ranks outside that branch's nomination cutoff.
- Each branch contributes its weight divided by the sum of the configured rank
  constant and its best rank. Preserve stable numeric accumulation and exact
  live-versus-replay score parity. Raw branch scores never enter ranking.
- Order final results by descending fusion score and ascending chunk identity
  for ties. Apply the final limit afterward and return consecutive one-based
  ranks. Preserve nomination and score ordering independently of input order.
- Preserve the immutable fusion configuration and all current constraints.
  Defaults remain full-text weight 1, dense weight 1, structural weight 2,
  rank constant 60, branch nomination limits 50, and final limit 100. Configured
  structural weight continues to exceed either text-branch weight.
- Preserve production's explicit unweighted measurement baseline. It uses
  effective weights of 1 while retaining the configured rank constant and
  limits, without mutating configuration. Add no report field or replay mode.
- Keep contribution construction and Source Article identity validation in the
  production adapter. Preserve original contribution order, routes, matched
  fields, branch scores, pre-fusion ranks, graph claims, and distinct graph
  identities. Keep source-identity reconstruction in the replay adapter.
- Keep compact-report formatting and bounded retention in the report adapter.
  It must use the shared eligibility policy when choosing extra contributing
  ranks. Retain the first 50 unique chunks per branch, deeper ranks contributing
  to eligible chunks, and explicit branch eligibility when configured budgets
  exceed 50. Preserve existing counts and serialized fields.
- Replay must honor recorded explicit eligibility when present and derive it
  from retained branch ranks under the existing format when absent. Discarded
  candidate tails cannot be reconstructed or made eligible by this refactor.
- Preserve failed, skipped, and successful-empty branch behavior and the
  distinction between those outcomes in the execution record. Preserve existing
  selection observations in production; replay adds no production observation
  side effects.
- Reuse standard Python computation and existing validated contracts. Add no
  dependency, storage protocol, schema migration, prompt version, or model call.
  Update existing ownership documentation if the extraction makes it inaccurate.

## Testing Decisions

- The user confirmed the existing production-fusion and compact-report replay
  interfaces as the test seams. Verify shared policy through those interfaces
  and compact-branch retention. Keep private ranking functions and intermediate
  maps outside the test contract.
- A good test supplies fixed ranked candidates and configuration, then asserts
  externally observable chunk identities, ranks, scores, retained contributions,
  unchanged input records, or compact-report fields. It does not assert private
  call order, helper names, or how many times an internal function executes.
- Retain the production fusion behavior checks as prior art. They cover
  structural priority, text-only evidence, duplicate routes, cross-branch
  accumulation, configuration, cutoff behavior, ties, failed and skipped
  branches, empty results, identity preservation, and the unweighted baseline.
- Retain the compact-report parity check as prior art. It compares production
  and replay across branch limits of 2, 50, and 75, repeated chunks, ties, and
  a deep rank contributing through another branch's nomination. Require equal
  identities, ranks, and numeric fusion scores.
- Preserve independently specified expected orders and scores at the existing
  interfaces. Parity alone is insufficient once both adapters share the same
  implementation. Characterize any uncovered rule before moving its ownership.
- Verify that report retention contains every rank required for replay without
  enlarging the first-50 measurement population. Cover explicit eligibility
  above 50, budgets below 50, cross-branch tail contributions, and empty branches.
- Exercise nondefault valid weights, rank constants, nomination limits, and
  final limits through both adapters. Cover deterministic ties and input-order
  variation, while keeping production contribution ordering unchanged.
- Preserve report compatibility checks using existing authored examples or
  historical reports without editing them. Verify that replay keeps Source
  Article identity and that ranking leaves production records and compact
  inputs unchanged.
- Run focused deterministic fusion, retrieval-report, RAG projection, and chunk
  review checks through uv. Use existing projection and sample checks to verify
  consumer behavior; add new checks only for uncovered compatibility risks.
  Normal deterministic CI remains the final regression check. No live Evaluation
  Run, graph query, browser verification, or model-quality claim is required.
- Inspect the final ownership directly to confirm one ranking implementation
  serves both adapters and compaction uses its eligibility policy. Passing
  outputs alone do not establish that duplicate policy was removed.

## Out of Scope

- Ranking-quality tuning, graph-aware reranking, new retrieval branches, and
  changes to weights, defaults, or structural priority.
- Changes to retrieval deadlines, graph queries, Jev query construction,
  Query Rewrite approval, Evidence Assembly, or Chat Agent generation.
- Changes to metric definitions, the 50-unique-chunk measurement budget,
  report versions, report size policy, or historical report contents.
- Arbitrary replay with larger discarded-candidate budgets or recovery of
  evidence that was not retained.
- Changes to Evaluation Run execution ownership, progressive persistence,
  report-bound review storage, annotation workflows, or reviewer presentation.
- New public ranking interfaces, storage adapters, ledgers, resumption,
  dependencies, prompts, or model-backed evaluations.

## Further Notes

This is the shared fusion ranking candidate selected from the October 8, 2026
architecture review. It is a bounded behavior-preserving refactor, delivered
through two implementation tickets. The other architecture candidates are
separate work.

ADR 0024 remains authoritative for Evaluation Run accounting and retains
ADR 0017's compact-report and repository-versioning decisions. This spec
preserves those decisions. Existing defaults are implementation settings, not
evidence that the ranking has been calibrated.

Depth comes from one policy serving two existing adapters. A new module that
merely forwards to two unchanged ranking implementations would not satisfy this
spec. Locality means eligibility and ranking changes have one owner; leverage
comes from production retrieval, RAG review, sampled chunk review, and existing
report-scoring consumers using that owner.

## Comments

2026-10-08: The user selected shared fusion ranking for specification and
confirmed testing through the existing production-fusion and compact-report
replay interfaces, keeping shared ranking internals private. Published as
ready-for-agent; implementation has not started.

2026-10-09: Both implementation tickets are complete with checked acceptance
criteria. Each passed independent Standards and Spec review with zero findings.
The final ticket regression run passed 1617 tests with 61 skipped; 31 Node
reviewer tests and changed-file type, lint and format checks also passed.
Five unchanged historical reports preserve all 101 exact fusion replays, RAG
projections, 1,010 top-ten candidate records and 808 seeded sample entries.
The project and work index are reconciled to completed. At this ticket handoff,
final sequence review had not run; its closure is recorded below. Remote CI has
not run.
No model calls, live graph queries or browser verification were performed.

2026-10-09: Final sequence review covered both tickets together through
`7673e0498329a4336985df306f4cd610042d039b`, using
`git diff 0b180fd77df13e9aaae3e70678732827ea81a616...HEAD`.
Independent Standards and Spec reviewers each found zero findings. Standards
confirmed compliance with repository instructions, domain language, ADRs 0017
and 0024, and the code-smell baseline. Spec checked every bounded PRD requirement
and both tickets, including their integration and compact-report consumers.

Direct inspection confirms one private preparation policy owns ordered best
branch ranks, nominations and eligibility for production, retention and replay.
One private scorer owns reciprocal-rank arithmetic, final identity ties and
truncation. Adapters retain production provenance and observations, Source Article
reconstruction, report formatting, counts and bounded retention. Existing public
interfaces, defaults, validation, metric definitions and report versions remain
unchanged. No code fixes were needed.

Final verification used `UV_CACHE_DIR=/private/tmp/shared-fusion-uv-cache`:

- `uv sync --locked --dev`: passed, 177 packages checked.
- `uv run --no-sync pytest -q tests/test_fusion.py tests/test_fusion_replay.py tests/test_retrieval_report.py`: 67 passed.
- `uv run --no-sync /private/tmp/source-guides-uv/archive-v0/t8HMQ3-8mvMjzC03/bin/ty check src/knowledge_map/core/fusion.py src/knowledge_map/evaluation/retrieval_report.py tests/test_fusion_replay.py`: passed with cached ty 0.0.85.
- `uv run --no-sync ruff check src/knowledge_map/core/fusion.py src/knowledge_map/evaluation/retrieval_report.py tests/test_fusion_replay.py` and the same files with `ruff format --check`: passed.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`: 31 passed on Node 22.23.1.
- `uv run --no-sync python /private/tmp/shared-fusion-sequence-check.py`: original baseline functions loaded read-only with `git show` passed all 11 non-telemetry characterization cases. All five historical reports matched for 101 exact fusion replays, five RAG projections, 1,010 top-ten records and 808 sample entries with seeds 42 and 43. Chunk identities, Source Article IDs, ranks and floating-point scores matched; inputs and report bytes stayed unchanged.
- `uv run --no-sync pytest -q tests`: 1617 passed, 61 skipped, one existing ignored-temperature provider warning. This final deterministic run followed both sequence reviews and used authorized loopback access for existing reviewer API tests.
- `git diff --check`: passed.

Closure checked both earlier ticket reviews and both final axes. Every review
has zero findings, so there are no per-finding dispositions, unresolved valid
findings or unresolved questions. All 17 ticket acceptance criteria remain
checked. The completed parent and work index now record final sequence closure.
The two existing type diagnostics in untouched `tests/test_retrieval_report.py`
remain outside this change; all changed-file type checks pass. Remote CI has not
run. No model calls, live graph queries or browser verification were performed.
These checks establish compatibility, not retrieval quality or weight calibration.
