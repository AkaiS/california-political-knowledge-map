"""Limits for the original evidence context supplied to the Chat Agent."""

from typing import Annotated

from pydantic import Field

from knowledge_map.schemas.retrieval import RetrievalValue


class EvidenceContextLimits(RetrievalValue):
    character_limit: Annotated[int, Field(strict=True, ge=1)] = 24000
    max_passages: Annotated[int, Field(strict=True, ge=1)] = 12
