"""What an Evaluator returns when a case gave it nothing to judge.

`pydantic-evals` validates every Evaluator return against
`bool | int | float | str | EvaluationReason | dict[...]`.  `None` is not in
that union: returning it records an `EvaluatorFailure` for the case and
drops the score, which reads in a report exactly like an evaluator that was
never registered.  A conditional evaluator returns :data:`UNSCORED` instead,
which scores nothing and fails nothing.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

#: An empty score mapping: this case was not judgeable, and that is not a failure.
UNSCORED: Mapping[str, float] = MappingProxyType({})
