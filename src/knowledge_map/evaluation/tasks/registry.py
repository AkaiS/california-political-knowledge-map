"""The tasks a Gold Set can be run against.

A task is registered in code rather than declared in the Gold Set file,
because what a task needs — a model, a database path, an agent — is not
something the author writes into a case.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_evals.evaluators import Evaluator


@dataclass(frozen=True)
class EvaluationTask:
    """One evaluated component, named by the Gold Set file that feeds it."""

    name: str
    input_type: type[Any]
    output_type: type[Any]
    build: Callable[[str], Callable[[Any], Any]]
    """Given a model identifier, return the callable one case is run through."""
    evaluators: Sequence[Evaluator]
    default_model: str
    metadata_type: type[Any] = dict
    collect: Callable[[], Any] | None = None
    """Read labeled candidates out of the project's own data, if it has any."""


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
