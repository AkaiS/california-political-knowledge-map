"""Combine retained branch ranks into Grounding Evidence candidates."""

from collections.abc import Collection, Iterable, Mapping, Sequence
from math import fsum

from knowledge_map.retrieval_telemetry import record_selection
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    FusedCandidate,
    RetrievalBranch,
    RetrievalExecutionResult,
)


def _prepare_ranking(
    ranks_by_branch: Mapping[RetrievalBranch, Iterable[tuple[str, int]]],
    *,
    config: FusionConfig,
    nomination_pools: Mapping[RetrievalBranch, Collection[str]] | None = None,
    recorded_eligibility: Mapping[RetrievalBranch, Sequence[str]] | None = None,
) -> tuple[dict[RetrievalBranch, dict[str, int]], dict[RetrievalBranch, list[str]]]:
    best_ranks: dict[RetrievalBranch, dict[str, int]] = {}
    eligible_by_branch: dict[RetrievalBranch, list[str]] = {}
    for branch in RetrievalBranch:
        branch_ranks: dict[str, int] = {}
        for chunk, rank in ranks_by_branch.get(branch, ()):
            branch_ranks[chunk] = min(branch_ranks.get(chunk, rank), rank)
        best_ranks[branch] = dict(
            sorted(branch_ranks.items(), key=lambda item: (item[1], item[0]))
        )
        # Retained tail ranks can contribute without becoming new nominations.
        pool = (nomination_pools or {}).get(branch, best_ranks[branch])
        branch_ids = (
            list(recorded_eligibility[branch])
            if recorded_eligibility is not None and branch in recorded_eligibility
            else [chunk for chunk in best_ranks[branch] if chunk in pool][
                : getattr(config, f"{branch.value}_candidate_limit")
            ]
        )
        eligible_by_branch[branch] = branch_ids
    return best_ranks, eligible_by_branch


def _rank_candidates(
    best_ranks: Mapping[RetrievalBranch, Mapping[str, int]],
    eligible_by_branch: Mapping[RetrievalBranch, Sequence[str]],
    *,
    config: FusionConfig,
    unweighted_baseline: bool = False,
) -> list[tuple[str, float]]:
    eligible = {chunk for chunks in eligible_by_branch.values() for chunk in chunks}
    contributions: dict[str, dict[RetrievalBranch, int]] = {}
    for branch, ranks in best_ranks.items():
        for chunk, rank in ranks.items():
            if chunk in eligible:
                contributions.setdefault(chunk, {})[branch] = rank
    ranked = sorted(
        (
            (
                chunk_id,
                fsum(
                    (
                        1.0
                        if unweighted_baseline
                        else getattr(config, f"{branch.value}_weight")
                    )
                    / (config.rank_constant + rank)
                    for branch, rank in ranks.items()
                ),
            )
            for chunk_id, ranks in contributions.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return ranked[: config.fused_candidate_limit]


def fuse_candidates(
    execution: RetrievalExecutionResult,
    *,
    config: FusionConfig | None = None,
    unweighted_baseline: bool = False,
) -> tuple[FusedCandidate, ...]:
    config = config or FusionConfig()
    contributions: dict[str, list[BranchCandidate]] = {}
    ranks_by_branch = {}
    evidence_by_branch = execution.evidence_by_branch
    for branch in RetrievalBranch:
        candidates = evidence_by_branch.get(branch, ())
        for candidate in candidates:
            contributions.setdefault(candidate.chunk_id, []).append(candidate)
        ranks_by_branch[branch] = [
            (candidate.chunk_id, candidate.ranking.rank) for candidate in candidates
        ]
    best_ranks, eligible_by_branch = _prepare_ranking(ranks_by_branch, config=config)
    record_selection(
        eligible_branches={
            branch.value: {"count": len(chunk_ids), "chunk_ids": chunk_ids}
            for branch, chunk_ids in eligible_by_branch.items()
        }
    )
    ranked = _rank_candidates(
        best_ranks,
        eligible_by_branch,
        config=config,
        unweighted_baseline=unweighted_baseline,
    )
    fused = tuple(
        FusedCandidate(
            chunk_id=chunk_id,
            rank=rank,
            fusion_score=score,
            contributions=tuple(contributions[chunk_id]),
        )
        for rank, (chunk_id, score) in enumerate(ranked, start=1)
    )
    record_selection(fused_chunk_ids=[candidate.chunk_id for candidate in fused])
    return fused
