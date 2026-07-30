import asyncio
import hashlib
import json
import logging
import math
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import BaseModel, SecretStr
from pydantic_evals.evaluators import (
    Evaluator,
    EvaluatorContext,
    EvaluatorFailure,
    ReportEvaluator,
    ReportEvaluatorContext,
)
from pydantic_evals.reporting.analyses import ScalarResult, TableResult
from pydantic_evals.reporting import ReportCaseFailure

from knowledge_map.evaluation import (
    CaseEvaluatorExecution,
    CaseMetricObservation,
    ConfiguredEvaluator,
    DeclaredArtifactReference,
    EvaluationCase,
    EvaluationCaseManifestEntry,
    EvaluationCaseDisposition,
    EvaluationCaseResult,
    EvaluationCaseIdentity,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationMetricDefinition,
    EvaluationMetricObservation,
    EvaluationMetricReference,
    EvaluationMetricValueType,
    EvaluationProducerStatus,
    EvaluationRequirement,
    EvaluationRequirementBinding,
    EvaluationRequirementCatalog,
    ReportEvaluatorExecution,
    EvaluationRunConfiguration,
    ValidatedComponentConfiguration,
    EvaluationRunIssue,
    EvaluationRunRecord,
    EvaluationRunner,
    EvaluationRunStatus,
    FinalizationClaimLostError,
    RunMetricObservation,
    EvaluationRubric,
    EvaluationRubricIdentity,
    EvaluationRubricRevisionReference,
    EvaluationSplit,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    EvaluationTaskBinding,
    ConfiguredEvaluatorReference,
    NoComparisonOperation,
    SchemaReference,
    SchemaRegistry,
    StructuredMetricValue,
    SuccessfulReportCaseEvidence,
    TaskFailure,
    TaskSuccess,
    evaluator_version_tag,
    preflight_selected_cases,
)
from knowledge_map.evaluation.store import (
    SQLiteEvaluationLedger,
)


class Input(BaseModel):
    prompt: str


class Output(BaseModel):
    answer: str


class Metadata(BaseModel):
    source: str


class ComponentConfiguration(BaseModel):
    temperature: int = 0
    api_key: SecretStr


def _run(runner: EvaluationRunner, **kwargs):
    """Preflight run scenarios at the public boundary."""
    plan = kwargs.pop("plan", None)
    selection = kwargs.pop("selection", None)
    split = kwargs.pop("split", None)
    if plan is None:
        plan = preflight_selected_cases(
            suite=kwargs["suite"],
            gold_set=kwargs["gold_set"],
            cases=kwargs["cases"],
            selection=selection,
            split=split,
        )
    assert plan is not None
    return runner.run(plan=plan, **kwargs)


@dataclass
class ControllableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


@dataclass
class RenewalClock:
    current: datetime
    initial: datetime
    renewal_seen: threading.Event

    def __call__(self) -> datetime:
        if self.current > self.initial:
            self.renewal_seen.set()
        return self.current


@dataclass
class ClockAdvancingBlockingCountCases(ReportEvaluator):
    clock: RenewalClock
    entered: threading.Event
    release: threading.Event
    calls: list[str]

    def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        self.calls.append(ctx.name)
        self.clock.current = self.clock.initial + timedelta(seconds=0.1)
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("blocking evaluator was not released")
        return ScalarResult(title="evaluated-cases", value=len(ctx.report.cases))


@dataclass
class AsyncClockAdvancingBlockingCountCases(ReportEvaluator):
    clock: RenewalClock
    entered: threading.Event
    release: threading.Event
    calls: list[str]

    async def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        self.calls.append(ctx.name)
        self.clock.current = self.clock.initial + timedelta(seconds=0.1)
        self.entered.set()
        if not await asyncio.to_thread(self.release.wait, 5):
            raise TimeoutError("blocking evaluator was not released")
        return ScalarResult(title="evaluated-cases", value=len(ctx.report.cases))


def _schemas_for(cases) -> SchemaRegistry:
    schemas = SchemaRegistry()
    schemas.register(cases[0].input_schema, Input)
    schemas.register(cases[0].expected_output_schema, Output)
    schemas.register(cases[0].metadata_schema, Metadata)
    return schemas


def test_structured_metric_value_accepts_only_strict_json_object_payloads():
    reference = SchemaReference(
        identity="tests.structured", revision=1, model_fingerprint="a" * 64
    )

    value = StructuredMetricValue(
        schema_reference=reference,
        payload={
            "nested": {"items": ["text", True, 3, 1.5, None]},
        },
    )

    assert value.payload["nested"] == {
        "items": ["text", True, 3, 1.5, None]
    }
    for invalid in (["root"], "root", 1, {1: "non-string-key"}, {"bad": (1, 2)}, {"bad": math.nan}):
        with pytest.raises(ValueError, match="strict JSON|JSON object|keys must be strings"):
            StructuredMetricValue(schema_reference=reference, payload=invalid)


def test_metric_observation_has_one_value_and_no_storage_field_alias():
    reference = SchemaReference(
        identity="tests.structured", revision=1, model_fingerprint="a" * 64
    )
    structured = StructuredMetricValue(schema_reference=reference, payload={"ok": True})
    metric = EvaluationMetricReference(
        namespaced_name="tests.example", evaluator_revision=1
    )

    observation = EvaluationMetricObservation(metric=metric, structured_value=structured)

    assert observation.value is structured
    assert "structured_json" not in EvaluationMetricObservation.model_fields
    with pytest.raises(ValueError, match="exactly one value"):
        EvaluationMetricObservation(
            metric=metric,
            boolean_value=True,
            structured_value=structured,
        )


def test_run_configuration_defaults_case_concurrency_to_one():
    configuration = EvaluationRunConfiguration(
        provider="deterministic", model="fixture"
    )

    assert configuration.case_concurrency == 1
    assert json.loads(configuration.configuration_json)["case_concurrency"] == 1


@pytest.mark.parametrize("case_concurrency", [0, -1])
def test_run_configuration_rejects_non_positive_case_concurrency(
    case_concurrency,
):
    with pytest.raises(ValueError, match="greater than 0"):
        EvaluationRunConfiguration(
            provider="deterministic",
            model="fixture",
            case_concurrency=case_concurrency,
        )


@dataclass
class ExactAnswer(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output == ctx.expected_output


@dataclass
class CountCases(ReportEvaluator):
    def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        return ScalarResult(title="evaluated-cases", value=len(ctx.report.cases))


@dataclass
class BlockingCountCases(ReportEvaluator):
    entered: threading.Event
    release: threading.Event
    calls: list[str]

    def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        self.calls.append(ctx.name)
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("blocking evaluator was not released")
        return ScalarResult(title="evaluated-cases", value=len(ctx.report.cases))


@dataclass
class CaseTable(ReportEvaluator):
    def evaluate(self, ctx: ReportEvaluatorContext) -> TableResult:
        return TableResult(
            title="case-table",
            columns=["case"],
            rows=[[case.name] for case in ctx.report.cases],
        )


@dataclass
class NoObservationEvaluator(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return True


@dataclass
class MappingCaseEvaluator(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> dict[str, bool | float]:
        return {"answer-correct": True, "answer-confidence": 0.75}


@dataclass
class CaseTableEvaluator(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> TableResult:
        return TableResult(
            title="case-table",
            columns=["case"],
            rows=[[ctx.name]],
        )


@dataclass
class FailingCaseEvaluator(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        raise ValueError("the case evaluator could not score this output")


@dataclass
class MismatchedStructuredEvaluator(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> Output:
        return Output(answer="wrong structured schema")


@dataclass
class FailingReportEvaluator(ReportEvaluator):
    def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        raise RuntimeError("the report evaluator is unavailable")


@dataclass
class NoObservationReportEvaluator(ReportEvaluator):
    def evaluate(self, ctx: ReportEvaluatorContext):
        return None


@dataclass
class CaptureTypedReport(ReportEvaluator):
    reports: list

    def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        self.reports.append(ctx.report)
        return ScalarResult(title="evaluated-cases", value=len(ctx.report.cases))


@dataclass
class RecordingCaseEvaluator(Evaluator):
    calls: list[str]

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        self.calls.append(ctx.name or "")
        return True


def test_runner_uses_the_frozen_plan_for_case_evaluator_scope(tmp_path):
    cases = (_case(1), _case(2))
    cases = (
        cases[0].model_copy(update={"requirements": ("grounded",)}),
        cases[1],
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-plan", revision=1),
        description="Shared-engine cases.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-plan", revision=1),
        description="Shared-engine suite.",
        requirement_catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(
                    key="grounded", semantic_description="The answer is grounded."
                ),
            )
        ),
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        case_evaluators=(
            ConfiguredEvaluator(name="universal", evaluator_revision=1),
            ConfiguredEvaluator(name="grounding", evaluator_revision=1),
        ),
        suite_case_evaluators=(ConfiguredEvaluatorReference(name="universal"),),
        requirement_bindings=(
            EvaluationRequirementBinding(
                requirement="grounded",
                evaluators=(
                    ConfiguredEvaluatorReference(name="universal"),
                    ConfiguredEvaluatorReference(name="grounding"),
                ),
            ),
        ),
        report_evaluators=(ConfiguredEvaluator(name="count-cases", evaluator_revision=1),),
    )
    universal_calls: list[str] = []
    grounding_calls: list[str] = []
    plan = preflight_selected_cases(
        suite=suite,
        gold_set=gold_set,
        cases=cases,
    )
    assert plan is not None

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            plan=plan,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                RecordingCaseEvaluator(universal_calls)
                if configured.name == "universal"
                else RecordingCaseEvaluator(grounding_calls)
                if configured.name == "grounding"
                else CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

    assert result.run.status == "finalization_pending"
    assert universal_calls == ["case-1@1", "case-2@1"]
    assert grounding_calls == ["case-1@1"]
    assert plan.cases[0].evaluators[0].provenance == (
        "suite-wide",
        "grounded",
    )
    assert [execution.evaluator_name for execution in result.case_evaluator_executions] == [
        "universal",
        "grounding",
        "universal",
    ]


def test_case_checkpoint_rolls_back_all_case_evidence_on_persistence_failure(
    tmp_path, monkeypatch
):
    cases, gold_set, base_suite = _lifecycle_fixture(
        "checkpoint-rollback", case_evaluator="exact-case"
    )
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.checkpoint",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.BOOLEAN,
        semantic_description="Whether checkpoint evidence was produced.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = base_suite.model_copy(
        update={
            "metrics": (metric,),
            "case_evaluators": (
                ConfiguredEvaluator(
                    name="exact-case",
                    evaluator_revision=1,
                    metrics=(
                        EvaluationMetricReference(
                            namespaced_name="tests.checkpoint", evaluator_revision=1
                        ),
                    ),
                ),
            ),
        }
    )

    def fail_observation_insert(observation):
        raise RuntimeError("observation storage failed")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        monkeypatch.setattr(
            ledger.execution_store, "_insert_case_observation", fail_observation_insert
        )
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                ExactAnswer() if configured.name == "exact-case" else CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        case_result = result.case_results[0]
        assert result.run.status == "failed"
        assert case_result.execution_disposition is EvaluationCaseDisposition.PENDING
        assert ledger.list_case_evaluator_executions(case_result.result_id) == []
        assert ledger.list_case_metric_observations(case_result.result_id) == []


def test_runner_materializes_a_report(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("report-materialization")
    database = tmp_path / "evaluation.sqlite"

    with SQLiteEvaluationLedger.in_memory() as evidence:
        result = _run(EvaluationRunner(evidence),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        report = evidence.materialize_aggregate_report(
            result.run.run_id, _schemas_for(cases)
        )

    assert [case.name for case in report.cases] == ["case-1@1"]
    assert report.cases[0].output == Output(answer="prompt-1")
    assert not database.exists()


def test_in_memory_execution_stops_before_evaluation_finalization():
    cases, gold_set, suite = _lifecycle_fixture("in-memory-execution-boundary")
    report_evaluator_calls: list[int] = []

    class RecordingReportEvaluator(ReportEvaluator):
        def evaluate(self, ctx: ReportEvaluatorContext):
            report_evaluator_calls.append(len(ctx.report.cases))
            return None

    with SQLiteEvaluationLedger.in_memory() as evidence:
        result = _run(
            EvaluationRunner(evidence),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: RecordingReportEvaluator(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

    assert result.run.status == "finalization_pending"
    assert result.report_evaluator_executions == ()
    assert report_evaluator_calls == []


def test_in_memory_run_completes_through_evaluation_finalization():
    cases, gold_set, suite = _lifecycle_fixture("in-memory-finalization-boundary")
    report_evaluator_calls: list[int] = []

    class RecordingReportEvaluator(ReportEvaluator):
        def evaluate(self, ctx: ReportEvaluatorContext):
            report_evaluator_calls.append(len(ctx.report.cases))
            return None

    with SQLiteEvaluationLedger.in_memory() as evidence:
        runner = EvaluationRunner(evidence)
        initial = _run(
            runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: RecordingReportEvaluator(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        completed = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: RecordingReportEvaluator(),
        )

    assert completed.run.status == "completed"
    assert [execution.status for execution in completed.report_evaluator_executions] == [
        "completed"
    ]
    assert report_evaluator_calls == [1]


def test_evaluation_stores_do_not_advertise_ephemerality(tmp_path):
    with SQLiteEvaluationLedger.in_memory() as evidence:
        assert not hasattr(evidence, "is_ephemeral")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        assert not hasattr(ledger, "is_ephemeral")


def test_run_retains_content_addressed_terminal_checkpoints():
    cases, gold_set, suite = _lifecycle_fixture("checkpoint-retention")

    with SQLiteEvaluationLedger.in_memory() as evidence:
        _run(EvaluationRunner(evidence),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        checkpoints = tuple(
            result
            for run in evidence.list_evaluation_runs()
            for result in evidence.list_evaluation_case_results(run.run_id)
            if result.checkpoint_id is not None
        )

    assert len(checkpoints) == 1
    assert checkpoints[0].checkpoint_id is not None
    assert checkpoints[0].checkpoint_content_hash is not None
    assert len(checkpoints[0].checkpoint_content_hash) == 64


def test_terminal_checkpoint_materializes_one_typed_report_case(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "typed-report-case", case_evaluator="exact-case"
    )
    registry = SchemaRegistry()
    registry.register(cases[0].input_schema, Input)
    registry.register(cases[0].expected_output_schema, Output)
    registry.register(cases[0].metadata_schema, Metadata)

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(
                answer=task_input.prompt.replace("prompt", "answer")
            ),
            evaluator_resolver=lambda configured: (
                ExactAnswer() if configured.name == "exact-case" else CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        report_case = ledger.materialize_report_case(
            result.case_results[0].result_id, registry
        )

    assert isinstance(report_case.inputs, Input)
    assert isinstance(report_case.expected_output, Output)
    assert isinstance(report_case.metadata, Metadata)
    assert isinstance(report_case.output, Output)
    assert report_case.output == Output(answer="answer-1")
    assert report_case.assertions["exact-case"].value is True
    assert report_case.assertions["exact-case"].reason is None
    assert report_case.assertions["exact-case"].evaluator_version
    assert report_case.task_duration >= 0
    assert report_case.total_duration >= report_case.task_duration
    assert report_case.trace_id is not None and len(report_case.trace_id) == 32
    assert report_case.span_id is not None and len(report_case.span_id) == 16


def test_mapping_case_evaluator_identity_survives_checkpoint_and_aggregate_materialization(
    tmp_path,
):
    cases, gold_set, suite = _lifecycle_fixture(
        "mapping-evaluator-version", case_evaluator="configured-judge"
    )
    configured = suite.case_evaluators[0]
    expected_version = evaluator_version_tag(
        configured.evaluator_revision,
        configured.configuration_fingerprint,
    )
    captured_reports: list = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                MappingCaseEvaluator()
                if configured.name == "configured-judge"
                else CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        checkpoint_case = ledger.materialize_report_case(
            initial.case_results[0].result_id, _schemas_for(cases)
        )
        runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CaptureTypedReport(captured_reports),
        )

    assert set(checkpoint_case.assertions) == {"answer-correct"}
    assert set(checkpoint_case.scores) == {"answer-confidence"}
    assert {
        checkpoint_case.assertions["answer-correct"].evaluator_version,
        checkpoint_case.scores["answer-confidence"].evaluator_version,
    } == {expected_version}
    aggregate_case = captured_reports[0].cases[0]
    assert aggregate_case.assertions["answer-correct"].evaluator_version == expected_version
    assert aggregate_case.scores["answer-confidence"].evaluator_version == expected_version


def test_typed_report_case_rejects_an_unallowlisted_schema(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("unknown-report-schema")
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        with pytest.raises(ValueError, match="schema is not allowlisted"):
            ledger.materialize_report_case(
                result.case_results[0].result_id, SchemaRegistry()
            )


def test_materialization_rejects_corrupted_stored_report_case_evidence(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("corrupted-report-evidence")
    registry = _schemas_for(cases)

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        case_result = result.case_results[0]
        row = ledger._connection.execute(
            "SELECT report_case_json FROM evaluation_case_results WHERE result_id = ?",
            (str(case_result.result_id),),
        ).fetchone()
        corrupted = json.loads(row["report_case_json"])
        corrupted["unexpected"] = "must not be ignored"
        ledger._connection.execute(
            "UPDATE evaluation_case_results SET report_case_json = ? WHERE result_id = ?",
            (json.dumps(corrupted), str(case_result.result_id)),
        )
        ledger._connection.commit()

        with pytest.raises(ValueError, match="unexpected"):
            ledger.materialize_report_case(case_result.result_id, registry)


def test_schema_registry_rejects_a_model_with_the_wrong_fingerprint():
    class IncompatibleInput(BaseModel):
        different: int

    reference = SchemaReference.for_model(
        Input, identity="tests.input", revision=1
    )

    with pytest.raises(ValueError, match="exact schema fingerprint"):
        SchemaRegistry().register(reference, IncompatibleInput)


def test_failed_terminal_checkpoint_materializes_a_typed_report_case_failure(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("typed-report-failure")
    registry = SchemaRegistry()
    registry.register(cases[0].input_schema, Input)
    registry.register(cases[0].expected_output_schema, Output)
    registry.register(cases[0].metadata_schema, Metadata)

    def fail_task(_task_input):
        raise RuntimeError("provider unavailable")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=fail_task,
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        report_case = ledger.materialize_report_case(
            result.case_results[0].result_id, registry
        )

    assert isinstance(report_case, ReportCaseFailure)
    assert isinstance(report_case.inputs, Input)
    assert isinstance(report_case.expected_output, Output)
    assert isinstance(report_case.metadata, Metadata)
    assert "provider unavailable" in report_case.error_message
    assert report_case.error_stacktrace


def test_terminal_case_checkpoint_replay_is_idempotent_and_replacement_is_rejected(
    tmp_path,
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending = _resolved_run_creation_inputs(
            ledger, "immutable-report-case"
        )
        ledger.create_evaluation_run(run, plan, manifest, pending)
        completed = pending[0].model_copy(
            update={
                "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                "task_outcome": TaskSuccess(output={"answer": "stable"}),
            }
        )
        evidence = {
            "kind": "success",
            "name": "case-1@1",
            "output": {"answer": "stable"},
            "metrics": {},
            "attributes": {},
            "scores": {},
            "labels": {},
            "assertions": {},
            "evaluator_failures": [],
            "task_duration": 0.1,
            "total_duration": 0.2,
            "source_case_name": None,
            "trace_id": None,
            "span_id": None,
        }

        ledger.record_case_evaluation(completed, (), (), evidence)
        ledger.record_case_evaluation(
            completed,
            (),
            (),
            {
                "total_duration": 0.2,
                "output": {"answer": "stable"},
                "name": "case-1@1",
                "kind": "success",
                "task_duration": 0.1,
            },
        )

        with pytest.raises(ValueError, match="different evidence"):
            ledger.record_case_evaluation(
                completed,
                (),
                (),
                {**evidence, "total_duration": 99.0},
            )


def _successful_report_case_evidence(**updates):
    evidence = {
        "kind": "success",
        "name": "case-1@1",
        "output": {"answer": "stable"},
        "metrics": {},
        "attributes": {},
        "scores": {},
        "labels": {},
        "assertions": {},
        "evaluator_failures": [],
        "task_duration": 0.1,
        "total_duration": 0.2,
        "source_case_name": None,
        "trace_id": None,
        "span_id": None,
    }
    evidence.update(updates)
    return evidence


def test_report_case_evidence_model_is_immutable_and_rejects_unknown_nested_fields():
    evidence = SuccessfulReportCaseEvidence.model_validate(
        _successful_report_case_evidence(
            assertions={
                "quality": {
                    "name": "quality",
                    "value": True,
                    "reason": None,
                    "source": {"name": "ExactAnswer", "arguments": None},
                    "evaluator_version": "revision-1:abc",
                }
            }
        )
    )

    with pytest.raises(ValueError, match="frozen"):
        evidence.total_duration = 4
    malformed = _successful_report_case_evidence(
        assertions={
            "quality": {
                "name": "quality",
                "value": True,
                "reason": None,
                "source": {
                    "name": "ExactAnswer",
                    "arguments": None,
                    "unexpected": True,
                },
                "evaluator_version": None,
            }
        }
    )
    with pytest.raises(ValueError, match="unexpected"):
        SuccessfulReportCaseEvidence.model_validate(malformed)


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (_successful_report_case_evidence(unexpected=True), "unexpected"),
        (_successful_report_case_evidence(output={"answer": "different"}), "output"),
        (_successful_report_case_evidence(task_duration=-0.1), "greater than or equal"),
        (
            _successful_report_case_evidence(task_duration=0.3, total_duration=0.2),
            "total_duration",
        ),
    ],
)
def test_checkpoint_rejects_invalid_success_evidence_before_persistence(
    tmp_path, evidence, message
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending = _resolved_run_creation_inputs(
            ledger, "invalid-success-evidence"
        )
        ledger.create_evaluation_run(run, plan, manifest, pending)
        completed = pending[0].model_copy(
            update={
                "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                "task_outcome": TaskSuccess(output={"answer": "stable"}),
            }
        )

        with pytest.raises(ValueError, match=message):
            ledger.record_case_evaluation(completed, (), (), evidence)

        assert ledger.list_evaluation_case_results(run.run_id)[0] == pending[0]


@pytest.mark.parametrize(
    ("disposition", "outcome", "evidence", "message"),
    [
        (
            EvaluationCaseDisposition.COMPLETED,
            TaskFailure(
                category="task_execution",
                exception_type="RuntimeError",
                safe_message="failed",
            ),
            _successful_report_case_evidence(),
            "successful ReportCase evidence",
        ),
        (
            EvaluationCaseDisposition.FAILED,
            TaskFailure(
                category="task_execution",
                exception_type="RuntimeError",
                safe_message="failed",
            ),
            _successful_report_case_evidence(),
            "successful ReportCase evidence",
        ),
        (
            EvaluationCaseDisposition.COMPLETED,
            TaskSuccess(output={"answer": "stable"}),
            {
                "kind": "failure",
                "name": "case-1@1",
                "error_message": "RuntimeError: failed",
                "error_stacktrace": "traceback",
            },
            "failed ReportCase evidence",
        ),
    ],
)
def test_checkpoint_rejects_evidence_variant_disposition_and_outcome_mismatches(
    tmp_path, disposition, outcome, evidence, message
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending = _resolved_run_creation_inputs(
            ledger, "mismatched-evidence"
        )
        ledger.create_evaluation_run(run, plan, manifest, pending)
        terminal = pending[0].model_copy(
            update={"execution_disposition": disposition, "task_outcome": outcome}
        )

        with pytest.raises(ValueError, match=message):
            ledger.record_case_evaluation(terminal, (), (), evidence)

        assert ledger.list_evaluation_case_results(run.run_id)[0] == pending[0]


def _lifecycle_fixture(suffix: str, *, case_evaluator: str | None = None):
    cases = (_case(1), _case(2))
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id=f"gold-set-{suffix}", revision=1),
        description="Lifecycle cases.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id=f"suite-{suffix}", revision=1),
        description="Lifecycle suite.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        case_evaluators=(
            ()
            if case_evaluator is None
            else (ConfiguredEvaluator(name=case_evaluator, evaluator_revision=1),)
        ),
        report_evaluators=(
            ConfiguredEvaluator(name="count-cases", evaluator_revision=1),
        ),
    )
    return cases, gold_set, suite


def test_runner_persists_the_resolved_plan_as_canonical_ledger_data(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("resolved-plan")
    expected_plan = preflight_selected_cases(
        suite=suite,
        gold_set=gold_set,
        cases=cases,
    )
    assert expected_plan is not None

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            plan=expected_plan,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        stored_plan = ledger.get_resolved_evaluation_plan(result.run.run_id)

        assert stored_plan == expected_plan
        assert stored_plan.canonical_json == expected_plan.canonical_json


def test_runner_does_not_accept_selection_alongside_a_resolved_plan(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("resolved-plan-selection")
    plan = preflight_selected_cases(
        suite=suite,
        gold_set=gold_set,
        cases=cases,
        selection=("case-1",),
    )
    assert plan is not None

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        with pytest.raises(TypeError, match="unexpected keyword argument 'selection'"):
            EvaluationRunner(ledger).run(
                plan=plan,
                suite=suite,
                gold_set=gold_set,
                cases=cases,
                selection=("case-2",),
                task=lambda task_input: Output(answer=task_input.prompt),
                evaluator_resolver=lambda configured: CountCases(),
                configuration=EvaluationRunConfiguration(
                    provider="deterministic", model="fixture"
                ),
            )


def test_ledger_round_trip_preserves_case_concurrency_and_its_fingerprint(
    tmp_path,
):
    cases, gold_set, suite = _lifecycle_fixture("case-concurrency")
    configuration = EvaluationRunConfiguration(
        provider="deterministic",
        model="fixture",
        case_concurrency=4,
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=configuration,
        )

        stored_run = ledger.get_evaluation_run(result.run.run_id)

        assert stored_run is not None
        assert stored_run.configuration == configuration
        assert json.loads(stored_run.configuration_json)["case_concurrency"] == 4
        assert stored_run.configuration.configuration_fingerprint != (
            EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ).configuration_fingerprint
        )


def test_shared_suite_execution_honors_an_explicit_case_concurrency_bound():
    cases = tuple(_case(number) for number in range(1, 5))
    _, _, suite = _lifecycle_fixture("shared-concurrency")
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(
            business_id="shared-concurrency-gold", revision=1
        ),
        description="Concurrent execution cases.",
        task_contract=suite.task_contract,
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    plan = preflight_selected_cases(
        suite=suite, gold_set=gold_set, cases=cases
    )
    assert plan is not None
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def task(task_input: Input) -> Output:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.03)
            return Output(answer=task_input.prompt)
        finally:
            with lock:
                active -= 1

    with SQLiteEvaluationLedger.in_memory() as evidence:
        result = EvaluationRunner(evidence).run(
            plan=plan,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=task,
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic",
                model="fixture",
                case_concurrency=2,
            ),
        )
        report = evidence.materialize_aggregate_report(
            result.run.run_id, _schemas_for(cases)
        )

    assert len(report.cases) == len(cases)
    assert maximum_active == 2


def test_ledger_serializes_concurrent_terminal_case_checkpoints(tmp_path, monkeypatch):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending_results = _resolved_run_creation_inputs(
            ledger, "concurrent-checkpoints"
        )
        ledger.create_evaluation_run(run, plan, manifest, pending_results)
        insert_case_execution = ledger.execution_store._insert_case_execution

        def delayed_insert(execution: CaseEvaluatorExecution) -> None:
            time.sleep(0.05)
            insert_case_execution(execution)

        monkeypatch.setattr(
            ledger.execution_store, "_insert_case_execution", delayed_insert
        )

        def checkpoint(result: EvaluationCaseResult) -> None:
            execution = CaseEvaluatorExecution(
                case_result_id=result.result_id,
                evaluator_name="checkpoint-evaluator",
                evaluator_revision=1,
                configuration_fingerprint=run.configuration.configuration_fingerprint,
                status=EvaluationProducerStatus.COMPLETED,
                duration_seconds=0,
            )
            ledger.record_case_evaluation(
                result.model_copy(
                    update={
                        "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                        "task_outcome": TaskSuccess(
                            output=Output(answer=result.case_record_id.hex)
                        ),
                    }
                ),
                (execution,),
                (),
            )

        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(checkpoint, pending_results))

        with pytest.raises(ValueError, match="already terminal"):
            checkpoint(pending_results[0])

        stored_results = ledger.list_case_results(run.run_id)
        assert [result.execution_disposition for result in stored_results] == [
            EvaluationCaseDisposition.COMPLETED,
            EvaluationCaseDisposition.COMPLETED,
        ]
        assert [result.task_outcome.kind for result in stored_results] == [
            "success",
            "success",
        ]
        assert [
            execution.evaluator_name
            for result in stored_results
            for execution in ledger.list_case_evaluator_executions(result.result_id)
        ] == ["checkpoint-evaluator", "checkpoint-evaluator"]


@pytest.mark.parametrize(
    ("configured_concurrency", "expected_maximum"),
    ((None, 1), (2, 2)),
)
def test_runner_honors_case_bound_and_checkpoints_each_case_once(
    tmp_path, configured_concurrency, expected_maximum
):
    cases = tuple(_case(number) for number in range(1, 5))
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(
            business_id="gold-set-concurrency", revision=1
        ),
        description="Concurrent cases.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    _, _, suite = _lifecycle_fixture(
        "concurrency", case_evaluator="exact-case"
    )
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def task(task_input: Input) -> Output:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.03)
            return Output(answer=task_input.prompt)
        finally:
            with lock:
                active -= 1

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=task,
            evaluator_resolver=lambda configured: (
                ExactAnswer()
                if configured.name == "exact-case"
                else CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic",
                model="fixture",
                **(
                    {}
                    if configured_concurrency is None
                    else {"case_concurrency": configured_concurrency}
                ),
            ),
        )

        assert result.run.status == "finalization_pending"
        assert maximum_active == expected_maximum
        assert len(result.case_results) == len(cases)
        assert all(
            case.execution_disposition is EvaluationCaseDisposition.COMPLETED
            for case in result.case_results
        )
        assert len(result.case_evaluator_executions) == len(cases)
        assert all(
            len(ledger.list_case_evaluator_executions(case.result_id)) == 1
            for case in result.case_results
        )


def _resolved_run_creation_inputs(ledger, suffix: str):
    cases, gold_set, suite = _lifecycle_fixture(suffix)
    plan = preflight_selected_cases(
        suite=suite,
        gold_set=gold_set,
        cases=cases,
    )
    assert plan is not None
    for case in cases:
        ledger.import_case(case)
    gold_record = ledger.import_gold_set(gold_set)
    suite_record = ledger.import_suite(suite)
    run = EvaluationRunRecord(
        suite_record_id=suite_record.record_id,
        suite_business_id=suite_record.business_id,
        suite_revision=suite_record.revision,
        suite_content_hash=suite_record.content_hash,
        gold_set_record_id=gold_record.record_id,
        gold_set_business_id=gold_record.business_id,
        gold_set_revision=gold_record.revision,
        gold_set_content_hash=gold_record.content_hash,
        configuration=EvaluationRunConfiguration(
            provider="deterministic", model="fixture"
        ),
    )
    manifest = tuple(
        EvaluationCaseManifestEntry(
            run_id=run.run_id,
            ordinal=ordinal,
            case=planned_case.case,
            split=planned_case.split,
        )
        for ordinal, planned_case in enumerate(plan.cases)
    )
    pending_results = tuple(
        EvaluationCaseResult(
            run_id=run.run_id,
            manifest_id=entry.manifest_id,
            case_record_id=entry.case_record_id,
        )
        for entry in manifest
    )
    return run, plan, manifest, pending_results


def test_ledger_rejects_an_invalid_checkpoint(tmp_path):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending = _resolved_run_creation_inputs(
            ledger, "invalid-evidence"
        )
        ledger.create_evaluation_run(run, plan, manifest, pending)
        completed = pending[0].model_copy(
            update={
                "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                "task_outcome": TaskSuccess(output={"answer": "stable"}),
            }
        )

        with pytest.raises(ValueError, match="unexpected"):
            ledger.record_case_evaluation(
                completed,
                (),
                (),
                {
                    "kind": "success",
                    "name": "case-1@1",
                    "output": {"answer": "stable"},
                    "unexpected": "invalid canonical evidence",
                },
            )


def test_ledger_rejects_a_run_whose_suite_does_not_match_the_resolved_plan(
    tmp_path,
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending_results = _resolved_run_creation_inputs(
            ledger, "suite-mismatch"
        )
        mismatched_run = run.model_copy(
            update={"suite_revision": run.suite_revision + 1}
        )

        with pytest.raises(ValueError, match="Suite revision"):
            ledger.create_evaluation_run(
                mismatched_run, plan, manifest, pending_results
            )

        assert ledger.get_evaluation_run(run.run_id) is None
        assert ledger.get_resolved_evaluation_plan(run.run_id) is None


def test_ledger_rejects_a_run_whose_gold_set_does_not_match_the_plan(tmp_path):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending_results = _resolved_run_creation_inputs(
            ledger, "gold-set-mismatch"
        )
        mismatched_run = run.model_copy(
            update={"gold_set_revision": run.gold_set_revision + 1}
        )

        with pytest.raises(ValueError, match="Gold Set revision"):
            ledger.create_evaluation_run(
                mismatched_run, plan, manifest, pending_results
            )

        assert ledger.get_evaluation_run(run.run_id) is None
        assert ledger.get_resolved_evaluation_plan(run.run_id) is None


def test_ledger_rejects_manifested_case_revisions_that_do_not_match_the_plan(
    tmp_path,
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending_results = _resolved_run_creation_inputs(
            ledger, "case-mismatch"
        )
        mismatched_case = manifest[0].case.model_copy(
            update={"revision": manifest[0].case_revision + 1}
        )
        mismatched_manifest = (
            manifest[0].model_copy(update={"case": mismatched_case}),
            *manifest[1:],
        )

        with pytest.raises(ValueError, match="manifested Evaluation Case revisions"):
            ledger.create_evaluation_run(
                run, plan, mismatched_manifest, pending_results
            )

        assert ledger.get_evaluation_run(run.run_id) is None
        assert ledger.list_evaluation_case_manifest(run.run_id) == []


def test_ledger_rejects_a_non_pending_case_result_during_run_creation(tmp_path):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending_results = _resolved_run_creation_inputs(
            ledger, "completed-envelope"
        )
        completed_results = (
            pending_results[0].model_copy(
                update={
                    "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                    "task_outcome": TaskSuccess(output=Output(answer="already done")),
                }
            ),
            *pending_results[1:],
        )

        with pytest.raises(ValueError, match="pending Evaluation Case Result"):
            ledger.create_evaluation_run(run, plan, manifest, completed_results)

        assert ledger.get_evaluation_run(run.run_id) is None
        assert ledger.list_evaluation_case_results(run.run_id) == []


def test_run_creation_rolls_back_plan_manifest_and_results_on_any_failure(
    tmp_path,
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending_results = _resolved_run_creation_inputs(
            ledger, "atomic-rollback"
        )
        duplicate_result_ids = (
            pending_results[0],
            pending_results[1].model_copy(
                update={"result_id": pending_results[0].result_id}
            ),
        )

        with pytest.raises(sqlite3.IntegrityError):
            ledger.create_evaluation_run(
                run, plan, manifest, duplicate_result_ids
            )

        assert ledger.get_evaluation_run(run.run_id) is None
        assert ledger.get_resolved_evaluation_plan(run.run_id) is None
        assert ledger.list_evaluation_case_manifest(run.run_id) == []
        assert ledger.list_evaluation_case_results(run.run_id) == []


def test_task_failure_preserves_provider_neutral_failure_evidence():
    failure = TaskFailure(
        category="timeout",
        exception_type="TimeoutError",
        safe_message="The component did not respond before the deadline.",
        retryable=True,
        failure_evidence={"attempt": 2, "deadline_seconds": 30},
    )

    assert failure.kind == "failure"
    assert failure.category == "timeout"
    assert failure.exception_type == "TimeoutError"
    assert failure.safe_message == "The component did not respond before the deadline."
    assert failure.retryable is True
    assert failure.failure_evidence == {"attempt": 2, "deadline_seconds": 30}


def test_task_outcomes_preserve_content_addressed_artifact_references():
    reference = DeclaredArtifactReference(
        content_hash="a" * 64,
        role="evaluation.task.output",
    )

    success = TaskSuccess(output=Output(answer="answer"), artifacts=(reference,))
    failure = TaskFailure(
        category="provider",
        exception_type="TimeoutError",
        safe_message="timed out",
        artifacts=(reference,),
    )

    assert success.artifacts == (reference,)
    assert failure.artifacts == (reference,)


def test_case_result_persists_task_artifacts_at_case_scope(tmp_path):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending = _resolved_run_creation_inputs(
            ledger, "task-artifact-scope"
        )
        ledger.create_evaluation_run(run, plan, manifest, pending)
        artifact = ledger.register_artifact(
            b"task failure evidence",
            kind="failure-evidence",
            media_type="text/plain",
            retention_class="run",
            sensitivity="internal",
        )
        reference = DeclaredArtifactReference(
            content_hash=artifact.content_hash,
            role="evaluation.task.failure-evidence",
        )
        updated = pending[0].model_copy(
            update={
                "execution_disposition": EvaluationCaseDisposition.FAILED,
                "task_outcome": TaskFailure(
                    category="provider",
                    exception_type="TimeoutError",
                    safe_message="timed out",
                    artifacts=(reference,),
                )
            }
        )

        ledger.record_case_evaluation(updated, (), ())

        links = ledger.list_case_result_artifacts(updated.result_id)
        assert links[0].artifact_id == artifact.artifact_id
        assert links[0].role == "evaluation.task.failure-evidence"


def test_runner_records_task_failure_without_misclassifying_the_run(tmp_path):
    cases = (_case(1), _case(2))
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-task-failure", revision=1),
        description="Task failure cases.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    count_metric = EvaluationMetricDefinition(
        namespaced_name="tests.task-failure-count",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.INTEGER,
        semantic_description="Number of cases whose task completed.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="task-failure-suite", revision=1),
        description="Task failure suite.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        report_evaluators=(
            ConfiguredEvaluator(
                name="count-cases",
                evaluator_revision=1,
                metrics=(
                    EvaluationMetricReference(
                        namespaced_name="tests.task-failure-count", evaluator_revision=1
                    ),
                ),
            ),
        ),
        metrics=(count_metric,),
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        def task(task_input: Input) -> Output:
            if task_input.prompt == "prompt-1":
                raise TimeoutError("provider request timed out")
            return Output(answer="answer-2")

        task_binding = EvaluationTaskBinding(
            operation=task,
            contract=suite.task_contract,
            input_model=Input,
            output_model=Output,
            metadata_model=Metadata,
        )

        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task_binding=task_binding,
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )

        assert result.run.status == "completed"
        assert [case.execution_disposition.value for case in result.case_results] == [
            "failed",
            "completed",
        ]
        failed_outcome = result.case_results[0].task_outcome
        assert isinstance(failed_outcome, TaskFailure)
        assert failed_outcome.category == "component"
        assert failed_outcome.exception_type == "TimeoutError"
        assert failed_outcome.safe_message == "provider request timed out"
        assert result.run_observations[0].integer_value == 1
        assert ledger.list_evaluation_case_results(result.run.run_id) == list(result.case_results)


def test_case_evaluator_failure_is_separate_from_task_and_run_status(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "case-evaluator-failure", case_evaluator="failing-case"
    )
    configured = suite.case_evaluators[0]
    expected_version = evaluator_version_tag(
        configured.evaluator_revision,
        configured.configuration_fingerprint,
    )
    captured_reports: list = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                FailingCaseEvaluator()
                if configured.name == "failing-case"
                else CountCases()
            ),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
        )
        materialized = ledger.materialize_report_case(
            initial.case_results[0].result_id, _schemas_for(cases)
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CaptureTypedReport(captured_reports),
        )

        assert result.run.status == "completed"
        assert all(case.task_outcome.kind == "success" for case in result.case_results)
        assert isinstance(materialized.evaluator_failures[0], EvaluatorFailure)
        assert materialized.evaluator_failures[0].name == "failing-case"
        assert materialized.evaluator_failures[0].source.name == "_RecordingEvaluator"
        assert materialized.evaluator_failures[0].error_type == "ValueError"
        assert materialized.evaluator_failures[0].error_stacktrace
        assert materialized.evaluator_failures[0].evaluator_version == expected_version
        aggregate_failure = captured_reports[0].cases[0].evaluator_failures[0]
        assert isinstance(aggregate_failure, EvaluatorFailure)
        assert aggregate_failure.evaluator_version == expected_version
        assert [execution.status.value for execution in result.case_evaluator_executions] == [
            "failed",
            "failed",
        ]
        assert all(
            "case evaluator could not score" in (execution.failure_message or "")
            for execution in result.case_evaluator_executions
        )
        assert result.report_evaluator_executions[0].status.value == "completed"


def test_report_evaluator_failure_is_retained_without_failing_the_run(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("report-evaluator-failure")
    suite = suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(name="failing-report", evaluator_revision=1),
            )
        }
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: FailingReportEvaluator(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: FailingReportEvaluator(),
        )

        assert result.run.status == "completed"
        assert all(case.task_outcome.kind == "success" for case in result.case_results)
        assert result.report_evaluator_executions[0].status.value == "failed"
        assert "report evaluator is unavailable" in (
            result.report_evaluator_executions[0].failure_message or ""
        )
        assert result.run_observations == ()


def test_report_evaluator_returning_nothing_records_no_observation(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("report-evaluator-none")
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: NoObservationReportEvaluator(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: NoObservationReportEvaluator(),
        )

    assert result.run.status == "completed"
    assert result.report_evaluator_executions[0].status.value == "completed"
    assert result.report_evaluator_executions[0].failure_message is None
    assert result.run_observations == ()


def test_run_artifact_read_models_preserve_smallest_execution_producer(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "artifact-links", case_evaluator="exact-case"
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                NoObservationEvaluator()
                if configured.name == "exact-case"
                else CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )
        consumed = ledger.register_artifact(
            b"suite input",
            kind="prompt",
            media_type="text/plain",
            retention_class="run",
            sensitivity="internal",
        )
        run_output = ledger.register_artifact(
            b"run report",
            kind="report",
            media_type="text/plain",
            retention_class="run",
            sensitivity="internal",
        )
        case_output = ledger.register_artifact(
            b"case output",
            kind="task-output",
            media_type="text/plain",
            retention_class="run",
            sensitivity="internal",
        )
        case_evidence = ledger.register_artifact(
            b"case rationale",
            kind="rationale",
            media_type="text/plain",
            retention_class="run",
            sensitivity="internal",
        )
        report_evidence = ledger.register_artifact(
            b"report analysis",
            kind="analysis",
            media_type="text/plain",
            retention_class="run",
            sensitivity="internal",
        )

        ledger.link_consumed_artifact_to_run(
            result.run.run_id, consumed, role="evaluation.run.prompt"
        )
        ledger.link_artifact_to_run(
            result.run.run_id, run_output, role="evaluation.run.report"
        )
        ledger.link_artifact_to_case_result(
            result.case_results[0].result_id,
            case_output,
            role="evaluation.case-result.task-output",
        )
        ledger.link_artifact_to_case_evaluator_execution(
            result.case_evaluator_executions[0].execution_id,
            case_evidence,
            role="evaluation.case-evaluator.rationale",
        )
        ledger.link_artifact_to_report_evaluator_execution(
            result.report_evaluator_executions[0].execution_id,
            report_evidence,
            role="evaluation.report-evaluator.analysis",
        )

        assert [item.artifact_id for item in ledger.list_consumed_artifacts(result.run.run_id)] == [
            consumed.artifact_id
        ]
        frozen_manifest_artifact_id = result.run.frozen_aggregate_manifest_artifact_id
        assert frozen_manifest_artifact_id is not None
        produced = ledger.list_produced_artifacts(result.run.run_id)
        assert {item.artifact_id for item in produced} == {
            frozen_manifest_artifact_id,
            run_output.artifact_id,
            case_output.artifact_id,
            case_evidence.artifact_id,
            report_evidence.artifact_id,
        }
        assert {
            (item.producer_type, item.role)
            for item in produced
        } == {
                ("run", "evaluation.aggregate-manifest.frozen"),
            ("run", "evaluation.run.report"),
            ("case_result", "evaluation.case-result.task-output"),
            ("case_evaluator_execution", "evaluation.case-evaluator.rationale"),
            ("report_evaluator_execution", "evaluation.report-evaluator.analysis"),
        }


def test_runner_persists_normalized_logfire_execution_identity(tmp_path, monkeypatch):
    import logfire

    class FakeSpan:
        def __init__(self):
            self.context = SimpleNamespace(
                trace_id=0x1234,
                span_id=0x5678,
            )

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get_span_context(self):
            return self.context

    monkeypatch.setattr(logfire, "span", lambda *args, **kwargs: FakeSpan())
    cases, gold_set, suite = _lifecycle_fixture(
        "telemetry-identities", case_evaluator="exact-case"
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                NoObservationEvaluator()
                if configured.name == "exact-case"
                else CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )

    assert result.case_evaluator_executions[0].trace_id == "00000000000000000000000000001234"
    assert result.case_evaluator_executions[0].span_id == "0000000000005678"
    assert result.report_evaluator_executions[0].trace_id == "00000000000000000000000000001234"
    assert result.report_evaluator_executions[0].span_id == "0000000000005678"


def test_runner_marks_authored_case_artifacts_as_run_inputs(tmp_path):
    original_cases, gold_set, suite = _lifecycle_fixture("authored-inputs")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        artifact = ledger.register_artifact(
            b"authoritative prompt",
            kind="prompt",
            media_type="text/plain",
            retention_class="long-term",
            sensitivity="internal",
        )
        cases = tuple(
            case.model_copy(
                update={
                    "artifacts": (
                        DeclaredArtifactReference(
                            content_hash=artifact.content_hash,
                            role="evaluation.case.prompt",
                        ),
                    )
                }
            )
            for case in original_cases
        )
        gold_set = gold_set.model_copy(
            update={
                "memberships": tuple(
                    membership.model_copy(
                        update={
                            "case": EvaluationCaseRevisionReference.from_case(case)
                        }
                    )
                    for membership, case in zip(gold_set.memberships, cases)
                )
            }
        )

        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        consumed = ledger.list_consumed_artifacts(result.run.run_id)
        assert [item.artifact_id for item in consumed] == [artifact.artifact_id]


def test_subset_run_consumes_artifacts_from_only_manifested_case_revisions(tmp_path):
    original_cases, base_gold_set, base_suite = _lifecycle_fixture(
        "subset-authored-inputs"
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        artifacts = {
            role: ledger.register_artifact(
                content,
                kind="authored-input",
                media_type="text/plain",
                retention_class="long-term",
                sensitivity="internal",
            )
            for role, content in {
                "evaluation.suite.definition": b"suite definition",
                "evaluation.gold-set.definition": b"gold set definition",
                "evaluation.rubric.criteria": b"rubric criteria",
                "evaluation.case.selected": b"selected case prompt",
                "evaluation.case.excluded": b"excluded case prompt",
            }.items()
        }
        cases = tuple(
            case.model_copy(
                update={
                    "artifacts": (
                        DeclaredArtifactReference(
                            content_hash=artifacts[role].content_hash,
                            role=role,
                        ),
                    )
                }
            )
            for case, role in zip(
                original_cases,
                ("evaluation.case.selected", "evaluation.case.excluded"),
            )
        )
        gold_set = base_gold_set.model_copy(
            update={
                "artifacts": (
                    DeclaredArtifactReference(
                        content_hash=artifacts[
                            "evaluation.gold-set.definition"
                        ].content_hash,
                        role="evaluation.gold-set.definition",
                    ),
                ),
                "memberships": tuple(
                    membership.model_copy(
                        update={
                            "case": EvaluationCaseRevisionReference.from_case(case)
                        }
                    )
                    for membership, case in zip(base_gold_set.memberships, cases)
                ),
            }
        )
        rubric = EvaluationRubric(
            identity=EvaluationRubricIdentity(
                business_id="rubric-subset-authored-inputs", revision=1
            ),
            description="Judge the selected case.",
            criteria=("The answer is correct.",),
            artifacts=(
                DeclaredArtifactReference(
                    content_hash=artifacts["evaluation.rubric.criteria"].content_hash,
                    role="evaluation.rubric.criteria",
                ),
            ),
        )
        suite = base_suite.model_copy(
            update={
                "rubrics": (EvaluationRubricRevisionReference.from_rubric(rubric),)
            }
        )
        suite_record = ledger.import_suite(suite)
        ledger.link_artifact_to_definition(
            suite_record.record_id,
            artifacts["evaluation.suite.definition"],
            role="evaluation.suite.definition",
        )

        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            rubrics=(rubric,),
            selection=lambda case: case.identity.business_id == "case-1",
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        consumed = ledger.list_consumed_artifacts(result.run.run_id)
        assert {(item.artifact_id, item.role) for item in consumed} == {
            (
                artifacts["evaluation.suite.definition"].artifact_id,
                "evaluation.suite.definition",
            ),
            (
                artifacts["evaluation.gold-set.definition"].artifact_id,
                "evaluation.gold-set.definition",
            ),
            (
                artifacts["evaluation.rubric.criteria"].artifact_id,
                "evaluation.rubric.criteria",
            ),
            (
                artifacts["evaluation.case.selected"].artifact_id,
                "evaluation.case.selected",
            ),
        }


def test_full_population_run_consumes_artifacts_from_every_case_revision(tmp_path):
    original_cases, base_gold_set, suite = _lifecycle_fixture(
        "full-population-authored-inputs"
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        first_artifact = ledger.register_artifact(
            b"first case prompt",
            kind="authored-input",
            media_type="text/plain",
            retention_class="long-term",
            sensitivity="internal",
        )
        second_artifact = ledger.register_artifact(
            b"second case prompt",
            kind="authored-input",
            media_type="text/plain",
            retention_class="long-term",
            sensitivity="internal",
        )
        cases = tuple(
            case.model_copy(
                update={
                    "artifacts": (
                        DeclaredArtifactReference(
                            content_hash=artifact.content_hash,
                            role=role,
                        ),
                    )
                }
            )
            for case, artifact, role in zip(
                original_cases,
                (first_artifact, second_artifact),
                ("evaluation.case.first", "evaluation.case.second"),
            )
        )
        gold_set = base_gold_set.model_copy(
            update={
                "memberships": tuple(
                    membership.model_copy(
                        update={
                            "case": EvaluationCaseRevisionReference.from_case(case)
                        }
                    )
                    for membership, case in zip(base_gold_set.memberships, cases)
                )
            }
        )

        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        consumed = ledger.list_consumed_artifacts(result.run.run_id)
        assert {(item.artifact_id, item.role) for item in consumed} == {
            (first_artifact.artifact_id, "evaluation.case.first"),
            (second_artifact.artifact_id, "evaluation.case.second"),
        }


def test_runner_marks_authored_rubric_artifacts_as_run_inputs(tmp_path):
    cases, gold_set, base_suite = _lifecycle_fixture("authored-rubric-input")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        artifact = ledger.register_artifact(
            b"judge rubric",
            kind="rubric",
            media_type="text/plain",
            retention_class="long-term",
            sensitivity="internal",
        )
        rubric = EvaluationRubric(
            identity=EvaluationRubricIdentity(business_id="rubric-1", revision=1),
            description="Judge the answer.",
            criteria=("The answer is useful.",),
            artifacts=(
                DeclaredArtifactReference(
                    content_hash=artifact.content_hash,
                    role="evaluation.rubric.criteria",
                ),
            ),
        )
        suite = base_suite.model_copy(
            update={
                "rubrics": (EvaluationRubricRevisionReference.from_rubric(rubric),)
            }
        )

        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            rubrics=(rubric,),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        consumed = ledger.list_consumed_artifacts(result.run.run_id)
        assert [item.artifact_id for item in consumed] == [artifact.artifact_id]


def test_cancelled_run_retains_completed_cases_and_pending_envelopes(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("cancelled")
    checks = 0

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
            should_cancel=should_cancel,
        )

        assert result.run.status == "cancelled"
        assert [case.execution_disposition.value for case in result.case_results] == [
            "completed",
            "pending",
        ]
        assert result.report_evaluator_executions == ()
        assert ledger.get_evaluation_run(result.run.run_id) == result.run


def test_process_interruption_preserves_prior_case_checkpoints(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("process-interruption")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        def task(task_input: Input) -> Output:
            if task_input.prompt == "prompt-2":
                raise KeyboardInterrupt()
            return Output(answer=task_input.prompt)

        with pytest.raises(KeyboardInterrupt):
            _run(EvaluationRunner(ledger),
                suite=suite,
                gold_set=gold_set,
                cases=cases,
                task=task,
                evaluator_resolver=lambda configured: CountCases(),
                configuration=EvaluationRunConfiguration(
                    provider="deterministic", model="fixture"
                ),
            )

        run = ledger.list_evaluation_runs()[0]
        assert [result.execution_disposition.value for result in ledger.list_case_results(run.run_id)] == [
            "completed",
            "pending",
        ]


def test_interrupted_finalization_retains_partial_report_evaluation(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("partial-report")
    suite = suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(name="count-cases", evaluator_revision=1),
                ConfiguredEvaluator(name="case-table", evaluator_revision=1),
            )
        }
    )
    checks = 0

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                CountCases() if configured.name == "count-cases" else CaseTable()
            ),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                CountCases() if configured.name == "count-cases" else CaseTable()
            ),
            should_stop_finalization=should_cancel,
        )

        assert result.run.status == "finalization_pending"
        assert [execution.evaluator_name for execution in result.report_evaluator_executions] == [
            "count-cases"
        ]


def test_controlled_finalization_stop_leaves_run_pending_after_inflight_evaluator(
    tmp_path,
):
    cases, gold_set, base_suite = _lifecycle_fixture("controlled-finalization-stop")
    suite = base_suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(name="count-cases", evaluator_revision=1),
                ConfiguredEvaluator(name="case-table", evaluator_revision=1),
            )
        }
    )
    entered = threading.Event()
    release = threading.Event()
    stop_requested = threading.Event()
    resolver_calls: list[str] = []
    evaluator_calls: list[str] = []
    gate_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                runner.finalize,
                initial.run.run_id,
                schemas=_schemas_for(cases),
                evaluator_resolver=lambda configured: (
                    resolver_calls.append(configured.name)
                    or (
                        BlockingCountCases(entered, release, evaluator_calls)
                        if configured.name == "count-cases"
                        else CaseTable()
                    )
                ),
                should_stop_finalization=stop_requested.is_set,
                release_gates={
                    "policy": lambda result: gate_calls.append("stopped") or True
                },
            )
            assert entered.wait(timeout=5) or future.result(timeout=0)
            stop_requested.set()
            release.set()
            result = future.result(timeout=5)

        assert result.run.status is EvaluationRunStatus.FINALIZATION_PENDING
        assert [execution.evaluator_name for execution in result.report_evaluator_executions] == [
            "count-cases"
        ]
        assert resolver_calls == ["count-cases"]
        assert evaluator_calls == ["count-cases"]
        assert gate_calls == []
        assert result.run.issues == ()
        assert result.run.finalization_claim is None
        assert ledger.get_finalization_claim(initial.run.run_id) is None

        resumed = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                resolver_calls.append(configured.name) or CaseTable()
            ),
            release_gates={
                "policy": lambda result: gate_calls.append("resumed") or True
            },
        )

        assert resumed.run.status is EvaluationRunStatus.COMPLETED
        assert resolver_calls == ["count-cases", "case-table"]
        assert gate_calls == ["resumed"]


def test_controlled_stop_release_failure_preserves_result_and_allows_later_recovery(
    tmp_path, monkeypatch, caplog
):
    cases, gold_set, suite = _lifecycle_fixture("controlled-stop-release-failure")
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite", clock=clock) as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_release = ledger.release_finalization_claim
        release_calls = 0

        def fail_first_release(run_id, claim_id):
            nonlocal release_calls
            release_calls += 1
            if release_calls == 1:
                raise RuntimeError("release persistence failed")
            return original_release(run_id, claim_id)

        monkeypatch.setattr(ledger, "release_finalization_claim", fail_first_release)
        with caplog.at_level(logging.INFO):
            stopped = runner.finalize(
                initial.run.run_id,
                schemas=_schemas_for(cases),
                lease_seconds=1,
                evaluator_resolver=lambda configured: CountCases(),
                should_stop_finalization=lambda: True,
            )

        assert stopped.run.status is EvaluationRunStatus.FINALIZATION_PENDING
        stored_claim = ledger.get_finalization_claim(initial.run.run_id)
        assert stored_claim is not None
        assert any(
            "evaluation_finalization.claim_release_failed" in record.getMessage()
            for record in caplog.records
        )

        clock.current = initial_time + timedelta(seconds=2)
        recovered = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )

        assert recovered.run.status is EvaluationRunStatus.COMPLETED
        assert any(
            issue.category == "finalization_claim_recovered"
            for issue in recovered.run.issues
        )
        assert ledger.get_finalization_claim(initial.run.run_id) is None


def test_release_cleanup_failure_does_not_mask_finalization_error(
    tmp_path, monkeypatch, caplog
):
    cases, gold_set, suite = _lifecycle_fixture("release-failure-existing-error")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        def broken_materialization(run_id, schemas):
            raise RuntimeError("report materialization failed")

        def broken_release(run_id, claim_id):
            raise RuntimeError("release persistence failed")

        monkeypatch.setattr(ledger, "materialize_aggregate_report", broken_materialization)
        monkeypatch.setattr(ledger, "release_finalization_claim", broken_release)

        with caplog.at_level(logging.INFO):
            with pytest.raises(RuntimeError, match="report materialization failed"):
                runner.finalize(
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    evaluator_resolver=lambda configured: CountCases(),
                )

        assert any(
            "evaluation_finalization.claim_release_failed" in record.getMessage()
            for record in caplog.records
        )


def test_incomplete_cases_cannot_freeze_the_aggregate_report(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("freeze-requires-terminal-cases")
    checks = 0

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
            should_cancel=should_cancel,
        )

        assert result.run.status == "cancelled"
        assert ledger.get_frozen_aggregate_manifest_artifact(result.run.run_id) is None
        with pytest.raises(ValueError, match="terminal"):
            EvaluationRunner(ledger).finalize(
                result.run.run_id,
                schemas=_schemas_for(cases),
                evaluator_resolver=lambda configured: CountCases(),
            )


def test_complete_cases_freeze_one_report_and_finalize_explicitly(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("explicit-finalization")
    resolver_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        result = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                resolver_calls.append(configured.name) or CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        assert result.run.status == "finalization_pending"
        assert resolver_calls == []
        artifact = ledger.get_frozen_aggregate_manifest_artifact(result.run.run_id)
        assert artifact is not None
        assert ledger.read_artifact(artifact)
        assert len(ledger.list_artifact_locations(artifact)) == 1

        finalized = runner.finalize(
            result.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                resolver_calls.append(configured.name) or CountCases()
            ),
        )

        assert finalized.run.status == "completed"
        assert resolver_calls == ["count-cases"]
        assert [execution.evaluator_name for execution in finalized.report_evaluator_executions] == [
            "count-cases"
        ]
        assert finalized.run.finalization_claim is None
        assert ledger.get_finalization_claim(finalized.run.run_id) is None


def test_finalization_materializes_typed_report_from_frozen_evidence(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("typed-finalization")
    schemas = SchemaRegistry()
    schemas.register(cases[0].input_schema, Input)
    schemas.register(cases[0].expected_output_schema, Output)
    schemas.register(cases[0].metadata_schema, Metadata)
    reports = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        EvaluationRunner(ledger).finalize(
            initial.run.run_id,
            schemas=schemas,
            evaluator_resolver=lambda configured: CaptureTypedReport(reports),
        )

    assert [case.name for case in reports[0].cases] == ["case-1@1", "case-2@1"]
    assert all(isinstance(case.inputs, Input) for case in reports[0].cases)
    assert all(isinstance(case.expected_output, Output) for case in reports[0].cases)
    assert all(isinstance(case.output, Output) for case in reports[0].cases)
    assert all(isinstance(case.metadata, Metadata) for case in reports[0].cases)


def test_run_with_only_rubric_judged_cases_finalizes_a_well_formed_report(tmp_path):
    authored_cases, gold_set, suite = _lifecycle_fixture("rubric-only")
    cases = tuple(
        EvaluationCase[Input, Output, Metadata](
            identity=case.identity,
            input_schema=case.input_schema,
            metadata_schema=case.metadata_schema,
            task_input=case.task_input,
            metadata=case.metadata,
            description=case.description,
            tags=case.tags,
            requirements=case.requirements,
            artifacts=case.artifacts,
        )
        for case in authored_cases
    )
    gold_set = EvaluationGoldSet.model_validate(
        {
            **gold_set.model_dump(exclude={"content_hash"}),
            "memberships": tuple(
                EvaluationGoldSetMembership(
                    case=EvaluationCaseRevisionReference(
                        record_id=case.identity.record_id,
                        business_id=case.identity.business_id,
                        revision=case.identity.revision,
                        content_hash=case.content_hash,
                    ),
                    split=EvaluationSplit.HELD_OUT,
                )
                for case in cases
            ),
        }
    )
    schemas = SchemaRegistry()
    schemas.register(suite.task_contract.input_schema, Input)
    schemas.register(suite.task_contract.output_schema, Output)
    schemas.register(suite.task_contract.metadata_schema, Metadata)
    reports = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        finalized = runner.finalize(
            initial.run.run_id,
            schemas=schemas,
            evaluator_resolver=lambda configured: CaptureTypedReport(reports),
        )

    assert finalized.run.status == "completed"
    assert [case.name for case in reports[0].cases] == ["case-1@1", "case-2@1"]
    assert all(case.expected_output is None for case in reports[0].cases)
    assert all(isinstance(case.output, Output) for case in reports[0].cases)


def test_one_run_can_finalize_cases_with_and_without_expected_outputs(tmp_path):
    authored_cases, gold_set, suite = _lifecycle_fixture("mixed-expected-outputs")
    unlabeled = EvaluationCase[Input, Output, Metadata](
        identity=authored_cases[1].identity,
        input_schema=authored_cases[1].input_schema,
        metadata_schema=authored_cases[1].metadata_schema,
        task_input=authored_cases[1].task_input,
        metadata=authored_cases[1].metadata,
        description=authored_cases[1].description,
    )
    cases = (authored_cases[0], unlabeled)
    gold_set = EvaluationGoldSet.model_validate(
        {
            **gold_set.model_dump(exclude={"content_hash"}),
            "memberships": tuple(
                EvaluationGoldSetMembership(
                    case=EvaluationCaseRevisionReference(
                        record_id=case.identity.record_id,
                        business_id=case.identity.business_id,
                        revision=case.identity.revision,
                        content_hash=case.content_hash,
                    ),
                    split=EvaluationSplit.HELD_OUT,
                )
                for case in cases
            ),
        }
    )
    schemas = SchemaRegistry()
    schemas.register(suite.task_contract.input_schema, Input)
    schemas.register(suite.task_contract.output_schema, Output)
    schemas.register(suite.task_contract.metadata_schema, Metadata)
    reports = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(
                answer=task_input.prompt.replace("prompt", "answer")
            ),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        finalized = runner.finalize(
            initial.run.run_id,
            schemas=schemas,
            evaluator_resolver=lambda configured: CaptureTypedReport(reports),
        )

    assert finalized.run.status == "completed"
    assert len(reports[0].cases) == 2
    assert reports[0].cases[0].expected_output == Output(answer="answer-1")
    assert reports[0].cases[1].expected_output is None
    assert [case.output for case in reports[0].cases] == [
        Output(answer="answer-1"),
        Output(answer="answer-2"),
    ]


def test_finalization_rejects_unresolved_frozen_schemas_before_evaluating(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("unresolved-finalization-schema")
    resolver_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        with pytest.raises(ValueError, match="schema is not allowlisted"):
            EvaluationRunner(ledger).finalize(
                initial.run.run_id,
                schemas=SchemaRegistry(),
                evaluator_resolver=lambda configured: (
                    resolver_calls.append(configured.name) or CountCases()
                ),
            )

        assert resolver_calls == []
        assert ledger.get_finalization_claim(initial.run.run_id) is None


def test_finalization_rejects_a_tampered_frozen_case_definition(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("tampered-frozen-case")
    resolver_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        record_id = initial.manifest[0].case.record_id
        row = ledger._connection.execute(
            "SELECT definition_json FROM evaluation_definition_revisions WHERE record_id = ?",
            (str(record_id),),
        ).fetchone()
        payload = json.loads(row["definition_json"])
        payload["task_input"]["prompt"] = "tampered"
        ledger._connection.execute(
            "DROP TRIGGER evaluation_definition_revisions_immutable_update"
        )
        ledger._connection.execute(
            "UPDATE evaluation_definition_revisions SET definition_json = ? WHERE record_id = ?",
            (json.dumps(payload), str(record_id)),
        )
        ledger._connection.commit()

        with pytest.raises(ValueError, match="case definition fingerprint"):
            EvaluationRunner(ledger).finalize(
                initial.run.run_id,
                schemas=_schemas_for(cases),
                evaluator_resolver=lambda configured: (
                    resolver_calls.append(configured.name) or CountCases()
                ),
            )

        assert resolver_calls == []


def test_finalization_rejects_an_unsupported_evidence_contract(tmp_path, monkeypatch):
    cases, gold_set, suite = _lifecycle_fixture("unsupported-evidence-contract")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        artifact = ledger.get_frozen_aggregate_manifest_artifact(initial.run.run_id)
        payload = json.loads(ledger.read_artifact(artifact))
        payload["evidence_contract_version"] = 999
        unsupported = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode()
        monkeypatch.setattr(ledger, "read_artifact", lambda ignored: unsupported)
        monkeypatch.setattr(
            ledger,
            "get_frozen_aggregate_manifest_artifact",
            lambda ignored: artifact.model_copy(
                update={"content_hash": hashlib.sha256(unsupported).hexdigest()}
            ),
        )

        with pytest.raises(ValueError, match="unsupported evidence-contract version: 999"):
            EvaluationRunner(ledger).finalize(
                initial.run.run_id,
                schemas=_schemas_for(cases),
                evaluator_resolver=lambda configured: CountCases(),
            )


def test_completed_cases_freeze_an_ordered_content_addressed_aggregate_manifest(
    tmp_path,
):
    cases, gold_set, suite = _lifecycle_fixture("aggregate-manifest")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        artifact = ledger.get_frozen_aggregate_manifest_artifact(result.run.run_id)
        assert artifact is not None
        assert artifact.kind == "frozen-aggregate-manifest"
        payload = json.loads(ledger.read_artifact(artifact))
        assert payload["run_id"] == str(result.run.run_id)
        assert [entry["manifest_entry_id"] for entry in payload["cases"]] == [
            str(entry.manifest_id) for entry in result.manifest
        ]
        assert [entry["case_result_id"] for entry in payload["cases"]] == [
            str(case_result.result_id) for case_result in result.case_results
        ]
        assert payload["evidence_contract_version"] == 1
        forbidden = {
            "inputs",
            "expected_output",
            "output",
            "metadata",
            "scores",
            "labels",
            "assertions",
        }
        assert forbidden.isdisjoint(str(key) for key in _nested_keys(payload))


def _nested_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _nested_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nested_keys(item)


def test_aggregate_manifest_freeze_is_idempotent_and_rejects_replacement(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("aggregate-manifest-replay")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original = ledger.get_frozen_aggregate_manifest_artifact(result.run.run_id)

        replay = ledger.freeze_aggregate_manifest(result.run.run_id)
        assert replay == original

        with pytest.raises(ValueError, match="different composition"):
            ledger.freeze_aggregate_manifest(
                result.run.run_id,
                report_provenance={"trace_id": "replacement"},
            )


def test_finalization_rejects_a_tampered_frozen_aggregate_manifest(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("aggregate-manifest-tamper")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        artifact = ledger.get_frozen_aggregate_manifest_artifact(result.run.run_id)
        assert artifact is not None
        location = ledger.list_artifact_locations(artifact)[0]
        with open(location.uri, "ab") as manifest_file:
            manifest_file.write(b" ")

        with pytest.raises(ValueError, match="artifact identity"):
            EvaluationRunner(ledger).finalize(
                result.run.run_id,
                schemas=_schemas_for(cases),
                evaluator_resolver=lambda configured: CountCases(),
            )
def test_finalization_claim_allows_one_live_owner_and_exposes_expiry(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("finalization-claim")
    database = tmp_path / "evaluation.sqlite"
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(database, clock=clock) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        with SQLiteEvaluationLedger(database, clock=clock) as competing_ledger:
            first_claim = first_ledger.acquire_finalization_claim(
                initial.run.run_id,
                owner_id="worker-a",
                lease_seconds=60,
            )
            second_claim = competing_ledger.acquire_finalization_claim(
                initial.run.run_id,
                owner_id="worker-b",
                lease_seconds=60,
            )

            assert first_claim.owner_id == "worker-a"
            assert first_claim.acquired_at == clock.current
            assert first_claim.expires_at == clock.current + timedelta(seconds=60)
            assert second_claim is None
            assert competing_ledger.get_finalization_claim(initial.run.run_id) == first_claim


def test_finalization_authority_uses_one_shared_ledger_clock(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("ledger-clock")
    database = tmp_path / "evaluation.sqlite"
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(database, clock=clock) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        with SQLiteEvaluationLedger(database, clock=clock) as second_ledger:
            claim = first_ledger.acquire_finalization_claim(
                initial.run.run_id,
                owner_id="worker-a",
                lease_seconds=10,
            )
            assert claim is not None
            assert claim.acquired_at == clock.current

            clock.current += timedelta(seconds=11)

            assert first_ledger.owns_finalization_claim(
                initial.run.run_id, claim.claim_id
            ) is False
            replacement = second_ledger.acquire_finalization_claim(
                initial.run.run_id,
                owner_id="worker-b",
                lease_seconds=10,
            )

            assert replacement is not None
            assert replacement.acquired_at == clock.current


def test_replacing_expired_finalization_claim_records_factual_recovery_issue(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("finalization-claim-recovery-issue")
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite", clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        prior_claim = ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-a",
            lease_seconds=10,
        )
        assert prior_claim is not None

        clock.current = prior_claim.expires_at + timedelta(seconds=1)
        recovery_time = clock.current
        successor_claim = ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-b",
            lease_seconds=10,
        )
        assert successor_claim is not None

        recovered = ledger.get_evaluation_run(initial.run.run_id)
        assert recovered is not None
        assert len(recovered.issues) == 1
        issue = recovered.issues[0]
        assert issue.category == "finalization_claim_recovered"
        assert issue.subject == f"claim:{prior_claim.claim_id}"
        assert json.loads(issue.message) == {
            "prior_claim_id": str(prior_claim.claim_id),
            "prior_owner_id": prior_claim.owner_id,
            "prior_acquired_at": prior_claim.acquired_at.isoformat(),
            "prior_expires_at": prior_claim.expires_at.isoformat(),
            "successor_owner_id": successor_claim.owner_id,
            "recovered_at": recovery_time.isoformat(),
        }


def test_ordinary_finalization_claim_acquisition_records_no_recovery_issue(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("ordinary-finalization-claim")
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite", clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        claim = ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-a",
            lease_seconds=10,
        )
        assert claim is not None

        acquired = ledger.get_evaluation_run(initial.run.run_id)
        assert acquired is not None
        assert acquired.issues == ()


def test_rejected_competing_finalization_claim_acquisition_records_no_recovery_issue(
    tmp_path,
):
    cases, gold_set, suite = _lifecycle_fixture("competing-finalization-claim")
    database = tmp_path / "evaluation.sqlite"
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(database, clock=clock) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        first_claim = first_ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-a",
            lease_seconds=10,
        )
        assert first_claim is not None

        with SQLiteEvaluationLedger(database, clock=clock) as second_ledger:
            assert (
                second_ledger.acquire_finalization_claim(
                    initial.run.run_id,
                    owner_id="worker-b",
                    lease_seconds=10,
                )
                is None
            )
            rejected = second_ledger.get_evaluation_run(initial.run.run_id)
            assert rejected is not None
            assert rejected.issues == ()


def test_report_checkpoint_samples_time_after_obtaining_the_write_position(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("checkpoint-write-position")
    database = tmp_path / "evaluation.sqlite"
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(database, clock=clock) as claim_ledger:
        initial = _run(EvaluationRunner(claim_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = claim_ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-a",
            lease_seconds=10,
        )
        assert claim is not None

        configured = suite.report_evaluators[0]
        execution = ReportEvaluatorExecution(
            run_id=initial.run.run_id,
            evaluator_name=configured.name,
            evaluator_revision=configured.evaluator_revision,
            configuration_fingerprint=configured.configuration_fingerprint,
            status=EvaluationProducerStatus.COMPLETED,
            duration_seconds=0,
        )

        with SQLiteEvaluationLedger(database, clock=clock) as waiting_ledger:
            write_attempted = threading.Event()
            waiting_ledger._connection.set_trace_callback(
                lambda statement: (
                    write_attempted.set()
                    if statement == "BEGIN IMMEDIATE"
                    else None
                )
            )
            blocker = sqlite3.connect(database)
            try:
                blocker.execute("BEGIN IMMEDIATE")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    checkpoint = executor.submit(
                        waiting_ledger.record_report_evaluation,
                        [execution],
                        [],
                        finalization_claim_id=claim.claim_id,
                    )
                    assert write_attempted.wait(timeout=5)

                    clock.current = claim.expires_at
                    blocker.commit()

                    with pytest.raises(RuntimeError, match="live finalization claim"):
                        checkpoint.result(timeout=5)
            finally:
                blocker.close()

            assert waiting_ledger.list_report_evaluator_executions(
                initial.run.run_id
            ) == []


def test_report_checkpoint_replay_is_one_atomic_idempotent_success(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("report-checkpoint-replay")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = ledger.acquire_finalization_claim(
            initial.run.run_id, owner_id="worker-a"
        )
        assert claim is not None
        execution = ReportEvaluatorExecution(
            run_id=initial.run.run_id,
            evaluator_name="count-cases",
            evaluator_revision=1,
            configuration_fingerprint="a" * 64,
            status=EvaluationProducerStatus.COMPLETED,
            duration_seconds=0.25,
        )
        issues = (
            EvaluationRunIssue(
                category="missing_metric",
                subject="report:count-cases",
                message="required metric was not produced",
            ),
        )

        ledger.record_report_evaluation(
            [execution], [], issues=issues, finalization_claim_id=claim.claim_id
        )
        ledger.record_report_evaluation(
            [execution], [], issues=issues, finalization_claim_id=claim.claim_id
        )

        assert ledger.list_report_evaluator_executions(initial.run.run_id) == [
            execution
        ]
        assert ledger.get_evaluation_run(initial.run.run_id).issues == issues


def test_finalization_retries_report_checkpoint_without_reevaluating(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("report-checkpoint-retry")
    evaluator_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_record = ledger.record_report_evaluation
        checkpoint_attempts = 0

        def contended_once(*args, **kwargs):
            nonlocal checkpoint_attempts
            checkpoint_attempts += 1
            if checkpoint_attempts == 1:
                raise sqlite3.OperationalError("database is locked")
            return original_record(*args, **kwargs)

        monkeypatch.setattr(ledger, "record_report_evaluation", contended_once)
        completed = EvaluationRunner(ledger).finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                evaluator_calls.append(configured.name) or CountCases()
            ),
        )

        assert completed.run.status is EvaluationRunStatus.COMPLETED
        assert checkpoint_attempts == 2
        assert evaluator_calls == ["count-cases"]
        assert len(completed.report_evaluator_executions) == 1


def test_finalization_replays_an_ambiguously_acknowledged_checkpoint(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("ambiguous-report-checkpoint")
    evaluator_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_record = ledger.record_report_evaluation
        checkpoint_attempts = 0

        def commit_then_report_contention(*args, **kwargs):
            nonlocal checkpoint_attempts
            checkpoint_attempts += 1
            result = original_record(*args, **kwargs)
            if checkpoint_attempts == 1:
                raise sqlite3.OperationalError("database is locked")
            return result

        monkeypatch.setattr(
            ledger, "record_report_evaluation", commit_then_report_contention
        )
        completed = EvaluationRunner(ledger).finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                evaluator_calls.append(configured.name) or CountCases()
            ),
        )

        assert completed.run.status is EvaluationRunStatus.COMPLETED
        assert checkpoint_attempts == 2
        assert evaluator_calls == ["count-cases"]
        assert len(completed.report_evaluator_executions) == 1


def test_finalization_retries_completion_after_ambiguous_commit(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("ambiguous-completion")
    evaluator_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_complete = ledger.complete_evaluation_run
        completion_attempts = 0

        def commit_then_report_contention(*args, **kwargs):
            nonlocal completion_attempts
            completion_attempts += 1
            result = original_complete(*args, **kwargs)
            if completion_attempts == 1:
                raise sqlite3.OperationalError("database is locked")
            return result

        monkeypatch.setattr(
            ledger, "complete_evaluation_run", commit_then_report_contention
        )
        completed = EvaluationRunner(ledger).finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                evaluator_calls.append(configured.name) or CountCases()
            ),
        )

        assert completed.run.status is EvaluationRunStatus.COMPLETED
        assert completion_attempts == 1
        assert evaluator_calls == ["count-cases"]


def test_report_checkpoint_rejects_conflicting_execution_replay_atomically(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("conflicting-report-execution")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = ledger.acquire_finalization_claim(
            initial.run.run_id, owner_id="worker-a"
        )
        assert claim is not None
        execution = ReportEvaluatorExecution(
            run_id=initial.run.run_id,
            evaluator_name="count-cases",
            evaluator_revision=1,
            configuration_fingerprint="a" * 64,
            status=EvaluationProducerStatus.COMPLETED,
            duration_seconds=0.25,
        )
        ledger.record_report_evaluation(
            [execution], [], finalization_claim_id=claim.claim_id
        )
        conflicting = execution.model_copy(
            update={
                "execution_id": UUID(int=execution.execution_id.int + 1),
                "duration_seconds": 0.5,
            }
        )

        with pytest.raises(ValueError, match="conflicts with existing execution identity"):
            ledger.record_report_evaluation(
                [conflicting], [], finalization_claim_id=claim.claim_id
            )

        assert ledger.list_report_evaluator_executions(initial.run.run_id) == [
            execution
        ]


def test_report_checkpoint_rejects_conflicting_observation_replay_atomically(
    tmp_path,
):
    cases, gold_set, suite = _lifecycle_fixture("conflicting-report-observation")
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.count",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.INTEGER,
        semantic_description="The number of evaluated cases.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(
                    name="count-cases",
                    evaluator_revision=1,
                    metrics=(EvaluationMetricReference.from_definition(metric),),
                ),
            ),
            "metrics": (metric,),
        }
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = ledger.acquire_finalization_claim(
            initial.run.run_id, owner_id="worker-a"
        )
        assert claim is not None
        execution = ReportEvaluatorExecution(
            run_id=initial.run.run_id,
            evaluator_name="count-cases",
            evaluator_revision=1,
            configuration_fingerprint="a" * 64,
            status=EvaluationProducerStatus.COMPLETED,
            duration_seconds=0.25,
        )
        observation = RunMetricObservation(
            report_evaluator_execution_id=execution.execution_id,
            metric=EvaluationMetricReference(
                namespaced_name="tests.count", evaluator_revision=1
            ),
            integer_value=1,
        )
        ledger.record_report_evaluation(
            [execution], [observation], finalization_claim_id=claim.claim_id
        )
        conflicting = observation.model_copy(update={"integer_value": 2})

        with pytest.raises(ValueError, match="conflicts with existing observation"):
            ledger.record_report_evaluation(
                [execution], [conflicting], finalization_claim_id=claim.claim_id
            )

        assert ledger.list_run_metric_observations(initial.run.run_id) == [
            observation
        ]


def test_case_metric_observation_cannot_be_written_through_a_different_case_result(
    tmp_path,
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending = _resolved_run_creation_inputs(
            ledger, "producer-owned-case-observation"
        )
        ledger.create_evaluation_run(run, plan, manifest, pending)
        metric = EvaluationMetricDefinition(
            namespaced_name="tests.producer-owned-case",
            evaluator_revision=1,
            value_type=EvaluationMetricValueType.INTEGER,
            semantic_description="A producer-owned case metric.",
            comparison_operation=NoComparisonOperation(
                namespaced_name="tests.comparison.none", revision=1
            ),
        )
        ledger.import_metric_definition(metric)
        execution = CaseEvaluatorExecution(
            case_result_id=pending[0].result_id,
            evaluator_name="case-evaluator",
            evaluator_revision=1,
            configuration_fingerprint="a" * 64,
            status=EvaluationProducerStatus.COMPLETED,
            duration_seconds=0.1,
        )
        observation = CaseMetricObservation(
            case_evaluator_execution_id=execution.execution_id,
            metric=EvaluationMetricReference.from_definition(metric),
            integer_value=1,
        )
        first_result = pending[0].model_copy(
            update={
                "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                "task_outcome": TaskSuccess(output=Output(answer="answer-1")),
            }
        )
        second_result = pending[1].model_copy(
            update={
                "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                "task_outcome": TaskSuccess(output=Output(answer="answer-2")),
            }
        )
        ledger.record_case_evaluation(first_result, [execution], [observation])

        with pytest.raises(ValueError, match="different case result"):
            ledger.record_case_evaluation(second_result, [], [observation])

        assert ledger.list_case_metric_observations(first_result.result_id) == [
            observation
        ]
        assert ledger.list_case_metric_observations(second_result.result_id) == []


def test_run_metric_observations_can_be_compared_across_runs_by_canonical_metric(
    tmp_path,
):
    cases, gold_set, base_suite = _lifecycle_fixture("comparable-run-metrics")
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.comparable-count",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.INTEGER,
        semantic_description="The number of evaluated cases.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = base_suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(
                    name="count-cases",
                    evaluator_revision=1,
                    metrics=(EvaluationMetricReference.from_definition(metric),),
                ),
            ),
            "metrics": (metric,),
        }
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        configuration = EvaluationRunConfiguration(
            provider="deterministic", model="fixture"
        )
        first = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=configuration,
        )
        second = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=configuration,
        )
        first = runner.finalize(
            first.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )
        second = runner.finalize(
            second.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )

        comparable = ledger.list_metric_observations_across_runs(
            EvaluationMetricReference.from_definition(metric)
        )

        assert comparable == [first.run_observations[0], second.run_observations[0]]
        assert {
            observation.report_evaluator_execution_id
            for observation in comparable
        } == {
            first.run_observations[0].report_evaluator_execution_id,
            second.run_observations[0].report_evaluator_execution_id,
        }


def test_run_metric_observation_cannot_be_written_through_a_different_run(
    tmp_path,
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        first_run, first_plan, first_manifest, first_pending = (
            _resolved_run_creation_inputs(ledger, "producer-owned-first-run")
        )
        second_run_id = UUID(int=first_run.run_id.int + 1)
        second_run = first_run.model_copy(update={"run_id": second_run_id})
        second_manifest = tuple(
            entry.model_copy(
                update={
                    "manifest_id": UUID(int=entry.manifest_id.int + 1),
                    "run_id": second_run_id,
                }
            )
            for entry in first_manifest
        )
        second_pending = tuple(
            result.model_copy(
                update={
                    "result_id": UUID(int=result.result_id.int + 1),
                    "run_id": second_run_id,
                    "manifest_id": entry.manifest_id,
                }
            )
            for result, entry in zip(first_pending, second_manifest)
        )
        ledger.create_evaluation_run(
            first_run, first_plan, first_manifest, first_pending
        )
        ledger.create_evaluation_run(
            second_run, first_plan, second_manifest, second_pending
        )
        metric = EvaluationMetricDefinition(
            namespaced_name="tests.producer-owned-run",
            evaluator_revision=1,
            value_type=EvaluationMetricValueType.INTEGER,
            semantic_description="A producer-owned run metric.",
            comparison_operation=NoComparisonOperation(
                namespaced_name="tests.comparison.none", revision=1
            ),
        )
        ledger.import_metric_definition(metric)
        first_execution = ReportEvaluatorExecution(
            run_id=first_run.run_id,
            evaluator_name="report-evaluator",
            evaluator_revision=1,
            configuration_fingerprint="a" * 64,
            status=EvaluationProducerStatus.COMPLETED,
            duration_seconds=0.1,
        )
        observation = RunMetricObservation(
            report_evaluator_execution_id=first_execution.execution_id,
            metric=EvaluationMetricReference.from_definition(metric),
            integer_value=1,
        )
        ledger.record_report_evaluation([first_execution], [observation])

        second_execution = ReportEvaluatorExecution(
            run_id=second_run.run_id,
            evaluator_name="report-evaluator",
            evaluator_revision=1,
            configuration_fingerprint="b" * 64,
            status=EvaluationProducerStatus.COMPLETED,
            duration_seconds=0.1,
        )
        with pytest.raises(ValueError, match="different Evaluation Run"):
            ledger.record_report_evaluation([second_execution], [observation])

        assert ledger.list_run_metric_observations(first_run.run_id) == [
            observation
        ]
        assert ledger.list_run_metric_observations(second_run.run_id) == []


def test_report_checkpoint_retry_stops_at_confirmed_claim_expiry(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("report-checkpoint-retry-expiry")
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)
    evaluator_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite", clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        checkpoint_attempts = 0

        def permanently_contended(*args, **kwargs):
            nonlocal checkpoint_attempts
            checkpoint_attempts += 1
            clock.current = initial_time + timedelta(seconds=1)
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(ledger, "record_report_evaluation", permanently_contended)

        with pytest.raises(FinalizationClaimLostError) as lost:
            EvaluationRunner(ledger).finalize(
                initial.run.run_id,
                schemas=_schemas_for(cases),
                worker_id="worker-a",
                lease_seconds=1,
                evaluator_resolver=lambda configured: (
                    evaluator_calls.append(configured.name) or CountCases()
                ),
            )

        assert lost.value.loss_classification == "claim_expired"
        assert lost.value.last_confirmed_expiry == initial_time + timedelta(seconds=1)
        assert checkpoint_attempts == 1
        assert evaluator_calls == ["count-cases"]
        assert ledger.list_report_evaluator_executions(initial.run.run_id) == []
        pending = ledger.get_evaluation_run(initial.run.run_id)
        assert pending is not None
        assert pending.status is EvaluationRunStatus.FINALIZATION_PENDING


def test_report_checkpoint_does_not_retry_non_retryable_persistence_defect(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("report-checkpoint-non-retryable")
    evaluator_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        checkpoint_attempts = 0

        def invalid_persistence(*args, **kwargs):
            nonlocal checkpoint_attempts
            checkpoint_attempts += 1
            raise sqlite3.IntegrityError("constraint failed")

        monkeypatch.setattr(ledger, "record_report_evaluation", invalid_persistence)

        with pytest.raises(sqlite3.IntegrityError, match="constraint failed"):
            EvaluationRunner(ledger).finalize(
                initial.run.run_id,
                schemas=_schemas_for(cases),
                evaluator_resolver=lambda configured: (
                    evaluator_calls.append(configured.name) or CountCases()
                ),
            )

        assert checkpoint_attempts == 1
        assert evaluator_calls == ["count-cases"]
        assert ledger.list_report_evaluator_executions(initial.run.run_id) == []


def test_finalization_claim_renews_from_ledger_time_without_changing_identity(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("renew-finalization-claim")
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite", clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-a",
            lease_seconds=10,
        )
        assert claim is not None

        clock.current += timedelta(seconds=5)
        renewed = ledger.renew_finalization_claim(
            initial.run.run_id,
            claim.claim_id,
            lease_seconds=10,
        )

        assert renewed is not None
        assert renewed.claim_id == claim.claim_id
        assert renewed.owner_id == claim.owner_id
        assert renewed.acquired_at == claim.acquired_at
        assert renewed.expires_at == clock.current + timedelta(seconds=10)
        assert ledger.get_finalization_claim(initial.run.run_id) == renewed


def test_finalization_claim_renewal_rejects_wrong_released_and_expired_claims(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("renew-finalization-claim-rejections")
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite", clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-a",
            lease_seconds=10,
        )
        assert claim is not None

        assert ledger.renew_finalization_claim(
            initial.run.run_id, UUID(int=claim.claim_id.int + 1)
        ) is None

        clock.current = claim.expires_at
        replacement = ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-b",
            lease_seconds=10,
        )
        assert replacement is not None
        assert ledger.renew_finalization_claim(
            initial.run.run_id, claim.claim_id
        ) is None

        assert ledger.release_finalization_claim(
            initial.run.run_id, replacement.claim_id
        )
        assert ledger.renew_finalization_claim(
            initial.run.run_id, replacement.claim_id
        ) is None

        replacement = ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="worker-c",
            lease_seconds=10,
        )
        assert replacement is not None
        clock.current = replacement.expires_at
        assert ledger.renew_finalization_claim(
            initial.run.run_id, replacement.claim_id
        ) is None


def test_finalize_refuses_a_live_claim_before_resolving_report_evaluators(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("finalization-claim-guard")
    database = tmp_path / "evaluation.sqlite"

    with SQLiteEvaluationLedger(database) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = first_ledger.acquire_finalization_claim(
            initial.run.run_id, owner_id="worker-a"
        )
        assert claim is not None

        with SQLiteEvaluationLedger(database) as competing_ledger:
            resolver_calls: list[str] = []
            with pytest.raises(RuntimeError, match="finalization claim"):
                EvaluationRunner(competing_ledger).finalize(
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-b",
                    evaluator_resolver=lambda configured: (
                        resolver_calls.append(configured.name) or CountCases()
                    ),
                )

            assert resolver_calls == []
            assert competing_ledger.get_finalization_claim(initial.run.run_id) == claim


def test_finalization_resumes_missing_report_work_and_skips_failed_terminal_work(
    tmp_path,
):
    cases, gold_set, base_suite = _lifecycle_fixture("resume-finalization")
    suite = base_suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(name="count-cases", evaluator_revision=1),
                ConfiguredEvaluator(name="case-table", evaluator_revision=1),
            )
        }
    )
    checks = 0
    first_finalizer_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        def stop_after_one() -> bool:
            nonlocal checks
            checks += 1
            return checks == 2

        partial = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                first_finalizer_calls.append(configured.name)
                or (_ for _ in ()).throw(RuntimeError("missing evaluator"))
                if configured.name == "count-cases"
                else CaseTable()
            ),
            should_stop_finalization=stop_after_one,
        )

        assert partial.run.status == "finalization_pending"
        assert first_finalizer_calls == ["count-cases"]
        assert [execution.status.value for execution in partial.report_evaluator_executions] == [
            "failed"
        ]
        assert partial.run.finalization_claim is None
        assert ledger.get_finalization_claim(initial.run.run_id) is None

        second_finalizer_calls: list[str] = []
        completed = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                second_finalizer_calls.append(configured.name)
                or CaseTable()
            ),
        )

        assert completed.run.status == "completed"
        assert second_finalizer_calls == ["case-table"]
        assert [execution.status.value for execution in completed.report_evaluator_executions] == [
            "failed",
            "completed",
        ]

        calls_before_idempotent = list(second_finalizer_calls)
        repeated = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                second_finalizer_calls.append(configured.name) or CaseTable()
            ),
        )
        assert repeated.run.status == "completed"
        assert second_finalizer_calls == calls_before_idempotent


def test_expired_finalization_claim_recovers_only_missing_report_work(tmp_path):
    cases, gold_set, base_suite = _lifecycle_fixture("expired-finalization-claim")
    suite = base_suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(name="count-cases", evaluator_revision=1),
                ConfiguredEvaluator(name="case-table", evaluator_revision=1),
            )
        }
    )
    checks = 0
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite", clock=clock) as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        def stop_after_one() -> bool:
            nonlocal checks
            checks += 1
            return checks == 2

        partial = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                (_ for _ in ()).throw(RuntimeError("report evaluator failed"))
                if configured.name == "count-cases"
                else CaseTable()
            ),
            should_stop_finalization=stop_after_one,
            worker_id="worker-a",
        )
        assert partial.run.status.value == "finalization_pending"
        assert [execution.evaluator_name for execution in partial.report_evaluator_executions] == [
            "count-cases"
        ]
        assert partial.report_evaluator_executions[0].status == EvaluationProducerStatus.FAILED

        stale_claim = ledger.acquire_finalization_claim(
            initial.run.run_id,
            owner_id="crashed-worker",
            lease_seconds=1,
        )
        assert stale_claim is not None
        clock.current += timedelta(seconds=2)

        recovery_calls: list[str] = []
        recovered = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                recovery_calls.append(configured.name) or CaseTable()
            ),
            worker_id="recovery-worker",
        )

        assert recovered.run.status.value == "completed"
        assert recovery_calls == ["case-table"]
        assert [execution.status for execution in recovered.report_evaluator_executions] == [
            EvaluationProducerStatus.FAILED,
            EvaluationProducerStatus.COMPLETED,
        ]
        assert ledger.release_finalization_claim(
            initial.run.run_id, stale_claim.claim_id
        ) is False


def test_competing_finalizers_have_one_active_worker_and_one_report_execution(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("concurrent-finalization-claim")
    database = tmp_path / "evaluation.sqlite"
    entered = threading.Event()
    release = threading.Event()
    evaluator_calls: list[str] = []

    with SQLiteEvaluationLedger(database) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        with SQLiteEvaluationLedger(database) as second_ledger:
            blocking = BlockingCountCases(entered, release, evaluator_calls)
            second_resolver_calls: list[str] = []
            with ThreadPoolExecutor(max_workers=2) as workers:
                first_future = workers.submit(
                    EvaluationRunner(first_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-a",
                    evaluator_resolver=lambda configured: blocking,
                )
                assert entered.wait(timeout=5)

                with pytest.raises(RuntimeError, match="live finalization claim"):
                    EvaluationRunner(second_ledger).finalize(
                        initial.run.run_id,
                        schemas=_schemas_for(cases),
                        worker_id="worker-b",
                        evaluator_resolver=lambda configured: (
                            second_resolver_calls.append(configured.name) or CountCases()
                        ),
                    )

                release.set()
                completed = first_future.result(timeout=5)

            assert completed.run.status.value == "completed"
            assert evaluator_calls == ["count-cases"]
            assert second_resolver_calls == []
            assert len(completed.report_evaluator_executions) == 1


def test_stale_finalizer_discards_inflight_result_and_raises_typed_claim_loss(
    tmp_path, monkeypatch
):
    cases, gold_set, base_suite = _lifecycle_fixture("stale-finalizer-claim-loss")
    suite = base_suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(name="count-cases", evaluator_revision=1),
                ConfiguredEvaluator(name="case-table", evaluator_revision=1),
            )
        }
    )
    database = tmp_path / "evaluation.sqlite"
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)
    renewal_started = threading.Event()
    allow_renewal = threading.Event()
    entered_a = threading.Event()
    release_a = threading.Event()
    entered_b = threading.Event()
    release_b = threading.Event()
    calls_a: list[str] = []
    calls_b: list[str] = []
    gate_calls: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_renew = first_ledger.renew_finalization_claim

        def paused_renewal(run_id, claim_id, *, lease_seconds=300.0):
            renewal_started.set()
            assert allow_renewal.wait(timeout=5)
            return original_renew(run_id, claim_id, lease_seconds=lease_seconds)

        monkeypatch.setattr(first_ledger, "renew_finalization_claim", paused_renewal)

        with SQLiteEvaluationLedger(database, clock=clock) as second_ledger:
            evaluator_a = BlockingCountCases(entered_a, release_a, calls_a)
            evaluator_b = BlockingCountCases(entered_b, release_b, calls_b)
            with ThreadPoolExecutor(max_workers=2) as workers:
                stale_future = workers.submit(
                    EvaluationRunner(first_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-a",
                    lease_seconds=1,
                    evaluator_resolver=lambda configured: evaluator_a,
                    release_gates={
                        "policy": lambda result: gate_calls.append("worker-a") or True
                    },
                )
                assert renewal_started.wait(timeout=5)
                assert entered_a.wait(timeout=5)

                clock.current = initial_time + timedelta(seconds=2)
                recovery_future = workers.submit(
                    EvaluationRunner(second_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-b",
                    lease_seconds=10,
                    evaluator_resolver=lambda configured: evaluator_b,
                    release_gates={
                        "policy": lambda result: gate_calls.append("worker-b") or True
                    },
                )
                assert entered_b.wait(timeout=5)

                allow_renewal.set()
                release_a.set()
                with pytest.raises(FinalizationClaimLostError) as lost:
                    stale_future.result(timeout=5)

                release_b.set()
                recovered = recovery_future.result(timeout=5)

            assert lost.value.run_id == initial.run.run_id
            assert lost.value.owner_id == "worker-a"
            assert lost.value.last_confirmed_expiry == initial_time + timedelta(seconds=1)
            assert lost.value.loss_classification
            assert calls_a == ["count-cases"]
            assert calls_b == ["count-cases", "case-table"]
            assert gate_calls == ["worker-b"]
            assert recovered.run.status is EvaluationRunStatus.COMPLETED
            assert len(recovered.report_evaluator_executions) == 2
            assert all(
                execution.status is EvaluationProducerStatus.COMPLETED
                for execution in recovered.report_evaluator_executions
            )
            assert all(issue.category != "finalization_claim_lost" for issue in recovered.run.issues)


def test_recovery_worker_alone_persists_one_terminal_execution_after_claim_loss(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("single-terminal-after-claim-loss")
    database = tmp_path / "evaluation.sqlite"
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)
    renewal_started = threading.Event()
    allow_renewal = threading.Event()
    entered_a = threading.Event()
    release_a = threading.Event()
    entered_b = threading.Event()
    release_b = threading.Event()
    calls_a: list[str] = []
    calls_b: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_renew = first_ledger.renew_finalization_claim

        def paused_renewal(run_id, claim_id, *, lease_seconds=300.0):
            renewal_started.set()
            assert allow_renewal.wait(timeout=5)
            return original_renew(run_id, claim_id, lease_seconds=lease_seconds)

        monkeypatch.setattr(first_ledger, "renew_finalization_claim", paused_renewal)

        with SQLiteEvaluationLedger(database, clock=clock) as second_ledger:
            evaluator_a = BlockingCountCases(entered_a, release_a, calls_a)
            evaluator_b = BlockingCountCases(entered_b, release_b, calls_b)
            with ThreadPoolExecutor(max_workers=2) as workers:
                stale_future = workers.submit(
                    EvaluationRunner(first_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-a",
                    lease_seconds=1,
                    evaluator_resolver=lambda configured: evaluator_a,
                )
                assert renewal_started.wait(timeout=5)
                assert entered_a.wait(timeout=5)

                clock.current = initial_time + timedelta(seconds=2)
                recovery_future = workers.submit(
                    EvaluationRunner(second_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-b",
                    lease_seconds=10,
                    evaluator_resolver=lambda configured: evaluator_b,
                )
                assert entered_b.wait(timeout=5)

                allow_renewal.set()
                release_a.set()
                with pytest.raises(FinalizationClaimLostError):
                    stale_future.result(timeout=5)

                release_b.set()
                recovered = recovery_future.result(timeout=5)

            assert calls_a == ["count-cases"]
            assert calls_b == ["count-cases"]
            assert recovered.run.status is EvaluationRunStatus.COMPLETED
            assert len(recovered.report_evaluator_executions) == 1
            assert recovered.report_evaluator_executions[0].status is EvaluationProducerStatus.COMPLETED


def test_claim_loss_during_release_gate_discards_gate_outcomes(tmp_path, monkeypatch):
    cases, gold_set, suite = _lifecycle_fixture("stale-finalizer-gate-loss")
    database = tmp_path / "evaluation.sqlite"
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)
    renewal_started = threading.Event()
    allow_renewal = threading.Event()
    gate_entered = threading.Event()
    release_gate = threading.Event()
    gate_calls: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_renew = first_ledger.renew_finalization_claim

        def paused_renewal(run_id, claim_id, *, lease_seconds=300.0):
            renewal_started.set()
            assert allow_renewal.wait(timeout=5)
            return original_renew(run_id, claim_id, lease_seconds=lease_seconds)

        monkeypatch.setattr(first_ledger, "renew_finalization_claim", paused_renewal)

        def stale_gate(result):
            gate_calls.append("worker-a")
            gate_entered.set()
            assert release_gate.wait(timeout=5)
            return True

        with SQLiteEvaluationLedger(database, clock=clock) as second_ledger:
            with ThreadPoolExecutor(max_workers=2) as workers:
                stale_future = workers.submit(
                    EvaluationRunner(first_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-a",
                    lease_seconds=1,
                    evaluator_resolver=lambda configured: CountCases(),
                    release_gates={"policy": stale_gate},
                )
                assert renewal_started.wait(timeout=5)
                assert gate_entered.wait(timeout=5)

                clock.current = initial_time + timedelta(seconds=2)
                recovered_future = workers.submit(
                    EvaluationRunner(second_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-b",
                    evaluator_resolver=lambda configured: CountCases(),
                    release_gates={
                        "policy": lambda result: gate_calls.append("worker-b") or True
                    },
                )
                recovered = recovered_future.result(timeout=5)

                allow_renewal.set()
                release_gate.set()
                with pytest.raises(FinalizationClaimLostError):
                    stale_future.result(timeout=5)

            assert recovered.run.status is EvaluationRunStatus.COMPLETED
            assert [outcome.gate_name for outcome in recovered.run.gate_outcomes] == [
                "policy"
            ]
            assert gate_calls == ["worker-a", "worker-b"]
            assert len(recovered.report_evaluator_executions) == 1


def test_heartbeat_keeps_a_long_running_release_gate_authoritative(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("heartbeat-release-gate")
    database = tmp_path / "evaluation.sqlite"
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = RenewalClock(initial_time, initial_time, threading.Event())
    gate_entered = threading.Event()
    renewal_completed = threading.Event()
    release_gate = threading.Event()
    gate_calls: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_renew = first_ledger.renew_finalization_claim

        def observe_renewal(run_id, claim_id, *, lease_seconds=300.0):
            renewed = original_renew(
                run_id, claim_id, lease_seconds=lease_seconds
            )
            if renewed is not None and clock.current > initial_time:
                renewal_completed.set()
            return renewed

        monkeypatch.setattr(
            first_ledger, "renew_finalization_claim", observe_renewal
        )

        def blocking_gate(result):
            gate_calls.append("worker-a")
            clock.current = initial_time + timedelta(seconds=0.1)
            gate_entered.set()
            assert release_gate.wait(timeout=5)
            return True

        with SQLiteEvaluationLedger(database, clock=clock) as second_ledger:
            with ThreadPoolExecutor(max_workers=2) as workers:
                first_future = workers.submit(
                    EvaluationRunner(first_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-a",
                    lease_seconds=0.15,
                    evaluator_resolver=lambda configured: CountCases(),
                    release_gates={"policy": blocking_gate},
                )
                assert gate_entered.wait(timeout=5)
                assert renewal_completed.wait(timeout=5)

                clock.current = initial_time + timedelta(seconds=0.16)
                live_claim = second_ledger.get_finalization_claim(initial.run.run_id)
                assert live_claim is not None
                assert live_claim.expires_at > clock.current
                with pytest.raises(RuntimeError, match="live finalization claim"):
                    EvaluationRunner(second_ledger).finalize(
                        initial.run.run_id,
                        schemas=_schemas_for(cases),
                        worker_id="worker-b",
                        evaluator_resolver=lambda configured: (
                            (_ for _ in ()).throw(AssertionError("worker B evaluated"))
                        ),
                        release_gates={
                            "policy": lambda result: gate_calls.append("worker-b")
                            or True
                        },
                    )

                release_gate.set()
                completed = first_future.result(timeout=5)

            assert completed.run.status is EvaluationRunStatus.COMPLETED
            assert [outcome.gate_name for outcome in completed.run.gate_outcomes] == [
                "policy"
            ]
            assert gate_calls == ["worker-a"]


def test_completion_racing_with_heartbeat_response_does_not_report_claim_loss(
    tmp_path, monkeypatch, caplog
):
    cases, gold_set, suite = _lifecycle_fixture("completion-heartbeat-race")
    database = tmp_path / "evaluation.sqlite"
    clock = ControllableClock(
        datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    )
    renewal_started = threading.Event()
    completion_committed = threading.Event()

    with SQLiteEvaluationLedger(database, clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_renew = ledger.renew_finalization_claim

        def renew_after_completion(run_id, claim_id, *, lease_seconds=300.0):
            renewal_started.set()
            assert completion_committed.wait(timeout=5)
            return original_renew(run_id, claim_id, lease_seconds=lease_seconds)

        monkeypatch.setattr(ledger, "renew_finalization_claim", renew_after_completion)
        original_complete = ledger.complete_evaluation_run

        def observe_completion(*args, **kwargs):
            completed = original_complete(*args, **kwargs)
            completion_committed.set()
            return completed

        monkeypatch.setattr(ledger, "complete_evaluation_run", observe_completion)

        with caplog.at_level(logging.INFO):
            completed = EvaluationRunner(ledger).finalize(
                initial.run.run_id,
                schemas=_schemas_for(cases),
                worker_id="worker-a",
                lease_seconds=1,
                evaluator_resolver=lambda configured: CountCases(),
            )

        assert renewal_started.is_set()
        assert completed.run.status is EvaluationRunStatus.COMPLETED
        assert not any(
            record.getMessage() == "evaluation_finalization.claim_lost"
            for record in caplog.records
        )


def test_expired_finalizer_without_successor_raises_claim_loss(tmp_path, monkeypatch):
    cases, gold_set, suite = _lifecycle_fixture("expired-finalizer-without-successor")
    database = tmp_path / "evaluation.sqlite"
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)
    renewal_started = threading.Event()
    allow_renewal = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_renew = ledger.renew_finalization_claim

        def paused_expiring_renewal(run_id, claim_id, *, lease_seconds=300.0):
            renewal_started.set()
            assert allow_renewal.wait(timeout=5)
            return original_renew(run_id, claim_id, lease_seconds=lease_seconds)

        monkeypatch.setattr(ledger, "renew_finalization_claim", paused_expiring_renewal)
        evaluator = BlockingCountCases(entered, release, calls)

        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                EvaluationRunner(ledger).finalize,
                initial.run.run_id,
                schemas=_schemas_for(cases),
                worker_id="worker-a",
                lease_seconds=1,
                evaluator_resolver=lambda configured: evaluator,
            )
            assert renewal_started.wait(timeout=5)
            assert entered.wait(timeout=5)

            expired_at = initial_time + timedelta(seconds=1)
            clock.current = expired_at
            allow_renewal.set()
            release.set()
            with pytest.raises(FinalizationClaimLostError) as lost:
                future.result(timeout=5)

        assert lost.value.loss_classification == "claim_expired"
        assert lost.value.last_confirmed_expiry == expired_at
        assert ledger.get_finalization_claim(initial.run.run_id) is None
        assert ledger.list_report_evaluator_executions(initial.run.run_id) == []
        pending = ledger.get_evaluation_run(initial.run.run_id)
        assert pending is not None
        assert pending.status is EvaluationRunStatus.FINALIZATION_PENDING
        assert all(issue.category != "finalization_claim_lost" for issue in pending.issues)


def test_renewal_failure_is_typed_telemetry_and_not_a_run_issue(
    tmp_path, monkeypatch, caplog
):
    cases, gold_set, suite = _lifecycle_fixture("renewal-failure-claim-loss")
    database = tmp_path / "evaluation.sqlite"
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)
    renewal_started = threading.Event()
    allow_failure = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        from knowledge_map.evaluation.runner import _FinalizationHeartbeat

        loss_recorded = threading.Event()
        original_record_loss = _FinalizationHeartbeat.record_loss

        def tracking_record_loss(hb_self, loss_classification, exc=None):
            original_record_loss(hb_self, loss_classification, exc)
            loss_recorded.set()

        monkeypatch.setattr(_FinalizationHeartbeat, "record_loss", tracking_record_loss)

        def failed_renewal(run_id, claim_id, *, lease_seconds=300.0):
            renewal_started.set()
            assert allow_failure.wait(timeout=5)
            raise OSError("renewal database unavailable")

        monkeypatch.setattr(ledger, "renew_finalization_claim", failed_renewal)
        evaluator = BlockingCountCases(entered, release, calls)
        caplog.set_level(logging.INFO, logger="knowledge_map.evaluation.runner")

        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                EvaluationRunner(ledger).finalize,
                initial.run.run_id,
                schemas=_schemas_for(cases),
                worker_id="worker-a",
                lease_seconds=10,
                evaluator_resolver=lambda configured: evaluator,
            )
            assert renewal_started.wait(timeout=5)
            assert entered.wait(timeout=5)
            allow_failure.set()
            assert loss_recorded.wait(timeout=5)
            release.set()
            with pytest.raises(FinalizationClaimLostError) as lost:
                future.result(timeout=5)

        assert lost.value.loss_classification == "renewal_failure"
        assert lost.value.renewal_failure_context == "OSError: renewal database unavailable"
        assert calls == ["count-cases"]
        assert ledger.list_report_evaluator_executions(initial.run.run_id) == []
        pending = ledger.get_evaluation_run(initial.run.run_id)
        assert pending is not None
        assert all(issue.category != "finalization_claim_lost" for issue in pending.issues)
        assert any(
            "evaluation_finalization.claim_lost" in record.message
            for record in caplog.records
        )


def test_transient_renewal_contention_pauses_work_until_authority_is_reconfirmed(
    tmp_path, monkeypatch, caplog
):
    cases, gold_set, suite = _lifecycle_fixture("transient-renewal-contention")
    database = tmp_path / "evaluation.sqlite"
    clock = ControllableClock(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))
    renewal_started = threading.Event()
    retry_started = threading.Event()
    allow_renewal = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        original_renew = ledger.renew_finalization_claim
        renewal_attempts = 0

        def contended_then_renew(run_id, claim_id, *, lease_seconds=300.0):
            nonlocal renewal_attempts
            renewal_attempts += 1
            if renewal_attempts == 1:
                renewal_started.set()
                raise sqlite3.OperationalError("database is locked")
            retry_started.set()
            assert allow_renewal.wait(timeout=5)
            return original_renew(run_id, claim_id, lease_seconds=lease_seconds)

        monkeypatch.setattr(ledger, "renew_finalization_claim", contended_then_renew)
        evaluator = BlockingCountCases(entered, release, calls)
        caplog.set_level(logging.INFO, logger="knowledge_map.evaluation.runner")

        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                EvaluationRunner(ledger).finalize,
                initial.run.run_id,
                schemas=_schemas_for(cases),
                worker_id="worker-a",
                lease_seconds=10,
                evaluator_resolver=lambda configured: evaluator,
            )
            assert renewal_started.wait(timeout=5)
            assert retry_started.wait(timeout=5)
            assert not entered.is_set()

            allow_renewal.set()
            assert entered.wait(timeout=5)
            release.set()
            completed = future.result(timeout=5)

        assert completed.run.status is EvaluationRunStatus.COMPLETED
        assert renewal_attempts == 2
        assert calls == ["count-cases"]
        assert len(completed.report_evaluator_executions) == 1
        assert any(
            "evaluation_finalization.renewal_transient_failure" in record.message
            for record in caplog.records
        )


def test_transient_renewal_contention_becomes_claim_loss_at_confirmed_expiry(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("transient-renewal-expiry")
    database = tmp_path / "evaluation.sqlite"
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)
    renewal_started = threading.Event()
    entered = threading.Event()
    calls: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        def permanently_contended_renewal(run_id, claim_id, *, lease_seconds=300.0):
            renewal_started.set()
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(
            ledger, "renew_finalization_claim", permanently_contended_renewal
        )
        evaluator = BlockingCountCases(entered, threading.Event(), calls)

        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                EvaluationRunner(ledger).finalize,
                initial.run.run_id,
                schemas=_schemas_for(cases),
                worker_id="worker-a",
                lease_seconds=1,
                evaluator_resolver=lambda configured: evaluator,
            )
            assert renewal_started.wait(timeout=5)
            clock.current = initial_time + timedelta(seconds=1)
            with pytest.raises(FinalizationClaimLostError) as lost:
                future.result(timeout=5)

        assert lost.value.loss_classification == "claim_expired"
        assert lost.value.last_confirmed_expiry == initial_time + timedelta(seconds=1)
        assert not entered.is_set()
        assert calls == []
        assert ledger.list_report_evaluator_executions(initial.run.run_id) == []


def test_transient_renewal_and_ownership_contention_stop_at_confirmed_expiry(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture("transient-contention-boundary")
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = ControllableClock(initial_time)
    renewal_started = threading.Event()
    ownership_calls = 0
    evaluator_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite", clock=clock) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )

        def contended_renewal(run_id, claim_id, *, lease_seconds=300.0):
            renewal_started.set()
            raise sqlite3.OperationalError("database is locked")

        def contended_ownership(run_id, claim_id):
            nonlocal ownership_calls
            ownership_calls += 1
            clock.current = initial_time + timedelta(seconds=1)
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(ledger, "renew_finalization_claim", contended_renewal)
        monkeypatch.setattr(ledger, "owns_finalization_claim", contended_ownership)

        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                EvaluationRunner(ledger).finalize,
                initial.run.run_id,
                schemas=_schemas_for(cases),
                worker_id="worker-a",
                lease_seconds=1,
                evaluator_resolver=lambda configured: (
                    evaluator_calls.append(configured.name) or CountCases()
                ),
            )
            assert renewal_started.wait(timeout=5)
            with pytest.raises(FinalizationClaimLostError) as lost:
                future.result(timeout=5)

        assert lost.value.loss_classification == "claim_expired"
        assert lost.value.last_confirmed_expiry == initial_time + timedelta(seconds=1)
        assert ownership_calls == 1
        assert evaluator_calls == []
        assert ledger.list_report_evaluator_executions(initial.run.run_id) == []


def _assert_long_running_finalizer_stays_authoritative(
    tmp_path, *, suffix: str, evaluator_factory
):
    cases, gold_set, suite = _lifecycle_fixture(suffix)
    database = tmp_path / "evaluation.sqlite"
    initial_time = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    clock = RenewalClock(initial_time, initial_time, threading.Event())
    entered = threading.Event()
    release = threading.Event()
    evaluator_calls: list[str] = []

    with SQLiteEvaluationLedger(database, clock=clock) as first_ledger:
        initial = _run(EvaluationRunner(first_ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        with SQLiteEvaluationLedger(database, clock=clock) as second_ledger:
            blocking = evaluator_factory(
                clock, entered, release, evaluator_calls
            )
            with ThreadPoolExecutor(max_workers=1) as workers:
                first_future = workers.submit(
                    EvaluationRunner(first_ledger).finalize,
                    initial.run.run_id,
                    schemas=_schemas_for(cases),
                    worker_id="worker-a",
                    lease_seconds=0.15,
                    evaluator_resolver=lambda configured: blocking,
                )
                assert entered.wait(timeout=5)
                assert clock.renewal_seen.wait(timeout=5)

                clock.current = initial_time + timedelta(seconds=0.16)
                with pytest.raises(RuntimeError, match="live finalization claim"):
                    EvaluationRunner(second_ledger).finalize(
                        initial.run.run_id,
                        schemas=_schemas_for(cases),
                        worker_id="worker-b",
                        evaluator_resolver=lambda configured: (
                            (_ for _ in ()).throw(AssertionError("worker B evaluated"))
                        ),
                    )

                release.set()
                completed = first_future.result(timeout=5)

            assert completed.run.status.value == "completed"
            assert evaluator_calls == ["count-cases"]
            assert len(completed.report_evaluator_executions) == 1


def test_heartbeat_keeps_a_long_running_sync_finalizer_authoritative(tmp_path):
    _assert_long_running_finalizer_stays_authoritative(
        tmp_path,
        suffix="heartbeat-sync-finalizer",
        evaluator_factory=ClockAdvancingBlockingCountCases,
    )


def test_heartbeat_keeps_a_long_running_async_finalizer_authoritative(tmp_path):
    _assert_long_running_finalizer_stays_authoritative(
        tmp_path,
        suffix="heartbeat-async-finalizer",
        evaluator_factory=AsyncClockAdvancingBlockingCountCases,
    )


def test_ledger_completion_requires_frozen_report_and_case_evaluator_evidence(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "guarded-completion", case_evaluator="exact-case"
    )

    with SQLiteEvaluationLedger(tmp_path / "guarded-completion-2.sqlite") as ledger:
        case_records = tuple(ledger.import_case(case) for case in cases)
        gold_record = ledger.import_gold_set(gold_set)
        suite_record = ledger.import_suite(suite)
        plan = preflight_selected_cases(suite=suite, gold_set=gold_set, cases=cases)
        assert plan is not None
        run = EvaluationRunRecord(
            suite_record_id=suite_record.record_id,
            suite_business_id=suite_record.business_id,
            suite_revision=suite_record.revision,
            suite_content_hash=suite_record.content_hash,
            gold_set_record_id=gold_record.record_id,
            gold_set_business_id=gold_record.business_id,
            gold_set_revision=gold_record.revision,
            gold_set_content_hash=gold_record.content_hash,
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
            status="running",
        )
        manifest = tuple(
            EvaluationCaseManifestEntry(
                run_id=run.run_id,
                ordinal=index,
                case=planned.case,
                split=planned.split,
            )
            for index, planned in enumerate(plan.cases)
        )
        pending = tuple(
            EvaluationCaseResult(
                run_id=run.run_id,
                manifest_id=entry.manifest_id,
                case_record_id=case_records[index].record_id,
            )
            for index, entry in enumerate(manifest)
        )
        ledger.create_evaluation_run(run, plan, manifest, pending)
        with pytest.raises(ValueError, match="aggregate manifest"):
            ledger.complete_evaluation_run(run.run_id)

        for result in pending:
            ledger.record_case_evaluation(
                result.model_copy(
                    update={
                        "execution_disposition": EvaluationCaseDisposition.COMPLETED,
                        "task_outcome": TaskSuccess(output=Output(answer="answer")),
                    }
                ),
                (),
                (),
                {
                    "kind": "success",
                    "name": "case@1",
                    "output": {"answer": "answer"},
                    "metrics": {},
                    "attributes": {},
                    "scores": {},
                    "labels": {},
                    "assertions": {},
                    "evaluator_failures": [],
                    "task_duration": 0,
                    "total_duration": 0,
                },
            )
        ledger.freeze_aggregate_manifest(run.run_id)
        claim = ledger.acquire_finalization_claim(run.run_id, owner_id="completion-test")
        assert claim is not None
        with pytest.raises(ValueError, match="case evaluators"):
            ledger.complete_evaluation_run(
                run.run_id, finalization_claim_id=claim.claim_id
            )


def test_completion_rejects_report_execution_with_wrong_frozen_evaluator_identity(
    tmp_path,
):
    cases, gold_set, suite = _lifecycle_fixture("wrong-report-evaluator-identity")

    with SQLiteEvaluationLedger(tmp_path / "wrong-report-evaluator-identity.sqlite") as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = ledger.acquire_finalization_claim(
            initial.run.run_id, owner_id="wrong-report-evaluator-test"
        )
        assert claim is not None
        expected = suite.report_evaluators[0]
        forged = ReportEvaluatorExecution(
            run_id=initial.run.run_id,
            evaluator_name=expected.name,
            evaluator_revision=expected.evaluator_revision + 1,
            configuration_fingerprint=expected.configuration_fingerprint,
            status=EvaluationProducerStatus.FAILED,
            duration_seconds=0,
            failure_message="forged terminal evidence",
        )
        ledger.record_report_evaluation(
            [forged], [], finalization_claim_id=claim.claim_id
        )

        with pytest.raises(ValueError, match="report evaluators"):
            ledger.complete_evaluation_run(
                initial.run.run_id, finalization_claim_id=claim.claim_id
            )

        assert ledger.get_evaluation_run(initial.run.run_id).status is EvaluationRunStatus.FINALIZATION_PENDING


def test_completion_rejects_report_execution_with_wrong_frozen_configuration(
    tmp_path,
):
    cases, gold_set, base_suite = _lifecycle_fixture(
        "wrong-report-evaluator-configuration"
    )
    suite = base_suite.model_copy(
        update={
            "report_evaluators": (
                ConfiguredEvaluator(
                    name="count-cases",
                    evaluator_revision=1,
                    configuration={"temperature": 0},
                ),
            )
        }
    )

    with SQLiteEvaluationLedger(
        tmp_path / "wrong-report-evaluator-configuration.sqlite"
    ) as ledger:
        initial = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        claim = ledger.acquire_finalization_claim(
            initial.run.run_id, owner_id="wrong-report-configuration-test"
        )
        assert claim is not None
        expected = suite.report_evaluators[0]
        forged = ReportEvaluatorExecution(
            run_id=initial.run.run_id,
            evaluator_name=expected.name,
            evaluator_revision=expected.evaluator_revision,
            configuration_fingerprint="a" * 64,
            status=EvaluationProducerStatus.COMPLETED,
            duration_seconds=0,
        )
        ledger.record_report_evaluation(
            [forged], [], finalization_claim_id=claim.claim_id
        )

        with pytest.raises(ValueError, match="report evaluators"):
            ledger.complete_evaluation_run(
                initial.run.run_id, finalization_claim_id=claim.claim_id
            )


def test_orchestration_failure_keeps_prior_case_commits_and_leaves_run_failed(
    tmp_path, monkeypatch
):
    cases, gold_set, suite = _lifecycle_fixture(
        "orchestration-failure", case_evaluator="case-evaluator"
    )

    def fail_report_freeze(*args, **kwargs):
        raise RuntimeError("report storage failed")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        monkeypatch.setattr(ledger, "freeze_aggregate_manifest", fail_report_freeze)
        result = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: NoObservationEvaluator(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
        )

        assert result.run.status == "failed"
        assert [case.execution_disposition.value for case in result.case_results] == [
            "completed",
            "completed",
        ]
        assert result.report_evaluator_executions == ()


def test_retry_is_a_new_run_linked_to_its_predecessor(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("retry")

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        first = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
        )
        second = _run(EvaluationRunner(ledger),
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
            retry_of_run_id=first.run.run_id,
        )

        assert first.run.run_id != second.run.run_id
        assert first.run.retry_of_run_id is None
        assert second.run.retry_of_run_id == first.run.run_id
        assert [run.run_id for run in ledger.list_evaluation_runs()] == [
            first.run.run_id,
            second.run.run_id,
        ]


def test_retry_of_an_incomplete_run_manifests_its_whole_plan(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("retry-incomplete")
    checks = 0

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        first_task_calls: list[str] = []
        first = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: (
                first_task_calls.append(task_input.prompt)
                or Output(answer=task_input.prompt)
            ),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
            should_cancel=should_cancel,
        )

        retry_task_calls: list[str] = []
        second = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: (
                retry_task_calls.append(task_input.prompt)
                or Output(answer=task_input.prompt)
            ),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
            retry_of_run_id=first.run.run_id,
        )

        assert first.run.status == "cancelled"
        assert first_task_calls == ["prompt-1"]
        assert [result.execution_disposition.value for result in first.case_results] == [
            "completed",
            "pending",
        ]
        # The retry is a distinct linked run over the whole caseload: the runner
        # manifests exactly the plan it is given and never narrows to the
        # predecessor's non-terminal cases. Per CONTEXT.md's Evaluation Run,
        # incomplete case execution requires a distinct linked retry; only
        # report evaluation may resume on the same run. `retry_of_run_id` is
        # provenance, not an instruction to resume where the predecessor stopped.
        assert second.run.retry_of_run_id == first.run.run_id
        assert [entry.case_business_id for entry in second.manifest] == [
            "case-1",
            "case-2",
        ]
        assert [planned.case.business_id for planned in ledger.get_resolved_evaluation_plan(second.run.run_id).cases] == [
            "case-1",
            "case-2",
        ]
        assert [result.execution_disposition.value for result in second.case_results] == [
            "completed",
            "completed",
        ]
        assert retry_task_calls == ["prompt-1", "prompt-2"]
        assert ledger.list_evaluation_case_manifest(first.run.run_id) == list(first.manifest)


def test_missing_metrics_and_gate_failures_are_run_diagnostics(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("diagnostics")
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.required",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.INTEGER,
        semantic_description="A required diagnostic metric.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = suite.model_copy(
        update={
            "metrics": (metric,),
            "report_evaluators": (
                ConfiguredEvaluator(
                    name="no-observation",
                    evaluator_revision=1,
                    metrics=(
                        EvaluationMetricReference(
                            namespaced_name="tests.required", evaluator_revision=1
                        ),
                    ),
                ),
            ),
        }
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: NoObservationReportEvaluator(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: NoObservationReportEvaluator(),
            release_gates={"quality-threshold": lambda run: False},
        )

        assert result.run.status == "completed"
        assert [issue.category for issue in result.run.issues] == [
            "missing_metric",
            "gate_failure",
        ]
        assert result.run.gate_outcomes[0].gate_name == "quality-threshold"
        assert result.run.gate_outcomes[0].passed is False
        assert ledger.get_evaluation_run(result.run.run_id) == result.run


def _case(number: int) -> EvaluationCase[Input, Output, Metadata]:
    return EvaluationCase(
        identity=EvaluationCaseIdentity(business_id=f"case-{number}", revision=1),
        input_schema=SchemaReference.for_model(Input, identity="tests.input", revision=1),
        expected_output_schema=SchemaReference.for_model(
            Output, identity="tests.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="tests.metadata", revision=1
        ),
        task_input=Input(prompt=f"prompt-{number}"),
        expected_output=Output(answer=f"answer-{number}"),
        metadata=Metadata(source="fixture"),
        description=f"Deterministic case {number}.",
    )


def test_runner_records_a_complete_deterministic_run(tmp_path):
    cases = (_case(1), _case(2))
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set", revision=1),
        description="Deterministic cases.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    exact_metric = EvaluationMetricDefinition(
        namespaced_name="tests.exact",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.BOOLEAN,
        semantic_description="Whether the answer exactly matches.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    count_metric = EvaluationMetricDefinition(
        namespaced_name="tests.case-count",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.INTEGER,
        semantic_description="Number of evaluated cases.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    table_metric = EvaluationMetricDefinition(
        namespaced_name="tests.case-table",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=SchemaReference.for_model(
            TableResult, identity="tests.case-table", revision=1
        ),
        semantic_description="The complete case table.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    input_schema = cases[0].input_schema
    output_schema = cases[0].expected_output_schema
    metadata_schema = cases[0].metadata_schema
    assert output_schema is not None
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite", revision=1),
        description="Deterministic suite.",
        task_contract=EvaluationTaskContract(
            input_schema=input_schema,
            output_schema=output_schema,
            metadata_schema=metadata_schema,
        ),
        case_evaluators=(
            ConfiguredEvaluator(
                name="exact-answer",
                evaluator_revision=1,
                metrics=(EvaluationMetricReference(namespaced_name="tests.exact", evaluator_revision=1),),
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(
                name="count-cases",
                evaluator_revision=1,
                metrics=(EvaluationMetricReference(namespaced_name="tests.case-count", evaluator_revision=1),),
            ),
            ConfiguredEvaluator(
                name="case-table",
                evaluator_revision=1,
                metrics=(
                    EvaluationMetricReference(
                        namespaced_name="tests.case-table", evaluator_revision=1
                    ),
                ),
            ),
        ),
        metrics=(exact_metric, count_metric, table_metric),
    )

    pending_dispositions: list[list[str]] = []
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        def task(task_input: Input) -> Output:
            current_run = ledger.list_evaluation_runs()[0]
            pending_dispositions.append(
                [result.execution_disposition.value for result in ledger.list_case_results(current_run.run_id)]
            )
            return Output(answer=task_input.prompt.replace("prompt", "answer"))

        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=task,
            evaluator_resolver=lambda configured: {
                "exact-answer": ExactAnswer(),
                "count-cases": CountCases(),
                "case-table": CaseTable(),
            }[configured.name],
            configuration=EvaluationRunConfiguration(
                provider="deterministic",
                model="fixture",
                random_seed=7,
                component_configuration=ValidatedComponentConfiguration.from_model(
                    ComponentConfiguration(
                        temperature=0,
                        api_key=SecretStr("must-not-persist"),
                    ),
                    identity="tests.component-configuration",
                    revision=1,
                ),
            ),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: {
                "count-cases": CountCases(),
                "case-table": CaseTable(),
            }[configured.name],
        )

        assert result.run.status == "completed"
        assert len(result.manifest) == 2
        assert len(result.case_results) == 2
        assert pending_dispositions == [["pending", "pending"], ["completed", "pending"]]
        assert all(case.task_outcome.kind == "success" for case in result.case_results)
        assert len(result.case_evaluator_executions) == 2
        assert len(result.report_evaluator_executions) == 2
        assert [observation.boolean_value for observation in result.case_observations] == [
            True,
            True,
        ]
        assert result.run_observations[0].integer_value == 2
        assert result.run_observations[1].structured_value == StructuredMetricValue(
            schema_reference=table_metric.structured_schema,
            payload={
                "columns": ["case"],
                "description": None,
                "rows": [["case-1@1"], ["case-2@1"]],
                "title": "case-table",
                "type": "table",
            },
        )
        assert ledger.list_case_observations(result.case_results[0].result_id) == [
            result.case_observations[0]
        ]
        assert ledger.list_run_observations(result.run.run_id) == list(result.run_observations)
        assert EvaluationMetricObservation(
            metric=EvaluationMetricReference(
                namespaced_name="tests.example", evaluator_revision=1
            ),
            boolean_value=True,
        ).value is True
        assert "must-not-persist" not in result.run.configuration_json
        assert ledger.get_evaluation_run(result.run.run_id) == result.run


def test_case_and_report_structured_observations_round_trip_as_envelopes(tmp_path):
    cases = (_case(1),)
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-both", revision=1),
        description="One deterministic case.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(cases[0]),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )
    case_metric = EvaluationMetricDefinition(
        namespaced_name="tests.case-table",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=SchemaReference.for_model(
            TableResult, identity="tests.case-table", revision=1
        ),
        semantic_description="The case table.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    report_metric = case_metric.model_copy(update={"namespaced_name": "tests.report-table"})
    suite = _lifecycle_fixture("structured-both")[2].model_copy(
        update={
            "case_evaluators": (
                ConfiguredEvaluator(
                    name="case-table",
                    evaluator_revision=1,
                    metrics=(EvaluationMetricReference.from_definition(case_metric),),
                ),
            ),
            "report_evaluators": (
                ConfiguredEvaluator(
                    name="report-table",
                    evaluator_revision=1,
                    metrics=(EvaluationMetricReference.from_definition(report_metric),),
                ),
            ),
            "metrics": (case_metric, report_metric),
        }
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        schemas = _schemas_for(cases)
        schemas.register(case_metric.structured_schema, TableResult)
        schemas.register(report_metric.structured_schema, TableResult)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                CaseTableEvaluator()
                if configured.name == "case-table"
                else CaseTable()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=schemas,
            evaluator_resolver=lambda configured: CaseTable(),
        )

        case_observation = ledger.list_case_observations(result.case_results[0].result_id)[0]
        run_observation = ledger.list_run_observations(result.run.run_id)[0]

        assert case_observation.structured_value is not None
        assert run_observation.structured_value is not None
        assert case_observation.structured_value.schema_reference == case_metric.structured_schema
        assert run_observation.structured_value.schema_reference == report_metric.structured_schema
        assert case_observation.structured_value.payload["rows"] == [["case-1@1"]]
        assert run_observation.structured_value.payload["rows"] == [["case-1@1"]]
        assert ledger.materialize_metric_observation(
            result.run.run_id, case_observation, schemas
        ) == TableResult(
            title="case-table",
            columns=["case"],
            rows=[["case-1@1"]],
        )
        assert ledger.materialize_metric_observation(
            result.run.run_id, run_observation, schemas
        ) == TableResult(
            title="case-table",
            columns=["case"],
            rows=[["case-1@1"]],
        )


def test_mismatched_structured_evaluator_output_is_failure_evidence_without_observation(
    tmp_path,
):
    cases, gold_set, base_suite = _lifecycle_fixture(
        "structured-mismatch", case_evaluator="invalid-structured"
    )
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.structured-mismatch",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=SchemaReference.for_model(
            TableResult, identity="tests.structured-mismatch", revision=1
        ),
        semantic_description="A structured evaluator result.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = base_suite.model_copy(
        update={
            "case_evaluators": (
                ConfiguredEvaluator(
                    name="invalid-structured",
                    evaluator_revision=1,
                    metrics=(EvaluationMetricReference.from_definition(metric),),
                ),
            ),
            "metrics": (metric,),
        }
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                MismatchedStructuredEvaluator()
                if configured.name == "invalid-structured"
                else CountCases()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )

        assert result.run.status == "completed"
        assert result.case_evaluator_executions[0].status is EvaluationProducerStatus.FAILED
        assert ledger.list_case_observations(result.case_results[0].result_id) == []
        assert [issue.category for issue in result.run.issues].count("missing_metric") == 2


def test_runner_freezes_a_subset_and_records_no_observation_invocations(tmp_path):
    cases = (_case(1), _case(2))
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-subset", revision=1),
        description="Deterministic cases.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    input_schema = cases[0].input_schema
    output_schema = cases[0].expected_output_schema
    assert output_schema is not None
    count_metric = EvaluationMetricDefinition(
        namespaced_name="tests.subset-count",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.INTEGER,
        semantic_description="Number of selected cases.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="subset-suite", revision=1),
        description="Subset suite.",
        task_contract=EvaluationTaskContract(
            input_schema=input_schema,
            output_schema=output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        case_evaluators=(ConfiguredEvaluator(name="no-observation", evaluator_revision=1),),
        report_evaluators=(
            ConfiguredEvaluator(
                name="count-cases",
                evaluator_revision=1,
                metrics=(
                    EvaluationMetricReference(
                        namespaced_name="tests.subset-count", evaluator_revision=1
                    ),
                ),
            ),
        ),
        metrics=(count_metric,),
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = _run(runner,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=lambda case: case.identity.business_id == "case-2",
            selection_expression="tag:subset-case-2",
            selection_provenance={"source": "pull-request"},
            task=lambda task_input: Output(answer=task_input.prompt.replace("prompt", "answer")),
            evaluator_resolver=lambda configured: {
                "no-observation": NoObservationEvaluator(),
                "count-cases": CountCases(),
            }[configured.name],
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )

        assert [entry.case_business_id for entry in result.manifest] == ["case-2"]
        assert result.run.selection_expression == "tag:subset-case-2"
        assert result.run.selection_provenance["source"] == "pull-request"
        assert result.run.selection_provenance["resolved_case_count"] == 1
        assert len(result.case_evaluator_executions) == 1
        assert result.case_evaluator_executions[0].status == "completed"
        assert result.case_observations == ()
        assert result.run_observations[0].integer_value == 1


def test_sqlite_evaluation_execution_store_owns_query_persistence():
    assert not hasattr(SQLiteEvaluationLedger, "_create_evaluation_run")
    assert not hasattr(SQLiteEvaluationLedger, "_record_case_evaluation")
    assert not hasattr(SQLiteEvaluationLedger, "_record_report_evaluation")
    assert not hasattr(SQLiteEvaluationLedger, "_complete_evaluation_run")
    assert not hasattr(SQLiteEvaluationLedger, "_validate_run_creation")
    assert not hasattr(SQLiteEvaluationLedger, "_assert_run_is_complete")
