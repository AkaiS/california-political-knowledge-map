"""The Query Rewriter can select a deployment independently of construction."""

from pydantic_ai.models import Model

from knowledge_map.core.question_preparation import get_query_rewriter
from knowledge_map.utils.deployments import (
    deployment_from_environment,
    query_rewriter_deployment_from_environment,
)


def test_rewriter_configuration_does_not_change_the_downstream_deployment(monkeypatch):
    monkeypatch.setenv("LLAMA_CPP_MODEL", "construction-model")
    monkeypatch.setenv("LLAMA_CPP_BASE_URL", "http://construction.test:8080")
    monkeypatch.setenv("QUERY_REWRITER_DEPLOYMENT", "local")
    monkeypatch.setenv("QUERY_REWRITER_MODEL", "stronger-rewriter-model")
    monkeypatch.setenv("QUERY_REWRITER_BASE_URL", "http://rewriter.test:9090")

    rewriter = query_rewriter_deployment_from_environment()
    downstream = deployment_from_environment(
        "local", default_local_model="unused", command_name="construction"
    )

    assert rewriter.model == "stronger-rewriter-model"
    assert rewriter.endpoint == "http://rewriter.test:9090"
    assert downstream.model == "construction-model"
    assert downstream.endpoint == "http://construction.test:8080/v1"
    configured_model = get_query_rewriter().model
    explicit_model = get_query_rewriter(downstream).model
    assert isinstance(configured_model, Model)
    assert isinstance(explicit_model, Model)
    assert configured_model.model_name == "stronger-rewriter-model"
    assert explicit_model.model_name == "construction-model"
