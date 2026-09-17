# 08 — Deterministic Evidence Assembly

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Turn ranked Grounding Evidence into the typed package returned to the Chat
Agent. The Evidence Assembler hydrates provenance, verifies displayed wording,
groups passages by Source Article, attaches relevant coverage limits, and
applies the context budget without introducing another model decision.

## Acceptance criteria

- [x] Every selected passage is tied to its Source Article and retains the
      retrieval routes and graph claims that led to it.
- [x] Any wording presented as a quotation is verified against the original
      Story body.
- [x] Transformed Article Chunk text cannot be silently presented as verbatim
      original wording.
- [x] Selected passages are grouped by Source Article while useful passages from
      different parts of one article remain available.
- [x] The package includes the relevant Coverage Description entries and omits
      unrelated collection detail.
- [x] Context limiting is deterministic and follows the accepted contract.
- [x] Assembly failure remains distinct from retrieval branch failure.
- [x] The assembler does not summarize evidence, decide sufficiency, adjudicate
      disagreements, or request another retrieval.
- [x] Behavioral tests cover original-wording verification, source grouping,
      route retention, coverage attachment, deterministic context limiting, and
      assembly failure.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).

## Comments

2026-09-17: Inspection identified these public test seams before implementation,
covered by the maintainer's advance confirmation:

- `knowledge_map.core.evidence.EvidenceAssembler.assemble(execution,
  candidates, *, coverage, relevant_collection_ids, limits, monthly_coverage)`
  returns `EvidencePackage | EvidenceAssemblyFailure`. Its injected asynchronous
  Grounding Evidence and original Story loaders represent the storage boundary.
  Tests observe original wording, grouping, retained routes and graph claims,
  coverage selection, context limits, and distinct assembly failure here.
- `knowledge_map.core.evidence.render_evidence_context(package)` supplies the
  exact character-measured evidence context for the Chat Agent, excluding the
  execution audit and transformed chunk wording.
- `knowledge_map.schemas.evidence.EvidenceContextLimits` validates positive
  character and passage budgets.

The coordinator remains ticket 09. Collection relevance is an explicit input
from the caller's coverage assessment; assembly does not infer relevance from
question wording. Stored chunks have no original-position map, so assembly
requires an exact Story substring and fails safely when it cannot verify one.

2026-09-17: Implemented the assembler in `core/evidence.py` and positive context
limits in `schemas/evidence.py`. The storage functions, verification rule,
coverage input, renderer, and budget policy are documented in
[Evidence Assembly](../../../../docs/evidence-assembly.md).

The TDD implementation used vertical red-green slices at the recorded public
seams. Tests establish exact Story offsets, rejection of transformed wording,
source grouping with distant passages, retained graph routes through JSON round
trips, coverage filtering, deterministic passage and character limits, and
distinct assembly failure. Further checks cover missing or conflicting
provenance, absent coverage, duplicate fused candidates, the exact budget
boundary, and branch outcome counts after budget omissions.

The initial limits are 24,000 Unicode characters and 12 whole passages.
`render_evidence_context` supplies the measured Chat Agent input and excludes
unverified stored chunk wording and the pre-selection execution audit. It keeps
branch outcome counts, failure disclosures, the approved assessment, selected
citations and routes, and relevant coverage. An oversized passage is omitted
while later candidates remain eligible; mandatory metadata cannot be dropped
to fit. Assembly invokes no model, summary, sufficiency check, or new retrieval.

The existing store has no original-position mapping for transformed chunks.
Such wording produces an explicit assembly failure unless the storage adapter
can provide an original passage with its provenance. No fuzzy alignment is
claimed. Concrete database adapters, collection-relevance assessment, deadline
coordination, and Chat Agent wiring remain ticket 09.

Verification:

- `uv run --no-sync pytest -q tests/test_evidence.py`: 32 passed.
- The focused assembly, retrieval-contract, and fusion suite: 122 passed.
- One final deterministic suite, `uv run --no-sync pytest -q`: 1,162 passed,
  47 opt-in Neo4j tests skipped, and the same two existing provider warnings.
- Changed-file `ruff check`, `ruff format --check`, `ty check`, and
  `git diff --check`: passed. Commands used a writable temporary `UV_CACHE_DIR`
  because the default cache is outside this worktree's sandbox. The cached type
  checker ran through `uv run --no-sync`.

All acceptance criteria are satisfied. No live-model, live-database, or browser
verification was needed for this deterministic boundary.
