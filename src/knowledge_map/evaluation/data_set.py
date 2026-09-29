"""Evaluation Data Sets authored as version-controlled YAML files.

A Data Set is one file under ``evals/``. Gold labels come from a human,
silver labels come from a model, and unlabeled questions support initial
trace review. Its revision is a commit; see ADR 0017. A case's ``id`` and
``split`` are authored by hand.
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


class LabelQuality(str, Enum):
    """Who wrote a Data Set's labels, which is how far a score can be read.

    A `GOLD` score is agreement with a person. A `SILVER` score is agreement
    with another model's reading of a guideline, so a case the annotator got
    wrong scores a correct answer as a miss, and the two must never be
    compared as though they measured the same thing. `UNLABELED` cases have
    no answer labels and support case review before evaluators are chosen.
    """

    GOLD = "gold"
    SILVER = "silver"
    UNLABELED = "unlabeled"


class EvaluationSplit(str, Enum):
    TRAINING = "training"
    CALIBRATION = "calibration"
    HELD_OUT = "held-out"


class EvaluationCase(BaseModel, Generic[InputT, OutputT, MetadataT]):
    """One authored example for a component task.

    ``id`` is authored, never derived, and must stay stable across revisions:
    it is what makes one report comparable to an earlier one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    split: EvaluationSplit = EvaluationSplit.HELD_OUT
    task_input: InputT
    expected_output: OutputT | None = None
    metadata: MetadataT | None = None
    tags: tuple[str, ...] = ()


class EvaluationDataSet(BaseModel, Generic[InputT, OutputT, MetadataT]):
    """Every authored case for one task, as read from one YAML file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str = Field(min_length=1)
    description: str = Field(min_length=1)
    cases: tuple[EvaluationCase[InputT, OutputT, MetadataT], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> EvaluationDataSet[InputT, OutputT, MetadataT]:
        seen: set[str] = set()
        repeated = sorted({c.id for c in self.cases if c.id in seen or seen.add(c.id)})
        if repeated:
            raise ValueError(
                "an Evaluation Data Set cannot repeat a case id: " + ", ".join(repeated)
            )
        return self

    def split(
        self, split: EvaluationSplit
    ) -> tuple[EvaluationCase[InputT, OutputT, MetadataT], ...]:
        """Return only the cases the author assigned to ``split``."""
        return tuple(case for case in self.cases if case.split is split)


def data_set_path(
    task: str, label_quality: LabelQuality, *, root: Path | None = None
) -> Path:
    """Locate the Data Set file for ``task``.

    ``label_quality`` selects the directory rather than defaulting to one,
    because a file's directory is the project's record of who labeled it and
    a wrong guess would file a model's labels among a person's.
    """
    return (root or Path("evals")) / label_quality.value / f"{task}.yaml"


def load_data_set(
    path: Path | str,
    *,
    input_type: type[Any] = Any,
    output_type: type[Any] = Any,
    metadata_type: type[Any] = Any,
) -> EvaluationDataSet[Any, Any, Any]:
    """Read and validate one Data Set file.

    Pass the task's own types to validate every case's ``task_input`` and
    ``expected_output`` as the file is read.
    """
    path = Path(path)
    document = yaml.safe_load(path.read_text())
    if not isinstance(document, Mapping):
        raise ValueError(f"{path} does not contain an Evaluation Data Set mapping")
    model = EvaluationDataSet[input_type, output_type, metadata_type]  # type: ignore[valid-type]
    return model.model_validate(document)
