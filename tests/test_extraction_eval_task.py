"""The extraction evaluators score the things they claim to score."""

import pytest
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_evals.evaluators import EvaluatorContext

import knowledge_map.adapters.extraction as extraction_adapter_module
import knowledge_map.evaluation.tasks.extraction as extraction_task_module
from knowledge_map.evaluation.tasks import task_named
from knowledge_map.evaluation.tasks.extraction import (
    AgreedOnTheClaimProperties,
    AgreedOnTheNodeDetail,
    AgreedOnTheStanceAlignment,
    ExtractedWithoutFailing,
    ExtractionExpectation,
    ExtractionInput,
    ExtractionOutput,
    FoundTheSilverNodes,
    FoundTheSilverRelationships,
    StayedInsideTheNewsOntology,
    node_identity,
    relationship_identity,
)
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    ModelRequestSettings,
    Node,
    Relationship,
)


def _node(name: str, label: str = "Organization", subs=(), **properties) -> Node:
    return Node(name=name, label=label, sub_labels=list(subs), properties=properties)


def _relationship(source: str, rtype: str, target: str, **properties) -> Relationship:
    return Relationship(
        source=source, target=target, relationship_type=rtype, properties=properties
    )


def _context(expected: ExtractionExpectation, output: ExtractionOutput):
    """One EvaluatorContext holding a silver answer and a model answer."""

    return EvaluatorContext(
        name="case",
        inputs=ExtractionInput(
            url="https://example.test/a", title="A", chunk_index=0, text="a"
        ),
        metadata=None,
        expected_output=expected,
        output=output,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def _scored(evaluator, *, expected_nodes=(), nodes=(), expected_edges=(), edges=(), **output_kwargs):
    return evaluator.evaluate(
        _context(
            ExtractionExpectation(
                nodes=list(expected_nodes), relationships=list(expected_edges)
            ),
            ExtractionOutput(
                nodes=list(nodes), relationships=list(edges), **output_kwargs
            ),
        )
    )


def test_every_evaluator_returns_a_type_pydantic_evals_accepts() -> None:
    """`None` raises per case, which would empty the report of those scores."""

    from pydantic_evals.evaluators._run_evaluator import (
        _EVALUATOR_OUTPUT_ADAPTER as adapter,
    )

    for evaluator in task_named("extraction").evaluators:
        for kwargs in (
            {},
            {"expected_nodes": [_node("Uber")], "nodes": [_node("Uber")]},
        ):
            adapter.validate_python(_scored(evaluator, **kwargs))


def test_extraction_is_a_registered_task_with_its_seven_evaluators() -> None:
    task = task_named("extraction")

    assert task.data_set_stem == "extraction"
    assert task.input_type is ExtractionInput
    assert task.output_type is ExtractionExpectation
    assert [type(evaluator).__name__ for evaluator in task.evaluators] == [
        "FoundTheSilverNodes",
        "AgreedOnTheNodeDetail",
        "FoundTheSilverRelationships",
        "AgreedOnTheClaimProperties",
        "AgreedOnTheStanceAlignment",
        "StayedInsideTheNewsOntology",
        "ExtractedWithoutFailing",
    ]


def test_an_identical_answer_scores_one_everywhere() -> None:
    nodes = [_node("Uber", "Organization", ["Corporation"]), _node("SB 371", "Bill")]
    edges = [_relationship("Uber", "LOBBIED_FOR", "SB 371")]

    assert _scored(
        FoundTheSilverNodes(), expected_nodes=nodes, nodes=nodes
    ) == {"node_precision": 1.0, "node_recall": 1.0, "node_f1": 1.0}
    assert _scored(
        FoundTheSilverRelationships(),
        expected_nodes=nodes,
        nodes=nodes,
        expected_edges=edges,
        edges=edges,
    ) == {
        "relationship_precision": 1.0,
        "relationship_recall": 1.0,
        "relationship_f1": 1.0,
    }


def test_an_empty_chunk_both_sides_left_empty_scores_one() -> None:
    """A chunk supporting nothing is a case to pass, not a case to skip."""

    assert _scored(FoundTheSilverNodes()) == {
        "node_precision": 1.0,
        "node_recall": 1.0,
        "node_f1": 1.0,
    }
    assert _scored(FoundTheSilverRelationships()) == {
        "relationship_precision": 1.0,
        "relationship_recall": 1.0,
        "relationship_f1": 1.0,
    }


def test_inventing_an_entity_on_an_empty_chunk_costs_precision() -> None:
    scores = _scored(FoundTheSilverNodes(), nodes=[_node("Uber")])

    assert scores["node_precision"] == 0.0
    assert scores["node_recall"] == 0.0


def test_a_missed_entity_costs_recall_and_leaves_precision_whole() -> None:
    scores = _scored(
        FoundTheSilverNodes(),
        expected_nodes=[_node("Uber"), _node("Consumer Watchdog")],
        nodes=[_node("Uber")],
    )

    assert scores["node_precision"] == 1.0
    assert scores["node_recall"] == 0.5


def test_the_label_is_part_of_a_node_identity() -> None:
    scores = _scored(
        FoundTheSilverNodes(),
        expected_nodes=[_node("Katie Porter", "Politician")],
        nodes=[_node("Katie Porter", "Organization")],
    )

    assert scores["node_f1"] == 0.0


@pytest.mark.parametrize("written", ["CalMatters", "calmatters", "  CalMatters  "])
def test_case_and_whitespace_are_not_a_disagreement(written: str) -> None:
    assert node_identity(_node(written)) == node_identity(_node("CalMatters"))


def test_a_shortened_name_is_a_disagreement_here() -> None:
    assert node_identity(_node("Newsom", "Politician")) != node_identity(
        _node("Gavin Newsom", "Politician")
    )


def test_sub_labels_are_scored_only_over_the_nodes_both_sides_found() -> None:
    scores = _scored(
        AgreedOnTheNodeDetail(),
        expected_nodes=[
            _node("Teamsters", subs=["LaborUnion"]),
            _node("UPS", subs=["Corporation"]),
        ],
        nodes=[_node("Teamsters", subs=["Corporation"])],
    )

    assert scores == {"sub_label_accuracy": 0.0}


def test_node_properties_are_scored_only_where_silver_declares_one() -> None:
    scores = _scored(
        AgreedOnTheNodeDetail(),
        expected_nodes=[
            _node("Jasmeet Bains", "Politician", current_party="Democrat"),
            _node("Digital Democracy"),
        ],
        nodes=[
            _node("Jasmeet Bains", "Politician", current_party="Democrat"),
            _node("Digital Democracy", current_party="Republican"),
        ],
    )

    assert scores == {"sub_label_accuracy": 1.0, "node_property_accuracy": 1.0}


def test_node_detail_is_unscored_when_nothing_overlaps() -> None:
    """Unscored is an empty mapping: `pydantic-evals` rejects `None` outright."""

    assert (
        _scored(
            AgreedOnTheNodeDetail(),
            expected_nodes=[_node("Teamsters")],
            nodes=[_node("UPS")],
        )
        == {}
    )


def test_endpoint_labels_are_not_part_of_a_claim_identity() -> None:
    """A mislabeled endpoint is already counted against the node score."""

    claimed = Relationship(
        source="Uber",
        target="SB 371",
        relationship_type="LOBBIED_FOR",
        source_label="Organization",
        target_label="Bill",
    )

    assert relationship_identity(claimed) == relationship_identity(
        _relationship("Uber", "LOBBIED_FOR", "SB 371")
    )


def test_the_relationship_type_is_part_of_a_claim_identity() -> None:
    scores = _scored(
        FoundTheSilverRelationships(),
        expected_edges=[_relationship("Uber", "LOBBIED_FOR", "SB 371")],
        edges=[_relationship("Uber", "LOBBIED_AGAINST", "SB 371")],
    )

    assert scores["relationship_f1"] == 0.0


def test_a_wrong_alignment_on_a_found_claim_is_scored_as_disagreement() -> None:
    scores = _scored(
        AgreedOnTheClaimProperties(),
        expected_edges=[
            _relationship("Gavin Newsom", "DECLARED_STANCE", "SB 7", alignment="NEGATIVE")
        ],
        edges=[
            _relationship("Gavin Newsom", "DECLARED_STANCE", "SB 7", alignment="POSITIVE")
        ],
    )

    assert scores == {"claim_property_accuracy": 0.0}


def test_claim_properties_are_unscored_when_silver_declares_none() -> None:
    edges = [_relationship("Uber", "LOBBIED_FOR", "SB 371")]

    assert (
        _scored(AgreedOnTheClaimProperties(), expected_edges=edges, edges=edges) == {}
    )


def test_a_conformed_away_item_is_reported_even_though_nothing_else_sees_it() -> None:
    assert _scored(StayedInsideTheNewsOntology()) is True
    assert _scored(StayedInsideTheNewsOntology(), dropped_item_count=2) is False


def test_a_failed_run_scores_zero_rather_than_disappearing() -> None:
    expected = [_node("Uber")]

    assert _scored(ExtractedWithoutFailing()) is True
    assert (
        _scored(ExtractedWithoutFailing(), failure_type="extraction_validation_failure")
        is False
    )
    scores = _scored(
        FoundTheSilverNodes(),
        expected_nodes=expected,
        failure_type="extraction_validation_failure",
    )
    assert scores["node_recall"] == 0.0


def _local_deployment() -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="explicit-evaluation-extraction-model",
        endpoint="http://explicit-evaluation-extraction.test:9999",
        request_settings=ModelRequestSettings(thinking=False),
    )


def _extraction_response(info, nodes: list[dict], relationships: list[dict]):
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"nodes": nodes, "relationships": relationships},
                tool_call_id="call-1",
            )
        ]
    )


def test_the_task_binds_one_explicit_deployment_and_conforms_each_chunk(monkeypatch):
    """One agent for the run, one Adherence Report per chunk."""

    seen: list[object] = []

    def model_factory(requested, *args, **kwargs):
        seen.append(requested)
        assert isinstance(requested, ModelDeployment)

        def respond(messages, info):
            return _extraction_response(
                info,
                [
                    {"name": "Uber", "label": "Organization", "sub_labels": ["Corporation"]},
                    {"name": "This Story", "label": "NewsArticle"},
                ],
                [],
            )

        return FunctionModel(respond)

    deployment = _local_deployment()
    monkeypatch.setenv("LLAMA_CPP_MODEL", "ambient-local-model")
    monkeypatch.setattr(extraction_adapter_module, "get_chat_model", model_factory)

    extract = extraction_task_module.build_task(deployment, None)
    chunk = ExtractionInput(
        url="https://example.test/extraction", title="A story", chunk_index=3, text="Uber."
    )

    first = extract(chunk)
    second = extract(chunk)

    assert seen == [deployment]
    assert [node.name for node in first.nodes] == ["Uber"]
    assert first.dropped_item_count == 1
    assert second.dropped_item_count == 1


def test_a_bare_stance_and_an_aligned_one_are_one_claim_to_the_f1_score() -> None:
    """Why the alignment needs its own score.

    `relationship_identity` keys on endpoints and type, so a stance carrying
    no alignment at all is counted found. The alignment score is the only
    place the difference is visible.
    """

    expected = [_relationship("Newsom", "DECLARED_STANCE", "SB 7", alignment="NEGATIVE")]
    bare = [_relationship("Newsom", "DECLARED_STANCE", "SB 7")]

    assert _scored(
        FoundTheSilverRelationships(), expected_edges=expected, edges=bare
    )["relationship_f1"] == 1.0
    assert _scored(
        AgreedOnTheStanceAlignment(), expected_edges=expected, edges=bare
    ) == {"stance_alignment_accuracy": 0.0}


def test_the_critic_supplying_the_wanted_alignment_scores_one() -> None:
    expected = [_relationship("Newsom", "DECLARED_STANCE", "SB 7", alignment="NEGATIVE")]

    assert _scored(
        AgreedOnTheStanceAlignment(), expected_edges=expected, edges=expected
    ) == {"stance_alignment_accuracy": 1.0}


def test_stance_alignment_is_unscored_where_silver_declares_no_stance() -> None:
    edges = [_relationship("Uber", "LOBBIED_FOR", "SB 371", amount="$1")]

    assert _scored(AgreedOnTheStanceAlignment(), expected_edges=edges, edges=edges) == {}
