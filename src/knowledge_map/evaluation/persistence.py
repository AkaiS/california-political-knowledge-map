"""Checkpoint framework results so an interrupted evaluation remains reviewable."""

from __future__ import annotations

import dataclasses
import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from pydantic_core import to_jsonable_python
from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure

from knowledge_map.schemas import ModelDeployment

from .data_set import EvaluationCase, LabelQuality
from .report_file import (
    _worktree_is_dirty,
    atomic_write_document,
    report_path,
    run_commit,
    trace_url,
)


class ReportCheckpoint:
    """One run, one atomically replaced report file, with an explicit population."""

    def __init__(
        self,
        *,
        task: str,
        cases: Sequence[EvaluationCase],
        deployment: ModelDeployment,
        data_set_path: Path,
        label_quality: LabelQuality,
        split: str | None = None,
        experiment_metadata: Mapping[str, Any] | None = None,
        root: Path | None = None,
    ) -> None:
        if not cases:
            raise ValueError("an evaluation must select at least one case")
        self._selected = [case.id for case in cases]
        if len(set(self._selected)) != len(self._selected):
            raise ValueError("selected case IDs must be unique")
        self._lock = RLock()
        self._started: set[str] = set()
        self._results: dict[str, ReportCase | ReportCaseFailure] = {}
        self._report = EvaluationReport(
            name=task, cases=[], experiment_metadata=dict(experiment_metadata or {})
        )
        ran_at = datetime.now(UTC)
        base = report_path(task, deployment=deployment, ran_at=ran_at, root=root)
        # Independent runs started in the same second still own separate files.
        self.path = base.with_stem(f"{base.stem}-{uuid4().hex[:8]}")
        self._provenance = {
            "task": task,
            "model": deployment.model,
            "deployment": deployment.model_dump(mode="json"),
            "commit": run_commit(),
            "dirty": _worktree_is_dirty(),
            "data_set": str(data_set_path),
            "data_set_sha256": hashlib.sha256(data_set_path.read_bytes()).hexdigest(),
            "label_quality": label_quality.value,
            "split": split,
            "ran_at": ran_at.isoformat(),
            "experiment_metadata": dict(experiment_metadata or {}),
        }
        self._selected_cases = to_jsonable_python(
            [
                {
                    "name": case.id,
                    "inputs": case.task_input,
                    "expected_output": case.expected_output,
                    "metadata": case.metadata,
                }
                for case in cases
            ],
            fallback=str,
        )
        self._status = "running"
        self._reason: str | None = None
        self._write()

    def started(self, case_id: str) -> None:
        with self._lock:
            self._validate_id(case_id)
            self._started.add(case_id)
            self._write()

    def terminal(self, result: ReportCase | ReportCaseFailure | None) -> None:
        if result is None:
            return
        with self._lock:
            self._validate_id(result.name)
            if result.name in self._results:
                raise ValueError(f"duplicate terminal outcome for {result.name}")
            self._started.add(result.name)
            self._results[result.name] = result
            self._report.cases = [
                self._results[name]
                for name in self._selected
                if isinstance(self._results.get(name), ReportCase)
            ]
            self._report.failures = [
                self._results[name]
                for name in self._selected
                if isinstance(self._results.get(name), ReportCaseFailure)
            ]
            self._write()

    def finish(self, report: EvaluationReport) -> None:
        with self._lock:
            names = [result.name for result in [*report.cases, *report.failures]]
            if Counter(names) != Counter(self._selected):
                self.interrupted(
                    "returned report does not match the selected case population"
                )
                raise ValueError(
                    "returned report does not match the selected case population"
                )
            self._report = report
            self._results = {
                result.name: result for result in [*report.cases, *report.failures]
            }
            self._started.update(names)
            self._status = "completed"
            self._reason = None
            self._write()

    def interrupted(self, reason: str) -> None:
        with self._lock:
            self._status = "incomplete"
            self._reason = reason
            self._write()

    def lifecycle(self, base: type[CaseLifecycle]) -> type[CaseLifecycle]:
        checkpoint = self

        class CheckpointLifecycle(base):
            async def setup(self) -> None:
                checkpoint.started(self.case.name)
                await super().setup()

            async def teardown(self, result: Any) -> None:
                # Preserve the terminal outcome even if task-specific cleanup aborts.
                try:
                    checkpoint.terminal(result)
                finally:
                    await super().teardown(result)

        return CheckpointLifecycle

    def _validate_id(self, case_id: str) -> None:
        if case_id not in self._selected:
            raise ValueError(f"unexpected case ID {case_id}")

    def _write(self) -> None:
        document = {
            **self._provenance,
            "trace_url": trace_url(self._report),
            "evaluation_run": {
                "status": self._status,
                "selected_case_ids": self._selected,
                "selected_cases": self._selected_cases,
                "selected_count": len(self._selected),
                "started_case_ids": [
                    name for name in self._selected if name in self._started
                ],
                "started_count": len(self._started),
                "terminal_count": len(self._results),
                "failure_count": len(self._report.failures),
                "unresolved_case_ids": [
                    name for name in self._selected if name not in self._results
                ],
                "interruption_reason": self._reason,
            },
            "report": to_jsonable_python(
                dataclasses.asdict(self._report), fallback=str
            ),
        }
        if self._provenance["task"] == "retrieval":
            from .retrieval_report import compact_retrieval_report

            document = compact_retrieval_report(document)
        atomic_write_document(self.path, document)
