"""Configuration for graph-prioritized reciprocal-rank fusion."""

from typing import Annotated, Self

from pydantic import Field, FiniteFloat, model_validator

from knowledge_map.schemas.retrieval import RetrievalValue

type Weight = Annotated[FiniteFloat, Field(strict=True, gt=0)]
type CandidateLimit = Annotated[int, Field(strict=True, ge=1)]


class FusionConfig(RetrievalValue):
    full_text_weight: Weight = 1.0
    dense_weight: Weight = 1.0
    structural_weight: Weight = 2.0
    rank_constant: Annotated[FiniteFloat, Field(strict=True, ge=0)] = 60.0
    full_text_candidate_limit: CandidateLimit = 50
    dense_candidate_limit: CandidateLimit = 50
    structural_candidate_limit: CandidateLimit = 50
    fused_candidate_limit: CandidateLimit = 100

    @model_validator(mode="after")
    def require_structural_priority(self) -> Self:
        if self.structural_weight <= max(self.full_text_weight, self.dense_weight):
            raise ValueError("structural weight must exceed each text-branch weight")
        return self
