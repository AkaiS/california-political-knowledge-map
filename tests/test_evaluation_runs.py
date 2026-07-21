import hashlib
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, SecretStr
from pydantic_evals.evaluators import (
    Evaluator,
    EvaluatorContext,
    ReportEvaluator,
    ReportEvaluatorContext,
)
from pydantic_evals.reporting.analyses import ScalarResult, TableResult
from pydantic_evals.reporting import ReportCaseFailure

from knowledge_map.evaluation import (
    CaseEvaluatorExecution,
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
    EvaluationRunConfiguration,
    EvaluationRunRecord,
    EvaluationRunner,
    EvaluationRubric,
    EvaluationRubricIdentity,
    EvaluationRubricRevisionReference,
    EvaluationSplit,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    ConfiguredEvaluatorReference,
    NoComparisonOperation,
    SchemaReference,
    SchemaRegistry,
    TaskFailure,
    TaskSuccess,
    preflight_selected_cases,
)
from knowledge_map.evaluation.store import SQLiteEvaluationLedger


class Input(BaseModel):
    prompt: str


class Output(BaseModel):
    answer: str


class Metadata(BaseModel):
    source: str


def _schemas_for(cases) -> SchemaRegistry:
    schemas = SchemaRegistry()
    schemas.register(cases[0].input_schema, Input)
    schemas.register(cases[0].expected_output_schema, Output)
    schemas.register(cases[0].metadata_schema, Metadata)
    return schemas


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
class FailingCaseEvaluator(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        raise ValueError("the case evaluator could not score this output")


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


def test_durable_runner_uses_the_frozen_plan_for_case_evaluator_scope(tmp_path):
    cases = (_case(1), _case(2))
    cases = (
        cases[0].model_copy(update={"requirements": ("grounded",)}),
        cases[1],
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-durable-plan", revision=1),
        description="Durable shared-engine cases.",
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-durable-plan", revision=1),
        description="Durable shared-engine suite.",
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
                evaluators=(ConfiguredEvaluatorReference(name="grounding"),),
            ),
        ),
        report_evaluators=(ConfiguredEvaluator(name="count-cases", evaluator_revision=1),),
    )
    universal_calls: list[str] = []
    grounding_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = EvaluationRunner(ledger).run(
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
    assert [execution.evaluator_name for execution in result.case_evaluator_executions] == [
        "universal",
        "grounding",
        "universal",
    ]


def test_durable_case_checkpoint_rolls_back_all_case_evidence_on_persistence_failure(
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
        monkeypatch.setattr(ledger, "_insert_case_observation", fail_observation_insert)
        result = EvaluationRunner(ledger).run(
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


def test_one_case_plan_has_equivalent_in_memory_and_durable_report_semantics(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "shared-parity", case_evaluator="exact-case"
    )
    plan_result = preflight_selected_cases(
        suite=suite,
        gold_set=gold_set,
        cases=cases,
        selection=("case-1",),
    )
    assert plan_result.plan is not None

    def resolve(configured):
        return ExactAnswer() if configured.name == "exact-case" else CountCases()

    in_memory = suite.execute(
        plan=plan_result.plan,
        cases=cases,
        task=lambda task_input: Output(answer=task_input.prompt),
        evaluator_resolver=resolve,
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = runner.run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            selection=("case-1",),
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=resolve,
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        durable = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=resolve,
        )

    assert durable.run.status == "completed"
    assert in_memory.cases[0].output.model_dump() == durable.case_results[0].task_outcome.output
    assert list(in_memory.cases[0].assertions) == ["ExactAnswer"]
    assert [execution.evaluator_name for execution in durable.case_evaluator_executions] == [
        "exact-case"
    ]
    assert in_memory.analyses[0].value == len(durable.case_results) == 1
    assert [execution.status.value for execution in durable.report_evaluator_executions] == [
        "completed"
    ]


def test_terminal_checkpoint_materializes_one_typed_report_case(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "typed-report-case", case_evaluator="exact-case"
    )
    registry = SchemaRegistry()
    registry.register(cases[0].input_schema, Input)
    registry.register(cases[0].expected_output_schema, Output)
    registry.register(cases[0].metadata_schema, Metadata)

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = EvaluationRunner(ledger).run(
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


def test_typed_report_case_rejects_an_unallowlisted_schema(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("unknown-report-schema")
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = EvaluationRunner(ledger).run(
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
        result = EvaluationRunner(ledger).run(
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
            "name": "case-1@1",
            "output": {"answer": "stable"},
            "task_duration": 0.1,
            "total_duration": 0.2,
        }

        ledger.record_case_evaluation(completed, (), (), evidence)
        ledger.record_case_evaluation(completed, (), (), evidence)

        with pytest.raises(ValueError, match="different evidence"):
            ledger.record_case_evaluation(
                completed,
                (),
                (),
                {**evidence, "total_duration": 99.0},
            )


def _lifecycle_fixture(suffix: str, *, case_evaluator: str | None = None):
    cases = (_case(1), _case(2))
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id=f"gold-set-{suffix}", revision=1),
        description="Lifecycle cases.",
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
    ).plan
    assert expected_plan is not None

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = EvaluationRunner(ledger).run(
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
        result = EvaluationRunner(ledger).run(
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

    report = suite.execute(
        cases=cases,
        task=task,
        evaluator_resolver=lambda configured: CountCases(),
        max_concurrency=2,
    )

    assert len(report.cases) == len(cases)
    assert maximum_active == 2


def test_ledger_serializes_concurrent_terminal_case_checkpoints(tmp_path, monkeypatch):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        run, plan, manifest, pending_results = _resolved_run_creation_inputs(
            ledger, "concurrent-checkpoints"
        )
        ledger.create_evaluation_run(run, plan, manifest, pending_results)
        insert_case_execution = ledger._insert_case_execution

        def delayed_insert(execution: CaseEvaluatorExecution) -> None:
            time.sleep(0.05)
            insert_case_execution(execution)

        monkeypatch.setattr(ledger, "_insert_case_execution", delayed_insert)

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
def test_durable_runner_honors_case_bound_and_checkpoints_each_case_once(
    tmp_path, configured_concurrency, expected_maximum
):
    cases = tuple(_case(number) for number in range(1, 5))
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(
            business_id="gold-set-durable-concurrency", revision=1
        ),
        description="Concurrent durable cases.",
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            )
            for case in cases
        ),
    )
    _, _, suite = _lifecycle_fixture(
        "durable-concurrency", case_evaluator="exact-case"
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
        result = EvaluationRunner(ledger).run(
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
    ).plan
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

        runner = EvaluationRunner(ledger)
        initial = runner.run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=task,
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
        assert failed_outcome.category == "task_execution"
        assert failed_outcome.exception_type == "TimeoutError"
        assert failed_outcome.safe_message == "provider request timed out"
        assert result.run_observations[0].integer_value == 1
        assert ledger.list_evaluation_case_results(result.run.run_id) == list(result.case_results)


def test_case_evaluator_failure_is_separate_from_task_and_run_status(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "case-evaluator-failure", case_evaluator="failing-case"
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = runner.run(
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
        result = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: CountCases(),
        )

        assert result.run.status == "completed"
        assert all(case.task_outcome.kind == "success" for case in result.case_results)
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
        initial = runner.run(
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


def test_run_artifact_read_models_preserve_smallest_execution_producer(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "artifact-links", case_evaluator="exact-case"
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = runner.run(
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
        initial = runner.run(
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

        result = EvaluationRunner(ledger).run(
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

        result = EvaluationRunner(ledger).run(
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

        result = EvaluationRunner(ledger).run(
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

        result = EvaluationRunner(ledger).run(
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
        result = EvaluationRunner(ledger).run(
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
            EvaluationRunner(ledger).run(
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
        initial = runner.run(
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
            should_cancel=should_cancel,
        )

        assert result.run.status == "finalization_pending"
        assert [execution.evaluator_name for execution in result.report_evaluator_executions] == [
            "count-cases"
        ]


def test_incomplete_cases_cannot_freeze_the_aggregate_report(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("freeze-requires-terminal-cases")
    checks = 0

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = EvaluationRunner(ledger).run(
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
        result = runner.run(
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
        initial = EvaluationRunner(ledger).run(
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


def test_finalization_rejects_unresolved_frozen_schemas_before_evaluating(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("unresolved-finalization-schema")
    resolver_calls: list[str] = []

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        initial = EvaluationRunner(ledger).run(
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
        initial = EvaluationRunner(ledger).run(
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
        initial = EvaluationRunner(ledger).run(
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
        result = EvaluationRunner(ledger).run(
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
        result = EvaluationRunner(ledger).run(
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
        result = EvaluationRunner(ledger).run(
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
    now = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)

    with SQLiteEvaluationLedger(database) as first_ledger:
        initial = EvaluationRunner(first_ledger).run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
        )
        with SQLiteEvaluationLedger(database) as competing_ledger:
            first_claim = first_ledger.acquire_finalization_claim(
                initial.run.run_id,
                owner_id="worker-a",
                lease_seconds=60,
                now=now,
            )
            second_claim = competing_ledger.acquire_finalization_claim(
                initial.run.run_id,
                owner_id="worker-b",
                lease_seconds=60,
                now=now,
            )

            assert first_claim.owner_id == "worker-a"
            assert first_claim.acquired_at == now
            assert first_claim.expires_at == now + timedelta(seconds=60)
            assert second_claim is None
            assert competing_ledger.get_finalization_claim(initial.run.run_id) == first_claim


def test_finalize_refuses_a_live_claim_before_resolving_report_evaluators(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("finalization-claim-guard")
    database = tmp_path / "evaluation.sqlite"

    with SQLiteEvaluationLedger(database) as first_ledger:
        initial = EvaluationRunner(first_ledger).run(
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
        initial = runner.run(
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
            should_cancel=stop_after_one,
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
    now = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        initial = runner.run(
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
            should_cancel=stop_after_one,
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
            now=now,
        )
        assert stale_claim is not None

        recovery_calls: list[str] = []
        recovered = runner.finalize(
            initial.run.run_id,
            schemas=_schemas_for(cases),
            evaluator_resolver=lambda configured: (
                recovery_calls.append(configured.name) or CaseTable()
            ),
            worker_id="recovery-worker",
            now=now + timedelta(seconds=2),
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
        initial = EvaluationRunner(first_ledger).run(
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


def test_ledger_completion_requires_frozen_report_and_case_evaluator_evidence(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "guarded-completion", case_evaluator="exact-case"
    )

    with SQLiteEvaluationLedger(tmp_path / "guarded-completion-2.sqlite") as ledger:
        case_records = tuple(ledger.import_case(case) for case in cases)
        gold_record = ledger.import_gold_set(gold_set)
        suite_record = ledger.import_suite(suite)
        plan = preflight_selected_cases(suite=suite, gold_set=gold_set, cases=cases).plan
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
                        "name": "case@1",
                        "output": {"answer": "answer"},
                        "metrics": {},
                        "attributes": {},
                        "scores": {},
                        "labels": {},
                        "assertions": {},
                    },
                )
        ledger.freeze_aggregate_manifest(run.run_id)
        with pytest.raises(ValueError, match="case evaluators"):
            ledger.complete_evaluation_run(run.run_id)


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
        result = EvaluationRunner(ledger).run(
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
        first = EvaluationRunner(ledger).run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
        )
        second = EvaluationRunner(ledger).run(
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


def test_retry_of_an_incomplete_run_manifests_only_nonterminal_cases(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture("retry-incomplete")
    checks = 0

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)
        first_task_calls: list[str] = []
        first = runner.run(
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
        second = runner.run(
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
            selection=("case-1", "case-2"),
        )

        assert first.run.status == "cancelled"
        assert first_task_calls == ["prompt-1"]
        assert [result.execution_disposition.value for result in first.case_results] == [
            "completed",
            "pending",
        ]
        assert second.run.retry_of_run_id == first.run.run_id
        assert [entry.case_business_id for entry in second.manifest] == ["case-2"]
        assert [planned.case.business_id for planned in ledger.get_resolved_evaluation_plan(second.run.run_id).cases] == [
            "case-2"
        ]
        assert [result.execution_disposition.value for result in second.case_results] == [
            "completed"
        ]
        assert retry_task_calls == ["prompt-2"]
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
        initial = runner.run(
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
        initial = runner.run(
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
                component_configuration={
                    "temperature": 0,
                    "api_key": SecretStr("must-not-persist"),
                },
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
        assert result.run_observations[1].structured_json == {
            "columns": ["case"],
            "description": None,
            "rows": [["case-1@1"], ["case-2@1"]],
            "title": "case-table",
            "type": "table",
        }
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


def test_runner_freezes_a_subset_and_records_no_observation_invocations(tmp_path):
    cases = (_case(1), _case(2))
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-subset", revision=1),
        description="Deterministic cases.",
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
        initial = runner.run(
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
