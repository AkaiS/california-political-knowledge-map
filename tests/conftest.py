"""Shared helpers for the Evaluation test suite."""

from __future__ import annotations

from typing import Any

from knowledge_map.evaluation.definitions import (
    EvaluationCase,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationSplit,
    EvaluationTaskContract,
)
from knowledge_map.evaluation.gold_sets import construct_evaluation_gold_set

TEST_SPLIT_RATIO = {
    EvaluationSplit.TRAINING: 0.6,
    EvaluationSplit.CALIBRATION: 0.2,
    EvaluationSplit.HELD_OUT: 0.2,
}


def build_gold_set(
    cases: tuple[EvaluationCase[Any, Any, Any], ...],
    *,
    business_id: str,
    description: str,
    revision: int = 1,
    task_contract: EvaluationTaskContract | None = None,
    split: EvaluationSplit | None = EvaluationSplit.HELD_OUT,
) -> EvaluationGoldSet:
    """Build a Gold Set through the factory for a test that is not about construction.

    Pins every case to `split` so the population a test asserts on does not depend
    on how business identities happen to hash; pass `split=None` to let the ratio
    decide.
    """
    contract = task_contract or EvaluationTaskContract(
        input_schema=cases[0].input_schema,
        output_schema=cases[0].expected_output_schema,
        metadata_schema=cases[0].metadata_schema,
    )
    pinned_splits = (
        None
        if split is None
        else {case.identity.business_id: split for case in cases}
    )
    return construct_evaluation_gold_set(
        identity=EvaluationGoldSetIdentity(business_id=business_id, revision=revision),
        description=description,
        task_contract=contract,
        cases=cases,
        split_ratio=TEST_SPLIT_RATIO,
        pinned_splits=pinned_splits,
    ).gold_set
