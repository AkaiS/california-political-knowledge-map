"""Policy Area Classification, decided once per Source Article.

Drives the classification schema and the Pydantic AI adapter that produces it.
Nothing here asserts prompt wording or call counts; the pipeline's own use of
the stage is asserted in ``test_pipeline.py`` and ``test_article_topics.py``.
"""

import inspect

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel

import knowledge_map.adapters.policy_areas as policy_area_adapter_module
from knowledge_map.adapters.policy_areas import (
    PolicyAreaClassificationError,
    PydanticAIPolicyAreaAdapter,
    get_classification_agent,
)
from knowledge_map.core.pipeline import PolicyAreaAdapter
from knowledge_map.ontology import news
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    ModelRequestSettings,
    PolicyAreaClassification,
)


def test_the_classification_schema_admits_a_vocabulary_member():
    classification = PolicyAreaClassification(
        policy_areas=["Housing & Community Development", "Health"]
    )

    assert classification.policy_areas == [
        "Housing & Community Development",
        "Health",
    ]


def test_the_classification_schema_refuses_an_answer_outside_the_vocabulary():
    """An area the vocabulary does not declare never becomes an area."""

    with pytest.raises(ValidationError):
        PolicyAreaClassification(policy_areas=["Interstellar Affairs"])


def test_the_classification_schema_refuses_a_vocabulary_id():
    """The stage owns the vocabulary, so an id and its canonical name are not
    two answers a model can pick between."""

    with pytest.raises(ValidationError):
        PolicyAreaClassification(policy_areas=["housing"])


def test_an_article_the_vocabulary_does_not_cover_classifies_to_nothing():
    assert PolicyAreaClassification().policy_areas == []


def test_the_schema_sets_no_maximum_number_of_areas():
    """No cap is introduced before the Gold Set records the distribution."""

    every_area = [area.name for area in news.POLICY_AREAS]

    assert PolicyAreaClassification(policy_areas=every_area).policy_areas == every_area


def _classifier(answer: dict):
    """A classification agent whose model returns ``answer`` verbatim."""

    def model(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=answer)]
        )

    return FunctionModel(model)


def test_the_adapter_returns_the_areas_the_article_discusses():
    adapter = PydanticAIPolicyAreaAdapter(agent=get_classification_agent())

    with adapter.agent.override(
        model=_classifier({"policy_areas": ["Housing & Community Development"]})
    ):
        assert adapter.classify("An article about rent.") == [
            "Housing & Community Development"
        ]


def test_an_article_the_vocabulary_does_not_cover_classifies_to_no_areas():
    adapter = PydanticAIPolicyAreaAdapter(agent=get_classification_agent())

    with adapter.agent.override(model=_classifier({"policy_areas": []})):
        assert adapter.classify("An article about nothing in the vocabulary.") == []


def test_an_unusable_answer_raises_the_stage_specific_failure():
    adapter = PydanticAIPolicyAreaAdapter(
        agent=get_classification_agent(retries=0)
    )

    with adapter.agent.override(
        model=_classifier({"policy_areas": ["Interstellar Affairs"]})
    ):
        with pytest.raises(PolicyAreaClassificationError) as failure:
            adapter.classify("An article about rent.")

    assert failure.value.original_text == "An article about rent."
    assert failure.value.validation_issues


def test_a_transport_failure_reaches_the_pipeline_untouched():
    """The stage's transport failures are classified by the pipeline's own
    connectivity and rate-limit handling, as every other stage call is."""

    error = ModelHTTPError(status_code=429, model_name="remote-model", body=None)

    def failing_model(messages, info):
        raise error

    adapter = PydanticAIPolicyAreaAdapter(agent=get_classification_agent())

    with adapter.agent.override(model=FunctionModel(failing_model)):
        with pytest.raises(ModelHTTPError):
            adapter.classify("An article about rent.")


def test_the_classification_agent_is_built_from_an_explicit_deployment(monkeypatch):
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

    agent = get_classification_agent(deployment)

    assert seen == [deployment]
    assert agent.model is model


def test_the_adapter_reports_health_from_a_completed_run():
    adapter = PydanticAIPolicyAreaAdapter(agent=get_classification_agent())

    with adapter.agent.override(model=_classifier({"policy_areas": []})):
        assert adapter.health_check() is True


def test_the_adapter_reports_unhealthy_when_the_model_cannot_be_reached():
    def failing_model(messages, info):
        raise ModelHTTPError(status_code=503, model_name="remote-model", body=None)

    adapter = PydanticAIPolicyAreaAdapter(agent=get_classification_agent())

    with adapter.agent.override(model=FunctionModel(failing_model)):
        assert adapter.health_check() is False


def test_the_pipeline_declares_one_policy_area_protocol():
    """One seam for both stages: classification here, assignment in 04."""

    methods = [
        name
        for name, _ in inspect.getmembers(PolicyAreaAdapter, inspect.isfunction)
        if not name.startswith("_")
    ]

    assert sorted(methods) == ["classify", "health_check"]
    assert callable(getattr(PydanticAIPolicyAreaAdapter, "classify", None))
    assert callable(getattr(PydanticAIPolicyAreaAdapter, "health_check", None))
