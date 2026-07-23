import json

import pytest
from pydantic import BaseModel, SecretStr

from knowledge_map.evaluation import (
    EvaluationRunConfiguration,
    ValidatedComponentConfiguration,
)


class ComponentSettings(BaseModel):
    endpoint: str
    temperature: float = 0
    api_key: SecretStr


def test_run_configuration_freezes_a_schema_identified_secret_free_component_snapshot():
    snapshot = ValidatedComponentConfiguration.from_model(
        ComponentSettings(
            endpoint="https://example.test",
            temperature=0.2,
            api_key=SecretStr("do-not-persist"),
        ),
        identity="tests.component-settings",
        revision=3,
    )

    configuration = EvaluationRunConfiguration(
        provider="openai",
        model="gpt-test",
        model_parameters={"temperature": 0.2},
        component_configuration=snapshot,
    )

    persisted = json.loads(configuration.configuration_json)
    persisted_snapshot = persisted["component_configuration"]

    assert snapshot.schema_reference.identity == "tests.component-settings"
    assert snapshot.schema_reference.revision == 3
    assert persisted_snapshot["schema_reference"] == {
        "identity": "tests.component-settings",
        "revision": 3,
        "model_fingerprint": snapshot.schema_reference.model_fingerprint,
    }
    assert persisted_snapshot["content"] == {
        "endpoint": "https://example.test",
        "temperature": 0.2,
    }
    assert "do-not-persist" not in configuration.configuration_json
    assert configuration.component_configuration.content_fingerprint == snapshot.content_fingerprint


def test_run_configuration_rejects_an_untyped_component_configuration_mapping():
    with pytest.raises(ValueError, match="component_configuration"):
        EvaluationRunConfiguration(
            provider="openai",
            model="gpt-test",
            component_configuration={"temperature": 0.2},
        )


def test_run_configuration_fingerprint_tracks_material_shared_and_component_settings():
    first = ValidatedComponentConfiguration.from_model(
        ComponentSettings(
            endpoint="https://example.test",
            temperature=0.2,
            api_key=SecretStr("first-secret"),
        ),
        identity="tests.component-settings",
        revision=3,
    )
    equivalent = ValidatedComponentConfiguration.from_model(
        ComponentSettings(
            endpoint="https://example.test",
            temperature=0.2,
            api_key=SecretStr("rotated-secret"),
        ),
        identity="tests.component-settings",
        revision=3,
    )

    baseline = EvaluationRunConfiguration(
        provider="openai",
        model="gpt-test",
        model_parameters={"temperature": 0.2, "top_p": 1},
        component_configuration=first,
    )
    same_meaning = EvaluationRunConfiguration(
        provider="openai",
        model="gpt-test",
        model_parameters={"top_p": 1, "temperature": 0.2},
        component_configuration=equivalent,
    )

    assert baseline.configuration_fingerprint == same_meaning.configuration_fingerprint
    assert baseline.configuration_fingerprint != EvaluationRunConfiguration(
        provider="openai",
        model="gpt-test",
        model_parameters={"temperature": 0.3, "top_p": 1},
        component_configuration=first,
    ).configuration_fingerprint
    assert baseline.configuration_fingerprint != EvaluationRunConfiguration(
        provider="openai",
        model="gpt-test",
        model_parameters={"temperature": 0.2, "top_p": 1},
        component_configuration=ValidatedComponentConfiguration.from_model(
            ComponentSettings(
                endpoint="https://other.example",
                temperature=0.2,
                api_key=SecretStr("first-secret"),
            ),
            identity="tests.component-settings",
            revision=3,
        ),
    ).configuration_fingerprint


def test_run_configuration_round_trips_typed_snapshot_and_defaults_concurrency():
    snapshot = ValidatedComponentConfiguration.from_model(
        ComponentSettings(
            endpoint="https://example.test",
            api_key=SecretStr("secret"),
        ),
        identity="tests.component-settings",
        revision=3,
    )
    configuration = EvaluationRunConfiguration(
        provider="openai",
        model="gpt-test",
        component_configuration=snapshot,
    )

    restored = EvaluationRunConfiguration.model_validate_json(
        configuration.configuration_json
    )

    assert configuration.case_concurrency == 1
    assert restored == configuration
    assert restored.component_configuration == snapshot
