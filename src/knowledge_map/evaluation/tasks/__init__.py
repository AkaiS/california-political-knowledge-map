"""One entry per evaluated component: its types, its task, its evaluators."""

from .registry import EvaluationTask, task_named, task_names
from . import relevance as _relevance  # noqa: F401  registers the task

__all__ = ["EvaluationTask", "task_named", "task_names"]
