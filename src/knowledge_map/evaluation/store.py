"""SQLite persistence for imported evaluation definitions and artifacts.

Authored definitions remain the source of truth in code or files.  This module
only stores the immutable identity and queryable index needed by the runtime.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import UUID
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure

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
from .suites import (
    CustomComparisonOperation,
    EvaluationMetricDefinition,
    EvaluationMetricReference,
    EvaluationMetricValueType,
    EvaluationSuite,
    NoComparisonOperation,
    OrderedComparisonOperation,
)
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
    REPORT_CASE_EVIDENCE_ADAPTER,
    RunMetricObservation,
    StructuredMetricValue,
    FailedReportCaseEvidence,
    SuccessfulReportCaseEvidence,
    TaskFailure,
    TaskOutcome,
    TaskSuccess,
)
from .reporting import (
    SchemaRegistry,
    _evaluation_result,
    _evaluator_failure,
    materialize_metric_observation as _materialize_metric_observation,
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


class EvaluationMetricDefinitionRecord(BaseModel):
    """The canonical ledger record for one repository-wide metric revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    namespaced_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
    )
    evaluator_revision: int = Field(ge=1)
    value_type: EvaluationMetricValueType
    structured_schema: SchemaReference | None = None
    semantic_description: str = Field(min_length=1)
    comparison_operation: (
        OrderedComparisonOperation | NoComparisonOperation | CustomComparisonOperation
    )
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def identity(self) -> tuple[str, int]:
        return (self.namespaced_name, self.evaluator_revision)

    @property
    def definition(self) -> EvaluationMetricDefinition:
        return EvaluationMetricDefinition(
            namespaced_name=self.namespaced_name,
            evaluator_revision=self.evaluator_revision,
            value_type=self.value_type,
            structured_schema=self.structured_schema,
            semantic_description=self.semantic_description,
            comparison_operation=self.comparison_operation,
            content_hash=self.content_hash,
        )


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


class SQLiteEvaluationSchemaInstaller:
    """Install the clean current evaluation schema on a supplied connection."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        install_callback: Callable[[], None],
    ) -> None:
        self.connection = connection
        self._install_callback = install_callback

    def install(self) -> None:
        self._install_callback()


class _SQLiteLedgerCapability:
    """Base for capability stores sharing the ledger connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._handlers: dict[str, Callable[..., Any]] = {}

    def bind(self, name: str, handler: Callable[..., Any]) -> None:
        self._handlers[name] = handler

    def __getattr__(self, name: str) -> Any:
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class SQLiteAuthoredDefinitionCatalog(_SQLiteLedgerCapability):
    """Catalog boundary for immutable authored evaluation definitions."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        ledger: Any,
    ) -> None:
        super().__init__(connection)
        self._ledger = ledger

    def import_definition(
        self, definition: Any
    ) -> EvaluationDefinitionRecord | EvaluationMetricDefinitionRecord:
        """Import an authored revision's identity and index metadata idempotently."""
        if isinstance(definition, EvaluationMetricDefinition):
            return self.import_metric_definition(definition)
        if isinstance(definition, EvaluationSuite):
            definition = self._canonical_suite(definition)
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

        existing = self.connection.execute(
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
            if isinstance(definition, EvaluationSuite):
                self._import_suite_metrics(definition, identity.record_id)
                self.connection.commit()
            return self._definition_from_row(existing)

        try:
            self.connection.execute(
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
            if isinstance(definition, EvaluationSuite):
                self._import_suite_metrics(definition, identity.record_id)
            if isinstance(definition, EvaluationGoldSet):
                self._insert_gold_set_memberships(definition)
            self._insert_declared_artifact_links(definition)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return record

    @staticmethod
    def _canonical_suite(suite: EvaluationSuite) -> EvaluationSuite:
        """Recompute nested metric and Suite hashes for model-copy-tolerant imports."""
        payload = suite.model_dump(mode="json")
        payload["metrics"] = [
            {**metric, "content_hash": None} for metric in payload["metrics"]
        ]
        payload["content_hash"] = None
        return EvaluationSuite.model_validate(payload)

    def import_metric_definition(
        self, metric: EvaluationMetricDefinition
    ) -> EvaluationMetricDefinitionRecord:
        """Import one canonical metric revision independently of any Suite."""
        canonical = self._canonical_metric_definition(metric)

        try:
            record = self._upsert_metric_definition(canonical)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return record

    def _upsert_metric_definition(
        self, metric: EvaluationMetricDefinition
    ) -> EvaluationMetricDefinitionRecord:
        existing = self.connection.execute(
            """
            SELECT * FROM evaluation_metric_definitions
            WHERE namespaced_name = ? AND evaluator_revision = ?
            """,
            metric.identity,
        ).fetchone()
        if existing is not None:
            if existing["content_hash"] != metric.content_hash:
                raise AuthoredDefinitionConflictError(
                    "metric content changed without a new revision"
                )
            return self._metric_definition_from_row(existing)

        record = EvaluationMetricDefinitionRecord(
            record_id=new_uuid7(),
            namespaced_name=metric.namespaced_name,
            evaluator_revision=metric.evaluator_revision,
            value_type=metric.value_type,
            structured_schema=metric.structured_schema,
            semantic_description=metric.semantic_description,
            comparison_operation=metric.comparison_operation,
            content_hash=metric.content_hash,
        )
        self.connection.execute(
            """
            INSERT INTO evaluation_metric_definitions (
                record_id, namespaced_name, evaluator_revision, value_type,
                structured_schema_json, semantic_description,
                comparison_operation_json, content_hash, definition_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(record.record_id),
                record.namespaced_name,
                record.evaluator_revision,
                record.value_type.value,
                None
                if record.structured_schema is None
                else json.dumps(
                    record.structured_schema.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                record.semantic_description,
                json.dumps(
                    record.comparison_operation.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                record.content_hash,
                json.dumps(
                    record.definition.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        return record

    def _import_suite_metrics(
        self, suite: EvaluationSuite, suite_record_id: UUID
    ) -> None:
        for metric in suite.metrics:
            canonical = self._canonical_metric_definition(metric)
            record = self._upsert_metric_definition(canonical)
            existing = self.connection.execute(
                """
                SELECT * FROM evaluation_suite_metrics
                WHERE suite_record_id = ?
                  AND namespaced_name = ?
                  AND evaluator_revision = ?
                """,
                (
                    str(suite_record_id),
                    record.namespaced_name,
                    record.evaluator_revision,
                ),
            ).fetchone()
            if existing is not None:
                if existing["metric_content_hash"] != record.content_hash:
                    raise AuthoredDefinitionConflictError(
                        "Suite-to-metric relationship points to conflicting metric content"
                    )
                continue
            self.connection.execute(
                """
                INSERT INTO evaluation_suite_metrics (
                    suite_record_id, metric_record_id, namespaced_name,
                    evaluator_revision, metric_content_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(suite_record_id),
                    str(record.record_id),
                    record.namespaced_name,
                    record.evaluator_revision,
                    record.content_hash,
                ),
            )

    @staticmethod
    def _canonical_metric_definition(
        metric: EvaluationMetricDefinition,
    ) -> EvaluationMetricDefinition:
        """Recompute a metric hash from fields for model-copy-tolerant imports."""
        payload = metric.model_dump(mode="json")
        payload["content_hash"] = None
        return EvaluationMetricDefinition.model_validate(payload)

    def _insert_declared_artifact_links(self, definition: Any) -> None:
        for declared in getattr(definition, "artifacts", ()):
            artifact = self._ledger.get_artifact(declared.content_hash)
            if artifact is None:
                raise KeyError(
                    f"unknown Evaluation Artifact: {declared.content_hash}"
                )
            self._ledger.artifact_catalog.link_artifact_to_definition(
                definition.identity.record_id, artifact, role=declared.role, commit=False
            )

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
            case_schemas = case_record.schema_references
            required_schemas_match = (
                len(case_schemas) in (2, 3)
                and case_schemas[0] == gold_set.task_contract.input_schema
                and case_schemas[-1] == gold_set.task_contract.metadata_schema
            )
            declared_expected_schema_matches = (
                len(case_schemas) == 2
                or case_schemas[1] == gold_set.task_contract.output_schema
            )
            if not required_schemas_match or not declared_expected_schema_matches:
                raise ValueError(
                    "Gold Set membership case does not implement the Gold Set task contract"
                )
            self.connection.execute(
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

    def get_metric_definition(
        self, *, namespaced_name: str, evaluator_revision: int
    ) -> EvaluationMetricDefinitionRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM evaluation_metric_definitions
            WHERE namespaced_name = ? AND evaluator_revision = ?
            """,
            (namespaced_name, evaluator_revision),
        ).fetchone()
        return None if row is None else self._metric_definition_from_row(row)

    def list_metric_definitions(self) -> list[EvaluationMetricDefinitionRecord]:
        rows = self.connection.execute(
            """
            SELECT * FROM evaluation_metric_definitions
            ORDER BY namespaced_name, evaluator_revision
            """
        ).fetchall()
        return [self._metric_definition_from_row(row) for row in rows]

    def list_suite_metric_definitions(
        self, suite_record_id: UUID
    ) -> list[EvaluationMetricDefinitionRecord]:
        rows = self.connection.execute(
            """
            SELECT m.*
            FROM evaluation_suite_metrics AS sm
            JOIN evaluation_metric_definitions AS m
              ON m.record_id = sm.metric_record_id
            WHERE sm.suite_record_id = ?
            ORDER BY sm.namespaced_name, sm.evaluator_revision
            """,
            (str(suite_record_id),),
        ).fetchall()
        return [self._metric_definition_from_row(row) for row in rows]

    list_suite_metrics = list_suite_metric_definitions

    def get_definition(
        self,
        *,
        business_id: str,
        revision: int,
        kind: EvaluationDefinitionKind | str,
    ) -> EvaluationDefinitionRecord | None:
        kind_value = EvaluationDefinitionKind(kind).value
        row = self.connection.execute(
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
        rows = self.connection.execute(
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

    def list_gold_set_memberships(
        self, gold_set_record_id: UUID
    ) -> list[EvaluationGoldSetMembershipRecord]:
        rows = self.connection.execute(
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

    @staticmethod
    def _metric_definition_from_row(
        row: sqlite3.Row,
    ) -> EvaluationMetricDefinitionRecord:
        return EvaluationMetricDefinitionRecord(
            record_id=UUID(row["record_id"]),
            namespaced_name=row["namespaced_name"],
            evaluator_revision=row["evaluator_revision"],
            value_type=EvaluationMetricValueType(row["value_type"]),
            structured_schema=(
                None
                if row["structured_schema_json"] is None
                else SchemaReference.model_validate(
                    json.loads(row["structured_schema_json"])
                )
            ),
            semantic_description=row["semantic_description"],
            comparison_operation=json.loads(row["comparison_operation_json"]),
            content_hash=row["content_hash"],
        )



class SQLiteEvaluationExecutionStore(_SQLiteLedgerCapability):
    """Execution and checkpoint boundary for evaluation runs."""

    def __init__(self, connection: sqlite3.Connection, ledger: Any) -> None:
        super().__init__(connection)
        self._ledger = ledger

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
            self.connection.execute("BEGIN")
            self.connection.execute(
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
            self.connection.execute(
                """
                INSERT INTO resolved_evaluation_plans (run_id, plan_json)
                VALUES (?, ?)
                """,
                (str(run.run_id), plan.canonical_json),
            )
            for entry in manifest_items:
                self.connection.execute(
                    """
                    INSERT INTO evaluation_case_manifests (
                        manifest_id, run_id, ordinal, case_record_id,
                        case_business_id, case_revision, case_content_hash,
                        split
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(entry.manifest_id), str(entry.run_id), entry.ordinal,
                        str(entry.case_record_id), entry.case_business_id,
                        entry.case_revision, entry.case_content_hash,
                        entry.split.value,
                    ),
                )
            for result in result_items:
                self.connection.execute(
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
            self.connection.commit()
        except Exception:
            self.connection.rollback()
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
        validated_evidence = self._validate_report_case_evidence(
            result, report_case_evidence
        )
        canonical_evidence = (
            None
            if validated_evidence is None
            else validated_evidence.model_dump(mode="json")
        )
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
                "report_case_evidence": canonical_evidence,
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
        with self._ledger._transaction_lock:
            try:
                self.connection.execute("BEGIN")
                cursor = self.connection.execute(
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
                        None if canonical_evidence is None else json.dumps(
                            canonical_evidence, sort_keys=True, separators=(",", ":")
                        ),
                        str(checkpoint_id),
                        checkpoint_hash,
                        str(result.result_id),
                    ),
                )
                if cursor.rowcount != 1:
                    existing = self.connection.execute(
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
                        and self._ledger.list_case_evaluator_executions(result.result_id)
                        == list(executions)
                        and self._ledger.list_case_metric_observations(result.result_id)
                        == list(observations)
                        and existing_evidence == canonical_evidence
                    ):
                        self.connection.commit()
                        return
                    raise ValueError(
                        f"Evaluation Case Result is already terminal with different evidence: {result.result_id}"
                    )
                if result.task_outcome is not None:
                    for artifact in result.task_outcome.artifacts:
                        self._ledger.artifact_catalog._link_artifact(
                            "evaluation_case_result_artifacts",
                            "case_result_id",
                            result.result_id,
                            artifact.content_hash,
                            artifact.role,
                            commit=False,
                        )
                for execution in executions:
                    self._insert_case_execution(execution)
                self._validate_case_observation_ownership(
                    result.result_id, observations
                )
                for observation in observations:
                    self._insert_case_observation(observation)
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    @staticmethod
    def _validate_report_case_evidence(
        result: EvaluationCaseResult,
        evidence: Mapping[str, Any] | None,
    ) -> SuccessfulReportCaseEvidence | FailedReportCaseEvidence | None:
        if evidence is None:
            return None
        validated = REPORT_CASE_EVIDENCE_ADAPTER.validate_python(evidence)
        if isinstance(validated, SuccessfulReportCaseEvidence):
            if (
                result.execution_disposition is not EvaluationCaseDisposition.COMPLETED
                or not isinstance(result.task_outcome, TaskSuccess)
            ):
                raise ValueError(
                    "successful ReportCase evidence requires a completed case "
                    "and successful task outcome"
                )
            if content_fingerprint(validated.output) != content_fingerprint(
                result.task_outcome.model_dump(mode="json")["output"]
            ):
                raise ValueError(
                    "successful ReportCase evidence output does not match the task outcome"
                )
        elif (
            result.execution_disposition is not EvaluationCaseDisposition.FAILED
            or not isinstance(result.task_outcome, TaskFailure)
        ):
            raise ValueError(
                "failed ReportCase evidence requires a failed case and failed task outcome"
            )
        return validated

    def record_report_evaluation(
        self,
        executions: Iterable[ReportEvaluatorExecution],
        observations: Iterable[RunMetricObservation],
        issues: Iterable[EvaluationRunIssue] = (),
        *,
        finalization_claim_id: UUID | None = None,
    ) -> None:
        """Atomically persist one report checkpoint and its diagnostics."""
        executions = tuple(executions)
        observations = tuple(observations)
        issue_items = tuple(issues)
        with self._ledger._transaction_lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                if finalization_claim_id is not None:
                    if not executions:
                        raise ValueError(
                            "a finalization claim requires a report execution checkpoint"
                        )
                    _, claim_timestamp = self._claim_timestamp()
                    claim = self.connection.execute(
                        """
                        SELECT 1
                        FROM evaluation_runs
                        WHERE run_id = ?
                          AND status = ?
                          AND finalization_claim_id = ?
                          AND finalization_claim_expires_at > ?
                        """,
                        (
                            str(executions[0].run_id),
                            EvaluationRunStatus.FINALIZATION_PENDING.value,
                            str(finalization_claim_id),
                            claim_timestamp,
                        ),
                    ).fetchone()
                    if claim is None:
                        raise RuntimeError(
                            "cannot checkpoint report evaluation without the live finalization claim"
                        )
                existing_executions: dict[UUID, ReportEvaluatorExecution] = {}
                for execution in executions:
                    row = self.connection.execute(
                        "SELECT * FROM report_evaluator_executions WHERE execution_id = ?",
                        (str(execution.execution_id),),
                    ).fetchone()
                    if row is not None:
                        existing = self._report_execution_from_row(row)
                        if existing != execution:
                            raise ValueError(
                                "report evaluator checkpoint replay conflicts with existing execution"
                            )
                        existing_executions[execution.execution_id] = existing
                    else:
                        identity = self.connection.execute(
                            """
                            SELECT * FROM report_evaluator_executions
                            WHERE run_id = ? AND evaluator_name = ?
                              AND evaluator_revision = ?
                              AND configuration_fingerprint = ?
                            """,
                            (
                                str(execution.run_id),
                                execution.evaluator_name,
                                execution.evaluator_revision,
                                execution.configuration_fingerprint,
                            ),
                        ).fetchone()
                        if identity is not None:
                            raise ValueError(
                                "report evaluator checkpoint replay conflicts with existing execution identity"
                            )

                existing_observations: dict[UUID, RunMetricObservation] = {}
                for observation in observations:
                    row = self.connection.execute(
                        "SELECT * FROM run_metric_observations WHERE observation_id = ?",
                        (str(observation.observation_id),),
                    ).fetchone()
                    if row is not None:
                        existing = RunMetricObservation(
                            observation_id=UUID(row["observation_id"]),
                            report_evaluator_execution_id=UUID(
                                row["report_evaluator_execution_id"]
                            ),
                            metric=EvaluationMetricReference(
                                namespaced_name=row["metric_namespaced_name"],
                                evaluator_revision=row["metric_evaluator_revision"],
                            ),
                            **self._observation_values(row),
                        )
                        if existing != observation:
                            raise ValueError(
                                "report evaluator checkpoint replay conflicts with existing observation"
                            )
                        existing_observations[observation.observation_id] = existing
                    else:
                        identity = self.connection.execute(
                            """
                            SELECT 1 FROM run_metric_observations
                            WHERE report_evaluator_execution_id = ?
                              AND metric_namespaced_name = ?
                              AND metric_evaluator_revision = ?
                            """,
                            (
                                str(observation.report_evaluator_execution_id),
                                observation.metric.namespaced_name,
                                observation.metric.evaluator_revision,
                            ),
                        ).fetchone()
                        if identity is not None:
                            raise ValueError(
                                "report evaluator checkpoint replay conflicts with existing observation identity"
                            )
                for execution in executions:
                    if execution.execution_id not in existing_executions:
                        self._insert_report_execution(execution)
                self._validate_report_observation_ownership(
                    executions[0].run_id if executions else None, observations
                )
                for observation in observations:
                    if observation.observation_id not in existing_observations:
                        self._insert_run_observation(observation)
                if issue_items:
                    current = self.connection.execute(
                        "SELECT issues_json FROM evaluation_runs WHERE run_id = ?",
                        (str(executions[0].run_id),),
                    ).fetchone()
                    if current is None:
                        raise KeyError(f"unknown Evaluation Run: {executions[0].run_id}")
                    existing = json.loads(current["issues_json"] or "[]")
                    for issue in issue_items:
                        payload = issue.model_dump(mode="json")
                        if payload not in existing:
                            existing.append(payload)
                    self.connection.execute(
                        "UPDATE evaluation_runs SET issues_json = ? WHERE run_id = ?",
                        (
                            json.dumps(existing, sort_keys=True, separators=(",", ":")),
                            str(executions[0].run_id),
                        ),
                    )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
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
        with self._ledger._transaction_lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                _, claim_timestamp = self._claim_timestamp()
                row = self.connection.execute(
                    "SELECT * FROM evaluation_runs WHERE run_id = ?",
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown Evaluation Run: {run_id}")
                if row["status"] != EvaluationRunStatus.COMPLETED.value:
                    if row["status"] == EvaluationRunStatus.FINALIZATION_PENDING.value:
                        if finalization_claim_id is None:
                            raise ValueError(
                                "Evaluation Run completion requires its exact live finalization claim"
                            )
                        claim = self.connection.execute(
                            """
                            SELECT 1
                            FROM evaluation_runs
                            WHERE run_id = ?
                              AND status = ?
                              AND finalization_claim_id = ?
                              AND finalization_claim_expires_at > ?
                            """,
                            (
                                str(run_id),
                                EvaluationRunStatus.FINALIZATION_PENDING.value,
                                str(finalization_claim_id),
                                claim_timestamp,
                            ),
                        ).fetchone()
                        if claim is None:
                            raise RuntimeError(
                                "cannot complete Evaluation Run without the live finalization claim"
                            )
                    self._assert_run_is_complete(run_id)
                    if (
                        finalization_claim_id is not None
                        and row["finalization_claim_id"]
                        != str(finalization_claim_id)
                    ):
                        raise ValueError(
                            "Evaluation Finalization does not own the run's claim"
                        )
                    self.connection.execute(
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
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
        run = self._ledger.get_evaluation_run(run_id)
        if run is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        return run

    def _assert_run_is_complete(self, run_id: UUID) -> None:
        row = self.connection.execute(
            "SELECT frozen_aggregate_manifest_artifact_id FROM evaluation_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        if row["frozen_aggregate_manifest_artifact_id"] is None:
            raise ValueError(
                "Evaluation Run cannot complete before the aggregate manifest is frozen"
            )
        pending = self.connection.execute(
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
        plan_row = self.connection.execute(
            "SELECT plan_json FROM resolved_evaluation_plans WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if plan_row is None:
            raise ValueError("Evaluation Run cannot complete without its frozen plan")
        plan = ResolvedEvaluationPlan.from_frozen_json(plan_row["plan_json"])
        suite = self._definition_for_run(run_id, EvaluationDefinitionKind.SUITE)
        case_evaluators = {
            evaluator["name"]: evaluator
            for evaluator in suite.get("case_evaluators", [])
        }
        for ordinal, planned_case in enumerate(plan.cases):
            result = self.connection.execute(
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
                (
                    row["evaluator_name"],
                    row["evaluator_revision"],
                    row["configuration_fingerprint"],
                )
                for row in self.connection.execute(
                    """
                    SELECT evaluator_name, evaluator_revision, configuration_fingerprint
                    FROM case_evaluator_executions
                    WHERE case_result_id = ?
                    """,
                    (result["result_id"],),
                )
            }
            expected_case_evaluators = set()
            for resolved in planned_case.evaluators:
                configured = case_evaluators.get(resolved.reference.name)
                if configured is None:
                    raise ValueError(
                        "Evaluation Run cannot complete while the frozen plan references "
                        f"unknown case evaluator: {resolved.reference.name}"
                    )
                expected_case_evaluators.add(
                    (
                        resolved.reference.name,
                        resolved.reference.evaluator_revision,
                        configured["configuration_fingerprint"],
                    )
                )
            missing_case_evaluators = expected_case_evaluators - terminal
            if missing_case_evaluators:
                raise ValueError(
                    "Evaluation Run cannot complete while case evaluators lack terminal evidence: "
                    + ", ".join(sorted(name for name, _, _ in missing_case_evaluators))
                )
        expected = {
            (
                evaluator["name"],
                evaluator["evaluator_revision"],
                evaluator["configuration_fingerprint"],
            )
            for evaluator in suite.get("report_evaluators", [])
        }
        terminal = {
            (
                row["evaluator_name"],
                row["evaluator_revision"],
                row["configuration_fingerprint"],
            )
            for row in self.connection.execute(
                """
                SELECT evaluator_name, evaluator_revision, configuration_fingerprint
                FROM report_evaluator_executions
                WHERE run_id = ?
                """,
                (str(run_id),),
            )
        }
        missing = expected - terminal
        if missing:
            raise ValueError(
                "Evaluation Run cannot complete while report evaluators lack terminal evidence: "
                + ", ".join(sorted(name for name, _, _ in missing))
            )



    def materialize_metric_observation(
        self,
        run_id: UUID,
        observation: CaseMetricObservation | RunMetricObservation,
        schemas: SchemaRegistry,
    ) -> Any:
        """Materialize one observation against the run's frozen Evaluation Suite."""
        if observation.structured_value is None:
            return observation.value
        suite = self._ledger.get_frozen_suite(run_id)
        return _materialize_metric_observation(
            observation, suite=suite, schemas=schemas
        )

    def materialize_report_case(
        self, case_result_id: UUID, schemas: SchemaRegistry
    ) -> ReportCase[Any, Any, Any] | ReportCaseFailure[Any, Any, Any]:
        """Reconstruct a typed framework case from one terminal checkpoint."""
        row = self.connection.execute(
            """
            SELECT r.*, d.definition_json,
                   d.content_hash AS stored_case_content_hash,
                   m.case_content_hash AS manifested_case_content_hash
            FROM evaluation_case_results AS r
            JOIN evaluation_definition_revisions AS d
              ON d.record_id = r.case_record_id
            JOIN evaluation_case_manifests AS m
              ON m.manifest_id = r.manifest_id
            WHERE r.result_id = ? AND r.execution_disposition IN ('completed', 'failed')
            """,
            (str(case_result_id),),
        ).fetchone()
        if row is None:
            raise ValueError("ReportCase requires a completed terminal checkpoint")
        if row["report_case_json"] is None:
            raise ValueError("terminal checkpoint lacks ReportCase evidence")
        authored = json.loads(row["definition_json"])
        semantic_authored = {
            key: value for key, value in authored.items() if key != "content_hash"
        }
        semantic_authored["identity"] = dict(semantic_authored["identity"])
        semantic_authored["identity"].pop("record_id", None)
        authored_hash = content_fingerprint(semantic_authored)
        if authored_hash not in {
            row["stored_case_content_hash"],
            row["manifested_case_content_hash"],
        } or row["stored_case_content_hash"] != row["manifested_case_content_hash"]:
            raise ValueError("frozen case definition fingerprint is mismatched")
        evidence = SQLiteEvaluationExecutionStore._validate_report_case_evidence(
            self._case_result_from_row(row), json.loads(row["report_case_json"])
        )
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
            if not isinstance(evidence, FailedReportCaseEvidence):
                raise ValueError("failed case requires failed ReportCase evidence")
            return ReportCaseFailure(
                name=evidence.name,
                inputs=typed_inputs,
                metadata=typed_metadata,
                expected_output=typed_expected,
                error_message=evidence.error_message,
                error_stacktrace=evidence.error_stacktrace,
                source_case_name=evidence.source_case_name,
                trace_id=evidence.trace_id,
                span_id=evidence.span_id,
            )
        if not isinstance(evidence, SuccessfulReportCaseEvidence):
            raise ValueError("completed case requires successful ReportCase evidence")
        output_schema = self._ledger.get_frozen_suite(
            UUID(row["run_id"])
        ).task_contract.output_schema
        return ReportCase(
            name=evidence.name,
            inputs=typed_inputs,
            metadata=typed_metadata,
            expected_output=typed_expected,
            output=schemas.validate(output_schema, evidence.output),
            metrics=dict(evidence.metrics),
            attributes=dict(evidence.attributes),
            scores={
                key: _evaluation_result(value.model_dump(mode="json"))
                for key, value in evidence.scores.items()
            },
            labels={
                key: _evaluation_result(value.model_dump(mode="json"))
                for key, value in evidence.labels.items()
            },
            assertions={
                key: _evaluation_result(value.model_dump(mode="json"))
                for key, value in evidence.assertions.items()
            },
            task_duration=evidence.task_duration,
            total_duration=evidence.total_duration,
            source_case_name=evidence.source_case_name,
            trace_id=evidence.trace_id,
            span_id=evidence.span_id,
            evaluator_failures=[
                _evaluator_failure(item.model_dump(mode="json"))
                for item in evidence.evaluator_failures
            ],
        )



    def freeze_aggregate_manifest(
        self,
        run_id: UUID,
        *,
        issues: Iterable[EvaluationRunIssue] = (),
        report_provenance: Mapping[str, Any] | None = None,
    ) -> EvaluationArtifactRecord:
        """Freeze the aggregate manifest and atomically enter finalization."""
        with self._ledger._transaction_lock:
            row = self.connection.execute(
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
            if row["frozen_aggregate_manifest_artifact_id"] is not None and report_provenance is None:
                existing_artifact = self._ledger.artifact_catalog.get_artifact_by_id(
                    UUID(row["frozen_aggregate_manifest_artifact_id"])
                )
                existing_manifest = FrozenAggregateManifest.model_validate_json(
                    self._ledger.artifact_catalog.read_artifact(existing_artifact)
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
            artifact = self._ledger.artifact_catalog.register_artifact(
                manifest_bytes,
                kind="frozen-aggregate-manifest",
                media_type="application/json",
                retention_class="run",
                sensitivity_classification="internal",
            )
            destination = self._ledger._artifact_root / f"{artifact.content_hash}.json"
            if not destination.exists():
                destination.write_bytes(manifest_bytes)
            self._ledger.artifact_catalog.put_artifact_location(
                artifact,
                str(destination),
                location_key="frozen-aggregate-manifest",
                location_kind="filesystem",
            )
        with self._ledger._transaction_lock:
            try:
                self.connection.execute("BEGIN")
                issue_items = tuple(issues)
                row = self.connection.execute(
                    "SELECT status, frozen_aggregate_manifest_artifact_id FROM evaluation_runs WHERE run_id = ?",
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown Evaluation Run: {run_id}")
                if row["frozen_aggregate_manifest_artifact_id"] is not None:
                    existing = self._ledger.artifact_catalog.get_artifact_by_id(UUID(row["frozen_aggregate_manifest_artifact_id"]))
                    if existing.content_hash != artifact.content_hash:
                        raise ValueError(
                            "the aggregate manifest is already frozen with a different composition"
                        )
                    self.connection.commit()
                    return existing
                if row["status"] not in {
                    EvaluationRunStatus.RUNNING.value,
                    EvaluationRunStatus.FINALIZATION_PENDING.value,
                }:
                    raise ValueError("only an active Evaluation Run can freeze its aggregate manifest")
                pending = self.connection.execute(
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
                self._ledger.artifact_catalog._link_artifact(
                    "evaluation_run_artifacts",
                    "run_id",
                    run_id,
                    artifact,
                    "evaluation.aggregate-manifest.frozen",
                    commit=False,
                )
                self.connection.execute(
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
                self.connection.commit()
                return artifact
            except Exception:
                self.connection.rollback()
                raise

    def _build_frozen_aggregate_manifest(
        self, run_id: UUID, *, report_provenance: Mapping[str, Any]
    ) -> FrozenAggregateManifest:
        run = self._ledger.get_evaluation_run(run_id)
        plan = self._ledger.get_resolved_evaluation_plan(run_id)
        if run is None or plan is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        suite = self._ledger.get_frozen_suite(run_id)
        entries = self.list_evaluation_case_manifest(run_id)
        rows = self.connection.execute(
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
            validated_evidence = SQLiteEvaluationExecutionStore._validate_report_case_evidence(
                self._case_result_from_row(row), json.loads(row["report_case_json"])
            )
            if validated_evidence is None:
                raise ValueError(
                    "aggregate manifest requires every terminal checkpoint to have evidence"
                )
            checkpoint_hash = content_fingerprint(
                {
                    "case_result": result_payload,
                    "report_case_evidence": validated_evidence.model_dump(mode="json"),
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

    def materialize_aggregate_report(
        self, run_id: UUID, schemas: SchemaRegistry
    ) -> EvaluationReport[Any, Any, Any]:
        """Verify the frozen composition and derive its evaluator-visible report."""
        artifact = self._ledger.get_frozen_aggregate_manifest_artifact(run_id)
        if artifact is None:
            raise ValueError("Evaluation Run has no frozen aggregate manifest")
        content = self._ledger.read_artifact(artifact)
        if hashlib.sha256(content).hexdigest() != artifact.content_hash:
            raise ValueError("frozen aggregate manifest bytes do not match their artifact identity")
        frozen = FrozenAggregateManifest.model_validate_json(content)
        if frozen.evidence_contract_version != EVIDENCE_CONTRACT_VERSION:
            raise ValueError(
                "unsupported evidence-contract version: "
                f"{frozen.evidence_contract_version}"
            )
        suite = self._ledger.get_frozen_suite(run_id)
        suite_reference = self.connection.execute(
            """
            SELECT content_hash FROM evaluation_definition_revisions
            WHERE record_id = ? AND kind = ?
            """,
            (str(frozen.suite_record_id), EvaluationDefinitionKind.SUITE.value),
        ).fetchone()
        if (
            suite_reference is None
            or suite.identity.record_id != frozen.suite_record_id
            or suite_reference["content_hash"] != frozen.suite_content_hash
        ):
            raise ValueError("frozen Evaluation Suite fingerprint is mismatched")
        plan = self._ledger.get_resolved_evaluation_plan(run_id)
        if plan is None or plan.content_hash != frozen.resolved_plan_content_hash:
            raise ValueError("frozen Resolved Evaluation Plan fingerprint is mismatched")
        if content_fingerprint(
            suite.task_contract.model_dump(mode="json")
        ) != frozen.task_contract_content_hash:
            raise ValueError("frozen Evaluation Task Contract fingerprint is mismatched")
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

        cases: list[ReportCase[Any, Any, Any]] = []
        failures: list[ReportCaseFailure[Any, Any, Any]] = []
        for frozen_entry in frozen.cases:
            projected = self._ledger.materialize_report_case(
                frozen_entry.case_result_id, schemas
            )
            if isinstance(projected, ReportCaseFailure):
                failures.append(projected)
            else:
                cases.append(projected)
        provenance = frozen.report_provenance
        return EvaluationReport(
            name=provenance.get("report_name", f"run@{run_id}"),
            cases=cases,
            failures=failures,
            experiment_metadata=provenance.get("experiment_metadata"),
            trace_id=provenance.get("trace_id"),
            span_id=provenance.get("span_id"),
        )

    def get_frozen_aggregate_manifest_artifact(
        self, run_id: UUID
    ) -> EvaluationArtifactRecord | None:
        row = self.connection.execute(
            "SELECT frozen_aggregate_manifest_artifact_id FROM evaluation_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        if row["frozen_aggregate_manifest_artifact_id"] is None:
            return None
        return self._ledger.artifact_catalog.get_artifact_by_id(UUID(row["frozen_aggregate_manifest_artifact_id"]))


    def _definition_for_run(
        self, run_id: UUID, kind: EvaluationDefinitionKind
    ) -> dict[str, Any]:
        run = self.connection.execute(
            "SELECT suite_record_id FROM evaluation_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if run is None:
            raise KeyError(f"unknown Evaluation Run: {run_id}")
        row = self.connection.execute(
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
        run = self._ledger.get_evaluation_run(run_id)
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
        run = self._ledger.get_evaluation_run(run_id)
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
        cursor = self.connection.execute(
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
        self.connection.commit()

    def get_evaluation_run(self, run_id: UUID) -> EvaluationRunRecord | None:
        row = self.connection.execute(
            "SELECT * FROM evaluation_runs WHERE run_id = ?", (str(run_id),)
        ).fetchone()
        return None if row is None else self._run_from_row(row)

    def _claim_timestamp(self) -> tuple[datetime, str]:
        timestamp = self._ledger.clock()
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
    ) -> EvaluationFinalizationClaim | None:
        """Atomically acquire a live finalization lease, if one is available."""
        if not owner_id:
            raise ValueError("finalization claim owner_id must be non-empty")
        if lease_seconds <= 0:
            raise ValueError("finalization claim lease_seconds must be greater than 0")
        with self._ledger._transaction_lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                acquired_at, acquired_timestamp = self._claim_timestamp()
                expires_at = acquired_at + timedelta(seconds=lease_seconds)
                claim = EvaluationFinalizationClaim(
                    run_id=run_id,
                    owner_id=owner_id,
                    acquired_at=acquired_at,
                    expires_at=expires_at,
                )
                row = self.connection.execute(
                    """
                    SELECT status, issues_json, finalization_claim_id,
                           finalization_claim_owner_id,
                           finalization_claim_acquired_at,
                           finalization_claim_expires_at
                    FROM evaluation_runs
                    WHERE run_id = ?
                    """,
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown Evaluation Run: {run_id}")
                if row["status"] != EvaluationRunStatus.FINALIZATION_PENDING.value:
                    raise ValueError(
                        "finalization claims require a finalization_pending Evaluation Run"
                    )
                prior_claim = None
                if row["finalization_claim_id"] is not None:
                    prior_claim = EvaluationFinalizationClaim(
                        claim_id=UUID(row["finalization_claim_id"]),
                        run_id=run_id,
                        owner_id=row["finalization_claim_owner_id"],
                        acquired_at=datetime.fromisoformat(
                            row["finalization_claim_acquired_at"]
                        ),
                        expires_at=datetime.fromisoformat(
                            row["finalization_claim_expires_at"]
                        ),
                    )
                    if prior_claim.expires_at > acquired_at:
                        prior_claim = None
                cursor = self.connection.execute(
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
                    self.connection.rollback()
                    return None
                if prior_claim is not None:
                    recovery_issue = EvaluationRunIssue(
                        category="finalization_claim_recovered",
                        subject=f"claim:{prior_claim.claim_id}",
                        message=json.dumps(
                            {
                                "prior_claim_id": str(prior_claim.claim_id),
                                "prior_owner_id": prior_claim.owner_id,
                                "prior_acquired_at": prior_claim.acquired_at.isoformat(),
                                "prior_expires_at": prior_claim.expires_at.isoformat(),
                                "successor_owner_id": claim.owner_id,
                                "recovered_at": acquired_at.isoformat(),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                    issues = json.loads(row["issues_json"] or "[]")
                    issues.append(recovery_issue.model_dump(mode="json"))
                    self.connection.execute(
                        "UPDATE evaluation_runs SET issues_json = ? WHERE run_id = ?",
                        (
                            json.dumps(issues, sort_keys=True, separators=(",", ":")),
                            str(run_id),
                        ),
                    )
                self.connection.commit()
                return claim
            except Exception:
                self.connection.rollback()
                raise

    def get_finalization_claim(
        self, run_id: UUID
    ) -> EvaluationFinalizationClaim | None:
        row = self.connection.execute(
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
    ) -> bool:
        with self._ledger._transaction_lock:
            try:
                self.connection.execute("BEGIN")
                _, timestamp = self._claim_timestamp()
                row = self.connection.execute(
                    """
                    SELECT 1 FROM evaluation_runs
                    WHERE run_id = ?
                      AND status = ?
                      AND finalization_claim_id = ?
                      AND finalization_claim_expires_at > ?
                    """,
                    (
                        str(run_id),
                        EvaluationRunStatus.FINALIZATION_PENDING.value,
                        str(claim_id),
                        timestamp,
                    ),
                ).fetchone()
                self.connection.commit()
                return row is not None
            except Exception:
                self.connection.rollback()
                raise

    def renew_finalization_claim(
        self,
        run_id: UUID,
        claim_id: UUID,
        *,
        lease_seconds: float = 300.0,
    ) -> EvaluationFinalizationClaim | None:
        """Atomically extend one still-live finalization claim."""
        if lease_seconds <= 0:
            raise ValueError("finalization claim lease_seconds must be greater than 0")
        with self._ledger._transaction_lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                renewed_at, renewed_timestamp = self._claim_timestamp()
                row = self.connection.execute(
                    """
                    SELECT finalization_claim_owner_id, finalization_claim_acquired_at
                    FROM evaluation_runs
                    WHERE run_id = ?
                      AND status = ?
                      AND finalization_claim_id = ?
                      AND finalization_claim_expires_at > ?
                    """,
                    (
                        str(run_id),
                        EvaluationRunStatus.FINALIZATION_PENDING.value,
                        str(claim_id),
                        renewed_timestamp,
                    ),
                ).fetchone()
                if row is None:
                    self.connection.rollback()
                    return None

                expires_at = renewed_at + timedelta(seconds=lease_seconds)
                cursor = self.connection.execute(
                    """
                    UPDATE evaluation_runs
                    SET finalization_claim_expires_at = ?
                    WHERE run_id = ?
                      AND status = ?
                      AND finalization_claim_id = ?
                      AND finalization_claim_expires_at > ?
                    """,
                    (
                        expires_at.isoformat(),
                        str(run_id),
                        EvaluationRunStatus.FINALIZATION_PENDING.value,
                        str(claim_id),
                        renewed_timestamp,
                    ),
                )
                if cursor.rowcount != 1:
                    self.connection.rollback()
                    return None
                self.connection.commit()
                return EvaluationFinalizationClaim(
                    claim_id=claim_id,
                    run_id=run_id,
                    owner_id=row["finalization_claim_owner_id"],
                    acquired_at=datetime.fromisoformat(
                        row["finalization_claim_acquired_at"]
                    ),
                    expires_at=expires_at,
                )
            except Exception:
                self.connection.rollback()
                raise

    def release_finalization_claim(self, run_id: UUID, claim_id: UUID) -> bool:
        """Release only the exact claim token that was acquired."""
        with self._ledger._transaction_lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                cursor = self.connection.execute(
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
                self.connection.commit()
                return cursor.rowcount == 1
            except Exception:
                self.connection.rollback()
                raise

    def get_resolved_evaluation_plan(
        self, run_id: UUID
    ) -> ResolvedEvaluationPlan | None:
        row = self.connection.execute(
            "SELECT plan_json FROM resolved_evaluation_plans WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        return (
            None
            if row is None
            else ResolvedEvaluationPlan.from_frozen_json(row["plan_json"])
        )

    def list_evaluation_runs(self) -> list[EvaluationRunRecord]:
        rows = self.connection.execute(
            "SELECT * FROM evaluation_runs ORDER BY rowid"
        ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def list_evaluation_case_manifest(
        self, run_id: UUID
    ) -> list[EvaluationCaseManifestEntry]:
        rows = self.connection.execute(
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
        rows = self.connection.execute(
            "SELECT * FROM evaluation_case_results WHERE run_id = ? ORDER BY rowid",
            (str(run_id),),
        ).fetchall()
        return [self._case_result_from_row(row) for row in rows]

    list_case_manifest = list_evaluation_case_manifest
    list_case_results = list_evaluation_case_results

    def list_case_evaluator_executions(
        self, case_result_id: UUID
    ) -> list[CaseEvaluatorExecution]:
        rows = self.connection.execute(
            "SELECT * FROM case_evaluator_executions WHERE case_result_id = ? ORDER BY rowid",
            (str(case_result_id),),
        ).fetchall()
        return [self._case_execution_from_row(row) for row in rows]

    def list_report_evaluator_executions(
        self, run_id: UUID
    ) -> list[ReportEvaluatorExecution]:
        rows = self.connection.execute(
            "SELECT * FROM report_evaluator_executions WHERE run_id = ? ORDER BY rowid",
            (str(run_id),),
        ).fetchall()
        return [self._report_execution_from_row(row) for row in rows]

    def list_case_metric_observations(
        self, case_result_id: UUID
    ) -> list[CaseMetricObservation]:
        rows = self.connection.execute(
            """
            SELECT o.*
            FROM case_metric_observations AS o
            JOIN case_evaluator_executions AS e
              ON e.execution_id = o.case_evaluator_execution_id
            WHERE e.case_result_id = ?
            ORDER BY o.rowid
            """,
            (str(case_result_id),),
        ).fetchall()
        return [
            CaseMetricObservation(
                observation_id=UUID(row["observation_id"]),
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
        rows = self.connection.execute(
            """
            SELECT o.*
            FROM run_metric_observations AS o
            JOIN report_evaluator_executions AS e
              ON e.execution_id = o.report_evaluator_execution_id
            WHERE e.run_id = ?
            ORDER BY o.rowid
            """,
            (str(run_id),),
        ).fetchall()
        return [
            RunMetricObservation(
                observation_id=UUID(row["observation_id"]),
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

    def list_metric_observations_across_runs(
        self,
        metric: EvaluationMetricReference | str,
        evaluator_revision: int | None = None,
    ) -> list[RunMetricObservation]:
        """Return one canonical run metric identity across all producing runs."""
        if isinstance(metric, EvaluationMetricReference):
            namespaced_name = metric.namespaced_name
            revision = metric.evaluator_revision
        else:
            if evaluator_revision is None:
                raise TypeError(
                    "evaluator_revision is required when metric is a namespaced name"
                )
            namespaced_name = metric
            revision = evaluator_revision
        rows = self.connection.execute(
            """
            SELECT o.*
            FROM run_metric_observations AS o
            JOIN report_evaluator_executions AS e
              ON e.execution_id = o.report_evaluator_execution_id
            JOIN evaluation_metric_definitions AS m
              ON m.namespaced_name = o.metric_namespaced_name
             AND m.evaluator_revision = o.metric_evaluator_revision
            WHERE o.metric_namespaced_name = ?
              AND o.metric_evaluator_revision = ?
            ORDER BY e.run_id, o.rowid
            """,
            (namespaced_name, revision),
        ).fetchall()
        return [
            RunMetricObservation(
                observation_id=UUID(row["observation_id"]),
                report_evaluator_execution_id=UUID(row["report_evaluator_execution_id"]),
                metric=EvaluationMetricReference(
                    namespaced_name=row["metric_namespaced_name"],
                    evaluator_revision=row["metric_evaluator_revision"],
                ),
                **self._observation_values(row),
            )
            for row in rows
        ]

    list_comparable_metric_observations = list_metric_observations_across_runs
    list_run_metric_observations_across_runs = list_metric_observations_across_runs

    @staticmethod
    def _observation_values(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "number_value": row["number_value"],
            "integer_value": row["integer_value"],
            "boolean_value": None if row["boolean_value"] is None else bool(row["boolean_value"]),
            "string_value": row["string_value"],
            "structured_value": (
                None
                if row["structured_json"] is None
                else StructuredMetricValue.model_validate(json.loads(row["structured_json"]))
            ),
        }

    def _insert_case_execution(self, execution: CaseEvaluatorExecution) -> None:
        self.connection.execute(
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
        self.connection.execute(
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
            None if observation.structured_value is None else json.dumps(
                observation.structured_value.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def _validate_case_observation_ownership(
        self,
        case_result_id: UUID,
        observations: Iterable[CaseMetricObservation],
    ) -> None:
        for observation in observations:
            self._validate_canonical_metric_identity(observation)
            row = self.connection.execute(
                """
                SELECT case_result_id
                FROM case_evaluator_executions
                WHERE execution_id = ?
                """,
                (str(observation.case_evaluator_execution_id),),
            ).fetchone()
            if row is None:
                raise ValueError(
                    "case metric observation references an unknown producer execution"
                )
            if row["case_result_id"] != str(case_result_id):
                raise ValueError(
                    "case metric observation producer belongs to a different case result"
                )

    def _validate_report_observation_ownership(
        self,
        run_id: UUID | None,
        observations: Iterable[RunMetricObservation],
    ) -> None:
        if observations and run_id is None:
            raise ValueError(
                "run metric observations require a report evaluator execution"
            )
        for observation in observations:
            self._validate_canonical_metric_identity(observation)
            row = self.connection.execute(
                """
                SELECT run_id
                FROM report_evaluator_executions
                WHERE execution_id = ?
                """,
                (str(observation.report_evaluator_execution_id),),
            ).fetchone()
            if row is None:
                raise ValueError(
                    "run metric observation references an unknown producer execution"
                )
            if row["run_id"] != str(run_id):
                raise ValueError(
                    "run metric observation producer belongs to a different Evaluation Run"
                )

    def _validate_canonical_metric_identity(
        self, observation: EvaluationMetricObservation
    ) -> None:
        row = self.connection.execute(
            """
            SELECT 1
            FROM evaluation_metric_definitions
            WHERE namespaced_name = ? AND evaluator_revision = ?
            """,
            (
                observation.metric.namespaced_name,
                observation.metric.evaluator_revision,
            ),
        ).fetchone()
        if row is None:
            raise ValueError(
                "metric observation must reference a canonical Evaluation Metric Definition"
            )

    def _insert_case_observation(self, observation: CaseMetricObservation) -> None:
        self.connection.execute(
            """
            INSERT INTO case_metric_observations (
                observation_id, case_evaluator_execution_id,
                metric_namespaced_name, metric_evaluator_revision, number_value,
                integer_value, boolean_value, string_value, structured_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(observation.observation_id),
                str(observation.case_evaluator_execution_id),
                *self._observation_columns(observation)[1:],
            ),
        )

    def _insert_run_observation(self, observation: RunMetricObservation) -> None:
        self.connection.execute(
            """
            INSERT INTO run_metric_observations (
                observation_id, report_evaluator_execution_id,
                metric_namespaced_name, metric_evaluator_revision, number_value,
                integer_value, boolean_value, string_value, structured_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(observation.observation_id),
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
                model_parameters=config["model_parameters"],
                execution_mode=config["execution_mode"], random_seed=config["random_seed"],
                case_concurrency=config["case_concurrency"],
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





class SQLiteEvaluationArtifactCatalog(_SQLiteLedgerCapability):
    """Artifact identity, location, lineage, and provenance boundary."""

    def __init__(self, connection: sqlite3.Connection, ledger: Any) -> None:
        super().__init__(connection)
        self._ledger = ledger

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
        existing = self.connection.execute(
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

        self.connection.execute(
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
        self.connection.commit()
        return candidate

    def get_artifact(self, content_hash: str) -> EvaluationArtifactRecord | None:
        row = self.connection.execute(
            "SELECT * FROM evaluation_artifacts WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return None if row is None else self._artifact_from_row(row)

    def get_artifact_by_id(self, artifact_id: UUID) -> EvaluationArtifactRecord:
        row = self.connection.execute(
            "SELECT * FROM evaluation_artifacts WHERE artifact_id = ?",
            (str(artifact_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Artifact: {artifact_id}")
        return self._artifact_from_row(row)

    def read_artifact(
        self, artifact: EvaluationArtifactRecord | UUID | str
    ) -> bytes:
        record = self._resolve_artifact(artifact)
        for location in self.list_artifact_locations(record):
            if location.location_kind == "filesystem":
                return Path(location.uri).read_bytes()
        raise FileNotFoundError(
            f"no readable location for Evaluation Artifact: {record.artifact_id}"
        )

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
        existing = self.connection.execute(
            """
            SELECT * FROM evaluation_artifact_locations
            WHERE artifact_id = ? AND location_key = ?
            """,
            (str(artifact_record.artifact_id), location_key),
        ).fetchone()
        location_id = UUID(existing["location_id"]) if existing else new_uuid7()
        self.connection.execute(
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
        self.connection.commit()
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
        rows = self.connection.execute(
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
        self.connection.execute(
            """
            INSERT OR IGNORE INTO evaluation_artifact_derivatives (
                source_artifact_id, derivative_artifact_id, relationship
            ) VALUES (?, ?, 'redaction')
            """,
            (str(source_record.artifact_id), str(derivative.artifact_id)),
        )
        self.connection.commit()
        return derivative

    def list_artifact_derivatives(
        self, source: EvaluationArtifactRecord | UUID | str
    ) -> list[ArtifactDerivativeRecord]:
        source_record = self._resolve_artifact(source)
        rows = self.connection.execute(
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
        row = self.connection.execute(
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
            row = self.connection.execute(
                "SELECT * FROM evaluation_artifacts WHERE artifact_id = ?",
                (str(artifact),),
            ).fetchone()
        else:
            try:
                artifact_id = UUID(artifact)
            except ValueError:
                return self.get_artifact(artifact) or self._missing_artifact(artifact)
            row = self.connection.execute(
                "SELECT * FROM evaluation_artifacts WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown Evaluation Artifact: {artifact}")
        return self._artifact_from_row(row)

    @staticmethod
    def _missing_artifact(value: str) -> EvaluationArtifactRecord:
        raise KeyError(f"unknown Evaluation Artifact: {value}")

    def link_artifact_to_definition(
        self,
        definition_record_id: UUID,
        artifact: EvaluationArtifactRecord | UUID | str,
        *,
        role: str,
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
        existing = self.connection.execute(
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
                artifact=self.get_artifact_by_id(UUID(existing["artifact_id"])),
            )
        self.connection.execute(
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
            self.connection.commit()
        return link

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
        existing = self.connection.execute(
            f"SELECT * FROM {table} WHERE {owner_column} = ? AND artifact_id = ? AND role = ?",
            (str(owner_id), str(link.artifact_id), link.role),
        ).fetchone()
        if existing is not None:
            return EvaluationArtifactLinkRecord(
                link_id=UUID(existing["link_id"]),
                artifact_id=UUID(existing["artifact_id"]),
                role=existing["role"],
                artifact=self.get_artifact_by_id(UUID(existing["artifact_id"])),
            )
        self.connection.execute(
            f"INSERT INTO {table} (link_id, {owner_column}, artifact_id, role) VALUES (?, ?, ?, ?)",
            (str(link.link_id), str(owner_id), str(link.artifact_id), link.role),
        )
        if commit:
            self.connection.commit()
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
        rows = self.connection.execute(
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
                artifact=self.get_artifact_by_id(UUID(row["artifact_id"])),
            )
            for row in rows
        ]

    def _list_artifact_links(
        self, table: str, owner_column: str, owner_id: UUID
    ) -> list[EvaluationArtifactLinkRecord]:
        rows = self.connection.execute(
            f"SELECT * FROM {table} WHERE {owner_column} = ? ORDER BY rowid",
            (str(owner_id),),
        ).fetchall()
        return [
            EvaluationArtifactLinkRecord(
                link_id=UUID(row["link_id"]),
                artifact_id=UUID(row["artifact_id"]),
                role=row["role"],
                artifact=self.get_artifact_by_id(UUID(row["artifact_id"])),
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
        rows = self.connection.execute(
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
                artifact=self.get_artifact_by_id(UUID(row["artifact_id"])),
            )
            for row in rows
        ]

    # Read/write names that make the replaceable-location behavior explicit.
    add_artifact_location = put_artifact_location
    replace_artifact_location = put_artifact_location
    list_locations = list_artifact_locations
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


class EvaluationLedger(Protocol):
    """Persistence contract consumed by the evaluation runtime."""

    @property
    def clock(self) -> Callable[[], datetime]: ...

    def __getattr__(self, name: str) -> Any: ...

    def create_evaluation_run(self, *args: Any, **kwargs: Any) -> None: ...

    def record_case_evaluation(self, *args: Any, **kwargs: Any) -> None: ...

    def record_report_evaluation(self, *args: Any, **kwargs: Any) -> None: ...

    def complete_evaluation_run(self, *args: Any, **kwargs: Any) -> Any: ...


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
        references = [
            definition.task_contract.input_schema,
            definition.task_contract.output_schema,
            definition.task_contract.metadata_schema,
        ]
        references.extend(
            metric.structured_schema
            for metric in definition.metrics
            if metric.structured_schema is not None
        )
        return tuple(dict.fromkeys(references))
    if isinstance(definition, EvaluationGoldSet):
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

    @classmethod
    def in_memory(
        cls, *, clock: Callable[[], datetime] | None = None
    ) -> "SQLiteEvaluationLedger":
        """Create a ledger whose records persist only for its process lifetime."""
        return cls(":memory:", clock=clock)

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._transaction_lock = RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if str(db_path) == ":memory:":
            self._artifact_root = Path(tempfile.mkdtemp(prefix="evaluation-artifacts-"))
            self._owns_artifact_root = True
        else:
            database_path = Path(db_path)
            self._artifact_root = database_path.parent / f".{database_path.name}.artifacts"
            self._owns_artifact_root = False
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self.schema_installer = SQLiteEvaluationSchemaInstaller(
            self._connection, self._create_schema
        )
        self.schema_installer.install()
        self.definition_catalog = SQLiteAuthoredDefinitionCatalog(
            self._connection, self
        )
        self.execution_store = SQLiteEvaluationExecutionStore(
            self._connection, self
        )
        self.artifact_catalog = SQLiteEvaluationArtifactCatalog(
            self._connection, self
        )
        self._bind_capability_methods()

    def close(self) -> None:
        self._connection.close()
        if self._owns_artifact_root:
            shutil.rmtree(self._artifact_root, ignore_errors=True)

    def __enter__(self) -> "SQLiteEvaluationLedger":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @property
    def clock(self) -> Callable[[], datetime]:
        """Return the clock used for all ledger authority decisions."""
        return self._clock

    @property
    def connection(self) -> sqlite3.Connection:
        """The one connection shared by the facade and its capabilities."""
        return self._connection

    # The facade owns the public boundary; capability stores own the routed
    # operation and use the private implementation methods below.  This keeps
    # cross-capability transactions on this one connection and lock.
    def import_definition(
        self, definition: Any
    ) -> EvaluationDefinitionRecord | EvaluationMetricDefinitionRecord:
        return self.definition_catalog.import_definition(definition)

    def import_metric_definition(
        self, metric: EvaluationMetricDefinition
    ) -> EvaluationMetricDefinitionRecord:
        return self.definition_catalog.import_metric_definition(metric)

    def get_metric_definition(
        self, *, namespaced_name: str, evaluator_revision: int
    ) -> EvaluationMetricDefinitionRecord | None:
        return self.definition_catalog.get_metric_definition(
            namespaced_name=namespaced_name, evaluator_revision=evaluator_revision
        )

    def list_metric_definitions(self) -> list[EvaluationMetricDefinitionRecord]:
        return self.definition_catalog.list_metric_definitions()

    def list_suite_metric_definitions(
        self, suite_record_id: UUID
    ) -> list[EvaluationMetricDefinitionRecord]:
        return self.definition_catalog.list_suite_metric_definitions(suite_record_id)

    list_suite_metrics = list_suite_metric_definitions

    def get_definition(
        self,
        *,
        business_id: str,
        revision: int,
        kind: EvaluationDefinitionKind | str,
    ) -> EvaluationDefinitionRecord | None:
        return self.definition_catalog.get_definition(
            business_id=business_id, revision=revision, kind=kind
        )

    def list_definitions(
        self,
        *,
        kind: EvaluationDefinitionKind | str | None = None,
        business_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[EvaluationDefinitionRecord]:
        return self.definition_catalog.list_definitions(
            kind=kind, business_id=business_id, metadata=metadata, tags=tags
        )

    find_definitions = list_definitions

    def list_gold_set_memberships(
        self, gold_set_record_id: UUID
    ) -> list[EvaluationGoldSetMembershipRecord]:
        return self.definition_catalog.list_gold_set_memberships(gold_set_record_id)

    def register_artifact(self, *args: Any, **kwargs: Any) -> EvaluationArtifactRecord:
        return self.artifact_catalog.register_artifact(*args, **kwargs)

    def get_artifact(self, content_hash: str) -> EvaluationArtifactRecord | None:
        return self.artifact_catalog.get_artifact(content_hash)

    def read_artifact(
        self, artifact: EvaluationArtifactRecord | UUID | str
    ) -> bytes:
        return self.artifact_catalog.read_artifact(artifact)

    def create_evaluation_run(
        self,
        run: EvaluationRunRecord,
        plan: ResolvedEvaluationPlan,
        manifest: Iterable[EvaluationCaseManifestEntry],
        pending_results: Iterable[EvaluationCaseResult],
    ) -> None:
        self.execution_store.create_evaluation_run(
            run, plan, manifest, pending_results
        )

    def record_case_evaluation(
        self,
        result: EvaluationCaseResult,
        executions: Iterable[CaseEvaluatorExecution],
        observations: Iterable[CaseMetricObservation],
        report_case_evidence: Mapping[str, Any] | None = None,
    ) -> None:
        self.execution_store.record_case_evaluation(
            result, executions, observations, report_case_evidence
        )

    def record_report_evaluation(
        self,
        executions: Iterable[ReportEvaluatorExecution],
        observations: Iterable[RunMetricObservation],
        issues: Iterable[EvaluationRunIssue] = (),
        *,
        finalization_claim_id: UUID | None = None,
    ) -> None:
        self.execution_store.record_report_evaluation(
            executions,
            observations,
            issues,
            finalization_claim_id=finalization_claim_id,
        )

    def complete_evaluation_run(
        self,
        run_id: UUID,
        *,
        issues: Iterable[EvaluationRunIssue] = (),
        gate_outcomes: Iterable[EvaluationGateOutcome] = (),
        finalization_claim_id: UUID | None = None,
    ) -> EvaluationRunRecord:
        return self.execution_store.complete_evaluation_run(
            run_id,
            issues=issues,
            gate_outcomes=gate_outcomes,
            finalization_claim_id=finalization_claim_id,
        )

    def _bind_capability_methods(self) -> None:
        """Route each domain operation through its shared-connection catalog."""
        definition_methods = (
            "import_definition",
            "import_metric_definition",
            "get_metric_definition",
            "list_metric_definitions",
            "list_suite_metric_definitions",
            "list_suite_metrics",
            "get_definition",
            "list_definitions",
            "find_definitions",
            "list_gold_set_memberships",
            "import_case",
            "import_gold_set",
            "import_rubric",
            "import_suite",
        )
        execution_methods = (
            "materialize_metric_observation",
            "materialize_report_case",
            "freeze_aggregate_manifest",
            "materialize_aggregate_report",
            "get_frozen_aggregate_manifest_artifact",
            "get_frozen_suite",
            "fail_evaluation_run",
            "cancel_evaluation_run",
            "get_evaluation_run",
            "acquire_finalization_claim",
            "get_finalization_claim",
            "owns_finalization_claim",
            "renew_finalization_claim",
            "release_finalization_claim",
            "get_resolved_evaluation_plan",
            "list_evaluation_runs",
            "list_evaluation_case_manifest",
            "list_evaluation_case_results",
            "list_case_manifest",
            "list_case_results",
            "list_case_evaluator_executions",
            "list_report_evaluator_executions",
            "list_case_metric_observations",
            "list_run_metric_observations",
            "list_case_observations",
            "list_run_observations",
            "list_metric_observations_across_runs",
            "list_comparable_metric_observations",
            "list_run_metric_observations_across_runs",
        )
        artifact_methods = (
            "register_artifact",
            "get_artifact",
            "get_artifact_by_id",
            "read_artifact",
            "put_artifact_location",
            "replace_artifact_location",
            "add_artifact_location",
            "list_artifact_locations",
            "list_locations",
            "register_redacted_derivative",
            "list_artifact_derivatives",
            "get_artifact_source",
            "link_artifact_to_definition",
            "link_consumed_artifact_to_run",
            "link_artifact_to_run",
            "link_artifact_to_case_result",
            "link_artifact_to_case_evaluator_execution",
            "link_artifact_to_report_evaluator_execution",
            "list_definition_artifacts",
            "list_consumed_artifacts",
            "list_run_artifacts",
            "list_case_result_artifacts",
            "list_case_evaluator_execution_artifacts",
            "list_report_evaluator_execution_artifacts",
            "list_produced_artifacts",
            "list_case_evaluator_artifacts",
            "list_report_evaluator_artifacts",
            "list_artifacts_consumed_by_run",
            "list_artifacts_produced_by_run",
            "attach_artifact_to_definition",
            "attach_artifact_to_run",
            "attach_artifact_to_case_result",
            "attach_artifact_to_case_evaluator_execution",
            "attach_artifact_to_report_evaluator_execution",
        )
        for component, names in (
            (self.definition_catalog, definition_methods),
            (self.execution_store, execution_methods),
            (self.artifact_catalog, artifact_methods),
        ):
            for name in names:
                handler = getattr(component, name, None) or getattr(self, name)
                component.bind(name, handler)
                setattr(self, name, getattr(component, name))

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

            CREATE TABLE IF NOT EXISTS evaluation_metric_definitions (
                record_id TEXT PRIMARY KEY,
                namespaced_name TEXT NOT NULL,
                evaluator_revision INTEGER NOT NULL CHECK (evaluator_revision >= 1),
                value_type TEXT NOT NULL CHECK (
                    value_type IN ('number', 'integer', 'boolean', 'string', 'structured')
                ),
                structured_schema_json TEXT,
                semantic_description TEXT NOT NULL,
                comparison_operation_json TEXT NOT NULL,
                content_hash TEXT NOT NULL CHECK (
                    length(content_hash) = 64 AND content_hash GLOB '[0-9a-f]*'
                ),
                definition_json TEXT NOT NULL,
                UNIQUE(namespaced_name, evaluator_revision),
                UNIQUE(record_id, namespaced_name, evaluator_revision)
            );

            CREATE INDEX IF NOT EXISTS idx_evaluation_metric_definition_hash
                ON evaluation_metric_definitions(content_hash);

            CREATE TABLE IF NOT EXISTS evaluation_suite_metrics (
                suite_record_id TEXT NOT NULL
                    REFERENCES evaluation_definition_revisions(record_id),
                metric_record_id TEXT NOT NULL
                    REFERENCES evaluation_metric_definitions(record_id),
                namespaced_name TEXT NOT NULL,
                evaluator_revision INTEGER NOT NULL CHECK (evaluator_revision >= 1),
                metric_content_hash TEXT NOT NULL CHECK (
                    length(metric_content_hash) = 64
                    AND metric_content_hash GLOB '[0-9a-f]*'
                ),
                PRIMARY KEY (suite_record_id, metric_record_id),
                UNIQUE (suite_record_id, namespaced_name, evaluator_revision),
                FOREIGN KEY (metric_record_id, namespaced_name, evaluator_revision)
                    REFERENCES evaluation_metric_definitions(
                        record_id, namespaced_name, evaluator_revision
                    )
            );

            CREATE TRIGGER IF NOT EXISTS evaluation_metric_definitions_immutable_update
            BEFORE UPDATE ON evaluation_metric_definitions
            BEGIN
                SELECT RAISE(ABORT, 'Evaluation Metric Definitions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS evaluation_metric_definitions_immutable_delete
            BEFORE DELETE ON evaluation_metric_definitions
            BEGIN
                SELECT RAISE(ABORT, 'Evaluation Metric Definitions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS evaluation_suite_metrics_immutable_update
            BEFORE UPDATE ON evaluation_suite_metrics
            BEGIN
                SELECT RAISE(ABORT, 'Suite-to-metric relationships are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS evaluation_suite_metrics_immutable_delete
            BEFORE DELETE ON evaluation_suite_metrics
            BEGIN
                SELECT RAISE(ABORT, 'Suite-to-metric relationships are immutable');
            END;

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
                frozen_aggregate_manifest_artifact_id TEXT,
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
                    + (structured_json IS NOT NULL) = 1),
                FOREIGN KEY (metric_namespaced_name, metric_evaluator_revision)
                    REFERENCES evaluation_metric_definitions(namespaced_name, evaluator_revision)
            );

            CREATE TABLE IF NOT EXISTS run_metric_observations (
                observation_id TEXT PRIMARY KEY,
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
                    + (structured_json IS NOT NULL) = 1),
                FOREIGN KEY (metric_namespaced_name, metric_evaluator_revision)
                    REFERENCES evaluation_metric_definitions(namespaced_name, evaluator_revision)
            );

            CREATE INDEX IF NOT EXISTS idx_case_metric_observations_producer_metric
                ON case_metric_observations(
                    case_evaluator_execution_id,
                    metric_namespaced_name,
                    metric_evaluator_revision
                );
            CREATE INDEX IF NOT EXISTS idx_run_metric_observations_producer_metric
                ON run_metric_observations(
                    report_evaluator_execution_id,
                    metric_namespaced_name,
                    metric_evaluator_revision
                );
            CREATE INDEX IF NOT EXISTS idx_case_metric_observations_metric_producer
                ON case_metric_observations(
                    metric_namespaced_name,
                    metric_evaluator_revision,
                    case_evaluator_execution_id
                );
            CREATE INDEX IF NOT EXISTS idx_run_metric_observations_metric_producer
                ON run_metric_observations(
                    metric_namespaced_name,
                    metric_evaluator_revision,
                    report_evaluator_execution_id
                );
            CREATE INDEX IF NOT EXISTS idx_case_evaluator_executions_result
                ON case_evaluator_executions(case_result_id);
            CREATE INDEX IF NOT EXISTS idx_report_evaluator_executions_run
                ON report_evaluator_executions(run_id);
            """
        )
        self._connection.commit()


# Domain-oriented aliases keep the persistence implementation name out of
# callers that only need the evaluation ledger/catalog contract.
EvaluationArtifact = EvaluationArtifactRecord
ArtifactLocation = ArtifactLocationRecord
EvaluationArtifactDerivative = ArtifactDerivativeRecord
SQLiteEvaluationStore = SQLiteEvaluationLedger
