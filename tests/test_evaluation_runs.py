import json
import sqlite3
from dataclasses import dataclass
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

from knowledge_map.evaluation import (
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

    assert result.run.status == "completed"
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
        durable = EvaluationRunner(ledger).run(
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
    cases, gold_set, suite = _lifecycle_fixture("task-artifact-scope")

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
        updated = result.case_results[0].model_copy(
            update={
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

        result = EvaluationRunner(ledger).run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=task,
            evaluator_resolver=lambda configured: CountCases(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
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
        result = EvaluationRunner(ledger).run(
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
        result = EvaluationRunner(ledger).run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: FailingReportEvaluator(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
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
        result = EvaluationRunner(ledger).run(
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
        produced = ledger.list_produced_artifacts(result.run.run_id)
        assert {item.artifact_id for item in produced} == {
            run_output.artifact_id,
            case_output.artifact_id,
            case_evidence.artifact_id,
            report_evidence.artifact_id,
        }
        assert {
            (item.producer_type, item.role)
            for item in produced
        } == {
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
        result = EvaluationRunner(ledger).run(
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


def test_cancelled_run_retains_partial_report_evaluation(tmp_path):
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
        return checks == 5

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = EvaluationRunner(ledger).run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: (
                CountCases() if configured.name == "count-cases" else CaseTable()
            ),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
            should_cancel=should_cancel,
        )

        assert result.run.status == "cancelled"
        assert [execution.evaluator_name for execution in result.report_evaluator_executions] == [
            "count-cases"
        ]


def test_orchestration_failure_keeps_prior_case_commits_and_leaves_run_failed(tmp_path):
    cases, gold_set, suite = _lifecycle_fixture(
        "orchestration-failure", case_evaluator="case-evaluator"
    )
    resolver_calls = 0

    def resolve(configured):
        nonlocal resolver_calls
        resolver_calls += 1
        if resolver_calls == 2:
            raise RuntimeError("resolver infrastructure failed")
        return NoObservationEvaluator()

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        result = EvaluationRunner(ledger).run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=resolve,
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
        result = EvaluationRunner(ledger).run(
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task=lambda task_input: Output(answer=task_input.prompt),
            evaluator_resolver=lambda configured: NoObservationReportEvaluator(),
            configuration=EvaluationRunConfiguration(provider="deterministic", model="fixture"),
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

        result = EvaluationRunner(ledger).run(
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
        result = EvaluationRunner(ledger).run(
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

        assert [entry.case_business_id for entry in result.manifest] == ["case-2"]
        assert result.run.selection_expression == "tag:subset-case-2"
        assert result.run.selection_provenance["source"] == "pull-request"
        assert result.run.selection_provenance["resolved_case_count"] == 1
        assert len(result.case_evaluator_executions) == 1
        assert result.case_evaluator_executions[0].status == "completed"
        assert result.case_observations == ()
        assert result.run_observations[0].integer_value == 1
