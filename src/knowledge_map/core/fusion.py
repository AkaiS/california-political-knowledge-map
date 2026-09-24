"""Combine retained branch ranks into Grounding Evidence candidates."""

from math import fsum

from knowledge_map.retrieval_telemetry import record_selection
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    FusedCandidate,
    RetrievalBranch,
    RetrievalExecutionResult,
)


def fuse_candidates(
    execution: RetrievalExecutionResult,
    *,
    config: FusionConfig | None = None,
    unweighted_baseline: bool = False,
) -> tuple[FusedCandidate, ...]:
    config = config or FusionConfig()
    weights = {
        RetrievalBranch.FULL_TEXT: config.full_text_weight,
        RetrievalBranch.DENSE: config.dense_weight,
        RetrievalBranch.STRUCTURAL: config.structural_weight,
    }
    limits = {
        RetrievalBranch.FULL_TEXT: config.full_text_candidate_limit,
        RetrievalBranch.DENSE: config.dense_candidate_limit,
        RetrievalBranch.STRUCTURAL: config.structural_candidate_limit,
    }
    contributions: dict[str, list[BranchCandidate]] = {}
    best_ranks: dict[str, dict[RetrievalBranch, int]] = {}
    eligible: set[str] = set()
    eligible_branches: dict[str, object] = {}
    for branch in RetrievalBranch:
        branch_ranks: dict[str, int] = {}
        for candidate in execution.evidence_by_branch.get(branch, ()):
            contributions.setdefault(candidate.chunk_id, []).append(candidate)
            ranks = best_ranks.setdefault(candidate.chunk_id, {})
            ranks[branch] = min(
                ranks.get(branch, candidate.ranking.rank), candidate.ranking.rank
            )
            branch_ranks[candidate.chunk_id] = ranks[branch]
        branch_ids = sorted(
            branch_ranks, key=lambda chunk: (branch_ranks[chunk], chunk)
        )[: limits[branch]]
        eligible.update(branch_ids)
        eligible_branches[branch.value] = {
            "count": len(branch_ids),
            "chunk_ids": branch_ids,
        }
    record_selection(eligible_branches=eligible_branches)
    ranked = sorted(
        (
            (
                chunk_id,
                fsum(
                    (1.0 if unweighted_baseline else weights[branch])
                    / (config.rank_constant + rank)
                    for branch, rank in ranks.items()
                ),
            )
            for chunk_id, ranks in best_ranks.items()
            if chunk_id in eligible
        ),
        key=lambda item: (-item[1], item[0]),
    )
    fused = tuple(
        FusedCandidate(
            chunk_id=chunk_id,
            rank=rank,
            fusion_score=score,
            contributions=tuple(contributions[chunk_id]),
        )
        for rank, (chunk_id, score) in enumerate(
            ranked[: config.fused_candidate_limit], start=1
        )
    )
    record_selection(fused_chunk_ids=[candidate.chunk_id for candidate in fused])
    return fused
