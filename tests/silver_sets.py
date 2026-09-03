"""Reading a silver set the way the eval CLI reads it.

Three silver-set tests load their file, and each one loading it its own way
would let the file drift from what `ca-map eval run <task>` validates it
against -- the one thing those tests exist to prevent.  So they load it
through one function, which asks the registry for the task's own types.
"""

from pathlib import Path
from typing import Any

from knowledge_map.evaluation import load_gold_set
from knowledge_map.evaluation.tasks import task_named


def load_silver_set(path: Path, task_name: str) -> Any:
    """Load the file at `path` through the registered task's own types."""

    task = task_named(task_name)
    return load_gold_set(
        path,
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )
