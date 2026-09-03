"""Topic Assignment, decided once per Source Article after extraction.

Drives the assignment schema, the two drops that stand between a model's answer
and persistence, and the Pydantic AI adapter that produces it.  The pipeline's
own use of the stage is asserted in ``test_pipeline.py``.
"""

import pytest
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel

import knowledge_map.adapters.policy_areas as policy_area_adapter_module
from knowledge_map.adapters.policy_areas import (
    PydanticAIPolicyAreaAdapter,
    TopicAssignmentError,
    get_assignment_agent,
)
from knowledge_map.core.topic_assignment import (
    extracted_measures,
    supported_assignments,
)
from knowledge_map.schemas import (
    DeploymentKind,
    ExtractionResult,
    ModelDeployment,
    ModelRequestSettings,
    Node,
    IngestionArticle,
    TopicAssignment,
)

ARTICLE = IngestionArticle(
    url="http://test.com/rent",
    title="Rent and clinics",
    content="SB 623 would cap rent increases.",
)

MEASURES = [Node(name="SB 623", label="Bill")]


def _assigner(answer: dict):
    """An assignment agent whose model returns ``answer`` verbatim."""

    def model(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=answer)]
        )

    return FunctionModel(model)


def test_the_adapter_returns_the_assignments_the_article_supports():
    adapter = PydanticAIPolicyAreaAdapter(assignment_agent=get_assignment_agent())
    answer = {
        "assignments": [
            {
                "measure_name": "SB 623",
                "measure_label": "Bill",
                "policy_area": "Housing & Community Development",
            }
        ]
    }

    with adapter.assignment_agent.override(model=_assigner(answer)):
        assignments = adapter.assign(
            ARTICLE, ["Housing & Community Development"], MEASURES
        )

    assert assignments == [
        TopicAssignment(
            measure_name="SB 623",
            measure_label="Bill",
            policy_area="Housing & Community Development",
        )
    ]


def test_an_article_connecting_no_measure_to_an_area_assigns_nothing():
    adapter = PydanticAIPolicyAreaAdapter(assignment_agent=get_assignment_agent())

    with adapter.assignment_agent.override(model=_assigner({"assignments": []})):
        assert adapter.assign(ARTICLE, ["Health"], MEASURES) == []


def test_an_unusable_answer_raises_the_stage_specific_failure():
    adapter = PydanticAIPolicyAreaAdapter(
        assignment_agent=get_assignment_agent(retries=0)
    )
    answer = {"assignments": [{"measure_name": "SB 623", "measure_label": "Statute"}]}

    with adapter.assignment_agent.override(model=_assigner(answer)):
        with pytest.raises(TopicAssignmentError) as failure:
            adapter.assign(ARTICLE, ["Health"], MEASURES)

    assert failure.value.original_text == ARTICLE.content
    assert failure.value.validation_issues


def test_a_transport_failure_reaches_the_pipeline_untouched():
    """The stage's transport failures are classified by the pipeline's own
    connectivity and rate-limit handling, as every other stage call is."""

    def failing_model(messages, info):
        raise ModelHTTPError(status_code=429, model_name="remote-model", body=None)

    adapter = PydanticAIPolicyAreaAdapter(assignment_agent=get_assignment_agent())

    with adapter.assignment_agent.override(model=FunctionModel(failing_model)):
        with pytest.raises(ModelHTTPError):
            adapter.assign(ARTICLE, ["Health"], MEASURES)


def _assignment(measure_name="SB 623", measure_label="Bill", policy_area="Health"):
    return TopicAssignment(
        measure_name=measure_name,
        measure_label=measure_label,
        policy_area=policy_area,
    )


def test_the_measures_handed_to_assignment_are_the_bills_and_props_extracted():
    extractions = [
        ExtractionResult(
            nodes=[
                Node(name="SB 623", label="Bill"),
                Node(name="Gavin Newsom", label="Politician"),
            ],
            relationships=[],
        ),
        ExtractionResult(nodes=[Node(name="Proposition 13", label="Prop")]),
    ]

    assert extracted_measures(extractions) == [
        Node(name="SB 623", label="Bill"),
        Node(name="Proposition 13", label="Prop"),
    ]


def test_one_measure_named_by_two_chunks_is_handed_over_once():
    """Assignment sees the article's measures, not one entry per mention."""

    extractions = [
        ExtractionResult(nodes=[Node(name="SB 623", label="Bill")]),
        ExtractionResult(nodes=[Node(name="SB 623", label="Bill")]),
    ]

    assert extracted_measures(extractions) == [Node(name="SB 623", label="Bill")]


def test_an_assignment_naming_an_extracted_measure_and_a_classified_area_survives():
    assignment = _assignment()

    assert supported_assignments([assignment], MEASURES, ["Health"]) == [assignment]


def test_an_assignment_naming_a_measure_no_extraction_produced_is_dropped():
    """A hallucinated endpoint cannot mint a node behind the write path's back."""

    assignment = _assignment(measure_name="SB 999")

    assert supported_assignments([assignment], MEASURES, ["Health"]) == []


def test_an_assignment_naming_a_measure_under_the_wrong_label_is_dropped():
    assignment = _assignment(measure_label="Prop")

    assert supported_assignments([assignment], MEASURES, ["Health"]) == []


def test_an_assignment_naming_an_area_outside_the_classified_set_is_dropped():
    """The two stages cannot contradict each other in the graph."""

    assignment = _assignment(policy_area="Water")

    assert supported_assignments([assignment], MEASURES, ["Health"]) == []


def test_every_assignment_is_dropped_when_the_article_has_no_areas():
    assert supported_assignments([_assignment()], MEASURES, []) == []


def test_a_repeated_assignment_reaches_persistence_once():
    assignment = _assignment()

    assert supported_assignments([assignment, assignment], MEASURES, ["Health"]) == [
        assignment
    ]


def test_the_assignment_agent_is_built_from_an_explicit_deployment(monkeypatch):
    """Its own agent and its own Model Deployment, as classification has."""

    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="explicit-local-model",
        request_settings=ModelRequestSettings(),
        endpoint="http://explicit.test:9999/v1",
    )
    seen: list[object] = []
    model = FunctionModel(lambda messages, info: ModelResponse(parts=[]))

    def model_factory(requested):
        seen.append(requested)
        return model

    monkeypatch.setattr(policy_area_adapter_module, "get_chat_model", model_factory)

    agent = get_assignment_agent(deployment)

    assert seen == [deployment]
    assert agent.model is model


def test_the_two_stages_run_on_their_own_agents():
    adapter = PydanticAIPolicyAreaAdapter()

    assert adapter.assignment_agent is not adapter.agent
