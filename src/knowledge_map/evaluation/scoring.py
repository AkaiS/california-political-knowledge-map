"""What an Evaluator returns when a case gave it nothing to judge.

`pydantic-evals` validates every Evaluator return against
`bool | int | float | str | EvaluationReason | dict[...]`.  `None` is not in
that union: returning it records an `EvaluatorFailure` for the case and
drops the score, which reads in a report exactly like an evaluator that was
never registered.  A conditional evaluator returns :data:`UNSCORED` instead,
which scores nothing and fails nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

#: An empty score mapping: this case was not judgeable, and that is not a failure.
UNSCORED: Mapping[str, float] = MappingProxyType({})


def f1(precision: float, recall: float) -> float:
    """The harmonic mean of precision and recall, and zero where both are.

    Every task that reports set agreement -- spans, clusters, nodes,
    relationships, Policy Areas, Topic Assignments -- reports the same three
    numbers, and the third is derived from the first two the same way in all
    of them.  One definition here rather than one per task keeps every score a
    report names `..._f1` meaning one thing.
    """

    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def detection_scores(
    expected: set[Any], found: set[Any], prefix: str
) -> dict[str, float]:
    """Precision, recall and F1 over what was expected against what was found.

    The three scores a set-agreement task reports, named for the thing being
    agreed on -- nodes, relationships, Policy Areas, Topic Assignments.  A
    case where both sides are empty is the caller's to answer, because
    agreeing on nothing is a pass in some tasks and unscoreable in others.
    """

    matched = len(expected & found)
    precision = matched / len(found) if found else 0.0
    recall = matched / len(expected) if expected else 0.0
    return {
        f"{prefix}_precision": precision,
        f"{prefix}_recall": recall,
        f"{prefix}_f1": f1(precision, recall),
    }
