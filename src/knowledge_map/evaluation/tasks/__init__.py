"""One entry per evaluated component: its types, its task, its evaluators."""

from . import coreference as _coreference  # noqa: F401  registers the task
from . import extraction as _extraction  # noqa: F401  registers the task
from . import policy_area_classification as _classification  # noqa: F401  registers
from . import relevance as _relevance  # noqa: F401  registers the task
from .registry import EvaluationTask, task_named, task_names

__all__ = ["EvaluationTask", "task_named", "task_names"]
