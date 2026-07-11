from dataclasses import dataclass

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
    EvaluationCase,
    EvaluationCaseIdentity,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationMetricDefinition,
    EvaluationMetricObservation,
    EvaluationMetricReference,
    EvaluationMetricValueType,
    EvaluationRunConfiguration,
    EvaluationRunner,
    EvaluationSplit,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    NoComparisonOperation,
    SchemaReference,
    TaskFailure,
)
from knowledge_map.evaluation.store import SQLiteEvaluationLedger


class Input(BaseModel):
    prompt: str


class Output(BaseModel):
    answer: str


class Metadata(BaseModel):
    source: str


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
            "pending",
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
