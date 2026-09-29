"""The tasks an Evaluation Data Set can be run against.

Register a task in code, not in the Data Set file: a task's wiring — a model,
a database path, an agent — is not something a case author supplies.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_evals.evaluators import Evaluator
from pydantic_evals.lifecycle import CaseLifecycle

from knowledge_map.schemas import ModelDeployment

from ..data_set import LabelQuality


@dataclass(frozen=True)
class EvaluationTask:
    """One evaluated component, named by the Data Set file that feeds it."""

    name: str
    input_type: type[Any]
    output_type: type[Any]
    build: Callable[[ModelDeployment, Any], Callable[[Any], Any]]
    """Given a Model Deployment and the Data Set, return the case callable.

    The Data Set is passed so a task that few-shots its prompt can draw
    those examples from the `training` split. A task that reaches into
    the project's database for examples instead will show the model the
    answers to its own held-out cases.
    """
    evaluators: Sequence[Evaluator]
    default_model: str
    label_quality: LabelQuality
    """Who wrote the labels this task is scored against.

    Declared per task rather than read off the file, because it decides
    which directory the file is looked for in -- and because it is the one
    fact a reader needs before comparing two tasks' numbers. It carries no
    default: silver is the common case, and a default would quietly file a
    person's labels as a model's on the day someone registers a gold task
    and forgets. Wrong provenance in a committed report cannot be spotted
    by reading the report.
    """
    metadata_type: type[Any] = dict
    collect: Callable[[], Any] | None = None
    """Read labeled candidates out of the project's own data, if it has any."""
    data_set_name: str | None = None
    """The Data Set file this task reads, when it is not the task's own name.

    Two tasks can measure two stages of one pipeline against the same
    authored cases -- the whole loop, and the annotator alone -- and the
    cases are the same cases. The file names one task in its `task:` field
    and the other borrows it, rather than the author maintaining the same
    twenty Stories twice and letting them drift.
    """
    prompts: Callable[[], Mapping[str, str]] = dict
    """The instruction text of each agent this task runs, keyed by agent.

    Called at run time, not at import: a task whose prompt is read from a
    file or rendered from the ontology must be digested as the run will
    actually send it. Only the part that is constant across cases belongs
    here -- instructions rendered per case vary by input, and what varies
    with them is the Data Set, which a report already names.
    """
    case_lifecycle: type[CaseLifecycle] | None = None
    """Optional case evidence capture through Pydantic Evals' lifecycle."""

    @property
    def data_set_stem(self) -> str:
        """The stem of the Data Set file, defaulting to the task's own name."""

        return self.data_set_name or self.name

    def prompt_digests(self) -> dict[str, str]:
        """Digest each agent's instructions, naming what the commit cannot.

        A commit moves for every change in the repository and says nothing
        at all when the worktree is dirty, so it cannot tell two runs of the
        same prompt from two runs of different ones. These digests can.
        """

        return {
            agent: "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            for agent, text in sorted(self.prompts().items())
        }


_TASKS: dict[str, EvaluationTask] = {}


def register(task: EvaluationTask) -> EvaluationTask:
    if task.name in _TASKS:
        raise ValueError(f"{task.name} is already registered")
    _TASKS[task.name] = task
    return task


def task_named(name: str) -> EvaluationTask:
    try:
        return _TASKS[name]
    except KeyError:
        raise KeyError(
            f"unknown evaluation task {name!r}; known tasks: " + ", ".join(task_names())
        ) from None


def task_names() -> tuple[str, ...]:
    return tuple(sorted(_TASKS))
