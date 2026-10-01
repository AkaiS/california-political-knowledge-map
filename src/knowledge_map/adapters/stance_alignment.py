"""The Stance Alignment Critic: a second pass that supplies a stance's direction.

The Entity Extraction agent produces `DECLARED_STANCE` claims whose endpoints
and type are right and whose `properties` is always `{}`, so the alignment is
asked for after the fact instead: the critic is shown one Article Chunk and only
the stance claims already extracted from it, and returns the direction of each,
or abstains where the passage states none.

One agent, one verdict per listed item, identity fields copied so a verdict can
be matched back to what it was asked about, and anything unmatched discarded
rather than trusted.  It never sees the extraction prompt, the ontology, or the
non-stance claims.

Why the extraction prompt is not the lever here, and what this pass was measured
to recover and to miss, is in
`work/initiatives/model-evaluation/research/stance-edges-a-critic-cannot-fix.md`.
"""

import logging
from collections.abc import Sequence

from pydantic_ai import Agent

from knowledge_map.prompts import load_prompt
from knowledge_map.schemas import (
    ModelDeployment,
    Relationship,
    StanceAlignmentVerdict,
)
from knowledge_map.utils.agents import create_agent
from knowledge_map.utils.models import DEFAULT_LOCAL_CHAT_MODEL, get_chat_model

logger = logging.getLogger(__name__)

STANCE_RELATIONSHIP_TYPE = "DECLARED_STANCE"
ALIGNMENT_PROPERTY = "alignment"


CRITIC_INSTRUCTIONS = (
    load_prompt("stance-alignment/critic-instructions", version=1)
)

#: The verdict that supplies no alignment.  Kept out of the ontology's
#: vocabulary so nothing downstream can mistake it for a direction.
ABSTENTION = "NO_STANCE_STATED"


def stance_claims(relationships: Sequence[Relationship]) -> list[Relationship]:
    """The `DECLARED_STANCE` claims out of an extraction's relationships."""

    return [
        relationship
        for relationship in relationships
        if relationship.relationship_type == STANCE_RELATIONSHIP_TYPE
    ]


def format_stance_claims(relationships: Sequence[Relationship]) -> str:
    """Render stance claims as the compact input to the Stance Alignment Critic."""

    return "\n".join(
        load_prompt("stance-alignment/claim", version=1).format(
            source=relationship.source, target=relationship.target
        )
        for relationship in relationships
    )


def critic_prompt(chunk_text: str, relationships: Sequence[Relationship]) -> str:
    """Ask for one alignment per listed claim, against the chunk it came from."""

    return load_prompt("stance-alignment/critic-request", version=1).format(
        chunk_text=chunk_text, claims=format_stance_claims(relationships)
    )


def get_alignment_critic_agent(
    deployment: ModelDeployment | None = None,
    *,
    defer_check: bool = True,
    retries: int = 3,
) -> Agent:
    """Build the Stance Alignment Critic from one explicit deployment."""

    model = (
        get_chat_model(deployment)
        if deployment is not None
        else get_chat_model(DEFAULT_LOCAL_CHAT_MODEL)
    )
    return create_agent(
        model,
        name="stance_alignment_critic",
        output_type=list[StanceAlignmentVerdict],
        instructions=CRITIC_INSTRUCTIONS,
        defer_model_check=defer_check,
        retries=retries,
    )


ClaimIdentity = tuple[str, str]


def _claim_identity(source: str, target: str) -> ClaimIdentity:
    """A stance claim's identity here: its two endpoint names, folded.

    The same folding the extraction report uses, so a verdict that differs from
    the claim only in case or spacing still lands on it.  A shortened endpoint
    name stays a mismatch and the verdict is dropped.
    """

    return (" ".join(source.split()).casefold(), " ".join(target.split()).casefold())


def _matching_verdicts(
    relationships: Sequence[Relationship],
    verdicts: Sequence[StanceAlignmentVerdict],
) -> dict[ClaimIdentity, StanceAlignmentVerdict]:
    """Keep only verdicts whose identity was sent to the critic."""

    asked = {
        _claim_identity(relationship.source, relationship.target)
        for relationship in relationships
    }
    matching: dict[ClaimIdentity, StanceAlignmentVerdict] = {}
    for verdict in verdicts:
        identity = _claim_identity(verdict.source, verdict.target)
        if verdict.alignment == ABSTENTION:
            # An abstention is a verdict, but not an alignment: dropping it
            # here is what leaves the claim exactly as the producer wrote it.
            continue
        if identity in asked:
            matching[identity] = verdict
        else:
            logger.warning(
                "Stance Alignment Critic returned a verdict for a claim it was "
                "not asked about: %s -> %s",
                verdict.source,
                verdict.target,
            )
    return matching


class StanceAlignmentResult:
    """One critic pass over an Article Chunk's relationships.

    ``call_count`` is 0 or 1 and is carried because the whole cost of this pass
    is the extra inference it makes: a chunk with no stance claim must not pay
    for one.

    ``abstained_count`` is how many stances the critic declined to align.  It
    is reported rather than inferred from the difference between the claims and
    ``aligned_count``, which also absorbs verdicts dropped for not matching.
    """

    __slots__ = ("abstained_count", "aligned_count", "call_count", "relationships")

    def __init__(
        self,
        relationships: list[Relationship],
        call_count: int,
        aligned_count: int,
        abstained_count: int = 0,
    ) -> None:
        self.relationships = relationships
        self.call_count = call_count
        self.aligned_count = aligned_count
        self.abstained_count = abstained_count


def apply_stance_alignment(
    chunk_text: str,
    relationships: Sequence[Relationship],
    agent: Agent | None = None,
    *,
    deployment: ModelDeployment | None = None,
) -> StanceAlignmentResult:
    """Return the relationships with `alignment` written onto their stances.

    Every non-stance relationship, and every stance the critic abstained on or
    returned no usable verdict for, is passed through untouched -- this pass
    adds a property and is never allowed to subtract a claim.  A stance left
    unaligned keeps the incomplete Claim Key it arrived with, which is the
    honest record of a passage that never stated a direction.
    """

    claims = stance_claims(relationships)
    if not claims:
        return StanceAlignmentResult(list(relationships), 0, 0)

    if agent is None:
        agent = get_alignment_critic_agent(deployment)

    result = agent.run_sync(critic_prompt(chunk_text, claims))
    matching = _matching_verdicts(claims, result.output)
    abstained = sum(1 for v in result.output if v.alignment == ABSTENTION)

    aligned = 0
    updated: list[Relationship] = []
    for relationship in relationships:
        verdict = (
            matching.get(_claim_identity(relationship.source, relationship.target))
            if relationship.relationship_type == STANCE_RELATIONSHIP_TYPE
            else None
        )
        if verdict is None:
            updated.append(relationship)
            continue
        aligned += 1
        updated.append(
            relationship.model_copy(
                update={
                    "properties": {
                        **relationship.properties,
                        ALIGNMENT_PROPERTY: verdict.alignment,
                    }
                }
            )
        )
    return StanceAlignmentResult(updated, 1, aligned, abstained)
