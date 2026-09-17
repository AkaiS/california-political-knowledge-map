# 09 — Concurrent retrieval and Chat Agent handoff

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Connect the approved Query Rewrite, retrieval branches, fusion, and Evidence
Assembler into one bounded pipeline. Enabled branches run concurrently under
one deadline. Completed evidence survives another branch's failure, and the
assembled package returns to the same Chat Agent that received the original
question.

## Acceptance criteria

- [x] A non-relational rewrite starts exactly the full-text and dense branches.
- [x] A Relational Question starts exactly the full-text, dense, and typed
      structural branches.
- [x] Every branch receives the approved Query Rewrite, never the original
      wording.
- [x] Enabled branches start concurrently after deterministic keyword
      preparation.
- [x] One configurable wall-clock deadline covers the retrieval run after
      approval.
- [x] Deadline exhaustion preserves evidence from completed branches and marks
      every unfinished branch as failed.
- [x] One branch failure never discards another branch's candidates.
- [x] Branch candidates pass through graph-prioritized fusion and deterministic
      Evidence Assembly before the Chat Agent receives them.
- [x] The pipeline uses the configurable initial weights and candidate limits
      supplied by the fusion ticket. Empirical tuning does not gate the handoff.
- [x] Every failed branch reaches user-facing disclosure. Structural failure on
      a Relational Question is prominent, while text-branch failures remain
      visible but secondary.
- [x] A successful empty structural traversal is presented as no matching graph
      connection in the available graph. A structural failure says the graph
      connection could not be searched.
- [x] A Deferred coverage limit presented before approval accompanies the final
      evidence package.
- [x] The pipeline records total model usage but applies no independent
      run-wide token ceiling.
- [x] The Chat Agent produces one Retrieval Answer from the assembled package.
      No post-retrieval model, sufficiency loop, or automatic second retrieval
      runs.
- [x] Fake-dependency tests cover both routes, concurrent completion, one and
      several branch failures, all branches failing, successful empty branches,
      deadline exhaustion, fusion, assembly, and final failure disclosure.

## Blocked by

- [01 — Query Rewrite and approval](01-query-rewrite-and-approval.md).
- [03 — Full-text retrieval from an approved rewrite](03-full-text-retrieval.md).
- [04 — Dense retrieval from an approved rewrite](04-dense-retrieval.md).
- [06 — Bounded multi-hop structural retrieval](06-bounded-multi-hop-structural-retrieval.md).
- [07 — Graph-prioritized reciprocal-rank fusion](07-graph-prioritized-reciprocal-rank-fusion.md).
- [08 — Deterministic Evidence Assembly](08-deterministic-evidence-assembly.md).

## Comments

2026-09-17: Inspection identified these public test seams before implementation,
covered by the maintainer's advance confirmation:

- `knowledge_map.core.retrieval.RetrievalCoordinator.run(rewrite, *, coverage,
  relevant_collection_ids, monthly_coverage=(), usage=None)` returns
  `EvidencePackage | EvidenceAssemblyFailure`. Constructor dependencies are the
  full-text, dense, and structural retrievers, asynchronous Grounding Evidence
  and Story loaders, fusion configuration, context limits, deadline duration,
  and a monotonic clock. Tests observe routing, concurrent branch progress,
  retained candidates, deadlines, fusion, assembly, coverage, and usage here.
- `knowledge_map.core.chat.ChatSession.prepare()`, `reject(correction)`, and
  `approve()` connect the existing question-preparation boundary to retrieval
  and one final `RetrievalAnswer`. The session receives the original question,
  one injected Chat Agent, a Query Rewriter, coverage and explicit relevant
  collection IDs, and a retrieval coordinator. Scripted Pydantic AI models
  observe policy inputs, the measured evidence context, and final disclosure.
- `knowledge_map.adapters.evidence.EvidenceStore.load_grounding(candidate)` and
  `load_story(citation)` are the concrete asynchronous storage boundary. A fake
  Neo4j driver and a temporary SQLite document store observe source identity,
  original wording, missing rows, and `EvidenceHydrationError` normalization.

The single retrieval deadline includes keyword preparation, branch execution,
fusion, and Evidence Assembly. Assembly deadline exhaustion retains the full
execution record in `EvidenceAssemblyFailure`; it cannot release unverified
passages to meet a deadline. The Chat Agent's final response runs after retrieval
and has no retrieval tool or automatic second-search path.

2026-09-17: Implemented the recorded seams in `core/retrieval.py`,
`core/chat.py`, and `adapters/evidence.py`. The construction example, deadline
behavior, configuration, storage contract, and usage events are documented in
[Retrieval pipeline and Chat Agent handoff](../../../../docs/retrieval-pipeline.md).

The implementation used vertical TDD slices. Tests first failed at the public
boundary for missing coordination, sequential branch progress, branch exception
propagation, missing deadlines, production adapter signatures, database error
normalization, missing Chat Agent handoff, omitted failure and Deferred notices,
and missing usage totals. Each behavior was implemented before the next slice.

Acceptance evidence:

- Both routes use the approved rewrite and one shared deadline. Event-based
  tests require all enabled branches to start before any can finish.
- One, several, and all failing branches retain every successful candidate.
  Deadline tests cover one through three unfinished branches, preparation,
  both hydration loaders, and caller cancellation. Assembly failure retains
  the completed execution audit without releasing unverified quotations.
- Actual retrievers run through the coordinator with fake Neo4j drivers,
  embedding transport, and scripted structural models. Fusion uses the initial
  graph weights and accepts changed weights and limits while retaining every
  route and pre-fusion candidate.
- Concrete storage reads original Stories from temporary SQLite databases,
  supports Source Article URL primary keys, normalizes database failures, and
  fails immediately on SQLite locks. This avoids a worker continuing through
  SQLite's default busy timeout after coroutine cancellation.
- The same Chat Agent assesses only rewritten intent and receives the exact
  `render_evidence_context` input after approval. Final notices are deterministic:
  structural failure comes first, text failures remain visible, successful
  structural emptiness has its own message, and Deferred explanations repeat.
  Declined and unavailable questions never enter retrieval. Assembly failure
  prevents the final model call and exposes every failure disclosure.
- Usage logs include rejected rewrite attempts, policy, structural construction,
  dense embedding, and the final answer. A scripted three-million-input-token
  conversation completes without an independent token cutoff.

Verification:

- New coordinator, Chat Agent, and storage tests: 33 passed.
- Focused affected suite: 254 passed.
- One final full deterministic suite, `uv run --no-sync pytest -q`: 1,195 passed,
  47 opt-in Neo4j tests skipped, and the same two existing provider warnings.
- Changed-file `ruff check`, `ruff format --check`, `ty check`, and
  `git diff --check`: passed. Commands used a writable temporary `UV_CACHE_DIR`;
  the cached type checker ran through `uv run --no-sync`.

All acceptance criteria are satisfied. Coverage descriptions and relevant
collection IDs remain explicit caller inputs. The final Chat Agent response
runs after the bounded retrieval phase. The existing exact-Story-substring
verification limitation remains: transformed chunks need an original-position
mapping before they can become quotations. No live model, database, browser,
or retrieval-quality evaluation was run for this integration ticket.
