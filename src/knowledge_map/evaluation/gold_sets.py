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
    _validate_cases(gold_set, case_items)
    return _construction_result(gold_set)


def revise_evaluation_gold_set(
    *,
    previous: EvaluationGoldSet,
    cases_to_add: Iterable[EvaluationCase[Any, Any, Any]] = (),
    case_business_ids_to_remove: Iterable[str] = (),
    split_ratio: Mapping[EvaluationSplit | str, float] | None = None,
    pinned_splits: Mapping[str, EvaluationSplit | str] | None = None,
) -> EvaluationGoldSetConstructionResult:
    """Derive the next immutable revision while preserving surviving splits."""
    added_cases = tuple(cases_to_add)
    normalized_pins = _normalize_pinned_splits(pinned_splits)
    _require_known_pins(added_cases, normalized_pins)
    removed_business_ids = frozenset(case_business_ids_to_remove)
    if not added_cases and not removed_business_ids:
        raise ValueError("an Evaluation Gold Set revision must add or remove cases")
    if added_cases and split_ratio is None:
        raise ValueError(
            "a split ratio is required to assign the Evaluation Cases being added"
        )
    normalized_ratio = {} if split_ratio is None else _normalize_split_ratio(split_ratio)

    previous_business_ids = {
        membership.case.business_id for membership in previous.memberships
    }
    unknown_removals = sorted(removed_business_ids - previous_business_ids)
    if unknown_removals:
        raise ValueError(
            "cannot remove cases absent from the previous Gold Set revision: "
            + ", ".join(unknown_removals)
        )

    surviving_memberships = tuple(
        membership
        for membership in previous.memberships
        if membership.case.business_id not in removed_business_ids
    )
    surviving_splits = {
        membership.case.business_id: membership.split
        for membership in surviving_memberships
    }
    # A survivor's inherited split outranks any pin, so no revision can walk a
    # case out of held-out. A pin on a survivor is discarded, not refused: a
    # misplaced pin is recoverable, a migrated case silently pollutes every
    # later measurement.
    predetermined_splits = {**normalized_pins, **surviving_splits}
    superseded_business_ids = {
        evaluation_case.identity.business_id for evaluation_case in added_cases
    }
    added_memberships = tuple(
        EvaluationGoldSetMembership(
            case=EvaluationCaseRevisionReference.from_case(evaluation_case),
            split=_assigned_split(
                evaluation_case.identity.business_id,
                normalized_ratio,
                predetermined_splits,
            ),
        )
        for evaluation_case in added_cases
    )
    retained_memberships = tuple(
        membership
        for membership in surviving_memberships
        if membership.case.business_id not in superseded_business_ids
    )
    memberships = tuple(
        sorted(
            (*retained_memberships, *added_memberships),
            key=_membership_sort_key,
        )
    )
    revised = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(
            business_id=previous.identity.business_id,
            revision=previous.identity.revision + 1,
        ),
        description=previous.description,
        task_contract=previous.task_contract,
        tags=previous.tags,
        artifacts=previous.artifacts,
        memberships=memberships,
    )
    _validate_cases(revised, added_cases)
    return _construction_result(revised)


def _construction_result(
    gold_set: EvaluationGoldSet,
) -> EvaluationGoldSetConstructionResult:
    counts = Counter(membership.split for membership in gold_set.memberships)
    return EvaluationGoldSetConstructionResult(
        gold_set=gold_set,
        split_counts={split: counts[split] for split in EvaluationSplit},
    )


def _validate_cases(
    gold_set: EvaluationGoldSet,
    cases: tuple[EvaluationCase[Any, Any, Any], ...],
) -> None:
    issues = tuple(
        issue
        for issue in evaluate_compatibility(None, gold_set, cases)
        if issue.source == "case"
    )
    if issues:
        raise EvaluationGoldSetConstructionError(issues)


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


def _membership_sort_key(
    membership: EvaluationGoldSetMembership,
) -> tuple[str, int, str, str]:
    return (
        membership.case.business_id,
        membership.case.revision,
        membership.case.content_hash,
        str(membership.case.record_id),
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
    predetermined_splits: Mapping[str, EvaluationSplit],
) -> EvaluationSplit:
    """Honour an already-decided split — an author's pin, or one a revision inherits."""
    if business_id in predetermined_splits:
        return predetermined_splits[business_id]
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
