"""SQLite persistence for imported evaluation definitions and artifacts.

Authored definitions remain the source of truth in code or files.  This module
only stores the immutable identity and queryable index needed by the runtime.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.reporting import ReportCase, ReportCaseFailure

from .definitions import (
    AuthoredDefinitionConflictError,
    EvaluationCase,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationSplit,
    EvaluationRubric,
    SchemaReference,
    new_uuid7,
    content_fingerprint,
)
from .suites import EvaluationMetricReference, EvaluationSuite
from .preflight import ResolvedEvaluationPlan
from .runs import (
    CaseEvaluatorExecution,
    CaseMetricObservation,
    EvaluationCaseDisposition,
    EvaluationCaseManifestEntry,
    EvaluationCaseResult,
    EVIDENCE_CONTRACT_VERSION,
    FrozenAggregateManifest,
    FrozenAggregateManifestEntry,
    EvaluationMetricObservation,
    EvaluationProducerStatus,
    EvaluationRunConfiguration,
    EvaluationFinalizationClaim,
    EvaluationGateOutcome,
    EvaluationRunIssue,
    EvaluationRunRecord,
    EvaluationRunStatus,
    ReportEvaluatorExecution,
    RunMetricObservation,
    TaskOutcome,
)
from .reporting import SchemaRegistry, _evaluation_result, report_from_bytes


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


class EvaluationArtifactLinkRecord(BaseModel):
    """A namespaced artifact link owned by one subject-specific table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: UUID
    artifact_id: UUID
    role: str = Field(
        pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
    )
    definition_record_id: UUID | None = None
    artifact: EvaluationArtifactRecord | None = None


class EvaluationProducedArtifactRecord(BaseModel):
    """An artifact with the smallest producer that created the evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: UUID
    role: str = Field(
        pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
    )
    producer_type: str = Field(min_length=1)
    producer_id: UUID
    artifact: EvaluationArtifactRecord


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
        self._transaction_lock = RLock()
        if str(db_path) == ":memory:":
            self._artifact_root = Path(tempfile.mkdtemp(prefix="evaluation-artifacts-"))
        else:
            database_path = Path(db_path)
            self._artifact_root = database_path.parent / f".{database_path.name}.artifacts"
        self._artifact_root.mkdir(parents=True, exist_ok=True)
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
                definition_json TEXT,
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

            CREATE TABLE IF NOT EXISTS evaluation_definition_artifacts (
                link_id TEXT PRIMARY KEY,
                definition_record_id TEXT NOT NULL
                    REFERENCES evaluation_definition_revisions(record_id)
                    ON DELETE CASCADE,
                artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id),
                role TEXT NOT NULL CHECK (
                    role GLOB '[a-z]*.[a-z]*'
                ),
                UNIQUE(definition_record_id, artifact_id, role)
            );

            CREATE TABLE IF NOT EXISTS evaluation_run_consumed_artifacts (
                link_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id)
                    ON DELETE CASCADE,
                artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id),
                role TEXT NOT NULL CHECK (role GLOB '[a-z]*.[a-z]*'),
                UNIQUE(run_id, artifact_id, role)
            );

            CREATE TABLE IF NOT EXISTS evaluation_run_artifacts (
                link_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id)
                    ON DELETE CASCADE,
                artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id),
                role TEXT NOT NULL CHECK (role GLOB '[a-z]*.[a-z]*'),
                UNIQUE(run_id, artifact_id, role)
            );

            CREATE TABLE IF NOT EXISTS evaluation_case_result_artifacts (
                link_id TEXT PRIMARY KEY,
                case_result_id TEXT NOT NULL
                    REFERENCES evaluation_case_results(result_id)
                    ON DELETE CASCADE,
                artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id),
                role TEXT NOT NULL CHECK (role GLOB '[a-z]*.[a-z]*'),
                UNIQUE(case_result_id, artifact_id, role)
            );

            CREATE TABLE IF NOT EXISTS case_evaluator_execution_artifacts (
                link_id TEXT PRIMARY KEY,
                execution_id TEXT NOT NULL
                    REFERENCES case_evaluator_executions(execution_id)
                    ON DELETE CASCADE,
                artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id),
                role TEXT NOT NULL CHECK (role GLOB '[a-z]*.[a-z]*'),
                UNIQUE(execution_id, artifact_id, role)
            );

            CREATE TABLE IF NOT EXISTS report_evaluator_execution_artifacts (
                link_id TEXT PRIMARY KEY,
                execution_id TEXT NOT NULL
                    REFERENCES report_evaluator_executions(execution_id)
                    ON DELETE CASCADE,
                artifact_id TEXT NOT NULL
                    REFERENCES evaluation_artifacts(artifact_id),
                role TEXT NOT NULL CHECK (role GLOB '[a-z]*.[a-z]*'),
                UNIQUE(execution_id, artifact_id, role)
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
                    status IN ('pending', 'running', 'finalization_pending', 'completed', 'failed', 'cancelled')
                ),
                retry_of_run_id TEXT REFERENCES evaluation_runs(run_id),
                issues_json TEXT NOT NULL DEFAULT '[]',
                gate_outcomes_json TEXT NOT NULL DEFAULT '[]',
                finalization_claim_id TEXT,
                finalization_claim_owner_id TEXT,
                finalization_claim_acquired_at TEXT,
                finalization_claim_expires_at TEXT
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

            CREATE TABLE IF NOT EXISTS resolved_evaluation_plans (
                run_id TEXT PRIMARY KEY REFERENCES evaluation_runs(run_id),
                plan_json TEXT NOT NULL
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
                task_outcome_json TEXT,
                report_case_json TEXT,
                checkpoint_id TEXT,
                checkpoint_content_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS case_evaluator_executions (
                execution_id TEXT PRIMARY KEY,
                case_result_id TEXT NOT NULL REFERENCES evaluation_case_results(result_id),
                evaluator_name TEXT NOT NULL,
                evaluator_revision INTEGER NOT NULL CHECK (evaluator_revision >= 1),
                configuration_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
                duration_seconds REAL NOT NULL CHECK (duration_seconds >= 0),
                failure_message TEXT,
                trace_id TEXT,
                span_id TEXT
            );

            CREATE TABLE IF NOT EXISTS report_evaluator_executions (
                execution_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id),
                evaluator_name TEXT NOT NULL,
                evaluator_revision INTEGER NOT NULL CHECK (evaluator_revision >= 1),
                configuration_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
                duration_seconds REAL NOT NULL CHECK (duration_seconds >= 0),
                failure_message TEXT,
                trace_id TEXT,
                span_id TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_report_evaluator_terminal_identity
                ON report_evaluator_executions(
                    run_id, evaluator_name, evaluator_revision,
                    configuration_fingerprint
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
        definition_columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(evaluation_definition_revisions)"
            )
        }
        if "definition_json" not in definition_columns:
            self._connection.execute(
                "ALTER TABLE evaluation_definition_revisions ADD COLUMN definition_json TEXT"
            )
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
        if "frozen_aggregate_manifest_artifact_id" not in run_columns:
            self._connection.execute(
                "ALTER TABLE evaluation_runs ADD COLUMN frozen_aggregate_manifest_artifact_id TEXT"
            )
        for column in (
            "finalization_claim_id",
            "finalization_claim_owner_id",
            "finalization_claim_acquired_at",
            "finalization_claim_expires_at",
        ):
            if column not in run_columns:
                self._connection.execute(
                    f"ALTER TABLE evaluation_runs ADD COLUMN {column} TEXT"
                )
        for table in ("case_evaluator_executions", "report_evaluator_executions"):
            columns = {
                row["name"]
                for row in self._connection.execute(f"PRAGMA table_info({table})")
            }
            for column in ("trace_id", "span_id"):
                if column not in columns:
                    self._connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} TEXT"
                    )
        self._connection.commit()

    def create_evaluation_run(
        self,
        run: EvaluationRunRecord,
        plan: ResolvedEvaluationPlan,
        manifest: Iterable[EvaluationCaseManifestEntry],
        pending_results: Iterable[EvaluationCaseResult],
    ) -> None:
        """Atomically create a run, its frozen manifest, and pending envelopes."""
        manifest_items = tuple(manifest)
        result_items = tuple(pending_results)
        self._validate_run_creation(run, plan, manifest_items, result_items)
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
                    issues_json, gate_outcomes_json, frozen_aggregate_manifest_artifact_id,
                    finalization_claim_id, finalization_claim_owner_id,
                    finalization_claim_acquired_at, finalization_claim_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO resolved_evaluation_plans (run_id, plan_json)
                VALUES (?, ?)
                """,
                (str(run.run_id), plan.canonical_json),
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
                        execution_disposition, task_outcome_json,
                        checkpoint_id, checkpoint_content_hash
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)
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

    @staticmethod
    def _validate_run_creation(
        run: EvaluationRunRecord,
        plan: ResolvedEvaluationPlan,
        manifest: tuple[EvaluationCaseManifestEntry, ...],
        pending_results: tuple[EvaluationCaseResult, ...],
    ) -> None:
        if (
            plan.suite.record_id,
            plan.suite.business_id,
            plan.suite.revision,
            plan.suite.content_hash,
        ) != (
            run.suite_record_id,
            run.suite_business_id,
            run.suite_revision,
            run.suite_content_hash,
        ):
            raise ValueError(
                "Resolved Evaluation Plan Suite revision does not match Evaluation Run"
            )
        if (
            plan.gold_set.record_id,
            plan.gold_set.business_id,
            plan.gold_set.revision,
            plan.gold_set.content_hash,
        ) != (
            run.gold_set_record_id,
            run.gold_set_business_id,
            run.gold_set_revision,
            run.gold_set_content_hash,
        ):
            raise ValueError(
                "Resolved Evaluation Plan Gold Set revision does not match "
                "Evaluation Run"
            )
        manifested_cases = tuple(
            (entry.ordinal, entry.run_id, entry.case, entry.split)
            for entry in manifest
        )
        planned_cases = tuple(
            (ordinal, run.run_id, planned.case, planned.split)
            for ordinal, planned in enumerate(plan.cases)
        )
        if manifested_cases != planned_cases:
            raise ValueError(
                "manifested Evaluation Case revisions do not match "
                "the Resolved Evaluation Plan"
            )
        if len(manifest) != len(pending_results):
            raise ValueError("every manifest entry requires exactly one pending result")
        expected_envelopes = {
            (entry.manifest_id, entry.case_record_id) for entry in manifest
        }
        actual_envelopes = {
            (result.manifest_id, result.case_record_id) for result in pending_results
        }
        if (
            actual_envelopes != expected_envelopes
            or len(actual_envelopes) != len(pending_results)
            or any(
                result.run_id != run.run_id
                or result.execution_disposition
                is not EvaluationCaseDisposition.PENDING
                or result.task_outcome is not None
                for result in pending_results
            )
        ):
            raise ValueError(
                "every manifested case requires exactly one pending "
                "Evaluation Case Result"
            )
    def record_case_evaluation(
        self,
        result: EvaluationCaseResult,
        executions: Iterable[CaseEvaluatorExecution],
        observations: Iterable[CaseMetricObservation],
        report_case_evidence: Mapping[str, Any] | None = None,
    ) -> None:
        """Atomically finalize one case result and its evaluator evidence."""
        executions = tuple(executions)
        observations = tuple(observations)
        task_outcome_payload = (
            None if result.task_outcome is None else result.task_outcome.model_dump(mode="json")
        )
        result_payload = {
            "result_id": str(result.result_id),
            "run_id": str(result.run_id),
            "manifest_id": str(result.manifest_id),
            "case_record_id": str(result.case_record_id),
            "execution_disposition": result.execution_disposition.value,
            "task_outcome": task_outcome_payload,
        }
        checkpoint_hash = content_fingerprint(
            {
                "case_result": result_payload,
                "report_case_evidence": report_case_evidence,
                "case_evaluator_executions": [
                    item.model_dump(mode="json") for item in executions
                ],
                "case_metric_observations": [
                    item.model_dump(mode="json") for item in observations
                ],
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            }
        )
        checkpoint_id = uuid5(NAMESPACE_URL, f"evaluation-checkpoint:{checkpoint_hash}")
        with self._transaction_lock:
            try:
                self._connection.execute("BEGIN")
                cursor = self._connection.execute(
                    """
                    UPDATE evaluation_case_results
                    SET execution_disposition = ?, task_outcome_json = ?, report_case_json = ?,
                        checkpoint_id = ?, checkpoint_content_hash = ?
                    WHERE result_id = ? AND execution_disposition = 'pending'
                    """,
                    (
                        result.execution_disposition.value,
                        None if result.task_outcome is None else json.dumps(
                            result.task_outcome.model_dump(mode="json"),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        None if report_case_evidence is None else json.dumps(
                            report_case_evidence, sort_keys=True, separators=(",", ":")
                        ),
                        str(checkpoint_id),
                        checkpoint_hash,
                        str(result.result_id),
                    ),
                )
                if cursor.rowcount != 1:
                    existing = self._connection.execute(
                        """
                        SELECT *
                        FROM evaluation_case_results
                        WHERE result_id = ?
                        """,
                        (str(result.result_id),),
                    ).fetchone()
                    if existing is None:
                        raise KeyError(
                            f"unknown Evaluation Case Result: {result.result_id}"
                        )
                    existing_result = self._case_result_from_row(existing)
                    existing_evidence = (
                        None
                        if existing["report_case_json"] is None
                        else json.loads(existing["report_case_json"])
                    )
                    if (
                        existing_result.model_copy(
                            update={"checkpoint_id": None, "checkpoint_content_hash": None}
                        ) == result
                        and self.list_case_evaluator_executions(result.result_id)
                        == list(executions)
                        and self.list_case_metric_observations(result.result_id)
                        == list(observations)
                        and existing_evidence == report_case_evidence
                    ):
                        self._connection.commit()
                        return
                    raise ValueError(
                        f"Evaluation Case Result is already terminal with different evidence: {result.result_id}"
                    )
                if result.task_outcome is not None:
                    for artifact in result.task_outcome.artifacts:
                        self._link_artifact(
                            "evaluation_case_result_artifacts",
                            "case_result_id",
                            result.result_id,
                            artifact.content_hash,
                            artifact.role,
                            commit=False,
                        )
                for execution in executions:
                    self._insert_case_execution(execution)
                for observation in observations:
                    self._insert_case_observation(observation)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def materialize_report_case(
        self, case_result_id: UUID, schemas: SchemaRegistry
    ) -> ReportCase[Any, Any, Any] | ReportCaseFailure[Any, Any, Any]:
        """Reconstruct a typed framework case from one terminal checkpoint."""
        row = self._connection.execute(
            """
            SELECT r.execution_disposition, r.report_case_json, d.definition_json
            FROM evaluation_case_results AS r
            JOIN evaluation_definition_revisions AS d
              ON d.record_id = r.case_record_id
            WHERE r.result_id = ? AND r.execution_disposition IN ('completed', 'failed')
            """,
            (str(case_result_id),),
        ).fetchone()
        if row is None:
            raise ValueError("ReportCase requires a completed terminal checkpoint")
        if row["report_case_json"] is None:
            raise ValueError("terminal checkpoint lacks ReportCase evidence")
        authored = json.loads(row["definition_json"])
        evidence = json.loads(row["report_case_json"])
        input_schema = SchemaReference.model_validate(authored["input_schema"])
        metadata_schema = SchemaReference.model_validate(authored["metadata_schema"])
        expected_schema = (
            None
            if authored.get("expected_output_schema") is None
            else SchemaReference.model_validate(authored["expected_output_schema"])
        )
        typed_inputs = schemas.validate(input_schema, authored["task_input"])
        typed_metadata = schemas.validate(metadata_schema, authored["metadata"])
        typed_expected = (
            None
            if authored.get("expected_output") is None
            else schemas.validate(expected_schema, authored["expected_output"])
        )
        if row["execution_disposition"] == EvaluationCaseDisposition.FAILED.value:
            return ReportCaseFailure(
                name=evidence["name"],
                inputs=typed_inputs,
                metadata=typed_metadata,
                expected_output=typed_expected,
                error_message=evidence["error_message"],
                error_stacktrace=evidence["error_stacktrace"],
                source_case_name=evidence.get("source_case_name"),
                trace_id=evidence.get("trace_id"),
                span_id=evidence.get("span_id"),
            )
        output_schema = expected_schema
        if output_schema is None:
            raise ValueError("successful ReportCase requires an output schema")
        return ReportCase(
            name=evidence["name"],
            inputs=typed_inputs,
            metadata=typed_metadata,
            expected_output=typed_expected,
            output=schemas.validate(output_schema, evidence["output"]),
            metrics=evidence.get("metrics", {}),
            attributes=evidence.get("attributes", {}),
            scores={k: _evaluation_result(v) for k, v in evidence.get("scores", {}).items()},
            labels={k: _evaluation_result(v) for k, v in evidence.get("labels", {}).items()},
            assertions={k: _evaluation_result(v) for k, v in evidence.get("assertions", {}).items()},
            task_duration=evidence.get("task_duration", 0),
            total_duration=evidence.get("total_duration", 0),
            source_case_name=evidence.get("source_case_name"),
            trace_id=evidence.get("trace_id"),
            span_id=evidence.get("span_id"),
            evaluator_failures=evidence.get("evaluator_failures", []),
        )

    def record_report_evaluation(
        self,
        executions: Iterable[ReportEvaluatorExecution],
        observations: Iterable[RunMetricObservation],
        issues: Iterable[EvaluationRunIssue] = (),
        *,
        finalization_claim_id: UUID | None = None,
        claim_now: datetime | None = None,
    ) -> None:
        """Atomically persist one report checkpoint and its diagnostics."""
        executions = tuple(executions)
        observations = tuple(observations)
        issue_items = tuple(issues)
        with self._transaction_lock:
            try:
                self._connection.execute("BEGIN")
                if finalization_claim_id is not None:
                    if not executions:
                        raise ValueError(
                            "a finalization claim requires a report execution checkpoint"
                        )
                    _, claim_timestamp = self._claim_timestamp(claim_now)
                    claim = self._connection.execute(
                        """
                        SELECT 1 FROM evaluation_runs
                        WHERE run_id = ?
                          AND finalization_claim_id = ?
                          AND finalization_claim_expires_at > ?
                        """,
                        (
                            str(executions[0].run_id),
                            str(finalization_claim_id),
                            claim_timestamp,
                        ),
                    ).fetchone()
                    if claim is None:
                        raise RuntimeError(
                            "cannot checkpoint report evaluation without the live finalization claim"
                        )
                for execution in executions:
                    self._insert_report_execution(execution)
                for observation in observations:
                    self._insert_run_observation(observation)
                if issue_items:
                    current = self._connection.execute(
                        "SELECT issues_json FROM evaluation_runs WHERE run_id = ?",
                        (str(executions[0].run_id),),
                    ).fetchone()
                    if current is None:
                        raise KeyError(f"unknown Evaluation Run: {executions[0].run_id}")
                    existing = json.loads(current["issues_json"] or "[]")
                    existing.extend(issue.model_dump(mode="json") for issue in issue_items)
                    self._connection.execute(
                        "UPDATE evaluation_runs SET issues_json = ? WHERE run_id = ?",
                        (
                            json.dumps(existing, sort_keys=True, separators=(",", ":")),
                            str(executions[0].run_id),
                        ),
                    )
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
        finalization_claim_id: UUID | None = None,
    ) -> EvaluationRunRecord:
        issue_items = tuple(issues)
        gate_items = tuple(gate_outcomes)
        with self._transaction_lock:
            try:
                self._connection.execute("BEGIN")
                row = self._connection.execute(
                    "SELECT * FROM evaluation_runs WHERE run_id = ?",
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown Evaluation Run: {run_id}")
                if row["status"] != EvaluationRunStatus.COMPLETED.value:
                    self._assert_run_is_complete(run_id)
                    if (
                        finalization_claim_id is not None
                        and row["finalization_claim_id"]
                        != str(finalization_claim_id)
                    ):
                        raise ValueError(
                            "Evaluation Finalization does not own the run's claim"
                        )
                    self._connection.execute(
                        """
                        UPDATE evaluation_runs
                        SET status = ?, issues_json = ?, gate_outcomes_json = ?,
                            finalization_claim_id = NULL,
                            finalization_claim_owner_id = NULL,
                            finalization_claim_acquired_at = NULL,
                            finalization_claim_expires_at = NULL
                        WHERE run_id = ?
                        """,
                        (
                            EvaluationRunStatus.COMPLETED.value,
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
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        run = self.get_evaluation_run(run_id)
        if run is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        return run

    def _assert_run_is_complete(self, run_id: UUID) -> None:
        row = self._connection.execute(
            "SELECT frozen_aggregate_manifest_artifact_id FROM evaluation_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        if row["frozen_aggregate_manifest_artifact_id"] is None:
            raise ValueError(
                "Evaluation Run cannot complete before the aggregate manifest is frozen"
            )
        pending = self._connection.execute(
            """
            SELECT 1 FROM evaluation_case_results
            WHERE run_id = ?
              AND (execution_disposition IN ('pending', 'cancelled')
                   OR task_outcome_json IS NULL)
            LIMIT 1
            """,
            (str(run_id),),
        ).fetchone()
        if pending is not None:
            raise ValueError(
                "Evaluation Run cannot complete while cases lack terminal evidence"
            )
        plan_row = self._connection.execute(
            "SELECT plan_json FROM resolved_evaluation_plans WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if plan_row is None:
            raise ValueError("Evaluation Run cannot complete without its frozen plan")
        plan = ResolvedEvaluationPlan.model_validate_json(plan_row["plan_json"])
        for ordinal, planned_case in enumerate(plan.cases):
            result = self._connection.execute(
                """
                SELECT result_id, task_outcome_json
                FROM evaluation_case_results
                WHERE run_id = ? AND manifest_id = (
                    SELECT manifest_id FROM evaluation_case_manifests
                    WHERE run_id = ? AND ordinal = ?
                )
                """,
                (str(run_id), str(run_id), ordinal),
            ).fetchone()
            if result is None or result["task_outcome_json"] is None:
                raise ValueError("Evaluation Run cannot complete without terminal task evidence")
            outcome = json.loads(result["task_outcome_json"])
            if outcome.get("kind") == "failure":
                continue
            terminal = {
                (row["evaluator_name"], row["evaluator_revision"])
                for row in self._connection.execute(
                    """
                    SELECT evaluator_name, evaluator_revision
                    FROM case_evaluator_executions
                    WHERE case_result_id = ?
                    """,
                    (result["result_id"],),
                )
            }
            missing_case_evaluators = {
                (resolved.reference.name, resolved.reference.evaluator_revision)
                for resolved in planned_case.evaluators
            } - terminal
            if missing_case_evaluators:
                raise ValueError(
                    "Evaluation Run cannot complete while case evaluators lack terminal evidence: "
                    + ", ".join(sorted(name for name, _ in missing_case_evaluators))
                )
        suite = self._definition_for_run(run_id, EvaluationDefinitionKind.SUITE)
        expected = {
            evaluator["name"] for evaluator in suite.get("report_evaluators", [])
        }
        terminal = {
            row["evaluator_name"]
            for row in self._connection.execute(
                "SELECT evaluator_name FROM report_evaluator_executions WHERE run_id = ?",
                (str(run_id),),
            )
        }
        missing = expected - terminal
        if missing:
            raise ValueError(
                "Evaluation Run cannot complete while report evaluators lack terminal evidence: "
                + ", ".join(sorted(missing))
            )

    def freeze_aggregate_manifest(
        self,
        run_id: UUID,
        *,
        issues: Iterable[EvaluationRunIssue] = (),
        report_provenance: Mapping[str, Any] | None = None,
    ) -> EvaluationArtifactRecord:
        """Freeze the aggregate manifest and atomically enter finalization."""
        with self._transaction_lock:
            row = self._connection.execute(
                "SELECT status, frozen_aggregate_manifest_artifact_id FROM evaluation_runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown Evaluation Run: {run_id}")
            if row["frozen_aggregate_manifest_artifact_id"] is None and row["status"] not in {
                EvaluationRunStatus.RUNNING.value,
                EvaluationRunStatus.FINALIZATION_PENDING.value,
            }:
                raise ValueError("only an active Evaluation Run can freeze its aggregate manifest")
            if row["frozen_aggregate_manifest_artifact_id"] is None:
                pending = self._connection.execute(
                    """
                    SELECT 1 FROM evaluation_case_results
                    WHERE run_id = ?
                      AND (execution_disposition IN ('pending', 'cancelled')
                           OR task_outcome_json IS NULL)
                    LIMIT 1
                    """,
                    (str(run_id),),
                ).fetchone()
                if pending is not None:
                    raise ValueError(
                        "aggregate manifest requires every manifested case to be terminal"
                    )
        if row["frozen_aggregate_manifest_artifact_id"] is not None and report_provenance is None:
            existing_artifact = self._get_artifact_by_id(
                UUID(row["frozen_aggregate_manifest_artifact_id"])
            )
            existing_manifest = FrozenAggregateManifest.model_validate_json(
                self.read_artifact(existing_artifact)
            )
            base_keys = {
                "configuration_fingerprint",
                "selection_expression",
                "selection_provenance",
            }
            report_provenance = {
                key: value
                for key, value in existing_manifest.report_provenance.items()
                if key not in base_keys
            }
        manifest = self._build_frozen_aggregate_manifest(
            run_id, report_provenance=report_provenance or {}
        )
        manifest_bytes = manifest.canonical_bytes
        artifact = self.register_artifact(
            manifest_bytes,
            kind="frozen-aggregate-manifest",
            media_type="application/json",
            retention_class="run",
            sensitivity_classification="internal",
        )
        destination = self._artifact_root / f"{artifact.content_hash}.json"
        if not destination.exists():
            destination.write_bytes(manifest_bytes)
        self.put_artifact_location(
            artifact,
            str(destination),
            location_key="frozen-aggregate-manifest",
            location_kind="filesystem",
        )
        with self._transaction_lock:
            try:
                self._connection.execute("BEGIN")
                issue_items = tuple(issues)
                row = self._connection.execute(
                    "SELECT status, frozen_aggregate_manifest_artifact_id FROM evaluation_runs WHERE run_id = ?",
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown Evaluation Run: {run_id}")
                if row["frozen_aggregate_manifest_artifact_id"] is not None:
                    existing = self._get_artifact_by_id(UUID(row["frozen_aggregate_manifest_artifact_id"]))
                    if existing.content_hash != artifact.content_hash:
                        raise ValueError(
                            "the aggregate manifest is already frozen with a different composition"
                        )
                    self._connection.commit()
                    return existing
                if row["status"] not in {
                    EvaluationRunStatus.RUNNING.value,
                    EvaluationRunStatus.FINALIZATION_PENDING.value,
                }:
                    raise ValueError("only an active Evaluation Run can freeze its aggregate manifest")
                pending = self._connection.execute(
                    """
                    SELECT 1 FROM evaluation_case_results
                    WHERE run_id = ?
                      AND (execution_disposition IN ('pending', 'cancelled')
                           OR task_outcome_json IS NULL)
                    LIMIT 1
                    """,
                    (str(run_id),),
                ).fetchone()
                if pending is not None:
                    raise ValueError(
                        "aggregate manifest requires every manifested case to be terminal"
                    )
                self._link_artifact(
                    "evaluation_run_artifacts",
                    "run_id",
                    run_id,
                    artifact,
                    "evaluation.aggregate-manifest.frozen",
                    commit=False,
                )
                self._connection.execute(
                    """
                    UPDATE evaluation_runs
                    SET status = ?, frozen_aggregate_manifest_artifact_id = ?, issues_json = ?
                    WHERE run_id = ?
                    """,
                    (
                        EvaluationRunStatus.FINALIZATION_PENDING.value,
                        str(artifact.artifact_id),
                        json.dumps(
                            [issue.model_dump(mode="json") for issue in issue_items],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        str(run_id),
                    ),
                )
                self._connection.commit()
                return artifact
            except Exception:
                self._connection.rollback()
                raise

    def _build_frozen_aggregate_manifest(
        self, run_id: UUID, *, report_provenance: Mapping[str, Any]
    ) -> FrozenAggregateManifest:
        run = self.get_evaluation_run(run_id)
        plan = self.get_resolved_evaluation_plan(run_id)
        if run is None or plan is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        suite = self.get_frozen_suite(run_id)
        entries = self.list_evaluation_case_manifest(run_id)
        rows = self._connection.execute(
            "SELECT * FROM evaluation_case_results WHERE run_id = ? ORDER BY rowid",
            (str(run_id),),
        ).fetchall()
        results = {UUID(row["manifest_id"]): row for row in rows}
        frozen_entries: list[FrozenAggregateManifestEntry] = []
        for entry in entries:
            row = results.get(entry.manifest_id)
            if row is None or row["execution_disposition"] not in {"completed", "failed"}:
                raise ValueError("aggregate manifest requires every manifested case to be terminal")
            if row["task_outcome_json"] is None or row["report_case_json"] is None:
                raise ValueError("aggregate manifest requires every terminal checkpoint to have evidence")
            manifest_hash = content_fingerprint(entry.model_dump(mode="json"))
            result_payload = {
                "result_id": row["result_id"],
                "run_id": row["run_id"],
                "manifest_id": row["manifest_id"],
                "case_record_id": row["case_record_id"],
                "execution_disposition": row["execution_disposition"],
                "task_outcome": json.loads(row["task_outcome_json"]),
            }
            result_hash = content_fingerprint(result_payload)
            executions = [
                item.model_dump(mode="json")
                for item in self.list_case_evaluator_executions(UUID(row["result_id"]))
            ]
            observations = [
                item.model_dump(mode="json")
                for item in self.list_case_metric_observations(UUID(row["result_id"]))
            ]
            checkpoint_hash = content_fingerprint(
                {
                    "case_result": result_payload,
                    "report_case_evidence": json.loads(row["report_case_json"]),
                    "case_evaluator_executions": executions,
                    "case_metric_observations": observations,
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                }
            )
            if (
                row["checkpoint_id"]
                != str(uuid5(NAMESPACE_URL, f"evaluation-checkpoint:{checkpoint_hash}"))
                or row["checkpoint_content_hash"] != checkpoint_hash
            ):
                raise ValueError("terminal checkpoint identity or content hash is mismatched")
            frozen_entries.append(
                FrozenAggregateManifestEntry(
                    ordinal=entry.ordinal,
                    manifest_entry_id=entry.manifest_id,
                    manifest_entry_content_hash=manifest_hash,
                    case_result_id=UUID(row["result_id"]),
                    case_result_content_hash=result_hash,
                    checkpoint_id=UUID(row["checkpoint_id"]),
                    checkpoint_content_hash=checkpoint_hash,
                )
            )
        return FrozenAggregateManifest(
            run_id=run_id,
            suite_record_id=run.suite_record_id,
            suite_content_hash=run.suite_content_hash,
            resolved_plan_content_hash=plan.content_hash,
            task_contract_content_hash=content_fingerprint(
                suite.task_contract.model_dump(mode="json")
            ),
            evidence_contract_version=EVIDENCE_CONTRACT_VERSION,
            report_provenance={
                "configuration_fingerprint": run.configuration.content_fingerprint,
                "selection_expression": run.selection_expression,
                "selection_provenance": run.selection_provenance,
                **report_provenance,
            },
            cases=tuple(frozen_entries),
        )

    def materialize_aggregate_report(self, run_id: UUID):
        """Verify the frozen composition and derive its evaluator-visible report."""
        artifact = self.get_frozen_aggregate_manifest_artifact(run_id)
        if artifact is None:
            raise ValueError("Evaluation Run has no frozen aggregate manifest")
        content = self.read_artifact(artifact)
        if hashlib.sha256(content).hexdigest() != artifact.content_hash:
            raise ValueError("frozen aggregate manifest bytes do not match their artifact identity")
        frozen = FrozenAggregateManifest.model_validate_json(content)
        base_provenance = {
            "configuration_fingerprint",
            "selection_expression",
            "selection_provenance",
        }
        extra_provenance = {
            key: value
            for key, value in frozen.report_provenance.items()
            if key not in base_provenance
        }
        current = self._build_frozen_aggregate_manifest(
            run_id, report_provenance=extra_provenance
        )
        if current.canonical_bytes != frozen.canonical_bytes:
            raise ValueError("terminal checkpoint evidence does not match the frozen aggregate manifest")

        cases: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for frozen_entry in frozen.cases:
            row = self._connection.execute(
                """
                SELECT r.execution_disposition, r.report_case_json, d.definition_json
                FROM evaluation_case_results AS r
                JOIN evaluation_definition_revisions AS d
                  ON d.record_id = r.case_record_id
                WHERE r.result_id = ?
                """,
                (str(frozen_entry.case_result_id),),
            ).fetchone()
            if row is None:
                raise ValueError("frozen aggregate manifest references missing case evidence")
            authored = json.loads(row["definition_json"])
            evidence = json.loads(row["report_case_json"])
            projected = {
                **evidence,
                "inputs": authored["task_input"],
                "metadata": authored["metadata"],
                "expected_output": authored.get("expected_output"),
            }
            if row["execution_disposition"] == EvaluationCaseDisposition.FAILED.value:
                failures.append(projected)
            else:
                cases.append(projected)
        provenance = frozen.report_provenance
        report_payload = {
            "name": provenance.get("report_name", f"run@{run_id}"),
            "cases": cases,
            "failures": failures,
            "experiment_metadata": provenance.get("experiment_metadata"),
            "trace_id": provenance.get("trace_id"),
            "span_id": provenance.get("span_id"),
        }
        return report_from_bytes(
            json.dumps(report_payload, sort_keys=True, separators=(",", ":")).encode()
        )

    def get_frozen_aggregate_manifest_artifact(
        self, run_id: UUID
    ) -> EvaluationArtifactRecord | None:
        row = self._connection.execute(
            "SELECT frozen_aggregate_manifest_artifact_id FROM evaluation_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        if row["frozen_aggregate_manifest_artifact_id"] is None:
            return None
        return self._get_artifact_by_id(UUID(row["frozen_aggregate_manifest_artifact_id"]))

    def read_artifact(self, artifact: EvaluationArtifactRecord | UUID | str) -> bytes:
        record = self._resolve_artifact(artifact)
        for location in self.list_artifact_locations(record):
            if location.location_kind == "filesystem":
                return Path(location.uri).read_bytes()
        raise FileNotFoundError(
            f"no readable location for Evaluation Artifact: {record.artifact_id}"
        )

    def _definition_for_run(
        self, run_id: UUID, kind: EvaluationDefinitionKind
    ) -> dict[str, Any]:
        run = self._connection.execute(
            "SELECT suite_record_id FROM evaluation_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if run is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        row = self._connection.execute(
            """
            SELECT definition_json FROM evaluation_definition_revisions
            WHERE record_id = ? AND kind = ?
            """,
            (run["suite_record_id"], kind.value),
        ).fetchone()
        if row is None or row["definition_json"] is None:
            raise ValueError("the frozen authored Evaluation Suite is unavailable")
        return json.loads(row["definition_json"])

    def get_frozen_suite(self, run_id: UUID):
        from .suites import EvaluationSuite

        payload = self._definition_for_run(run_id, EvaluationDefinitionKind.SUITE)
        # Recompute from the stored semantic fields.  This also keeps the
        # ledger tolerant of callers that used Pydantic ``model_copy`` to
        # change authored fields without rerunning model post-init hooks.
        payload["content_hash"] = None
        return EvaluationSuite.model_validate(
            payload
        )

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

    @staticmethod
    def _claim_timestamp(value: datetime | None) -> tuple[datetime, str]:
        timestamp = value or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            raise ValueError("finalization claim timestamps must include a timezone")
        timestamp = timestamp.astimezone(timezone.utc)
        return timestamp, timestamp.isoformat()

    def acquire_finalization_claim(
        self,
        run_id: UUID,
        *,
        owner_id: str,
        lease_seconds: float = 300.0,
        now: datetime | None = None,
    ) -> EvaluationFinalizationClaim | None:
        """Atomically acquire a live finalization lease, if one is available."""
        if not owner_id:
            raise ValueError("finalization claim owner_id must be non-empty")
        if lease_seconds <= 0:
            raise ValueError("finalization claim lease_seconds must be greater than 0")
        acquired_at, acquired_timestamp = self._claim_timestamp(now)
        expires_at = acquired_at + timedelta(seconds=lease_seconds)
        claim = EvaluationFinalizationClaim(
            run_id=run_id,
            owner_id=owner_id,
            acquired_at=acquired_at,
            expires_at=expires_at,
        )
        with self._transaction_lock:
            try:
                self._connection.execute("BEGIN")
                row = self._connection.execute(
                    "SELECT status FROM evaluation_runs WHERE run_id = ?",
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown Evaluation Run: {run_id}")
                if row["status"] != EvaluationRunStatus.FINALIZATION_PENDING.value:
                    raise ValueError(
                        "finalization claims require a finalization_pending Evaluation Run"
                    )
                cursor = self._connection.execute(
                    """
                    UPDATE evaluation_runs
                    SET finalization_claim_id = ?,
                        finalization_claim_owner_id = ?,
                        finalization_claim_acquired_at = ?,
                        finalization_claim_expires_at = ?
                    WHERE run_id = ?
                      AND status = ?
                      AND (
                          finalization_claim_id IS NULL
                          OR finalization_claim_expires_at <= ?
                      )
                    """,
                    (
                        str(claim.claim_id),
                        claim.owner_id,
                        acquired_timestamp,
                        expires_at.astimezone(timezone.utc).isoformat(),
                        str(run_id),
                        EvaluationRunStatus.FINALIZATION_PENDING.value,
                        acquired_timestamp,
                    ),
                )
                if cursor.rowcount != 1:
                    self._connection.rollback()
                    return None
                self._connection.commit()
                return claim
            except Exception:
                self._connection.rollback()
                raise

    def get_finalization_claim(
        self, run_id: UUID
    ) -> EvaluationFinalizationClaim | None:
        row = self._connection.execute(
            """
            SELECT finalization_claim_id, finalization_claim_owner_id,
                   finalization_claim_acquired_at, finalization_claim_expires_at
            FROM evaluation_runs
            WHERE run_id = ?
            """,
            (str(run_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        if row["finalization_claim_id"] is None:
            return None
        return EvaluationFinalizationClaim(
            claim_id=UUID(row["finalization_claim_id"]),
            run_id=run_id,
            owner_id=row["finalization_claim_owner_id"],
            acquired_at=datetime.fromisoformat(row["finalization_claim_acquired_at"]),
            expires_at=datetime.fromisoformat(row["finalization_claim_expires_at"]),
        )

    def owns_finalization_claim(
        self,
        run_id: UUID,
        claim_id: UUID,
        *,
        now: datetime | None = None,
    ) -> bool:
        _, timestamp = self._claim_timestamp(now)
        row = self._connection.execute(
            """
            SELECT 1 FROM evaluation_runs
            WHERE run_id = ?
              AND finalization_claim_id = ?
              AND finalization_claim_expires_at > ?
            """,
            (str(run_id), str(claim_id), timestamp),
        ).fetchone()
        return row is not None

    def release_finalization_claim(self, run_id: UUID, claim_id: UUID) -> bool:
        """Release only the exact claim token that was acquired."""
        with self._transaction_lock:
            cursor = self._connection.execute(
                """
                UPDATE evaluation_runs
                SET finalization_claim_id = NULL,
                    finalization_claim_owner_id = NULL,
                    finalization_claim_acquired_at = NULL,
                    finalization_claim_expires_at = NULL
                WHERE run_id = ? AND finalization_claim_id = ?
                """,
                (str(run_id), str(claim_id)),
            )
            self._connection.commit()
            return cursor.rowcount == 1

    def get_resolved_evaluation_plan(
        self, run_id: UUID
    ) -> ResolvedEvaluationPlan | None:
        row = self._connection.execute(
            "SELECT plan_json FROM resolved_evaluation_plans WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        return (
            None
            if row is None
            else ResolvedEvaluationPlan.model_validate_json(row["plan_json"])
        )

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
                configuration_fingerprint, status, duration_seconds, failure_message,
                trace_id, span_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(execution.execution_id), str(execution.case_result_id),
                execution.evaluator_name, execution.evaluator_revision,
                execution.configuration_fingerprint, execution.status.value,
                execution.duration_seconds, execution.failure_message,
                execution.trace_id, execution.span_id,
            ),
        )

    def _insert_report_execution(self, execution: ReportEvaluatorExecution) -> None:
        self._connection.execute(
            """
            INSERT INTO report_evaluator_executions (
                execution_id, run_id, evaluator_name, evaluator_revision,
                configuration_fingerprint, status, duration_seconds, failure_message,
                trace_id, span_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(execution.execution_id), str(execution.run_id), execution.evaluator_name,
                execution.evaluator_revision, execution.configuration_fingerprint,
                execution.status.value, execution.duration_seconds, execution.failure_message,
                execution.trace_id, execution.span_id,
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
                case_concurrency=config["case_concurrency"],
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
            frozen_aggregate_manifest_artifact_id=(
                None
                if row["frozen_aggregate_manifest_artifact_id"] is None
                else UUID(row["frozen_aggregate_manifest_artifact_id"])
            ),
            finalization_claim=(
                None
                if row["finalization_claim_id"] is None
                else EvaluationFinalizationClaim(
                    claim_id=UUID(row["finalization_claim_id"]),
                    run_id=UUID(row["run_id"]),
                    owner_id=row["finalization_claim_owner_id"],
                    acquired_at=datetime.fromisoformat(
                        row["finalization_claim_acquired_at"]
                    ),
                    expires_at=datetime.fromisoformat(
                        row["finalization_claim_expires_at"]
                    ),
                )
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
            checkpoint_id=(
                None if row["checkpoint_id"] is None else UUID(row["checkpoint_id"])
            ),
            checkpoint_content_hash=row["checkpoint_content_hash"],
        )

    @staticmethod
    def _case_execution_from_row(row: sqlite3.Row) -> CaseEvaluatorExecution:
        return CaseEvaluatorExecution(
            execution_id=UUID(row["execution_id"]), case_result_id=UUID(row["case_result_id"]),
            evaluator_name=row["evaluator_name"], evaluator_revision=row["evaluator_revision"],
            configuration_fingerprint=row["configuration_fingerprint"],
            status=EvaluationProducerStatus(row["status"]),
            duration_seconds=row["duration_seconds"], failure_message=row["failure_message"],
            trace_id=row["trace_id"], span_id=row["span_id"],
        )

    @staticmethod
    def _report_execution_from_row(row: sqlite3.Row) -> ReportEvaluatorExecution:
        return ReportEvaluatorExecution(
            execution_id=UUID(row["execution_id"]), run_id=UUID(row["run_id"]),
            evaluator_name=row["evaluator_name"], evaluator_revision=row["evaluator_revision"],
            configuration_fingerprint=row["configuration_fingerprint"],
            status=EvaluationProducerStatus(row["status"]),
            duration_seconds=row["duration_seconds"], failure_message=row["failure_message"],
            trace_id=row["trace_id"], span_id=row["span_id"],
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
                    schema_references_json, metadata_json, definition_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(
                        definition.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            if isinstance(definition, EvaluationGoldSet):
                self._insert_gold_set_memberships(definition)
            self._insert_declared_artifact_links(definition)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return record

    def _insert_declared_artifact_links(self, definition: Any) -> None:
        for declared in getattr(definition, "artifacts", ()):
            artifact = self.get_artifact(declared.content_hash)
            if artifact is None:
                raise KeyError(
                    f"unknown Evaluation Artifact: {declared.content_hash}"
                )
            self._link_definition_artifact(
                definition.identity.record_id, artifact, declared.role, commit=False
            )

    def _link_definition_artifact(
        self,
        definition_record_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        role: str,
        *,
        commit: bool = True,
    ) -> EvaluationArtifactLinkRecord:
        artifact_record = self._resolve_artifact(artifact)
        link = EvaluationArtifactLinkRecord(
            link_id=new_uuid7(),
            definition_record_id=definition_record_id,
            artifact_id=artifact_record.artifact_id,
            role=role,
            artifact=artifact_record,
        )
        existing = self._connection.execute(
            """
            SELECT * FROM evaluation_definition_artifacts
            WHERE definition_record_id = ? AND artifact_id = ? AND role = ?
            """,
            (str(definition_record_id), str(link.artifact_id), link.role),
        ).fetchone()
        if existing is not None:
            return EvaluationArtifactLinkRecord(
                link_id=UUID(existing["link_id"]),
                artifact_id=UUID(existing["artifact_id"]),
                role=existing["role"],
                definition_record_id=UUID(existing["definition_record_id"]),
                artifact=self._get_artifact_by_id(UUID(existing["artifact_id"])),
            )
        self._connection.execute(
            """
            INSERT INTO evaluation_definition_artifacts (
                link_id, definition_record_id, artifact_id, role
            ) VALUES (?, ?, ?, ?)
            """,
            (
                str(link.link_id), str(definition_record_id),
                str(link.artifact_id), link.role,
            ),
        )
        if commit:
            self._connection.commit()
        return link

    def link_artifact_to_definition(
        self,
        definition_record_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        *,
        role: str,
    ) -> EvaluationArtifactLinkRecord:
        """Link an artifact to an authored definition revision by namespaced role."""
        return self._link_definition_artifact(definition_record_id, artifact, role)

    def _link_artifact(
        self,
        table: str,
        owner_column: str,
        owner_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        role: str,
        *,
        commit: bool = True,
    ) -> EvaluationArtifactLinkRecord:
        artifact_record = self._resolve_artifact(artifact)
        link = EvaluationArtifactLinkRecord(
            link_id=new_uuid7(), artifact_id=artifact_record.artifact_id,
            role=role, artifact=artifact_record,
        )
        existing = self._connection.execute(
            f"SELECT * FROM {table} WHERE {owner_column} = ? AND artifact_id = ? AND role = ?",
            (str(owner_id), str(link.artifact_id), link.role),
        ).fetchone()
        if existing is not None:
            return EvaluationArtifactLinkRecord(
                link_id=UUID(existing["link_id"]),
                artifact_id=UUID(existing["artifact_id"]),
                role=existing["role"],
                artifact=self._get_artifact_by_id(UUID(existing["artifact_id"])),
            )
        self._connection.execute(
            f"INSERT INTO {table} (link_id, {owner_column}, artifact_id, role) VALUES (?, ?, ?, ?)",
            (str(link.link_id), str(owner_id), str(link.artifact_id), link.role),
        )
        if commit:
            self._connection.commit()
        return link

    def link_consumed_artifact_to_run(
        self,
        run_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        *,
        role: str,
    ) -> EvaluationArtifactLinkRecord:
        return self._link_artifact(
            "evaluation_run_consumed_artifacts", "run_id", run_id, artifact, role
        )

    def link_artifact_to_run(
        self,
        run_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        *,
        role: str,
    ) -> EvaluationArtifactLinkRecord:
        return self._link_artifact(
            "evaluation_run_artifacts", "run_id", run_id, artifact, role
        )

    def link_artifact_to_case_result(
        self,
        case_result_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        *,
        role: str,
    ) -> EvaluationArtifactLinkRecord:
        return self._link_artifact(
            "evaluation_case_result_artifacts", "case_result_id", case_result_id,
            artifact, role,
        )

    def link_artifact_to_case_evaluator_execution(
        self,
        execution_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        *,
        role: str,
    ) -> EvaluationArtifactLinkRecord:
        return self._link_artifact(
            "case_evaluator_execution_artifacts", "execution_id", execution_id,
            artifact, role,
        )

    def link_artifact_to_report_evaluator_execution(
        self,
        execution_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        *,
        role: str,
    ) -> EvaluationArtifactLinkRecord:
        return self._link_artifact(
            "report_evaluator_execution_artifacts", "execution_id", execution_id,
            artifact, role,
        )

    def list_definition_artifacts(
        self, definition_record_id: UUID
    ) -> list[EvaluationArtifactLinkRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM evaluation_definition_artifacts
            WHERE definition_record_id = ? ORDER BY rowid
            """,
            (str(definition_record_id),),
        ).fetchall()
        return [
            EvaluationArtifactLinkRecord(
                link_id=UUID(row["link_id"]),
                artifact_id=UUID(row["artifact_id"]),
                role=row["role"],
                definition_record_id=UUID(row["definition_record_id"]),
                artifact=self._get_artifact_by_id(UUID(row["artifact_id"])),
            )
            for row in rows
        ]

    def _list_artifact_links(
        self, table: str, owner_column: str, owner_id: UUID
    ) -> list[EvaluationArtifactLinkRecord]:
        rows = self._connection.execute(
            f"SELECT * FROM {table} WHERE {owner_column} = ? ORDER BY rowid",
            (str(owner_id),),
        ).fetchall()
        return [
            EvaluationArtifactLinkRecord(
                link_id=UUID(row["link_id"]),
                artifact_id=UUID(row["artifact_id"]),
                role=row["role"],
                artifact=self._get_artifact_by_id(UUID(row["artifact_id"])),
            )
            for row in rows
        ]

    def list_consumed_artifacts(
        self, run_id: UUID
    ) -> list[EvaluationArtifactLinkRecord]:
        return self._list_artifact_links(
            "evaluation_run_consumed_artifacts", "run_id", run_id
        )

    def list_run_artifacts(self, run_id: UUID) -> list[EvaluationArtifactLinkRecord]:
        return self._list_artifact_links("evaluation_run_artifacts", "run_id", run_id)

    def list_case_result_artifacts(
        self, case_result_id: UUID
    ) -> list[EvaluationArtifactLinkRecord]:
        return self._list_artifact_links(
            "evaluation_case_result_artifacts", "case_result_id", case_result_id
        )

    def list_case_evaluator_execution_artifacts(
        self, execution_id: UUID
    ) -> list[EvaluationArtifactLinkRecord]:
        return self._list_artifact_links(
            "case_evaluator_execution_artifacts", "execution_id", execution_id
        )

    def list_report_evaluator_execution_artifacts(
        self, execution_id: UUID
    ) -> list[EvaluationArtifactLinkRecord]:
        return self._list_artifact_links(
            "report_evaluator_execution_artifacts", "execution_id", execution_id
        )

    def list_produced_artifacts(
        self, run_id: UUID
    ) -> list[EvaluationProducedArtifactRecord]:
        rows = self._connection.execute(
            """
            SELECT artifact_id, role, 'run' AS producer_type, run_id AS producer_id
            FROM evaluation_run_artifacts WHERE run_id = ?
            UNION ALL
            SELECT a.artifact_id, a.role, 'case_result', r.result_id
            FROM evaluation_case_result_artifacts a
            JOIN evaluation_case_results r ON r.result_id = a.case_result_id
            WHERE r.run_id = ?
            UNION ALL
            SELECT a.artifact_id, a.role, 'case_evaluator_execution', a.execution_id
            FROM case_evaluator_execution_artifacts a
            JOIN case_evaluator_executions e ON e.execution_id = a.execution_id
            JOIN evaluation_case_results c ON c.result_id = e.case_result_id
            JOIN evaluation_runs r ON r.run_id = c.run_id
            WHERE r.run_id = ?
            UNION ALL
            SELECT a.artifact_id, a.role, 'report_evaluator_execution', a.execution_id
            FROM report_evaluator_execution_artifacts a
            JOIN report_evaluator_executions e ON e.execution_id = a.execution_id
            WHERE e.run_id = ?
            ORDER BY producer_type, role
            """,
            (str(run_id), str(run_id), str(run_id), str(run_id)),
        ).fetchall()
        return [
            EvaluationProducedArtifactRecord(
                artifact_id=UUID(row["artifact_id"]),
                role=row["role"],
                producer_type=row["producer_type"],
                producer_id=UUID(row["producer_id"]),
                artifact=self._get_artifact_by_id(UUID(row["artifact_id"])),
            )
            for row in rows
        ]

    # Short aliases retain a discoverable API for callers that use the subject
    # name rather than the full execution-record name.
    list_case_evaluator_artifacts = list_case_evaluator_execution_artifacts
    list_report_evaluator_artifacts = list_report_evaluator_execution_artifacts
    list_artifacts_consumed_by_run = list_consumed_artifacts
    list_artifacts_produced_by_run = list_produced_artifacts
    attach_artifact_to_definition = link_artifact_to_definition
    attach_artifact_to_run = link_artifact_to_run
    attach_artifact_to_case_result = link_artifact_to_case_result
    attach_artifact_to_case_evaluator_execution = link_artifact_to_case_evaluator_execution
    attach_artifact_to_report_evaluator_execution = (
        link_artifact_to_report_evaluator_execution
    )

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

    def _get_artifact_by_id(self, artifact_id: UUID) -> EvaluationArtifactRecord:
        row = self._connection.execute(
            "SELECT * FROM evaluation_artifacts WHERE artifact_id = ?",
            (str(artifact_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Artifact: {artifact_id}")
        return self._artifact_from_row(row)

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
