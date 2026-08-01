"""Pure compatibility checks for authored evaluation definitions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .definitions import EvaluationCase, EvaluationGoldSet, SchemaReference
from .suites import EvaluationSuite


class EvaluationCompatibilityIssue(BaseModel):
    """One independently actionable incompatibility in authored definitions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: Literal["contract_schema_mismatch", "unknown_requirement"]
    case_business_id: str
    case_revision: int
    source: Literal["case", "suite_gold_set"] = "case"
    schema_role: Literal["input", "expected_output", "metadata"] | None = None
    actual_schema: SchemaReference | None = None
    expected_schema: SchemaReference | None = None
    requirement: str | None = None

    @property
    def schema_role_name(self) -> str:
        """Name this issue's schema role to a reader: a case's expected output is
        the task's output, and every seam that reports an incompatibility says so
        the same way."""
        assert self.schema_role is not None
        return "output" if self.schema_role == "expected_output" else self.schema_role


def evaluate_compatibility(
    suite: EvaluationSuite | None,
    gold_set: EvaluationGoldSet | None,
    cases: tuple[EvaluationCase[Any, Any, Any], ...] = (),
) -> tuple[EvaluationCompatibilityIssue, ...]:
    """Return every compatibility issue without performing I/O or resolving a run."""
    if suite is None and gold_set is None:
        raise ValueError("compatibility requires an Evaluation Suite or Gold Set")

    issues: list[EvaluationCompatibilityIssue] = []
    if gold_set is not None:
        if suite is not None:
            issues.extend(
                _schema_issues(
                    case_business_id=gold_set.identity.business_id,
                    case_revision=gold_set.identity.revision,
                    source="suite_gold_set",
                    actual_schemas=(
                        gold_set.task_contract.input_schema,
                        gold_set.task_contract.output_schema,
                        gold_set.task_contract.metadata_schema,
                    ),
                    expected_schemas=(
                        suite.task_contract.input_schema,
                        suite.task_contract.output_schema,
                        suite.task_contract.metadata_schema,
                    ),
                )
            )

    target_contract = (
        suite.task_contract if suite is not None else gold_set.task_contract
    )
    for evaluation_case in cases:
        issues.extend(
            _schema_issues(
                case_business_id=evaluation_case.identity.business_id,
                case_revision=evaluation_case.identity.revision,
                source="case",
                actual_schemas=(
                    evaluation_case.input_schema,
                    evaluation_case.expected_output_schema,
                    evaluation_case.metadata_schema,
                ),
                expected_schemas=(
                    target_contract.input_schema,
                    target_contract.output_schema,
                    target_contract.metadata_schema,
                ),
            )
        )
        for requirement in evaluation_case.requirements:
            if suite is not None and not suite.requirement_catalog.contains(requirement):
                issues.append(
                    EvaluationCompatibilityIssue(
                        category="unknown_requirement",
                        case_business_id=evaluation_case.identity.business_id,
                        case_revision=evaluation_case.identity.revision,
                        requirement=requirement,
                    )
                )
    return tuple(issues)


def _schema_issues(
    *,
    case_business_id: str,
    case_revision: int,
    source: Literal["case", "suite_gold_set"],
    actual_schemas: tuple[
        SchemaReference | None, SchemaReference | None, SchemaReference | None
    ],
    expected_schemas: tuple[SchemaReference, SchemaReference, SchemaReference],
) -> tuple[EvaluationCompatibilityIssue, ...]:
    issues: list[EvaluationCompatibilityIssue] = []
    for schema_role, actual, expected in zip(
        ("input", "expected_output", "metadata"),
        actual_schemas,
        expected_schemas,
        strict=True,
    ):
        if actual is not None and not actual.is_exactly_compatible_with(expected):
            issues.append(
                EvaluationCompatibilityIssue(
                    category="contract_schema_mismatch",
                    case_business_id=case_business_id,
                    case_revision=case_revision,
                    source=source,
                    schema_role=schema_role,
                    actual_schema=actual,
                    expected_schema=expected,
                )
            )
    return tuple(issues)
