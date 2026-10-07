"""One entry per evaluated component: its types, its task, its evaluators."""

from . import chat as _chat  # noqa: F401  registers the task
from . import coreference as _coreference  # noqa: F401  registers the task
from . import extraction as _extraction  # noqa: F401  registers the task
from . import policy_area_classification as _classification  # noqa: F401  registers
from . import relevance as _relevance  # noqa: F401  registers the task
from . import retrieval as _retrieval  # noqa: F401  registers the task
from . import topic_assignment as _topic_assignment  # noqa: F401  registers
from .registry import EvaluationTask, task_named, task_names

__all__ = ["EvaluationTask", "task_named", "task_names"]
