from pydantic import BaseModel
import pytest

from knowledge_map.evaluation import (
    ConfiguredEvaluator,
    EvaluationMetricObservation,
    EvaluationMetricDefinition,
    EvaluationMetricReference,
    EvaluationMetricValueType,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    NoComparisonOperation,
    ResolvedSchemaBinding,
    SchemaReference,
    SchemaRegistry,
    StructuredMetricValue,
    materialize_structured_metric_observation,
    materialize_metric_observation,
)


class StructuredScore(BaseModel):
    label: str
    score: float


class IncompatibleStructuredScore(BaseModel):
    label: str


def test_structured_observation_materializes_through_an_allowlisted_binding():
    reference = SchemaReference.for_model(
        StructuredScore, identity="tests.structured-score", revision=1
    )
    schemas = SchemaRegistry()
    schemas.register(reference, StructuredScore)
    observation = EvaluationMetricObservation(
        metric=EvaluationMetricReference(
            namespaced_name="tests.score", evaluator_revision=1
        ),
        structured_value=StructuredMetricValue(
            schema_reference=reference,
            payload={"label": "good", "score": 0.9},
        ),
    )

    binding = schemas.resolve_binding(reference)

    assert binding == ResolvedSchemaBinding(
        expected_reference=reference,
        model_type=StructuredScore,
    )
    assert materialize_structured_metric_observation(observation, binding) == StructuredScore(
        label="good", score=0.9
    )


def test_materialization_rejects_an_envelope_with_a_different_schema_tag():
    expected = SchemaReference.for_model(
        StructuredScore, identity="tests.expected", revision=1
    )
    actual = SchemaReference.for_model(
        StructuredScore, identity="tests.actual", revision=1
    )
    observation = EvaluationMetricObservation(
        metric=EvaluationMetricReference(
            namespaced_name="tests.score", evaluator_revision=1
        ),
        structured_value=StructuredMetricValue(
            schema_reference=actual,
            payload={"label": "good", "score": 0.9},
        ),
    )

    with pytest.raises(ValueError, match="schema tag"):
        materialize_structured_metric_observation(
            observation,
            ResolvedSchemaBinding(expected_reference=expected, model_type=StructuredScore),
        )


def test_materialization_resolves_the_observation_metric_through_the_suite():
    reference = SchemaReference.for_model(
        StructuredScore, identity="tests.structured-score", revision=1
    )
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.score",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=reference,
        semantic_description="A structured score.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison", revision=1
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="tests-suite", revision=1),
        description="A suite for materialization.",
        task_contract=EvaluationTaskContract(
            input_schema=reference,
            output_schema=reference,
            metadata_schema=reference,
        ),
        report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
        metrics=(metric,),
    )
    schemas = SchemaRegistry()
    schemas.register(reference, StructuredScore)
    observation = EvaluationMetricObservation(
        metric=EvaluationMetricReference.from_definition(metric),
        structured_value=StructuredMetricValue(
            schema_reference=reference,
            payload={"label": "good", "score": 0.9},
        ),
    )

    assert materialize_metric_observation(observation, suite=suite, schemas=schemas) == StructuredScore(
        label="good", score=0.9
    )


def test_scalar_observations_bypass_schema_resolution_and_remain_directly_usable():
    observation = EvaluationMetricObservation(
        metric=EvaluationMetricReference(
            namespaced_name="tests.scalar", evaluator_revision=1
        ),
        number_value=0.75,
    )

    assert materialize_metric_observation(
        observation, suite=None, schemas=SchemaRegistry()
    ) == 0.75


def test_unknown_schema_registry_entries_cannot_materialize_an_observation():
    reference = SchemaReference.for_model(
        StructuredScore, identity="tests.unknown", revision=1
    )

    with pytest.raises(ValueError, match="schema is not allowlisted"):
        SchemaRegistry().resolve_binding(reference)


def test_schema_registry_rejects_an_incompatible_registered_model():
    reference = SchemaReference.for_model(
        StructuredScore, identity="tests.incompatible", revision=1
    )

    with pytest.raises(ValueError, match="exact schema fingerprint"):
        SchemaRegistry().register(reference, IncompatibleStructuredScore)


def test_materialization_rejects_a_payload_that_the_bound_model_cannot_validate():
    reference = SchemaReference.for_model(
        StructuredScore, identity="tests.invalid-payload", revision=1
    )
    schemas = SchemaRegistry()
    schemas.register(reference, StructuredScore)
    observation = EvaluationMetricObservation(
        metric=EvaluationMetricReference(
            namespaced_name="tests.score", evaluator_revision=1
        ),
        structured_value=StructuredMetricValue(
            schema_reference=reference,
            payload={"label": "missing score"},
        ),
    )

    with pytest.raises(ValueError):
        materialize_structured_metric_observation(
            observation, schemas.resolve_binding(reference)
        )


def test_mixed_observations_materialize_independently_when_one_structured_value_is_invalid():
    valid_reference = SchemaReference.for_model(
        StructuredScore, identity="tests.valid", revision=1
    )
    invalid_reference = SchemaReference.for_model(
        StructuredScore, identity="tests.invalid", revision=1
    )
    valid_metric = EvaluationMetricDefinition(
        namespaced_name="tests.valid",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=valid_reference,
        semantic_description="A valid structured score.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.valid", revision=1
        ),
    )
    invalid_metric = valid_metric.model_copy(
        update={
            "namespaced_name": "tests.invalid",
            "structured_schema": invalid_reference,
            "comparison_operation": NoComparisonOperation(
                namespaced_name="tests.comparison.invalid", revision=1
            ),
        }
    )
    scalar_metric = EvaluationMetricDefinition(
        namespaced_name="tests.scalar",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.INTEGER,
        semantic_description="A scalar count.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.scalar", revision=1
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="mixed-suite", revision=1),
        description="A mixed observation suite.",
        task_contract=EvaluationTaskContract(
            input_schema=valid_reference,
            output_schema=valid_reference,
            metadata_schema=valid_reference,
        ),
        report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
        metrics=(valid_metric, invalid_metric, scalar_metric),
    )
    schemas = SchemaRegistry()
    schemas.register(valid_reference, StructuredScore)
    schemas.register(invalid_reference, StructuredScore)
    observations = (
        EvaluationMetricObservation(
            metric=EvaluationMetricReference.from_definition(valid_metric),
            structured_value=StructuredMetricValue(
                schema_reference=valid_reference,
                payload={"label": "good", "score": 0.9},
            ),
        ),
        EvaluationMetricObservation(
            metric=EvaluationMetricReference.from_definition(invalid_metric),
            structured_value=StructuredMetricValue(
                schema_reference=invalid_reference,
                payload={"label": "missing score"},
            ),
        ),
        EvaluationMetricObservation(
            metric=EvaluationMetricReference.from_definition(scalar_metric),
            integer_value=3,
        ),
    )

    materialized = []
    failures = []
    for observation in observations:
        try:
            materialized.append(
                materialize_metric_observation(
                    observation, suite=suite, schemas=schemas
                )
            )
        except ValueError as exc:
            failures.append(exc)

    assert materialized == [StructuredScore(label="good", score=0.9), 3]
    assert len(failures) == 1
