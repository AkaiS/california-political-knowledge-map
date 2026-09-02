"""No task's Evaluator may return `None`, whatever the task.

`pydantic-evals` rejects `None` from an Evaluator: the case records an
`EvaluatorFailure` and the score vanishes from the report, which is
indistinguishable from an evaluator nobody registered.  It cost the
coreference Critic metrics their entire first run.  This is checked for
every registered task at once, because the constraint comes from the
library and not from anything a task knows about itself.
"""

import ast
from pathlib import Path

import pytest
from pydantic_evals.evaluators._run_evaluator import (  # noqa: PLC2701
    _EVALUATOR_OUTPUT_ADAPTER as EVALUATOR_OUTPUT_ADAPTER,
)

from knowledge_map.evaluation.scoring import UNSCORED

TASKS_DIR = Path("src/knowledge_map/evaluation/tasks")


def _evaluate_methods() -> list[tuple[str, ast.FunctionDef]]:
    """Every `evaluate` method defined on an Evaluator in the tasks package."""

    found: list[tuple[str, ast.FunctionDef]] = []
    for path in sorted(TASKS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                isinstance(base, ast.Name) and base.id == "Evaluator"
                for base in node.bases
            ):
                continue
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "evaluate":
                    found.append((f"{path.name}::{node.name}", item))
    return found


def test_the_tasks_package_defines_evaluators_to_check() -> None:
    """The AST walk below is silent if it stops finding anything."""

    names = [name for name, _ in _evaluate_methods()]

    assert len(names) >= 10
    assert any("coreference.py" in name for name in names)
    assert any("extraction.py" in name for name in names)
    assert any("relevance.py" in name for name in names)


@pytest.mark.parametrize(
    "name,method", _evaluate_methods(), ids=[name for name, _ in _evaluate_methods()]
)
def test_no_evaluator_returns_none(name: str, method: ast.FunctionDef) -> None:
    returns_none = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and node.value.value is None
    ]

    assert not returns_none, (
        f"{name} returns None; return UNSCORED so the case is unscored rather "
        "than failed"
    )


def test_unscored_is_a_value_pydantic_evals_accepts() -> None:
    assert EVALUATOR_OUTPUT_ADAPTER.validate_python(UNSCORED) == {}

    with pytest.raises(Exception):
        EVALUATOR_OUTPUT_ADAPTER.validate_python(None)
