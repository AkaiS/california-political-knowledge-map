import asyncio
import pytest
from pydantic import BaseModel, model_validator

from knowledge_map.evaluation import (
    EvaluationTaskBinding,
    EvaluationTaskContract,
    SchemaReference,
    TaskSuccess,
)


class Input(BaseModel):
    prompt: str


class Output(BaseModel):
    answer: str


class Metadata(BaseModel):
    source: str


class OtherOutput(BaseModel):
    value: int


def _contract() -> EvaluationTaskContract:
    return EvaluationTaskContract(
        input_schema=SchemaReference.for_model(
            Input, identity="tests.input", revision=1
        ),
        output_schema=SchemaReference.for_model(
            Output, identity="tests.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="tests.metadata", revision=1
        ),
    )


def test_task_binding_invokes_sync_operation_and_returns_typed_success():
    binding = EvaluationTaskBinding(
        operation=lambda value: Output(answer=value.prompt.upper()),
        contract=_contract(),
        input_model=Input,
        output_model=Output,
        metadata_model=Metadata,
    )

    outcome = binding.invoke(Input(prompt="hello"))

    assert isinstance(outcome, TaskSuccess)
    assert outcome.output == Output(answer="HELLO")


def test_task_binding_rejects_an_operation_model_that_does_not_match_contract():
    with pytest.raises(ValueError, match="output schema"):
        EvaluationTaskBinding(
            operation=lambda value: OtherOutput(value=1),
            contract=_contract(),
            input_model=Input,
            output_model=OtherOutput,
            metadata_model=Metadata,
        )


def test_task_binding_invokes_async_operation_and_validates_output_once():
    validation_calls: list[str] = []

    class CountedOutput(BaseModel):
        answer: str

        @model_validator(mode="after")
        def count_validation(self):
            validation_calls.append(self.answer)
            return self

    async def operation(value: Input) -> dict[str, str]:
        return {"answer": value.prompt}

    contract = EvaluationTaskContract(
        input_schema=SchemaReference.for_model(
            Input, identity="tests.input", revision=1
        ),
        output_schema=SchemaReference.for_model(
            CountedOutput, identity="tests.output.counted", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="tests.metadata", revision=1
        ),
    )

    binding = EvaluationTaskBinding(
        operation=operation,
        contract=contract,
        input_model=Input,
        output_model=CountedOutput,
        metadata_model=Metadata,
    )

    outcome = asyncio.run(binding.invoke_async({"prompt": "async"}))

    assert isinstance(outcome, TaskSuccess)
    assert outcome.output.model_dump() == {"answer": "async"}
    assert validation_calls == ["async"]


def test_task_binding_normalizes_output_and_component_failures_with_artifacts():
    output_reference = {
        "content_hash": "a" * 64,
        "role": "evaluation.task.output",
    }
    failure_reference = {
        "content_hash": "b" * 64,
        "role": "evaluation.task.failure",
    }

    invalid = EvaluationTaskBinding(
        operation=lambda value: {"wrong": True},
        contract=_contract(),
        input_model=Input,
        output_model=Output,
        metadata_model=Metadata,
        failure_artifacts=(failure_reference,),
    )
    invalid_outcome = invalid.invoke(Input(prompt="invalid"))

    assert invalid_outcome.kind == "failure"
    assert invalid_outcome.category == "output_validation"
    assert invalid_outcome.retryable is False
    assert invalid_outcome.artifacts[0].role == "evaluation.task.failure"

    failed = EvaluationTaskBinding(
        operation=lambda value: (_ for _ in ()).throw(RuntimeError("boom")),
        contract=_contract(),
        input_model=Input,
        output_model=Output,
        metadata_model=Metadata,
        failure_artifacts=(failure_reference,),
    )
    failed_outcome = failed.invoke(Input(prompt="failed"))

    assert failed_outcome.kind == "failure"
    assert failed_outcome.category == "component"
    assert failed_outcome.exception_type == "RuntimeError"
    assert failed_outcome.artifacts[0].content_hash == "b" * 64


def test_task_binding_preserves_success_artifact_references_without_persisting_them():
    reference = {
        "content_hash": "c" * 64,
        "role": "evaluation.task.output",
    }
    binding = EvaluationTaskBinding(
        operation=lambda value: Output(answer="answer"),
        contract=_contract(),
        input_model=Input,
        output_model=Output,
        metadata_model=Metadata,
        output_artifacts=(reference,),
    )

    outcome = binding.invoke(Input(prompt="artifact"))

    assert isinstance(outcome, TaskSuccess)
    assert outcome.artifacts[0].content_hash == "c" * 64


def test_task_contract_is_exactly_compatible_with():
    contract1 = _contract()
    contract2 = _contract()

    other_output_contract = EvaluationTaskContract(
        input_schema=SchemaReference.for_model(
            Input, identity="tests.input", revision=1
        ),
        output_schema=SchemaReference.for_model(
            OtherOutput, identity="tests.other_output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="tests.metadata", revision=1
        ),
    )

    assert contract1.is_exactly_compatible_with(contract2) is True
    assert contract1.is_exactly_compatible_with(other_output_contract) is False


def test_runner_rejects_a_mismatched_task_binding_contract():
    from knowledge_map.evaluation import (
        EvaluationSuite,
        EvaluationSuiteIdentity,
        ConfiguredEvaluator,
        EvaluationMetricDefinition,
        EvaluationMetricValueType,
        EvaluationMetricReference,
        NoComparisonOperation,
    )
    from knowledge_map.evaluation.preflight import ResolvedEvaluationPlan, EvaluationDefinitionRevisionReference

    suite_contract = _contract()
    mismatched_contract = EvaluationTaskContract(
        input_schema=SchemaReference.for_model(
            Input, identity="tests.input", revision=1
        ),
        output_schema=SchemaReference.for_model(
            OtherOutput, identity="tests.other_output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="tests.metadata", revision=1
        ),
    )

    mismatched_binding = EvaluationTaskBinding(
        operation=lambda val: OtherOutput(value=42),
        contract=mismatched_contract,
        input_model=Input,
        output_model=OtherOutput,
        metadata_model=Metadata,
    )

    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="test-suite", revision=1),
        description="Suite description",
        task_contract=suite_contract,
        report_evaluators=(
            ConfiguredEvaluator(
                name="test-eval",
                evaluator_revision=1,
                metrics=(
                    EvaluationMetricReference(
                        namespaced_name="tests.metric", evaluator_revision=1
                    ),
                ),
            ),
        ),
        metrics=(
            EvaluationMetricDefinition(
                namespaced_name="tests.metric",
                evaluator_revision=1,
                value_type=EvaluationMetricValueType.INTEGER,
                semantic_description="Metric desc",
                comparison_operation=NoComparisonOperation(
                    namespaced_name="tests.none", revision=1
                ),
            ),
        ),
    )

    plan = ResolvedEvaluationPlan(
        suite=EvaluationDefinitionRevisionReference(
            record_id="00000000-0000-0000-0000-000000000001",
            business_id="test-suite",
            revision=1,
            content_hash="a" * 64,
        ),
        gold_set=EvaluationDefinitionRevisionReference(
            record_id="00000000-0000-0000-0000-000000000002",
            business_id="test-gold-set",
            revision=1,
            content_hash="b" * 64,
        ),
        cases=(),
    )
    from knowledge_map.evaluation import (
        EvaluationRunner,
        EvaluationRunConfiguration,
        InMemoryEvaluationEvidenceBuffer,
        EvaluationGoldSet,
        EvaluationGoldSetIdentity,
        EvaluationGoldSetMembership,
        EvaluationCaseRevisionReference,
        EvaluationSplit,
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="test-gold-set", revision=1),
        description="Gold set description",
        task_contract=suite_contract,
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference(
                    record_id="00000000-0000-0000-0000-000000000003",
                    business_id="case-1",
                    revision=1,
                    content_hash="c" * 64,
                ),
                split=EvaluationSplit.TRAINING,
            ),
        ),
    )
    with InMemoryEvaluationEvidenceBuffer() as evidence:
        runner = EvaluationRunner(evidence)
        with pytest.raises(ValueError, match="task_binding contract does not match"):
            runner.run(
                plan=plan,
                suite=suite,
                gold_set=gold_set,
                cases=(),
                task_binding=mismatched_binding,
                evaluator_resolver=lambda cfg: None,
                configuration=EvaluationRunConfiguration(
                    provider="deterministic", model="fixture"
                ),
            )
