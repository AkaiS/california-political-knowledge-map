# 07 — Graph-prioritized reciprocal-rank fusion

Labels: completed

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Combine branch candidates through weighted reciprocal-rank fusion over their
union. Make weights, the reciprocal-rank constant, and candidate limits explicit
configuration with documented initial defaults. The initial structural weight
must exceed either text-branch weight without excluding candidates found only
through full-text or dense retrieval. Exact tuning is later measurement work and
does not block this implementation.

## Acceptance criteria

- [x] Fusion consumes the union of branch candidates and does not require a
      candidate to appear in every branch.
- [x] Branch weights, the reciprocal-rank constant, and candidate limits are
      explicit configuration with documented initial defaults.
- [x] The initial and any replacement configuration requires typed structural
      retrieval to have greater weight than either full-text or dense retrieval.
- [x] An unweighted measurement baseline and alternative weighted
      configurations can run without changing fusion code.
- [x] A candidate found through several branches accumulates each branch's
      reciprocal-rank contribution.
- [x] A candidate absent from structural retrieval remains eligible through a
      text branch.
- [x] Deduplication uses Article Chunk identity and retains every retrieval
      route, matched field, supporting graph claim, branch-local score, and
      pre-fusion rank.
- [x] Fusion never compares raw scores across branches.
- [x] Candidate deduplication does not merge graph entities or resolve identity
      ambiguity.
- [x] Behavioral tests cover structural priority, text-only gap filling,
      candidates found through several routes, rank ties, configuration
      validation, and the unweighted baseline.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).

## Comments

2026-09-17: Inspection identified these public test seams before implementation,
covered by the maintainer's advance confirmation:

- `knowledge_map.schemas.fusion.FusionConfig` construction and JSON validation
  expose branch weights, the reciprocal-rank constant, and candidate limits.
- `knowledge_map.core.fusion.fuse_candidates(execution:
  RetrievalExecutionResult, *, config: FusionConfig | None = None,
  unweighted_baseline: bool = False) -> tuple[FusedCandidate, ...]` consumes the
  retained branch outcomes and exposes ranking, candidate identity, and every
  original contribution. The explicit baseline flag is for measurement; every
  configured set of weights still requires structural priority.

Tests use the existing retrieval contracts directly. No model, database, or
private implementation seam is needed. The coordinator remains ticket 09.

2026-09-17: Implemented configurable weighted reciprocal-rank fusion in
`core/fusion.py` with validated settings in `schemas/fusion.py`. The defaults,
baseline mode, candidate-limit semantics, and calling example are recorded in
[retrieval fusion](../../../../docs/retrieval-fusion.md).

Each branch nominates its highest-ranked unique chunks. Fusion scores their
union using each chunk's best rank per branch, counts a branch once despite
repeated discovery routes, and never reads raw scores. A nominated chunk retains
and scores every recorded branch contribution, including those below another
branch's nomination cutoff. The final output cutoff leaves all branch outputs
in the unchanged execution record. Equal scores and nomination ranks use chunk
ID for deterministic ordering. Candidate deduplication preserves graph claims
and distinct database element IDs without resolving entity ambiguity.

The TDD implementation used vertical red-green slices at the recorded seams.
Validation used Pydantic's numeric constraints plus the structural-priority
validator. The unweighted baseline overrides effective weights only for the
explicit measurement call, while every configured weight set keeps structural
priority.

Verification:

- `uv run --no-sync pytest -q tests/test_fusion.py`: 44 passed.
- `uv run --no-sync pytest -q tests/test_fusion.py tests/test_retrieval_contracts.py`:
  90 passed.
- Final full deterministic suite, `uv run --no-sync pytest -q`: 1130 passed,
  47 opt-in integration tests skipped, and the same two existing provider
  warnings.
- Changed-file `ruff check`, `ruff format --check`, `ty check`, and
  `git diff --check`: passed. The `uvx` launcher hit its macOS system-configuration
  panic; running the cached type checker through `uv run --no-sync` passed.

All acceptance criteria are satisfied. No quality tuning is claimed. These
limits select among retained candidates; database work remains bounded by the
branches' own query limits and deadline. Evidence Assembly and coordinator
wiring remain tickets 08 and 09.
