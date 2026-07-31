"""Pure construction helpers for Evaluation Gold Sets."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, NamedTuple

from .compatibility import EvaluationCompatibilityIssue, evaluate_compatibility
from .definitions import (
    DeclaredArtifactReference,
    EvaluationCase,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationSplit,
    EvaluationTaskContract,
)


class EvaluationGoldSetConstructionResult(NamedTuple):
    """A constructed Gold Set and its realized membership counts."""

    gold_set: EvaluationGoldSet
    split_counts: dict[EvaluationSplit, int]


class EvaluationGoldSetConstructionError(ValueError):
    """Raised once with every incompatible case schema found by construction."""

    def __init__(self, issues: tuple[EvaluationCompatibilityIssue, ...]):
        self.issues = issues
        super().__init__(
            "Evaluation Gold Set construction failed: "
            + "; ".join(_compatibility_issue_message(issue) for issue in issues)
        )


def construct_evaluation_gold_set(
    *,
    identity: EvaluationGoldSetIdentity,
    description: str,
    task_contract: EvaluationTaskContract,
    cases: Iterable[EvaluationCase[Any, Any, Any]],
    split_ratio: Mapping[EvaluationSplit | str, float],
    tags: Iterable[str] = (),
    artifacts: Iterable[DeclaredArtifactReference] = (),
    pinned_splits: Mapping[str, EvaluationSplit | str] | None = None,
) -> EvaluationGoldSetConstructionResult:
    """Construct one immutable, compatibility-checked Evaluation Gold Set."""
    normalized_ratio = _normalize_split_ratio(split_ratio)
    case_items = tuple(cases)
    normalized_pins = _normalize_pinned_splits(pinned_splits)
    _require_known_pins(case_items, normalized_pins)

    memberships = tuple(
        EvaluationGoldSetMembership(
            case=EvaluationCaseRevisionReference.from_case(evaluation_case),
            split=_assigned_split(
                evaluation_case.identity.business_id,
                normalized_ratio,
                normalized_pins,
            ),
        )
        for evaluation_case in sorted(case_items, key=_case_sort_key)
    )
    gold_set = EvaluationGoldSet(
        identity=identity,
        description=description,
        task_contract=task_contract,
        tags=tuple(tags),
        artifacts=tuple(artifacts),
        memberships=memberships,
    )

    issues = tuple(
        issue
        for issue in evaluate_compatibility(None, gold_set, case_items)
        if issue.source == "case"
    )
    if issues:
        raise EvaluationGoldSetConstructionError(issues)

    counts = Counter(membership.split for membership in memberships)
    return EvaluationGoldSetConstructionResult(
        gold_set=gold_set,
        split_counts={split: counts[split] for split in EvaluationSplit},
    )


def _normalize_split_ratio(
    split_ratio: Mapping[EvaluationSplit | str, float],
) -> dict[EvaluationSplit, float]:
    try:
        normalized = {
            EvaluationSplit(split): float(share) for split, share in split_ratio.items()
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("split ratio must use valid Evaluation Split keys and numbers") from exc

    expected_splits = set(EvaluationSplit)
    if set(normalized) != expected_splits or len(split_ratio) != len(expected_splits):
        raise ValueError("split ratio must declare training, calibration, and held-out")
    if any(not math.isfinite(share) or share < 0 for share in normalized.values()):
        raise ValueError("split ratio shares must be finite and non-negative")
    if not math.isclose(
        math.fsum(normalized.values()), 1.0, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("split ratio must sum to one")
    return normalized


def _normalize_pinned_splits(
    pinned_splits: Mapping[str, EvaluationSplit | str] | None,
) -> dict[str, EvaluationSplit]:
    if pinned_splits is None:
        return {}
    try:
        return {
            business_id: EvaluationSplit(split)
            for business_id, split in pinned_splits.items()
        }
    except ValueError as exc:
        raise ValueError("pinned splits must use valid Evaluation Split values") from exc


def _require_known_pins(
    cases: tuple[EvaluationCase[Any, Any, Any], ...],
    pinned_splits: Mapping[str, EvaluationSplit],
) -> None:
    business_ids = {evaluation_case.identity.business_id for evaluation_case in cases}
    unknown = sorted(set(pinned_splits) - business_ids)
    if unknown:
        raise ValueError("pinned splits name unknown cases: " + ", ".join(unknown))


def _case_sort_key(
    evaluation_case: EvaluationCase[Any, Any, Any],
) -> tuple[str, int, str, str]:
    return (
        evaluation_case.identity.business_id,
        evaluation_case.identity.revision,
        evaluation_case.content_hash,
        str(evaluation_case.identity.record_id),
    )


def _split_for_business_id(
    business_id: str, split_ratio: Mapping[EvaluationSplit, float]
) -> EvaluationSplit:
    digest = hashlib.sha256(business_id.encode("utf-8")).digest()
    position = int.from_bytes(digest, "big") / (1 << 256)
    training_boundary = split_ratio[EvaluationSplit.TRAINING]
    calibration_boundary = training_boundary + split_ratio[EvaluationSplit.CALIBRATION]
    if position < training_boundary:
        return EvaluationSplit.TRAINING
    if position < calibration_boundary:
        return EvaluationSplit.CALIBRATION
    return EvaluationSplit.HELD_OUT


def _assigned_split(
    business_id: str,
    split_ratio: Mapping[EvaluationSplit, float],
    pinned_splits: Mapping[str, EvaluationSplit],
) -> EvaluationSplit:
    if business_id in pinned_splits:
        return pinned_splits[business_id]
    return _split_for_business_id(business_id, split_ratio)


def _compatibility_issue_message(issue: EvaluationCompatibilityIssue) -> str:
    assert issue.schema_role is not None
    schema_name = (
        "expected-output" if issue.schema_role == "expected_output" else issue.schema_role
    )
    return (
        f"case {issue.case_business_id}@{issue.case_revision} has an incompatible "
        f"{schema_name} schema"
    )
