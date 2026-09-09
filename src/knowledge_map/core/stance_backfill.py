"""Supply `alignment` to `DECLARED_STANCE` edges already in the graph.

Every stored stance edge reached the graph without the one property the
ontology says a stance entails.  The Stance Alignment Critic recovers that
property from an Article Chunk, and this module points it at the graph instead
of at an extraction result: it reads the stances that lack an alignment, gives
the critic back the Article Chunk each one was asserted from, and reports what
the critic would write.

The unit of inference is the Article Chunk, not the edge: the critic is shown a
chunk and every stance claimed from it at once, so a chunk asserting four
stances costs one inference rather than four.

An edge asserted by several chunks is judged from each of them, and a
disagreement between them is reported rather than resolved.  A stance the critic
abstained on, and one whose asserting chunks were not all read, are both left
carrying the incomplete Claim Key they arrived with.

What the runs against the stored graph measured is in
`work/initiatives/model-evaluation/research/stance-edges-a-critic-cannot-fix.md`.
"""

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from pydantic_ai import Agent

from knowledge_map.adapters.neo4j_db import _claim_key
from knowledge_map.adapters.stance_alignment import (
    ALIGNMENT_PROPERTY,
    STANCE_RELATIONSHIP_TYPE,
    apply_stance_alignment,
    get_alignment_critic_agent,
)
from knowledge_map.schemas import ModelDeployment, Relationship

logger = logging.getLogger(__name__)


# Only edges missing the property are read: one that already carries an
# alignment was either written by a complete claim or settled by an earlier
# run, and re-deciding it would overwrite a judgement this pass cannot see.
UNALIGNED_STANCES_QUERY = f"""
MATCH (src)-[r:{STANCE_RELATIONSHIP_TYPE}]->(tgt)
WHERE r.{ALIGNMENT_PROPERTY} IS NULL
RETURN elementId(r) AS edge_id,
       src.name AS source,
       tgt.name AS target,
       head(labels(src)) AS source_label,
       head(labels(tgt)) AS target_label,
       coalesce(r.chunks, []) AS chunks
"""

CHUNK_TEXT_QUERY = "MATCH (c:Chunk {id: $chunk_id}) RETURN c.text AS text"

# `needs_review` is the write path's record that the Claim Key was incomplete.
# A normalized alignment completes it, so the stamp goes in the same statement
# that supplies the value -- leaving it behind would mark a settled edge unsettled.
WRITE_ALIGNMENT_QUERY = f"""
MATCH ()-[r:{STANCE_RELATIONSHIP_TYPE}]->()
WHERE elementId(r) = $edge_id
SET r.{ALIGNMENT_PROPERTY} = $alignment
REMOVE r.needs_review
"""


@dataclass(frozen=True)
class StoredStance:
    """A `DECLARED_STANCE` edge in the graph that carries no alignment."""

    edge_id: str
    source: str
    target: str
    source_label: str | None
    target_label: str | None
    chunks: tuple[str, ...]

    def as_relationship(self) -> Relationship:
        """The edge as the critic expects to be shown it."""

        return Relationship(
            source=self.source,
            target=self.target,
            relationship_type=STANCE_RELATIONSHIP_TYPE,
            source_label=self.source_label,
            target_label=self.target_label,
        )


@dataclass
class ProposedAlignment:
    """What the critic would write onto one stored stance, and on what evidence.

    ``alignment`` is the value after the write path's own normalization, so a
    proposal that reads `POSITIVE` here is the string the graph would hold.  It
    is ``None`` when the critic returned nothing usable, when the chunks
    asserting the edge disagreed, or when some of them were never read.
    """

    stance: StoredStance
    alignment: str | None = None
    by_chunk: dict[str, str] = field(default_factory=dict)
    conflicted: bool = False
    unexamined_chunks: tuple[str, ...] = ()

    @property
    def settled(self) -> bool:
        return self.alignment is not None


@dataclass
class BackfillPlan:
    """Every proposal one pass produced, and what the pass cost."""

    proposals: list[ProposedAlignment] = field(default_factory=list)
    call_count: int = 0
    abstained_count: int = 0
    chunks_read: int = 0
    missing_chunk_ids: list[str] = field(default_factory=list)
    written: int = 0

    @property
    def settled(self) -> list[ProposedAlignment]:
        return [p for p in self.proposals if p.settled]

    @property
    def unsettled(self) -> list[ProposedAlignment]:
        return [p for p in self.proposals if not p.settled]

    @property
    def conflicted(self) -> list[ProposedAlignment]:
        return [p for p in self.proposals if p.conflicted]

    @property
    def incomplete(self) -> list[ProposedAlignment]:
        return [p for p in self.proposals if p.unexamined_chunks]


def read_unaligned_stances(session) -> list[StoredStance]:
    """The stored stances the critic has something to add to."""

    return [
        StoredStance(
            edge_id=record["edge_id"],
            source=record["source"],
            target=record["target"],
            source_label=record["source_label"],
            target_label=record["target_label"],
            chunks=tuple(record["chunks"]),
        )
        for record in session.run(UNALIGNED_STANCES_QUERY)
    ]


def group_by_chunk(
    stances: Sequence[StoredStance],
) -> dict[str, list[StoredStance]]:
    """Collect the stances each Article Chunk asserts.

    A stance with no chunk reference is left out: the critic judges from the
    passage, so an edge with no passage behind it has nothing to be judged from.
    """

    grouped: dict[str, list[StoredStance]] = {}
    for stance in stances:
        for chunk_id in stance.chunks:
            grouped.setdefault(chunk_id, []).append(stance)
    return grouped


def _chunk_text(session, chunk_id: str) -> str | None:
    record = session.run(CHUNK_TEXT_QUERY, chunk_id=chunk_id).single()
    if record is None:
        return None
    return record["text"]


def _normalized_alignment(value: object) -> str | None:
    """The alignment as the write path would store it, or nothing.

    Routed through `_claim_key` rather than compared to a local list, so this
    pass cannot propose a value the graph would refuse.
    """

    key, _ = _claim_key(STANCE_RELATIONSHIP_TYPE, {ALIGNMENT_PROPERTY: value})
    return key.get(ALIGNMENT_PROPERTY)


def _verdicts_for_chunk(
    chunk_text: str,
    stances: Sequence[StoredStance],
    agent: Agent | None,
    deployment: ModelDeployment | None,
) -> tuple[dict[str, str], int, int]:
    """Run one critic pass over one chunk, keyed back to the edges it was asked about."""

    result = apply_stance_alignment(
        chunk_text,
        [stance.as_relationship() for stance in stances],
        agent,
        deployment=deployment,
    )
    abstained = result.abstained_count

    # `apply_stance_alignment` returns the relationships in the order it was
    # given them, so position is what carries an alignment back to its edge.
    verdicts: dict[str, str] = {}
    for stance, relationship in zip(stances, result.relationships, strict=True):
        alignment = _normalized_alignment(
            relationship.properties.get(ALIGNMENT_PROPERTY)
        )
        if alignment is not None:
            verdicts[stance.edge_id] = alignment
    return verdicts, result.call_count, abstained


def plan_stance_alignment(
    session,
    *,
    agent: Agent | None = None,
    deployment: ModelDeployment | None = None,
    limit: int | None = None,
) -> BackfillPlan:
    """Decide an alignment for every stored stance that lacks one.

    Reads and infers only; nothing here writes.  ``limit`` caps the number of
    Article Chunks read, which is what a run costs.
    """

    stances = read_unaligned_stances(session)
    by_chunk = group_by_chunk(stances)
    proposals = {stance.edge_id: ProposedAlignment(stance) for stance in stances}

    plan = BackfillPlan(proposals=list(proposals.values()))
    if agent is None and by_chunk:
        agent = get_alignment_critic_agent(deployment)

    examined: set[str] = set()
    for chunk_id in sorted(by_chunk)[: limit if limit is not None else None]:
        text = _chunk_text(session, chunk_id)
        if not text:
            plan.missing_chunk_ids.append(chunk_id)
            logger.warning("Stance backfill: chunk %s has no text in the graph", chunk_id)
            continue
        plan.chunks_read += 1
        examined.add(chunk_id)
        verdicts, calls, abstained = _verdicts_for_chunk(
            text, by_chunk[chunk_id], agent, deployment
        )
        plan.call_count += calls
        plan.abstained_count += abstained
        for edge_id, alignment in verdicts.items():
            proposals[edge_id].by_chunk[chunk_id] = alignment

    for proposal in plan.proposals:
        _settle(proposal, examined)
    return plan


def _settle(proposal: ProposedAlignment, examined: set[str]) -> None:
    """Reduce a stance's per-chunk verdicts to the one value that would be written.

    A chunk that was never read is not evidence that agrees; it is evidence
    nobody looked at, and settling on the rest would write an alignment the run
    never checked against the passages it skipped.  A chunk the critic abstained
    on is different and does not block settlement: it was read, and declining to
    answer is not the same as disagreeing.
    """

    unexamined = tuple(c for c in proposal.stance.chunks if c not in examined)
    if unexamined:
        proposal.unexamined_chunks = unexamined
        return

    distinct = set(proposal.by_chunk.values())
    if len(distinct) == 1:
        proposal.alignment = distinct.pop()
    elif len(distinct) > 1:
        proposal.conflicted = True
        logger.warning(
            "Stance backfill: chunks disagree on %s -> %s: %s",
            proposal.stance.source,
            proposal.stance.target,
            proposal.by_chunk,
        )


def apply_plan(session, plan: BackfillPlan) -> BackfillPlan:
    """Write the settled proposals onto their edges.

    Separate from `plan_stance_alignment` so a run can be inspected before any
    of it reaches the graph.
    """

    for proposal in plan.settled:
        session.run(
            WRITE_ALIGNMENT_QUERY,
            edge_id=proposal.stance.edge_id,
            alignment=proposal.alignment,
        )
        plan.written += 1
    return plan


def backfill_stance_alignment(
    adapter,
    *,
    dry_run: bool = True,
    agent: Agent | None = None,
    deployment: ModelDeployment | None = None,
    limit: int | None = None,
) -> BackfillPlan:
    """Supply `alignment` to the graph's unaligned stances.

    Defaults to a dry run: the plan comes back fully decided and the graph is
    untouched, so what the critic would write can be read before it is trusted.
    """

    driver = adapter.connect()
    with driver.session() as session:
        plan = plan_stance_alignment(
            session, agent=agent, deployment=deployment, limit=limit
        )
        if not dry_run:
            apply_plan(session, plan)
    return plan


def format_plan(plan: BackfillPlan) -> Iterator[str]:
    """The plan as one line per proposal, for reading a run back."""

    for proposal in plan.proposals:
        stance = proposal.stance
        if proposal.alignment:
            verdict = proposal.alignment
        elif proposal.conflicted:
            verdict = "CONFLICT"
        elif proposal.unexamined_chunks:
            verdict = "PARTIAL"
        else:
            verdict = "NONE"
        yield f"{verdict:<8} {stance.source} -> {stance.target}"
