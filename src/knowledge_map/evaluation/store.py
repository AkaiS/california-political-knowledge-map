"""SQLite persistence for imported evaluation definitions and artifacts.

Authored definitions remain the source of truth in code or files.  This module
only stores the immutable identity and queryable index needed by the runtime.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .definitions import (
    AuthoredDefinitionConflictError,
    EvaluationCase,
    EvaluationGoldSet,
    EvaluationSplit,
    EvaluationRubric,
    SchemaReference,
    new_uuid7,
)
from .suites import EvaluationMetricReference, EvaluationSuite
from .runs import (
    CaseEvaluatorExecution,
    CaseMetricObservation,
    EvaluationCaseDisposition,
    EvaluationCaseManifestEntry,
    EvaluationCaseResult,
    EvaluationMetricObservation,
    EvaluationProducerStatus,
    EvaluationRunConfiguration,
    EvaluationGateOutcome,
    EvaluationRunIssue,
    EvaluationRunRecord,
    EvaluationRunStatus,
    ReportEvaluatorExecution,
    RunMetricObservation,
    TaskOutcome,
)


class EvaluationDefinitionKind(str, Enum):
    CASE = "evaluation_case"
    GOLD_SET = "evaluation_gold_set"
    RUBRIC = "evaluation_rubric"
    SUITE = "evaluation_suite"


class EvaluationDefinitionRecord(BaseModel):
    """The database index for one externally authored definition revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    kind: EvaluationDefinitionKind
    business_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_references: tuple[SchemaReference, ...] = ()
    metadata: Mapping[str, Any] = Field(default_factory=dict)


class EvaluationGoldSetMembershipRecord(BaseModel):
    """A relationally enforced assignment of a case revision to a split."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    membership_id: UUID
    gold_set_record_id: UUID
    case_record_id: UUID
    case_business_id: str = Field(min_length=1)
    case_revision: int = Field(ge=1)
    case_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    split: EvaluationSplit


class EvaluationArtifactRecord(BaseModel):
    """Immutable metadata for content stored outside the relational ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    retention_class: str = Field(min_length=1)
    sensitivity_classification: str = Field(min_length=1)
    redaction_classification: str = Field(min_length=1)

    @property
    def record_id(self) -> UUID:
        """Alias for callers that treat all ledger records uniformly."""
        return self.artifact_id

    @property
    def sensitivity(self) -> str:
        return self.sensitivity_classification

    @property
    def redaction(self) -> str:
        return self.redaction_classification


class ArtifactLocationRecord(BaseModel):
    """A replaceable external resolution location for one artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    location_id: UUID
    artifact_id: UUID
    location_key: str = Field(min_length=1)
    location_kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)

    @property
    def location(self) -> str:
        return self.uri


class ArtifactDerivativeRecord(BaseModel):
    """A provenance link from a derived artifact to its source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_artifact_id: UUID
    derivative_artifact_id: UUID
    relationship: str = Field(min_length=1)


class ArtifactConflictError(ValueError):
    """An artifact hash was reused with different immutable metadata."""


def _definition_kind(definition: Any) -> EvaluationDefinitionKind:
    if isinstance(definition, EvaluationCase):
        return EvaluationDefinitionKind.CASE
    if isinstance(definition, EvaluationGoldSet):
        return EvaluationDefinitionKind.GOLD_SET
    if isinstance(definition, EvaluationRubric):
        return EvaluationDefinitionKind.RUBRIC
    if isinstance(definition, EvaluationSuite):
        return EvaluationDefinitionKind.SUITE
    raise TypeError(f"unsupported authored definition: {type(definition).__name__}")


def _definition_schema_references(definition: Any) -> tuple[SchemaReference, ...]:
    if isinstance(definition, EvaluationCase):
        return tuple(
            schema
            for schema in (
                definition.input_schema,
                definition.expected_output_schema,
                definition.metadata_schema,
            )
            if schema is not None
        )
    if isinstance(definition, EvaluationSuite):
        return (
            definition.task_contract.input_schema,
            definition.task_contract.output_schema,
            definition.task_contract.metadata_schema,
        )
    return ()


def _definition_metadata(definition: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "description": definition.description,
        "tags": list(getattr(definition, "tags", ())),
    }
    if isinstance(definition, EvaluationSuite):
        metadata.update(
            {
                "case_evaluator_names": [
                    evaluator.name for evaluator in definition.case_evaluators
                ],
                "report_evaluator_names": [
                    evaluator.name for evaluator in definition.report_evaluators
                ],
                "metric_identities": [
                    {
                        "namespaced_name": metric.namespaced_name,
                        "evaluator_revision": metric.evaluator_revision,
                    }
                    for metric in definition.metrics
                ],
            }
        )
    return metadata


class SQLiteEvaluationLedger:
    """A relational ledger for imported definitions and artifact metadata."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteEvaluationLedger":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS evaluation_definition_revisions (
                record_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN (
                    'evaluation_case', 'evaluation_gold_set',
                    'evaluation_rubric', 'evaluation_suite'
                )),
                business_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                content_hash TEXT NOT NULL CHECK (
                    length(content_hash) = 64 AND content_hash GLOB '[0-9a-f]*'
                ),
                schema_references_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                UNIQUE(kind, business_id, revision)
            );

            CREATE INDEX IF NOT EXISTS idx_evaluation_definition_business
                ON evaluation_definition_revisions(kind, business_id, revision);
            CREATE INDEX IF NOT EXISTS idx_evaluation_definition_hash
                ON evaluation_definition_revisions(content_hash);

            CREATE TABLE IF NOT EXISTS evaluation_gold_set_memberships (
                membership_id TEXT PRIMARY KEY,
                gold_set_record_id TEXT NOT NULL
                    REFERENCES evaluation_definition_revisions(record_id),
                case_record_id TEXT NOT NULL
                    REFERENCES evaluation_definition_revisions(record_id),
                case_business_id TEXT NOT NULL,
                case_revision INTEGER NOT NULL CHECK (case_revision >= 1),
                case_content_hash TEXT NOT NULL CHECK (
                    length(case_content_hash) = 64
                    AND case_content_hash GLOB '[0-9a-f]*'
                ),
                split TEXT NOT NULL CHECK (
                    split IN ('training', 'calibration', 'held-out')
                ),
                UNIQUE(gold_set_record_id, case_record_id),
                UNIQUE(gold_set_record_id, case_business_id, case_revision)
            );

            CREATE TRIGGER IF NOT EXISTS evaluation_gold_set_membership_guard
            BEFORE INSERT ON evaluation_gold_set_memberships
            BEGIN
                SELECT RAISE(ABORT, 'membership owner must be an Evaluation Gold Set')
                WHERE (SELECT kind FROM evaluation_definition_revisions
                       WHERE record_id = NEW.gold_set_record_id)
                      <> 'evaluation_gold_set';
                SELECT RAISE(ABORT, 'membership case must be an Evaluation Case')
                WHERE (SELECT kind FROM evaluation_definition_revisions
                       WHERE record_id = NEW.case_record_id)
                      <> 'evaluation_case';
                SELECT RAISE(ABORT, 'membership case revision does not match its record')
                WHERE NOT EXISTS (
                    SELECT 1 FROM evaluation_definition_revisions
                    WHERE record_id = NEW.case_record_id
                      AND business_id = NEW.case_business_id
                      AND revision = NEW.case_revision
                      AND content_hash = NEW.case_content_hash
                );
            END;

            CREATE TABLE IF NOT EXISTS evaluation_artifacts (
                artifact_id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL UNIQUE CHECK (
                    length(content_hash) = 64
                    AND content_hash NOT GLOB '*[^0-9a-f]*'
                ),
                kind TEXT NOT NULL,
                media_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
                retention_class TEXT NOT NULL,
                sensitivity_classification TEXT NOT NULL,
                redaction_classification TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_evaluation_artifacts_kind
                ON evaluation_artifacts(kind);

            CREATE TABLE IF NOT EXISTS evaluation_artifact_locations (
                location_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id) ON DELETE CASCADE,
                location_key TEXT NOT NULL,
                location_kind TEXT NOT NULL,
                uri TEXT NOT NULL,
                UNIQUE(artifact_id, location_key)
            );

            CREATE TABLE IF NOT EXISTS evaluation_artifact_derivatives (
                source_artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id),
                derivative_artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id),
                relationship TEXT NOT NULL,
                PRIMARY KEY(source_artifact_id, derivative_artifact_id),
                CHECK(source_artifact_id <> derivative_artifact_id)
            );

            CREATE TRIGGER IF NOT EXISTS evaluation_definition_revisions_immutable_update
            BEFORE UPDATE ON evaluation_definition_revisions
            BEGIN
                SELECT RAISE(ABORT, 'evaluation definition revisions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS evaluation_definition_revisions_immutable_delete
            BEFORE DELETE ON evaluation_definition_revisions
            BEGIN
                SELECT RAISE(ABORT, 'evaluation definition revisions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS evaluation_gold_set_memberships_immutable_update
            BEFORE UPDATE ON evaluation_gold_set_memberships
            BEGIN
                SELECT RAISE(ABORT, 'Gold Set memberships are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS evaluation_gold_set_memberships_immutable_delete
            BEFORE DELETE ON evaluation_gold_set_memberships
            BEGIN
                SELECT RAISE(ABORT, 'Gold Set memberships are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS evaluation_artifacts_immutable_update
            BEFORE UPDATE ON evaluation_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'Evaluation Artifacts are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS evaluation_artifacts_immutable_delete
            BEFORE DELETE ON evaluation_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'Evaluation Artifacts are immutable');
            END;

            CREATE TABLE IF NOT EXISTS evaluation_runs (
                run_id TEXT PRIMARY KEY,
                suite_record_id TEXT NOT NULL
                    REFERENCES evaluation_definition_revisions(record_id),
                suite_business_id TEXT NOT NULL,
                suite_revision INTEGER NOT NULL CHECK (suite_revision >= 1),
                suite_content_hash TEXT NOT NULL,
                gold_set_record_id TEXT NOT NULL
                    REFERENCES evaluation_definition_revisions(record_id),
                gold_set_business_id TEXT NOT NULL,
                gold_set_revision INTEGER NOT NULL CHECK (gold_set_revision >= 1),
                gold_set_content_hash TEXT NOT NULL,
                configuration_json TEXT NOT NULL,
                configuration_fingerprint TEXT NOT NULL,
                selection_expression TEXT,
                selection_provenance_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending', 'running', 'completed', 'failed', 'cancelled')
                ),
                retry_of_run_id TEXT REFERENCES evaluation_runs(run_id),
                issues_json TEXT NOT NULL DEFAULT '[]',
                gate_outcomes_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS evaluation_case_manifests (
                manifest_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id),
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                case_record_id TEXT NOT NULL
                    REFERENCES evaluation_definition_revisions(record_id),
                case_business_id TEXT NOT NULL,
                case_revision INTEGER NOT NULL CHECK (case_revision >= 1),
                case_content_hash TEXT NOT NULL,
                split TEXT NOT NULL CHECK (split IN ('training', 'calibration', 'held-out')),
                UNIQUE(run_id, case_record_id),
                UNIQUE(run_id, ordinal)
            );

            CREATE TABLE IF NOT EXISTS evaluation_case_results (
                result_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id),
                manifest_id TEXT NOT NULL UNIQUE
                    REFERENCES evaluation_case_manifests(manifest_id),
                case_record_id TEXT NOT NULL
                    REFERENCES evaluation_definition_revisions(record_id),
                execution_disposition TEXT NOT NULL
                    CHECK (execution_disposition IN (
                        'pending', 'completed', 'failed', 'cancelled'
                    )),
                task_outcome_json TEXT
            );

            CREATE TABLE IF NOT EXISTS case_evaluator_executions (
                execution_id TEXT PRIMARY KEY,
                case_result_id TEXT NOT NULL REFERENCES evaluation_case_results(result_id),
                evaluator_name TEXT NOT NULL,
                evaluator_revision INTEGER NOT NULL CHECK (evaluator_revision >= 1),
                configuration_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
                duration_seconds REAL NOT NULL CHECK (duration_seconds >= 0),
                failure_message TEXT
            );

            CREATE TABLE IF NOT EXISTS report_evaluator_executions (
                execution_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id),
                evaluator_name TEXT NOT NULL,
                evaluator_revision INTEGER NOT NULL CHECK (evaluator_revision >= 1),
                configuration_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
                duration_seconds REAL NOT NULL CHECK (duration_seconds >= 0),
                failure_message TEXT
            );

            CREATE TABLE IF NOT EXISTS case_metric_observations (
                observation_id TEXT PRIMARY KEY,
                case_result_id TEXT NOT NULL
                    REFERENCES evaluation_case_results(result_id),
                case_evaluator_execution_id TEXT NOT NULL
                    REFERENCES case_evaluator_executions(execution_id),
                metric_namespaced_name TEXT NOT NULL,
                metric_evaluator_revision INTEGER NOT NULL CHECK (metric_evaluator_revision >= 1),
                number_value REAL,
                integer_value INTEGER,
                boolean_value INTEGER,
                string_value TEXT,
                structured_json TEXT,
                CHECK ((number_value IS NOT NULL) + (integer_value IS NOT NULL)
                    + (boolean_value IS NOT NULL) + (string_value IS NOT NULL)
                    + (structured_json IS NOT NULL) = 1)
            );

            CREATE TABLE IF NOT EXISTS run_metric_observations (
                observation_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id),
                report_evaluator_execution_id TEXT NOT NULL
                    REFERENCES report_evaluator_executions(execution_id),
                metric_namespaced_name TEXT NOT NULL,
                metric_evaluator_revision INTEGER NOT NULL CHECK (metric_evaluator_revision >= 1),
                number_value REAL,
                integer_value INTEGER,
                boolean_value INTEGER,
                string_value TEXT,
                structured_json TEXT,
                CHECK ((number_value IS NOT NULL) + (integer_value IS NOT NULL)
                    + (boolean_value IS NOT NULL) + (string_value IS NOT NULL)
                    + (structured_json IS NOT NULL) = 1)
            );
            """
        )
        run_columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(evaluation_runs)")
        }
        if "retry_of_run_id" not in run_columns:
            self._connection.execute(
                "ALTER TABLE evaluation_runs ADD COLUMN retry_of_run_id TEXT"
            )
        if "issues_json" not in run_columns:
            self._connection.execute(
                "ALTER TABLE evaluation_runs ADD COLUMN issues_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "gate_outcomes_json" not in run_columns:
            self._connection.execute(
                "ALTER TABLE evaluation_runs ADD COLUMN gate_outcomes_json TEXT NOT NULL DEFAULT '[]'"
            )
        self._connection.commit()

    def create_evaluation_run(
        self,
        run: EvaluationRunRecord,
        manifest: Iterable[EvaluationCaseManifestEntry],
        pending_results: Iterable[EvaluationCaseResult],
    ) -> None:
        """Atomically create a run, its frozen manifest, and pending envelopes."""
        manifest_items = tuple(manifest)
        result_items = tuple(pending_results)
        if len(manifest_items) != len(result_items):
            raise ValueError("every manifest entry requires exactly one pending result")
        try:
            self._connection.execute("BEGIN")
            self._connection.execute(
                """
                INSERT INTO evaluation_runs (
                    run_id, suite_record_id, suite_business_id, suite_revision,
                    suite_content_hash, gold_set_record_id, gold_set_business_id,
                    gold_set_revision, gold_set_content_hash, configuration_json,
                    configuration_fingerprint, selection_expression,
                    selection_provenance_json, status, retry_of_run_id,
                    issues_json, gate_outcomes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.run_id), str(run.suite_record_id), run.suite_business_id,
                    run.suite_revision, run.suite_content_hash,
                    str(run.gold_set_record_id), run.gold_set_business_id,
                    run.gold_set_revision, run.gold_set_content_hash,
                    run.configuration.configuration_json,
                    run.configuration.content_fingerprint,
                    run.selection_expression,
                    json.dumps(run.selection_provenance, sort_keys=True, separators=(",", ":")),
                    run.status.value,
                    None if run.retry_of_run_id is None else str(run.retry_of_run_id),
                    json.dumps(
                        [issue.model_dump(mode="json") for issue in run.issues],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        [gate.model_dump(mode="json") for gate in run.gate_outcomes],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            for entry in manifest_items:
                self._connection.execute(
                    """
                    INSERT INTO evaluation_case_manifests (
                        manifest_id, run_id, ordinal, case_record_id,
                        case_business_id, case_revision, case_content_hash, split
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(entry.manifest_id), str(entry.run_id), entry.ordinal,
                        str(entry.case_record_id), entry.case_business_id,
                        entry.case_revision, entry.case_content_hash, entry.split.value,
                    ),
                )
            for result in result_items:
                self._connection.execute(
                    """
                    INSERT INTO evaluation_case_results (
                        result_id, run_id, manifest_id, case_record_id,
                        execution_disposition, task_outcome_json
                    ) VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        str(result.result_id), str(result.run_id), str(result.manifest_id),
                        str(result.case_record_id), result.execution_disposition.value,
                    ),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def record_case_evaluation(
        self,
        result: EvaluationCaseResult,
        executions: Iterable[CaseEvaluatorExecution],
        observations: Iterable[CaseMetricObservation],
    ) -> None:
        """Atomically finalize one case result and its evaluator evidence."""
        executions = tuple(executions)
        observations = tuple(observations)
        try:
            self._connection.execute("BEGIN")
            cursor = self._connection.execute(
                """
                UPDATE evaluation_case_results
                SET execution_disposition = ?, task_outcome_json = ?
                WHERE result_id = ?
                """,
                (
                    result.execution_disposition.value,
                    None if result.task_outcome is None else json.dumps(
                        result.task_outcome.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    str(result.result_id),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown Evaluation Case Result: {result.result_id}")
            for execution in executions:
                self._insert_case_execution(execution)
            for observation in observations:
                self._insert_case_observation(observation)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def record_report_evaluation(
        self,
        executions: Iterable[ReportEvaluatorExecution],
        observations: Iterable[RunMetricObservation],
    ) -> None:
        """Atomically persist report evaluator executions and run observations."""
        executions = tuple(executions)
        observations = tuple(observations)
        try:
            self._connection.execute("BEGIN")
            for execution in executions:
                self._insert_report_execution(execution)
            for observation in observations:
                self._insert_run_observation(observation)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def complete_evaluation_run(
        self,
        run_id: UUID,
        *,
        issues: Iterable[EvaluationRunIssue] = (),
        gate_outcomes: Iterable[EvaluationGateOutcome] = (),
    ) -> EvaluationRunRecord:
        self._set_evaluation_run_status(
            run_id,
            EvaluationRunStatus.COMPLETED,
            issues=issues,
            gate_outcomes=gate_outcomes,
        )
        run = self.get_evaluation_run(run_id)
        if run is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        return run

    def fail_evaluation_run(
        self,
        run_id: UUID,
        *,
        issues: Iterable[EvaluationRunIssue] = (),
    ) -> EvaluationRunRecord:
        self._set_evaluation_run_status(run_id, EvaluationRunStatus.FAILED, issues=issues)
        run = self.get_evaluation_run(run_id)
        if run is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        return run

    def cancel_evaluation_run(
        self,
        run_id: UUID,
        *,
        issues: Iterable[EvaluationRunIssue] = (),
    ) -> EvaluationRunRecord:
        self._set_evaluation_run_status(run_id, EvaluationRunStatus.CANCELLED, issues=issues)
        run = self.get_evaluation_run(run_id)
        if run is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        return run

    def _set_evaluation_run_status(
        self,
        run_id: UUID,
        status: EvaluationRunStatus,
        *,
        issues: Iterable[EvaluationRunIssue] = (),
        gate_outcomes: Iterable[EvaluationGateOutcome] = (),
    ) -> None:
        issue_items = tuple(issues)
        gate_items = tuple(gate_outcomes)
        cursor = self._connection.execute(
            """
            UPDATE evaluation_runs
            SET status = ?, issues_json = ?, gate_outcomes_json = ?
            WHERE run_id = ?
            """,
            (
                status.value,
                json.dumps(
                    [issue.model_dump(mode="json") for issue in issue_items],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(
                    [gate.model_dump(mode="json") for gate in gate_items],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                str(run_id),
            ),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        self._connection.commit()

    def get_evaluation_run(self, run_id: UUID) -> EvaluationRunRecord | None:
        row = self._connection.execute(
            "SELECT * FROM evaluation_runs WHERE run_id = ?", (str(run_id),)
        ).fetchone()
        return None if row is None else self._run_from_row(row)

    def list_evaluation_runs(self) -> list[EvaluationRunRecord]:
        rows = self._connection.execute(
            "SELECT * FROM evaluation_runs ORDER BY rowid"
        ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def list_evaluation_case_manifest(
        self, run_id: UUID
    ) -> list[EvaluationCaseManifestEntry]:
        rows = self._connection.execute(
            "SELECT * FROM evaluation_case_manifests WHERE run_id = ? ORDER BY ordinal",
            (str(run_id),),
        ).fetchall()
        return [
            EvaluationCaseManifestEntry(
                manifest_id=UUID(row["manifest_id"]), run_id=UUID(row["run_id"]),
                ordinal=row["ordinal"],
                case=EvaluationCaseRevisionReference(
                    record_id=UUID(row["case_record_id"]),
                    business_id=row["case_business_id"],
                    revision=row["case_revision"],
                    content_hash=row["case_content_hash"],
                ),
                split=EvaluationSplit(row["split"]),
            )
            for row in rows
        ]

    def list_evaluation_case_results(self, run_id: UUID) -> list[EvaluationCaseResult]:
        rows = self._connection.execute(
            "SELECT * FROM evaluation_case_results WHERE run_id = ? ORDER BY rowid",
            (str(run_id),),
        ).fetchall()
        return [self._case_result_from_row(row) for row in rows]

    list_case_manifest = list_evaluation_case_manifest
    list_case_results = list_evaluation_case_results

    def list_case_evaluator_executions(
        self, case_result_id: UUID
    ) -> list[CaseEvaluatorExecution]:
        rows = self._connection.execute(
            "SELECT * FROM case_evaluator_executions WHERE case_result_id = ? ORDER BY rowid",
            (str(case_result_id),),
        ).fetchall()
        return [self._case_execution_from_row(row) for row in rows]

    def list_report_evaluator_executions(
        self, run_id: UUID
    ) -> list[ReportEvaluatorExecution]:
        rows = self._connection.execute(
            "SELECT * FROM report_evaluator_executions WHERE run_id = ? ORDER BY rowid",
            (str(run_id),),
        ).fetchall()
        return [self._report_execution_from_row(row) for row in rows]

    def list_case_metric_observations(
        self, case_result_id: UUID
    ) -> list[CaseMetricObservation]:
        rows = self._connection.execute(
            """
            SELECT * FROM case_metric_observations
            WHERE case_result_id = ? ORDER BY rowid
            """,
            (str(case_result_id),),
        ).fetchall()
        return [
            CaseMetricObservation(
                observation_id=UUID(row["observation_id"]),
                case_result_id=UUID(row["case_result_id"]),
                case_evaluator_execution_id=UUID(row["case_evaluator_execution_id"]),
                metric=EvaluationMetricReference(
                    namespaced_name=row["metric_namespaced_name"],
                    evaluator_revision=row["metric_evaluator_revision"],
                ),
                **self._observation_values(row),
            )
            for row in rows
        ]

    def list_run_metric_observations(
        self, run_id: UUID
    ) -> list[RunMetricObservation]:
        rows = self._connection.execute(
            """
            SELECT * FROM run_metric_observations
            WHERE run_id = ? ORDER BY rowid
            """,
            (str(run_id),),
        ).fetchall()
        return [
            RunMetricObservation(
                observation_id=UUID(row["observation_id"]),
                run_id=UUID(row["run_id"]),
                report_evaluator_execution_id=UUID(row["report_evaluator_execution_id"]),
                metric=EvaluationMetricReference(
                    namespaced_name=row["metric_namespaced_name"],
                    evaluator_revision=row["metric_evaluator_revision"],
                ),
                **self._observation_values(row),
            )
            for row in rows
        ]

    list_case_observations = list_case_metric_observations
    list_run_observations = list_run_metric_observations

    @staticmethod
    def _observation_values(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "number_value": row["number_value"],
            "integer_value": row["integer_value"],
            "boolean_value": None if row["boolean_value"] is None else bool(row["boolean_value"]),
            "string_value": row["string_value"],
            "structured_json": None if row["structured_json"] is None else json.loads(row["structured_json"]),
        }

    def _insert_case_execution(self, execution: CaseEvaluatorExecution) -> None:
        self._connection.execute(
            """
            INSERT INTO case_evaluator_executions (
                execution_id, case_result_id, evaluator_name, evaluator_revision,
                configuration_fingerprint, status, duration_seconds, failure_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(execution.execution_id), str(execution.case_result_id),
                execution.evaluator_name, execution.evaluator_revision,
                execution.configuration_fingerprint, execution.status.value,
                execution.duration_seconds, execution.failure_message,
            ),
        )

    def _insert_report_execution(self, execution: ReportEvaluatorExecution) -> None:
        self._connection.execute(
            """
            INSERT INTO report_evaluator_executions (
                execution_id, run_id, evaluator_name, evaluator_revision,
                configuration_fingerprint, status, duration_seconds, failure_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(execution.execution_id), str(execution.run_id), execution.evaluator_name,
                execution.evaluator_revision, execution.configuration_fingerprint,
                execution.status.value, execution.duration_seconds, execution.failure_message,
            ),
        )

    @staticmethod
    def _observation_columns(observation: EvaluationMetricObservation) -> tuple[Any, ...]:
        return (
            str(observation.observation_id), observation.metric.namespaced_name,
            observation.metric.evaluator_revision, observation.number_value,
            observation.integer_value, observation.boolean_value,
            observation.string_value,
            None if observation.structured_json is None else json.dumps(
                observation.structured_json, sort_keys=True, separators=(",", ":")
            ),
        )

    def _insert_case_observation(self, observation: CaseMetricObservation) -> None:
        self._connection.execute(
            """
            INSERT INTO case_metric_observations (
                observation_id, case_result_id, case_evaluator_execution_id,
                metric_namespaced_name, metric_evaluator_revision, number_value,
                integer_value, boolean_value, string_value, structured_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(observation.observation_id), str(observation.case_result_id),
                str(observation.case_evaluator_execution_id),
                *self._observation_columns(observation)[1:],
            ),
        )

    def _insert_run_observation(self, observation: RunMetricObservation) -> None:
        self._connection.execute(
            """
            INSERT INTO run_metric_observations (
                observation_id, run_id, report_evaluator_execution_id,
                metric_namespaced_name, metric_evaluator_revision, number_value,
                integer_value, boolean_value, string_value, structured_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(observation.observation_id), str(observation.run_id),
                str(observation.report_evaluator_execution_id),
                *self._observation_columns(observation)[1:],
            ),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> EvaluationRunRecord:
        config = json.loads(row["configuration_json"])
        return EvaluationRunRecord(
            run_id=UUID(row["run_id"]), suite_record_id=UUID(row["suite_record_id"]),
            suite_business_id=row["suite_business_id"], suite_revision=row["suite_revision"],
            suite_content_hash=row["suite_content_hash"],
            gold_set_record_id=UUID(row["gold_set_record_id"]),
            gold_set_business_id=row["gold_set_business_id"],
            gold_set_revision=row["gold_set_revision"],
            gold_set_content_hash=row["gold_set_content_hash"],
            configuration=EvaluationRunConfiguration(
                provider=config["provider"], model=config["model"],
                execution_mode=config["execution_mode"], random_seed=config["random_seed"],
                model_settings=config["model_settings"],
                component_configuration=config["component_configuration"],
                code_fingerprint=config.get("code_fingerprint"),
            ),
            selection_expression=row["selection_expression"],
            selection_provenance=json.loads(row["selection_provenance_json"]),
            status=EvaluationRunStatus(row["status"]),
            retry_of_run_id=(
                None if row["retry_of_run_id"] is None else UUID(row["retry_of_run_id"])
            ),
            issues=tuple(
                EvaluationRunIssue.model_validate(item)
                for item in json.loads(row["issues_json"] or "[]")
            ),
            gate_outcomes=tuple(
                EvaluationGateOutcome.model_validate(item)
                for item in json.loads(row["gate_outcomes_json"] or "[]")
            ),
        )

    @staticmethod
    def _case_result_from_row(row: sqlite3.Row) -> EvaluationCaseResult:
        from .runs import TaskFailure, TaskSuccess

        outcome = None
        if row["task_outcome_json"] is not None:
            outcome_data = json.loads(row["task_outcome_json"])
            outcome = TaskSuccess.model_validate(outcome_data) if outcome_data["kind"] == "success" else TaskFailure.model_validate(outcome_data)
        return EvaluationCaseResult(
            result_id=UUID(row["result_id"]), run_id=UUID(row["run_id"]),
            manifest_id=UUID(row["manifest_id"]), case_record_id=UUID(row["case_record_id"]),
            execution_disposition=EvaluationCaseDisposition(row["execution_disposition"]),
            task_outcome=outcome,
        )

    @staticmethod
    def _case_execution_from_row(row: sqlite3.Row) -> CaseEvaluatorExecution:
        return CaseEvaluatorExecution(
            execution_id=UUID(row["execution_id"]), case_result_id=UUID(row["case_result_id"]),
            evaluator_name=row["evaluator_name"], evaluator_revision=row["evaluator_revision"],
            configuration_fingerprint=row["configuration_fingerprint"],
            status=EvaluationProducerStatus(row["status"]),
            duration_seconds=row["duration_seconds"], failure_message=row["failure_message"],
        )

    @staticmethod
    def _report_execution_from_row(row: sqlite3.Row) -> ReportEvaluatorExecution:
        return ReportEvaluatorExecution(
            execution_id=UUID(row["execution_id"]), run_id=UUID(row["run_id"]),
            evaluator_name=row["evaluator_name"], evaluator_revision=row["evaluator_revision"],
            configuration_fingerprint=row["configuration_fingerprint"],
            status=EvaluationProducerStatus(row["status"]),
            duration_seconds=row["duration_seconds"], failure_message=row["failure_message"],
        )

    def import_definition(self, definition: Any) -> EvaluationDefinitionRecord:
        """Import an authored revision's identity and index metadata idempotently."""
        kind = _definition_kind(definition)
        identity = definition.identity
        record = EvaluationDefinitionRecord(
            record_id=identity.record_id,
            kind=kind,
            business_id=identity.business_id,
            revision=identity.revision,
            content_hash=definition.content_hash,
            schema_references=_definition_schema_references(definition),
            metadata=_definition_metadata(definition),
        )

        existing = self._connection.execute(
            """
            SELECT * FROM evaluation_definition_revisions
            WHERE kind = ? AND business_id = ? AND revision = ?
            """,
            (record.kind.value, record.business_id, record.revision),
        ).fetchone()
        if existing is not None:
            if existing["content_hash"] != record.content_hash:
                raise AuthoredDefinitionConflictError(
                    "authored content changed without a new revision"
                )
            return self._definition_from_row(existing)

        try:
            self._connection.execute(
                """
                INSERT INTO evaluation_definition_revisions (
                    record_id, kind, business_id, revision, content_hash,
                    schema_references_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.record_id),
                    record.kind.value,
                    record.business_id,
                    record.revision,
                    record.content_hash,
                    json.dumps(
                        [
                            schema.model_dump(mode="json")
                            for schema in record.schema_references
                        ],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    json.dumps(record.metadata, sort_keys=True, separators=(",", ":")),
                ),
            )
            if isinstance(definition, EvaluationGoldSet):
                self._insert_gold_set_memberships(definition)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return record

    def import_case(
        self, evaluation_case: EvaluationCase[Any, Any, Any]
    ) -> EvaluationDefinitionRecord:
        return self.import_definition(evaluation_case)

    def import_gold_set(self, gold_set: EvaluationGoldSet) -> EvaluationDefinitionRecord:
        return self.import_definition(gold_set)

    def import_rubric(self, rubric: EvaluationRubric) -> EvaluationDefinitionRecord:
        return self.import_definition(rubric)

    def import_suite(self, suite: EvaluationSuite) -> EvaluationDefinitionRecord:
        return self.import_definition(suite)

    def _insert_gold_set_memberships(self, gold_set: EvaluationGoldSet) -> None:
        for membership in gold_set.memberships:
            case_record = self.get_definition(
                business_id=membership.case.business_id,
                revision=membership.case.revision,
                kind=EvaluationDefinitionKind.CASE,
            )
            if (
                case_record is None
                or case_record.record_id != membership.case.record_id
                or case_record.content_hash != membership.case.content_hash
            ):
                raise ValueError(
                    "Gold Set membership must reference an imported exact Evaluation Case revision"
                )
            self._connection.execute(
                """
                INSERT INTO evaluation_gold_set_memberships (
                    membership_id, gold_set_record_id, case_record_id,
                    case_business_id, case_revision, case_content_hash, split
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(new_uuid7()),
                    str(gold_set.identity.record_id),
                    str(membership.case.record_id),
                    membership.case.business_id,
                    membership.case.revision,
                    membership.case.content_hash,
                    membership.split.value,
                ),
            )

    def list_gold_set_memberships(
        self, gold_set_record_id: UUID
    ) -> list[EvaluationGoldSetMembershipRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM evaluation_gold_set_memberships
            WHERE gold_set_record_id = ?
            ORDER BY rowid
            """,
            (str(gold_set_record_id),),
        ).fetchall()
        return [
            EvaluationGoldSetMembershipRecord(
                membership_id=UUID(row["membership_id"]),
                gold_set_record_id=UUID(row["gold_set_record_id"]),
                case_record_id=UUID(row["case_record_id"]),
                case_business_id=row["case_business_id"],
                case_revision=row["case_revision"],
                case_content_hash=row["case_content_hash"],
                split=EvaluationSplit(row["split"]),
            )
            for row in rows
        ]

    def register_artifact(
        self,
        content: bytes | bytearray | None = None,
        *,
        content_hash: str | None = None,
        byte_size: int | None = None,
        kind: str,
        media_type: str,
        retention_class: str,
        sensitivity_classification: str | None = None,
        redaction_classification: str = "original",
        sensitivity: str | None = None,
        redaction: str | None = None,
    ) -> EvaluationArtifactRecord:
        """Register external content by hash, deduplicating identical metadata."""
        if content is not None:
            raw_content = bytes(content)
            computed_hash = hashlib.sha256(raw_content).hexdigest()
            if content_hash is not None and content_hash != computed_hash:
                raise ValueError("content_hash does not match content")
            content_hash = computed_hash
            if byte_size is not None and byte_size != len(raw_content):
                raise ValueError("byte_size does not match content")
            byte_size = len(raw_content)
        elif content_hash is None or byte_size is None:
            raise ValueError("content or both content_hash and byte_size are required")

        sensitivity_classification = sensitivity_classification or sensitivity
        if sensitivity_classification is None:
            raise ValueError("sensitivity_classification is required")
        redaction_classification = redaction or redaction_classification
        candidate = EvaluationArtifactRecord(
            artifact_id=new_uuid7(),
            content_hash=content_hash,
            kind=kind,
            media_type=media_type,
            byte_size=byte_size,
            retention_class=retention_class,
            sensitivity_classification=sensitivity_classification,
            redaction_classification=redaction_classification,
        )
        existing = self._connection.execute(
            "SELECT * FROM evaluation_artifacts WHERE content_hash = ?",
            (candidate.content_hash,),
        ).fetchone()
        if existing is not None:
            existing_record = self._artifact_from_row(existing)
            same_metadata = existing_record.model_copy(
                update={"artifact_id": candidate.artifact_id}
            )
            if same_metadata != candidate:
                raise ArtifactConflictError(
                    "artifact content hash was reused with different metadata"
                )
            return existing_record

        self._connection.execute(
            """
            INSERT INTO evaluation_artifacts (
                artifact_id, content_hash, kind, media_type, byte_size,
                retention_class, sensitivity_classification,
                redaction_classification
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(candidate.artifact_id),
                candidate.content_hash,
                candidate.kind,
                candidate.media_type,
                candidate.byte_size,
                candidate.retention_class,
                candidate.sensitivity_classification,
                candidate.redaction_classification,
            ),
        )
        self._connection.commit()
        return candidate

    def get_artifact(self, content_hash: str) -> EvaluationArtifactRecord | None:
        row = self._connection.execute(
            "SELECT * FROM evaluation_artifacts WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return None if row is None else self._artifact_from_row(row)

    def put_artifact_location(
        self,
        artifact: EvaluationArtifactRecord | UUID | str,
        uri: str | None = None,
        *,
        location_key: str = "default",
        location_kind: str = "external",
        location: str | None = None,
    ) -> ArtifactLocationRecord:
        """Create or replace one named location without changing artifact identity."""
        uri = uri or location
        if uri is None:
            raise ValueError("uri or location is required")
        artifact_record = self._resolve_artifact(artifact)
        existing = self._connection.execute(
            """
            SELECT * FROM evaluation_artifact_locations
            WHERE artifact_id = ? AND location_key = ?
            """,
            (str(artifact_record.artifact_id), location_key),
        ).fetchone()
        location_id = UUID(existing["location_id"]) if existing else new_uuid7()
        self._connection.execute(
            """
            INSERT INTO evaluation_artifact_locations (
                location_id, artifact_id, location_key, location_kind, uri
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(artifact_id, location_key) DO UPDATE SET
                location_kind = excluded.location_kind,
                uri = excluded.uri
            """,
            (
                str(location_id),
                str(artifact_record.artifact_id),
                location_key,
                location_kind,
                uri,
            ),
        )
        self._connection.commit()
        return ArtifactLocationRecord(
            location_id=location_id,
            artifact_id=artifact_record.artifact_id,
            location_key=location_key,
            location_kind=location_kind,
            uri=uri,
        )

    def list_artifact_locations(
        self, artifact: EvaluationArtifactRecord | UUID | str
    ) -> list[ArtifactLocationRecord]:
        artifact_record = self._resolve_artifact(artifact)
        rows = self._connection.execute(
            """
            SELECT * FROM evaluation_artifact_locations
            WHERE artifact_id = ? ORDER BY location_key
            """,
            (str(artifact_record.artifact_id),),
        ).fetchall()
        return [
            ArtifactLocationRecord(
                location_id=UUID(row["location_id"]),
                artifact_id=UUID(row["artifact_id"]),
                location_key=row["location_key"],
                location_kind=row["location_kind"],
                uri=row["uri"],
            )
            for row in rows
        ]

    def register_redacted_derivative(
        self,
        source: EvaluationArtifactRecord | UUID | str,
        content: bytes | bytearray | None = None,
        *,
        content_hash: str | None = None,
        byte_size: int | None = None,
        kind: str,
        media_type: str,
        retention_class: str,
        sensitivity_classification: str,
    ) -> EvaluationArtifactRecord:
        """Register redacted bytes as a new artifact linked to their source."""
        source_record = self._resolve_artifact(source)
        derivative = self.register_artifact(
            content,
            content_hash=content_hash,
            byte_size=byte_size,
            kind=kind,
            media_type=media_type,
            retention_class=retention_class,
            sensitivity_classification=sensitivity_classification,
            redaction_classification="redacted",
        )
        if derivative.artifact_id == source_record.artifact_id:
            raise ValueError("a redacted derivative must have different bytes")
        self._connection.execute(
            """
            INSERT OR IGNORE INTO evaluation_artifact_derivatives (
                source_artifact_id, derivative_artifact_id, relationship
            ) VALUES (?, ?, 'redaction')
            """,
            (str(source_record.artifact_id), str(derivative.artifact_id)),
        )
        self._connection.commit()
        return derivative

    def list_artifact_derivatives(
        self, source: EvaluationArtifactRecord | UUID | str
    ) -> list[ArtifactDerivativeRecord]:
        source_record = self._resolve_artifact(source)
        rows = self._connection.execute(
            """
            SELECT * FROM evaluation_artifact_derivatives
            WHERE source_artifact_id = ? ORDER BY derivative_artifact_id
            """,
            (str(source_record.artifact_id),),
        ).fetchall()
        return [
            ArtifactDerivativeRecord(
                source_artifact_id=UUID(row["source_artifact_id"]),
                derivative_artifact_id=UUID(row["derivative_artifact_id"]),
                relationship=row["relationship"],
            )
            for row in rows
        ]

    def get_artifact_source(
        self, artifact: EvaluationArtifactRecord | UUID | str
    ) -> UUID | None:
        artifact_record = self._resolve_artifact(artifact)
        row = self._connection.execute(
            """
            SELECT source_artifact_id FROM evaluation_artifact_derivatives
            WHERE derivative_artifact_id = ?
            """,
            (str(artifact_record.artifact_id),),
        ).fetchone()
        return None if row is None else UUID(row["source_artifact_id"])

    def _resolve_artifact(
        self, artifact: EvaluationArtifactRecord | UUID | str
    ) -> EvaluationArtifactRecord:
        if isinstance(artifact, EvaluationArtifactRecord):
            return artifact
        if isinstance(artifact, UUID):
            row = self._connection.execute(
                "SELECT * FROM evaluation_artifacts WHERE artifact_id = ?",
                (str(artifact),),
            ).fetchone()
        else:
            try:
                artifact_id = UUID(artifact)
            except ValueError:
                return self.get_artifact(artifact) or self._missing_artifact(artifact)
            row = self._connection.execute(
                "SELECT * FROM evaluation_artifacts WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Artifact: {artifact}")
        return self._artifact_from_row(row)

    @staticmethod
    def _missing_artifact(value: str) -> EvaluationArtifactRecord:
        raise KeyError(f"unknown Evaluation Artifact: {value}")

    # Read/write names that make the replaceable-location behavior explicit.
    add_artifact_location = put_artifact_location
    replace_artifact_location = put_artifact_location
    list_locations = list_artifact_locations

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> EvaluationArtifactRecord:
        return EvaluationArtifactRecord(
            artifact_id=UUID(row["artifact_id"]),
            content_hash=row["content_hash"],
            kind=row["kind"],
            media_type=row["media_type"],
            byte_size=row["byte_size"],
            retention_class=row["retention_class"],
            sensitivity_classification=row["sensitivity_classification"],
            redaction_classification=row["redaction_classification"],
        )

    def get_definition(
        self,
        *,
        business_id: str,
        revision: int,
        kind: EvaluationDefinitionKind | str,
    ) -> EvaluationDefinitionRecord | None:
        kind_value = EvaluationDefinitionKind(kind).value
        row = self._connection.execute(
            """
            SELECT * FROM evaluation_definition_revisions
            WHERE kind = ? AND business_id = ? AND revision = ?
            """,
            (kind_value, business_id, revision),
        ).fetchone()
        return None if row is None else self._definition_from_row(row)

    def list_definitions(
        self,
        *,
        kind: EvaluationDefinitionKind | str | None = None,
        business_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[EvaluationDefinitionRecord]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(EvaluationDefinitionKind(kind).value)
        if business_id is not None:
            clauses.append("business_id = ?")
            parameters.append(business_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self._connection.execute(
            """
            SELECT * FROM evaluation_definition_revisions
            """
            + where
            + " ORDER BY kind, business_id, revision",
            parameters,
        ).fetchall()
        records = [self._definition_from_row(row) for row in rows]
        if metadata is not None:
            records = [
                record
                for record in records
                if all(record.metadata.get(key) == value for key, value in metadata.items())
            ]
        if tags is not None:
            required_tags = set(tags)
            records = [
                record
                for record in records
                if required_tags.issubset(set(record.metadata.get("tags", [])))
            ]
        return records

    find_definitions = list_definitions

    @staticmethod
    def _definition_from_row(row: sqlite3.Row) -> EvaluationDefinitionRecord:
        return EvaluationDefinitionRecord(
            record_id=UUID(row["record_id"]),
            kind=row["kind"],
            business_id=row["business_id"],
            revision=row["revision"],
            content_hash=row["content_hash"],
            schema_references=tuple(
                SchemaReference.model_validate(item)
                for item in json.loads(row["schema_references_json"])
            ),
            metadata=json.loads(row["metadata_json"]),
        )


# Domain-oriented aliases keep the persistence implementation name out of
# callers that only need the evaluation ledger/catalog contract.
EvaluationArtifact = EvaluationArtifactRecord
ArtifactLocation = ArtifactLocationRecord
EvaluationArtifactDerivative = ArtifactDerivativeRecord
EvaluationLedger = SQLiteEvaluationLedger
SQLiteEvaluationStore = SQLiteEvaluationLedger
