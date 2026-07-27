"""Pre-execution resolution of selected cases into an immutable evaluator plan."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .definitions import (
    EvaluationCase,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationSplit,
    canonical_json,
    content_fingerprint,
)
from .suites import (
    ConfiguredEvaluatorReference,
    EvaluationSuite,
)
from .compatibility import EvaluationCompatibilityIssue, evaluate_compatibility


class EvaluationDefinitionRevisionReference(BaseModel):
    """A content-addressed reference to one immutable authored revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    business_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResolvedCaseEvaluator(BaseModel):
    """One effective evaluator application and all reasons it applies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: ConfiguredEvaluatorReference
    provenance: tuple[str, ...] = Field(min_length=1)


class ResolvedEvaluationCase(BaseModel):
    """The exact case revision and evaluator applications frozen for a run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: EvaluationCaseRevisionReference
    split: EvaluationSplit
    requirements: tuple[str, ...] = ()
    evaluators: tuple[ResolvedCaseEvaluator, ...] = ()


class ResolvedEvaluationPlan(BaseModel):
    """The authoritative, immutable assignment consumed by run execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    suite: EvaluationDefinitionRevisionReference
    gold_set: EvaluationDefinitionRevisionReference
    cases: tuple[ResolvedEvaluationCase, ...]
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def model_post_init(self, __context: Any) -> None:
        fingerprint = content_fingerprint(
            self.model_dump(mode="json", exclude={"content_hash"})
        )
        if self.content_hash is not None and self.content_hash != fingerprint:
            raise ValueError("content_hash does not match the resolved evaluation plan")
        object.__setattr__(self, "content_hash", fingerprint)

    @property
    def canonical_json(self) -> str:
        """Return the deterministic compact serialization authoritative for a plan."""
        return canonical_json(self.model_dump(mode="json"))

    @property
    def readable_json(self) -> str:
        """Return a human-readable projection derived from canonical plan data."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )


class EvaluationPreflightIssue(BaseModel):
    """One actionable reason a Suite and selected cases cannot be paired."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    message: str = Field(min_length=1)
    case_business_id: str | None = None
    case_revision: int | None = Field(default=None, ge=1)
    requirement: str | None = None


class EvaluationPreflightResult(BaseModel):
    """A complete preflight report; a plan exists only when it is compatible."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: ResolvedEvaluationPlan | None = None
    issues: tuple[EvaluationPreflightIssue, ...] = ()

    @property
    def is_compatible(self) -> bool:
        return not self.issues and self.plan is not None


class EvaluationPreflightError(ValueError):
    """Raised when a run attempts to proceed with an incompatible preflight."""

    def __init__(self, result: EvaluationPreflightResult):
        self.result = result
        super().__init__(
            "Evaluation preflight failed: "
            + "; ".join(issue.message for issue in result.issues)
        )


def preflight_selected_cases(
    *,
    suite: EvaluationSuite,
    gold_set: EvaluationGoldSet,
    cases: tuple[EvaluationCase[Any, Any, Any], ...],
    selection: Callable[[EvaluationCase[Any, Any, Any]], bool]
    | Iterable[str]
    | None = None,
    split: EvaluationSplit | None = None,
) -> EvaluationPreflightResult:
    """Resolve selected members after validating the whole Gold Set contract."""
    compatibility_issues = evaluate_compatibility(suite, gold_set, cases)
    contract_issues = [
        _as_preflight_issue(issue)
        for issue in compatibility_issues
        if issue.source == "suite_gold_set"
    ]
    if contract_issues:
        return EvaluationPreflightResult(issues=tuple(contract_issues))

    membership_contract_issues = [
        _as_preflight_issue(issue)
        for issue in compatibility_issues
        if issue.source == "gold_set_member"
    ]
    if membership_contract_issues:
        return EvaluationPreflightResult(issues=tuple(membership_contract_issues))

    case_by_reference = {
        (case.identity.business_id, case.identity.revision): case for case in cases
    }
    resolved_cases: list[EvaluationCase[Any, Any, Any]] = []
    for membership in gold_set.memberships:
        reference = membership.case
        case = case_by_reference.get((reference.business_id, reference.revision))
        if case is None or case.content_hash != reference.content_hash:
            continue
        resolved_cases.append(case)
    resolved_contract_issues = [
        _as_preflight_issue(issue, resolved=True)
        for issue in evaluate_compatibility(None, gold_set, tuple(resolved_cases))
        if issue.source == "case"
    ]
    if resolved_contract_issues:
        return EvaluationPreflightResult(issues=tuple(resolved_contract_issues))

    selected_names = (
        set(selection) if selection is not None and not callable(selection) else None
    )
    selected: list[tuple[Any, EvaluationCase[Any, Any, Any]]] = []
    issues: list[EvaluationPreflightIssue] = []

    for membership in gold_set.memberships:
        if split is not None and membership.split is not split:
            continue
        key = (membership.case.business_id, membership.case.revision)
        case = case_by_reference.get(key)
        if selected_names is not None and membership.case.business_id not in selected_names:
            continue
        if case is None or case.content_hash != membership.case.content_hash:
            issues.append(
                EvaluationPreflightIssue(
                    category="case_reference",
                    subject=f"{membership.case.business_id}@{membership.case.revision}",
                    message=(
                        "Gold Set membership requires the exact supplied "
                        "Evaluation Case revision"
                    ),
                    case_business_id=membership.case.business_id,
                    case_revision=membership.case.revision,
                )
            )
            continue
        if callable(selection) and not selection(case):
            continue
        selected.append((membership, case))

    for membership, case in selected:
        _collect_case_issues(suite, case, issues)

    if issues:
        return EvaluationPreflightResult(issues=tuple(issues))

    plan_cases = tuple(
        ResolvedEvaluationCase(
            case=membership.case,
            split=membership.split,
            requirements=case.requirements,
            evaluators=_resolve_effective_evaluators(suite, case),
        )
        for membership, case in selected
    )
    plan = ResolvedEvaluationPlan(
        suite=EvaluationDefinitionRevisionReference(
            record_id=suite.identity.record_id,
            business_id=suite.identity.business_id,
            revision=suite.identity.revision,
            content_hash=suite.content_hash,
        ),
        gold_set=EvaluationDefinitionRevisionReference(
            record_id=gold_set.identity.record_id,
            business_id=gold_set.identity.business_id,
            revision=gold_set.identity.revision,
            content_hash=gold_set.content_hash,
        ),
        cases=plan_cases,
    )
    return EvaluationPreflightResult(plan=plan)


def _collect_case_issues(
    suite: EvaluationSuite,
    case: EvaluationCase[Any, Any, Any],
    issues: list[EvaluationPreflightIssue],
) -> None:
    case_subject = f"{case.identity.business_id}@{case.identity.revision}"
    compatibility_issues = evaluate_compatibility(suite, None, (case,))
    issues.extend(_as_preflight_issue(issue) for issue in compatibility_issues)

    for requirement in case.requirements:
        if not any(
            binding.requirement == requirement
            for binding in suite.requirement_bindings
        ):
            issues.append(
                EvaluationPreflightIssue(
                    category="missing_requirement_binding",
                    subject=f"{case_subject}:{requirement}",
                    message=f"Evaluation Requirement has no Suite binding: {requirement}",
                    case_business_id=case.identity.business_id,
                    case_revision=case.identity.revision,
                    requirement=requirement,
                )
            )


def _as_preflight_issue(
    issue: EvaluationCompatibilityIssue,
    *,
    resolved: bool = False,
) -> EvaluationPreflightIssue:
    case_subject = f"{issue.case_business_id}@{issue.case_revision}"
    if issue.category == "unknown_requirement":
        return EvaluationPreflightIssue(
            category="unknown_requirement",
            subject=f"{case_subject}:{issue.requirement}",
            message=(
                "Evaluation Requirement is unknown to the Suite catalog: "
                f"{issue.requirement}"
            ),
            case_business_id=issue.case_business_id,
            case_revision=issue.case_revision,
            requirement=issue.requirement,
        )

    assert issue.schema_role is not None
    field_name = (
        "output" if issue.schema_role == "expected_output" else issue.schema_role
    )
    if issue.source == "suite_gold_set":
        message = (
            f"Gold Set {field_name} schema is incompatible with the Suite task contract"
        )
    elif issue.source == "gold_set_member":
        message = (
            f"Gold Set member {case_subject} has an incompatible {field_name} schema"
        )
    elif resolved:
        message = (
            f"resolved case {case_subject} has an incompatible {field_name} "
            "schema for the Gold Set"
        )
    else:
        message = (
            f"case {field_name} schema is incompatible with the suite task contract"
        )
    return EvaluationPreflightIssue(
        category="task_contract",
        subject=case_subject,
        message=message,
        case_business_id=issue.case_business_id,
        case_revision=issue.case_revision,
    )


def _resolve_effective_evaluators(
    suite: EvaluationSuite,
    case: EvaluationCase[Any, Any, Any],
) -> tuple[ResolvedCaseEvaluator, ...]:
    configured_by_name = {evaluator.name: evaluator for evaluator in suite.case_evaluators}
    provenance_by_name: dict[str, list[str]] = {}
    for reference in suite.suite_wide_case_evaluator_references:
        provenance_by_name.setdefault(reference.name, []).append("suite-wide")
    bindings = {binding.requirement: binding for binding in suite.requirement_bindings}
    for requirement in case.requirements:
        for reference in bindings[requirement].evaluators:
            provenance_by_name.setdefault(reference.name, []).append(requirement)

    return tuple(
        ResolvedCaseEvaluator(
            reference=ConfiguredEvaluatorReference(
                name=name,
                evaluator_revision=configured_by_name[name].evaluator_revision,
            ),
            provenance=tuple(provenance),
        )
        for name, provenance in provenance_by_name.items()
    )
