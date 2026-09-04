"""Evaluation over Data Sets authored as files, versioned by git (ADR 0017)."""

from .data_set import (
    EvaluationCase,
    EvaluationDataSet,
    EvaluationSplit,
    LabelQuality,
    data_set_path,
    load_data_set,
)
from .engine import build_dataset, run_data_set
from .report_file import report_path, run_commit, trace_url, write_report

__all__ = [
    "EvaluationCase",
    "EvaluationDataSet",
    "EvaluationSplit",
    "LabelQuality",
    "build_dataset",
    "data_set_path",
    "load_data_set",
    "report_path",
    "run_commit",
    "run_data_set",
    "trace_url",
    "write_report",
]
