"""Persistence-free runtime bindings for evaluated component operations."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .definitions import (
    DeclaredArtifactReference,
    EvaluationTaskContract,
    SchemaReference,
)
from .runs import TaskFailure, TaskOutcome, TaskSuccess


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)
MetadataT = TypeVar("MetadataT", bound=BaseModel)

ArtifactEvidence = (
    Iterable[DeclaredArtifactReference]
    | Callable[[Any], Iterable[DeclaredArtifactReference]]
)


class EvaluationTaskBinding(Generic[InputT, OutputT, MetadataT]):
    """Bind one component operation to one exact typed task contract.

    The binding is deliberately unaware of persistence.  It only invokes the
    operation, validates its returned value, and describes any artifact
    evidence supplied by the caller.
    """

    def __init__(
        self,
        *,
        operation: Callable[[InputT], OutputT | TaskSuccess | Any],
        contract: EvaluationTaskContract | None = None,
        task_contract: EvaluationTaskContract | None = None,
        input_model: type[InputT],
        output_model: type[OutputT],
        metadata_model: type[MetadataT],
        output_artifacts: ArtifactEvidence | None = None,
        failure_artifacts: ArtifactEvidence | None = None,
    ) -> None:
        if (contract is None) == (task_contract is None):
            raise ValueError("provide exactly one contract or task_contract")
        contract = contract or task_contract
        assert contract is not None
        self.operation = operation
        self.contract = contract
        self.input_model = input_model
        self.output_model = output_model
        self.metadata_model = metadata_model
        self.output_artifacts = output_artifacts
        self.failure_artifacts = failure_artifacts
        self._validate_model_contract(
            "input", input_model, contract.input_schema
        )
        self._validate_model_contract(
            "output", output_model, contract.output_schema
        )
        self._validate_model_contract(
            "metadata", metadata_model, contract.metadata_schema
        )

    @property
    def task_contract(self) -> EvaluationTaskContract:
        return self.contract

    @staticmethod
    def _validate_model_contract(
        field_name: str,
        model_type: type[BaseModel],
        expected: SchemaReference,
    ) -> None:
        actual = SchemaReference(
            identity=expected.identity,
            revision=expected.revision,
            model_fingerprint=SchemaReference.for_model(
                model_type,
                identity=expected.identity,
                revision=expected.revision,
            ).model_fingerprint,
        )
        if not actual.is_exactly_compatible_with(expected):
            raise ValueError(
                f"{field_name} schema does not exactly match the Evaluation Task Contract"
            )

    def invoke(
        self,
        task_input: InputT | Mapping[str, Any],
        *,
        metadata: MetadataT | Mapping[str, Any] | None = None,
    ) -> TaskOutcome:
        """Invoke a synchronous operation and return a terminal outcome."""
        try:
            validated_input = self.input_model.model_validate(task_input)
            self._validate_metadata(metadata)
            result = self.operation(validated_input)
            if inspect.isawaitable(result):
                result.close() if inspect.iscoroutine(result) else None
                raise TypeError(
                    "asynchronous task operations must be invoked with invoke_async"
                )
            return self._success(result)
        except _OutputValidationError as exc:
            return self._output_failure(exc.error)
        except ValidationError as exc:
            return self._input_failure(exc)
        except Exception as exc:
            return self._component_failure(exc)

    invoke_sync = invoke

    @property
    def is_async(self) -> bool:
        """Whether the bound operation is declared as an async callable."""
        return inspect.iscoroutinefunction(self.operation)

    async def invoke_async(
        self,
        task_input: InputT | Mapping[str, Any],
        *,
        metadata: MetadataT | Mapping[str, Any] | None = None,
    ) -> TaskOutcome:
        """Invoke a synchronous or asynchronous operation asynchronously."""
        try:
            validated_input = self.input_model.model_validate(task_input)
            self._validate_metadata(metadata)
            result = self.operation(validated_input)
            if inspect.isawaitable(result):
                result = await result
            return self._success(result)
        except _OutputValidationError as exc:
            return self._output_failure(exc.error)
        except ValidationError as exc:
            return self._input_failure(exc)
        except Exception as exc:
            return self._component_failure(exc)

    def _validate_metadata(
        self, metadata: MetadataT | Mapping[str, Any] | None
    ) -> MetadataT | None:
        if metadata is None:
            return None
        return self.metadata_model.model_validate(metadata)

    def _success(self, result: Any) -> TaskOutcome:
        supplied_artifacts: Iterable[DeclaredArtifactReference] = ()
        if isinstance(result, TaskFailure):
            return result
        if isinstance(result, TaskSuccess):
            supplied_artifacts = result.artifacts
            result = result.output
        try:
            output = self.output_model.model_validate(result)
        except ValidationError as exc:
            raise _OutputValidationError(exc) from exc
        artifacts = tuple(supplied_artifacts) + self._artifacts(
            self.output_artifacts, output
        )
        return TaskSuccess(output=output, artifacts=artifacts)

    def _output_failure(self, error: ValidationError) -> TaskFailure:
        return TaskFailure(
            category="output_validation",
            exception_type=type(error).__name__,
            safe_message="component output does not match the Evaluation Task Contract",
            retryable=False,
            failure_evidence={"errors": _json_safe(error.errors())},
            artifacts=self._artifacts(self.failure_artifacts, error),
        )

    def _input_failure(self, error: ValidationError) -> TaskFailure:
        return TaskFailure(
            category="input_validation",
            exception_type=type(error).__name__,
            safe_message="task input does not match the Evaluation Task Contract",
            retryable=False,
            failure_evidence={"errors": _json_safe(error.errors())},
            artifacts=self._artifacts(self.failure_artifacts, error),
        )

    def _component_failure(self, error: BaseException) -> TaskFailure:
        return TaskFailure(
            category="component",
            exception_type=type(error).__name__,
            safe_message=str(error) or type(error).__name__,
            retryable=False,
            failure_evidence={"message": str(error) or type(error).__name__},
            artifacts=self._artifacts(self.failure_artifacts, error),
        )

    @staticmethod
    def _artifacts(
        evidence: ArtifactEvidence | None, value: Any
    ) -> tuple[DeclaredArtifactReference, ...]:
        if evidence is None:
            return ()
        references = evidence(value) if callable(evidence) else evidence
        return tuple(references)


class TaskBindingInvocationError(RuntimeError):
    """Internal bridge from a failed Binding outcome to framework case failure."""

    def __init__(self, outcome: TaskFailure) -> None:
        self.outcome = outcome
        super().__init__(outcome.safe_message)


class _OutputValidationError(Exception):
    def __init__(self, error: ValidationError) -> None:
        self.error = error
        super().__init__(str(error))


def _json_safe(value: Any) -> Any:
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)
