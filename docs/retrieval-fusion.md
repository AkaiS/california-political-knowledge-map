# Retrieval fusion

`knowledge_map.core.fusion.fuse_candidates` combines the successful branches in
a `RetrievalExecutionResult` into ranked `FusedCandidate` values. It preserves
the execution record for later inspection and Evidence Assembly.

```python
from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.schemas.fusion import FusionConfig

config = FusionConfig()
ranked = fuse_candidates(execution, config=config)
baseline = fuse_candidates(execution, config=config, unweighted_baseline=True)
```

`FusionConfig` construction and JSON validation, and `fuse_candidates`, are the
public test seams recorded before implementation under the maintainer's advance
confirmation. Tests supply the existing retrieval contracts. Fusion needs no
model, database, or clock dependency. The [retrieval coordinator](retrieval-pipeline.md)
consumes it before Evidence Assembly.

## Configuration

The initial defaults are starting values for implementation, not measured
quality recommendations:

| Setting | Default | Constraint |
| --- | --- | --- |
| `full_text_weight` | 1.0 | Finite, positive number |
| `dense_weight` | 1.0 | Finite, positive number |
| `structural_weight` | 2.0 | Finite, greater than either text weight |
| `rank_constant` | 60.0 | Finite, nonnegative number |
| `full_text_candidate_limit` | 50 | Positive integer, unique Article Chunks |
| `dense_candidate_limit` | 50 | Positive integer, unique Article Chunks |
| `structural_candidate_limit` | 50 | Positive integer, unique Article Chunks |
| `fused_candidate_limit` | 100 | Positive integer, final Article Chunks |

The config is immutable and forbids unknown fields. It rejects booleans for
numeric settings and fractional or string counts. Every replacement config
must preserve structural weight priority. Set other valid weights, the rank
constant, or limits through the same constructor or `FusionConfig.model_validate`
without changing fusion code.

The explicit `unweighted_baseline=True` mode replaces all effective weights with
1.0 for measurement. It keeps the configured rank constant and limits and does
not mutate or relax the configured weights. Production calls leave this flag
false. Quality measurement and later tuning remain separate work.

## Ranking and limits

For each Article Chunk, fusion takes its best recorded rank in each successful
branch. Each branch contributes `weight / (rank_constant + best_rank)` once.
Several routes from the same branch do not multiply its influence. Contributions
from different branches add together. Raw scores are carried through unchanged
and never enter the calculation or tie breaking.

Each branch nominates up to its configured number of unique chunks, ordered by
best rank and then chunk ID. Fusion ranks the union of those nominations. A
chunk need only be nominated by one branch; graph gaps do not disqualify
full-text or dense candidates. For an admitted chunk, every recorded branch
contributes its best rank, even if the chunk fell outside that branch's
nomination limit. All of its original candidate records survive as contributions.
This preserves every route, matched field, branch-local score, pre-fusion rank,
supporting graph claim, and any hydrated Grounding Evidence.

The final order is descending fusion score, then ascending chunk ID for ties.
Ranks are consecutive and one-based. The final candidate limit applies after
fusion. Chunks omitted by either cutoff remain in the original execution
record. Repeated routes consume no extra chunk nominations, and input list or
branch order does not determine a tied chunk's selection.

Fusion deduplicates only Article Chunk IDs. It does not compare or merge entity
names, internal IDs, database element IDs, or graph claims. The existing
`FusedCandidate` contract rejects conflicting Source Article identities for a
selected chunk. Distinct graph nodes, Claim Keys, and review flags survive
unchanged in the original contributions.

Failed and skipped branches contribute no candidates or scores. Successful
empty branches remain empty. Fusion returns an empty tuple when there are no
candidates; the execution record retains the different branch outcomes.

The limits here govern selection from retained branch outputs, not database
query work or the Evidence Assembler's context budget. The dense retriever's
existing `candidate_limit` bounds its vector query independently; the coordinator
can pass `config.dense_candidate_limit` to it. Full-text and structural branches
currently retain all completed matches before fusion. Original Story wording
verification and context limits remain Evidence Assembly's responsibility.

## Verification

`uv run --no-sync pytest -q tests/test_fusion.py` covers structural priority,
text-only evidence, branch accumulation, duplicate routes, configuration and
cutoff behavior, ties, identity preservation, failures, and the unweighted
measurement baseline. It uses fixed ranked candidates and no external services.
