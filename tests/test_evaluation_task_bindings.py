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
