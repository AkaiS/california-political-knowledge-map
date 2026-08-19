"""Evaluation Gold Sets authored as version-controlled YAML files.

A Gold Set is one file under ``evals/gold/``. Its revision is a commit; see
ADR 0017. Nothing here persists to a database, and nothing here computes an
identity: a case's ``id`` and ``split`` are authored by hand.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")
MetadataT = TypeVar("MetadataT")


class EvaluationSplit(str, Enum):
    TRAINING = "training"
    CALIBRATION = "calibration"
    HELD_OUT = "held-out"


class EvaluationCase(BaseModel, Generic[InputT, OutputT, MetadataT]):
    """One authored example for a component task.

    ``id`` is stable across revisions of the Gold Set and is what makes a
    report comparable to an earlier one. It is authored, not derived, so
    regenerating the file cannot silently renumber the population.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    split: EvaluationSplit = EvaluationSplit.HELD_OUT
    task_input: InputT
    expected_output: OutputT | None = None
    metadata: MetadataT | None = None
    tags: tuple[str, ...] = ()


class EvaluationGoldSet(BaseModel, Generic[InputT, OutputT, MetadataT]):
    """Every authored case for one task, as read from one YAML file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str = Field(min_length=1)
    description: str = Field(min_length=1)
    cases: tuple[EvaluationCase[InputT, OutputT, MetadataT], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> EvaluationGoldSet[InputT, OutputT, MetadataT]:
        seen: set[str] = set()
        repeated = sorted({c.id for c in self.cases if c.id in seen or seen.add(c.id)})
        if repeated:
            raise ValueError(
                "an Evaluation Gold Set cannot repeat a case id: " + ", ".join(repeated)
            )
        return self

    def split(
        self, split: EvaluationSplit
    ) -> tuple[EvaluationCase[InputT, OutputT, MetadataT], ...]:
        """Return only the cases the author assigned to ``split``."""
        return tuple(case for case in self.cases if case.split is split)


def gold_set_path(task: str, *, root: Path | None = None) -> Path:
    """Locate the Gold Set file for ``task``."""
    return (root or Path("evals/gold")) / f"{task}.yaml"


def load_gold_set(
    path: Path | str,
    *,
    input_type: type[Any] = Any,
    output_type: type[Any] = Any,
    metadata_type: type[Any] = Any,
) -> EvaluationGoldSet[Any, Any, Any]:
    """Read and validate one Gold Set file.

    Pass the task's own types to have every case's ``task_input`` and
    ``expected_output`` validated against them as the file is read; the
    file is the only place a case is authored, so this is where a typo in
    one is caught.
    """
    path = Path(path)
    document = yaml.safe_load(path.read_text())
    if not isinstance(document, Mapping):
        raise ValueError(f"{path} does not contain a Gold Set mapping")
    model = EvaluationGoldSet[input_type, output_type, metadata_type]  # type: ignore[valid-type]
    return model.model_validate(document)
