"""The backfill that supplies `alignment` to stances already in the graph."""

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, ToolCallPart

from knowledge_map.core.stance_backfill import (
    BackfillPlan,
    ProposedAlignment,
    StoredStance,
    apply_plan,
    backfill_stance_alignment,
    group_by_chunk,
    plan_stance_alignment,
    read_unaligned_stances,
)
from knowledge_map.schemas import StanceAlignmentVerdict


def _stance(source: str, target: str, *chunks: str, edge_id: str = "") -> StoredStance:
    return StoredStance(
        edge_id=edge_id or f"{source}->{target}",
        source=source,
        target=target,
        source_label="Politician",
        target_label="Bill",
        chunks=chunks,
    )


class FakeSession:
    """Answers the two reads and records the writes, in place of a Neo4j session."""

    def __init__(self, stances: list[StoredStance], chunk_text: dict[str, str]) -> None:
        self._stances = stances
        self._chunk_text = chunk_text
        self.writes: list[dict] = []

    def run(self, query: str, **parameters):
        if "elementId(r) = $edge_id" in query:
            self.writes.append(parameters)
            return _Result([])
        if "c.text" in query:
            text = self._chunk_text.get(parameters["chunk_id"])
            return _Result([{"text": text}] if text is not None else [])
        return _Result(
            [
                {
                    "edge_id": s.edge_id,
                    "source": s.source,
                    "target": s.target,
                    "source_label": s.source_label,
                    "target_label": s.target_label,
                    "chunks": list(s.chunks),
                }
                for s in self._stances
            ]
        )


class _Result:
    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None


def _critic(verdicts: dict[tuple[str, str], str]) -> Agent:
    """A critic that answers from a fixed table, keyed on the claim's endpoints."""

    def respond(messages, info):
        prompt = messages[-1].parts[-1].content
        answers = [
            StanceAlignmentVerdict(source=source, target=target, alignment=alignment)
            for (source, target), alignment in verdicts.items()
            if f"source={source!r}" in prompt and f"target={target!r}" in prompt
        ]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={"response": [a.model_dump() for a in answers]},
                )
            ]
        )

    return Agent(
        FunctionModel(respond),
        output_type=list[StanceAlignmentVerdict],
    )


def test_a_chunk_asserting_several_stances_costs_one_inference() -> None:
    """The unit of inference is the chunk, which is what makes a backfill affordable."""

    stances = [
        _stance("Newsom", "SB 7", "chunk-1"),
        _stance("Isaac Bryan", "AB 1883", "chunk-1"),
    ]
    session = FakeSession(stances, {"chunk-1": "Newsom vetoed SB 7. Bryan authored AB 1883."})
    agent = _critic(
        {("Newsom", "SB 7"): "NEGATIVE", ("Isaac Bryan", "AB 1883"): "POSITIVE"}
    )

    plan = plan_stance_alignment(session, agent=agent)

    assert plan.call_count == 1
    assert plan.chunks_read == 1
    assert {p.stance.target: p.alignment for p in plan.settled} == {
        "SB 7": "NEGATIVE",
        "AB 1883": "POSITIVE",
    }


def test_a_dry_run_decides_everything_and_writes_nothing() -> None:
    stances = [_stance("Newsom", "SB 7", "chunk-1")]
    session = FakeSession(stances, {"chunk-1": "Newsom vetoed SB 7."})

    class FakeAdapter:
        def connect(self):
            return _FakeDriver(session)

    plan = backfill_stance_alignment(
        FakeAdapter(), dry_run=True, agent=_critic({("Newsom", "SB 7"): "NEGATIVE"})
    )

    assert plan.settled[0].alignment == "NEGATIVE"
    assert plan.written == 0
    assert session.writes == []


def test_applying_a_plan_writes_the_alignment_and_clears_needs_review() -> None:
    """`needs_review` recorded the incomplete Claim Key that the alignment completes."""

    stances = [_stance("Newsom", "SB 7", "chunk-1", edge_id="edge-9")]
    session = FakeSession(stances, {"chunk-1": "Newsom vetoed SB 7."})

    plan = plan_stance_alignment(
        session, agent=_critic({("Newsom", "SB 7"): "NEGATIVE"})
    )
    apply_plan(session, plan)

    assert session.writes == [{"edge_id": "edge-9", "alignment": "NEGATIVE"}]
    assert plan.written == 1


def test_chunks_that_disagree_leave_the_stance_unsettled() -> None:
    """A second chunk is more evidence, not a tiebreak this pass is entitled to make."""

    stances = [_stance("Newsom", "SB 7", "chunk-1", "chunk-2")]
    session = FakeSession(
        stances,
        {"chunk-1": "Newsom vetoed SB 7.", "chunk-2": "Newsom praised SB 7."},
    )

    def respond(messages, info):
        prompt = messages[-1].parts[-1].content
        alignment = "NEGATIVE" if "vetoed" in prompt else "POSITIVE"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={
                        "response": [
                            {
                                "source": "Newsom",
                                "target": "SB 7",
                                "alignment": alignment,
                            }
                        ]
                    },
                )
            ]
        )

    agent = Agent(FunctionModel(respond), output_type=list[StanceAlignmentVerdict])
    plan = plan_stance_alignment(session, agent=agent)

    assert plan.conflicted
    assert plan.settled == []
    assert plan.conflicted[0].by_chunk == {
        "chunk-1": "NEGATIVE",
        "chunk-2": "POSITIVE",
    }
    apply_plan(session, plan)
    assert session.writes == []


def test_a_stance_the_critic_skips_is_left_alone() -> None:
    stances = [
        _stance("Newsom", "SB 7", "chunk-1"),
        _stance("Ghost", "AB 1", "chunk-1"),
    ]
    session = FakeSession(stances, {"chunk-1": "Newsom vetoed SB 7."})

    plan = plan_stance_alignment(
        session, agent=_critic({("Newsom", "SB 7"): "NEGATIVE"})
    )

    assert [p.stance.source for p in plan.unsettled] == ["Ghost"]
    assert plan.unsettled[0].alignment is None


def test_a_chunk_missing_from_the_graph_is_reported_not_guessed() -> None:
    stances = [_stance("Newsom", "SB 7", "chunk-gone")]
    session = FakeSession(stances, {})

    plan = plan_stance_alignment(session, agent=_critic({}))

    assert plan.missing_chunk_ids == ["chunk-gone"]
    assert plan.call_count == 0
    assert plan.settled == []


def test_a_stance_with_no_chunk_reference_makes_no_inference() -> None:
    """The critic judges from a passage, so an edge without one has nothing to read."""

    stances = [_stance("Newsom", "SB 7")]
    session = FakeSession(stances, {})

    plan = plan_stance_alignment(session, agent=_critic({}))

    assert plan.call_count == 0
    assert plan.unsettled[0].stance.source == "Newsom"


def test_limit_caps_the_chunks_read() -> None:
    stances = [
        _stance("Newsom", "SB 7", "chunk-1"),
        _stance("Isaac Bryan", "AB 1883", "chunk-2"),
    ]
    session = FakeSession(
        stances, {"chunk-1": "Newsom vetoed SB 7.", "chunk-2": "Bryan authored AB 1883."}
    )

    plan = plan_stance_alignment(
        session,
        agent=_critic(
            {("Newsom", "SB 7"): "NEGATIVE", ("Isaac Bryan", "AB 1883"): "POSITIVE"}
        ),
        limit=1,
    )

    assert plan.chunks_read == 1
    assert len(plan.settled) == 1


def test_limit_leaving_a_chunk_unread_does_not_settle_that_stance() -> None:
    """An unread chunk is evidence nobody looked at, not evidence that agrees.

    Settling on the chunks a capped run happened to reach would write an
    alignment the run never checked against the passages it skipped.
    """

    stances = [_stance("Newsom", "SB 7", "chunk-1", "chunk-2", edge_id="edge-2")]
    session = FakeSession(
        stances,
        {"chunk-1": "Newsom vetoed SB 7.", "chunk-2": "Newsom praised SB 7."},
    )

    plan = plan_stance_alignment(
        session, agent=_critic({("Newsom", "SB 7"): "NEGATIVE"}), limit=1
    )

    assert plan.chunks_read == 1
    assert plan.settled == []
    assert plan.incomplete[0].unexamined_chunks == ("chunk-2",)

    apply_plan(session, plan)
    assert session.writes == []


def test_a_chunk_missing_from_the_graph_blocks_settlement_of_its_stance() -> None:
    """Text the run could not read is unexamined for the same reason."""

    stances = [_stance("Newsom", "SB 7", "chunk-1", "chunk-gone")]
    session = FakeSession(stances, {"chunk-1": "Newsom vetoed SB 7."})

    plan = plan_stance_alignment(
        session, agent=_critic({("Newsom", "SB 7"): "NEGATIVE"})
    )

    assert plan.missing_chunk_ids == ["chunk-gone"]
    assert plan.settled == []
    assert plan.incomplete[0].unexamined_chunks == ("chunk-gone",)


def test_every_chunk_read_settles_even_where_one_abstained() -> None:
    """Abstention is not unexamined evidence: the chunk was read and declined."""

    stances = [_stance("Newsom", "SB 7", "chunk-1", "chunk-2")]
    session = FakeSession(
        stances,
        {"chunk-1": "Newsom vetoed SB 7.", "chunk-2": "SB 7 reached the governor."},
    )

    def respond(messages, info):
        prompt = messages[-1].parts[-1].content
        alignment = "NEGATIVE" if "vetoed" in prompt else "NO_STANCE_STATED"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={
                        "response": [
                            {"source": "Newsom", "target": "SB 7", "alignment": alignment}
                        ]
                    },
                )
            ]
        )

    agent = Agent(FunctionModel(respond), output_type=list[StanceAlignmentVerdict])
    plan = plan_stance_alignment(session, agent=agent)

    assert plan.incomplete == []
    assert plan.settled[0].alignment == "NEGATIVE"


def test_an_alignment_the_write_path_would_refuse_is_not_proposed() -> None:
    """The proposal is normalized the way the graph would store it, or dropped."""

    stances = [_stance("Newsom", "SB 7", "chunk-1")]
    session = FakeSession(stances, {"chunk-1": "Newsom vetoed SB 7."})

    plan = plan_stance_alignment(
        session, agent=_critic({("Newsom", "SB 7"): "NEGATIVE"})
    )

    assert plan.settled[0].alignment == "NEGATIVE"


def test_group_by_chunk_lists_every_chunk_asserting_a_stance() -> None:
    stances = [
        _stance("Newsom", "SB 7", "chunk-1", "chunk-2"),
        _stance("Isaac Bryan", "AB 1883", "chunk-2"),
    ]

    grouped = group_by_chunk(stances)

    assert sorted(grouped) == ["chunk-1", "chunk-2"]
    assert len(grouped["chunk-2"]) == 2


def test_read_unaligned_stances_carries_the_endpoints_and_chunks() -> None:
    stances = [_stance("Newsom", "SB 7", "chunk-1", edge_id="edge-3")]
    session = FakeSession(stances, {})

    read = read_unaligned_stances(session)

    assert read == stances


class _FakeDriver:
    def __init__(self, session) -> None:
        self._session = session

    def session(self):
        return _FakeSessionContext(self._session)


class _FakeSessionContext:
    def __init__(self, session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def test_an_abstained_stance_is_left_unsettled_and_never_written() -> None:
    """A passage that states no direction is not evidence of one."""

    stances = [_stance("Mike Gipson", "AB 1642", "chunk-1", edge_id="edge-7")]
    session = FakeSession(
        stances, {"chunk-1": "AB 1642 passed alongside AB 1795, authored by Mike Gipson."}
    )

    plan = plan_stance_alignment(
        session, agent=_critic({("Mike Gipson", "AB 1642"): "NO_STANCE_STATED"})
    )

    assert plan.settled == []
    assert plan.abstained_count == 1
    assert plan.unsettled[0].alignment is None
    assert plan.unsettled[0].conflicted is False

    apply_plan(session, plan)
    assert session.writes == []


def test_an_abstention_does_not_suppress_the_stances_beside_it() -> None:
    """The critic answers per claim, so one abstention must not cost the chunk."""

    stances = [
        _stance("Mike Gipson", "AB 1642", "chunk-1"),
        _stance("Newsom", "SB 7", "chunk-1"),
    ]
    session = FakeSession(stances, {"chunk-1": "Gipson authored AB 1795. Newsom vetoed SB 7."})

    plan = plan_stance_alignment(
        session,
        agent=_critic(
            {
                ("Mike Gipson", "AB 1642"): "NO_STANCE_STATED",
                ("Newsom", "SB 7"): "NEGATIVE",
            }
        ),
    )

    assert plan.abstained_count == 1
    assert [(p.stance.source, p.alignment) for p in plan.settled] == [
        ("Newsom", "NEGATIVE")
    ]
    assert [p.stance.source for p in plan.unsettled] == ["Mike Gipson"]


def test_an_abstention_on_one_chunk_leaves_another_chunks_direction_standing() -> None:
    """Abstaining is declining to answer, not disagreeing with the answer."""

    stances = [_stance("Newsom", "SB 7", "chunk-1", "chunk-2")]
    session = FakeSession(
        stances,
        {"chunk-1": "Newsom vetoed SB 7.", "chunk-2": "SB 7 reached the governor."},
    )

    def respond(messages, info):
        prompt = messages[-1].parts[-1].content
        alignment = "NEGATIVE" if "vetoed" in prompt else "NO_STANCE_STATED"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={
                        "response": [
                            {"source": "Newsom", "target": "SB 7", "alignment": alignment}
                        ]
                    },
                )
            ]
        )

    agent = Agent(FunctionModel(respond), output_type=list[StanceAlignmentVerdict])
    plan = plan_stance_alignment(session, agent=agent)

    assert plan.conflicted == []
    assert plan.settled[0].alignment == "NEGATIVE"
    assert plan.abstained_count == 1
