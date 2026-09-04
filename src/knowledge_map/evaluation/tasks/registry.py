"""The tasks a Gold Set can be run against.

Register a task in code, not in the Gold Set file: a task's wiring — a model,
a database path, an agent — is not something a case author supplies.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_evals.evaluators import Evaluator

from knowledge_map.schemas import ModelDeployment


@dataclass(frozen=True)
class EvaluationTask:
    """One evaluated component, named by the Gold Set file that feeds it."""

    name: str
    input_type: type[Any]
    output_type: type[Any]
    build: Callable[[ModelDeployment, Any], Callable[[Any], Any]]
    """Given a Model Deployment and the Gold Set, return the case callable.

    The Gold Set is passed so a task that few-shots its prompt can draw
    those examples from the `training` split. A task that reaches into
    the project's database for examples instead will show the model the
    answers to its own held-out cases.
    """
    evaluators: Sequence[Evaluator]
    default_model: str
    metadata_type: type[Any] = dict
    collect: Callable[[], Any] | None = None
    """Read labeled candidates out of the project's own data, if it has any."""
    gold_set_name: str | None = None
    """The Gold Set file this task reads, when it is not the task's own name.

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
    with them is the Gold Set, which a report already names.
    """

    @property
    def gold_set_stem(self) -> str:
        """The stem of the Gold Set file, defaulting to the task's own name."""

        return self.gold_set_name or self.name

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
