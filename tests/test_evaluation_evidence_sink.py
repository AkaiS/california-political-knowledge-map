import pytest
from pydantic import BaseModel
from pydantic_evals.lifecycle import CaseLifecycle

from knowledge_map.evaluation import (
    ConfiguredEvaluator,
    EvaluationCase,
    EvaluationCaseIdentity,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationSplit,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    EvaluationTaskBinding,
    SchemaReference,
    TaskSuccess,
    preflight_selected_cases,
)
from knowledge_map.evaluation.engine import EvaluationEngine


@pytest.mark.parametrize(
    "missing_operation",
    (
        "record_task_outcome",
        "case_lifecycle",
        "checkpoint_case",
        "checkpoint_report",
        "checkpoint_partial_report_evidence",
    ),
)
def test_engine_rejects_a_sink_missing_any_declared_evidence_operation(
    missing_operation,
):
    operations = {
        "record_task_outcome": lambda self, task_input, outcome: None,
        "case_lifecycle": None,
        "checkpoint_case": lambda self, case: None,
        "checkpoint_report": lambda self, report: None,
        "checkpoint_partial_report_evidence": lambda self: None,
    }
    del operations[missing_operation]
    incomplete_sink = type("IncompleteEvidenceSink", (), operations)()

    with pytest.raises(TypeError, match="EvaluationCheckpointSink"):
        EvaluationEngine(incomplete_sink)


class Input(BaseModel):
    value: str


class Output(BaseModel):
    value: str


class Metadata(BaseModel):
    source: str


def _execution_fixture():
    input_schema = SchemaReference.for_model(Input, identity="tests.input", revision=1)
    output_schema = SchemaReference.for_model(
        Output, identity="tests.output", revision=1
    )
    metadata_schema = SchemaReference.for_model(
        Metadata, identity="tests.metadata", revision=1
    )
    contract = EvaluationTaskContract(
        input_schema=input_schema,
        output_schema=output_schema,
        metadata_schema=metadata_schema,
    )
    case = EvaluationCase(
        identity=EvaluationCaseIdentity(business_id="case", revision=1),
        input_schema=input_schema,
        expected_output_schema=output_schema,
        metadata_schema=metadata_schema,
        task_input=Input(value="input"),
        expected_output=Output(value="output"),
        metadata=Metadata(source="human"),
        description="A lifecycle case.",
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite", revision=1),
        description="A lifecycle suite.",
        task_contract=contract,
        report_evaluators=(
            ConfiguredEvaluator(name="unused-report", evaluator_revision=1),
        ),
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold", revision=1),
        description="A lifecycle gold set.",
        task_contract=contract,
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )
    plan = preflight_selected_cases(
        suite=suite, gold_set=gold_set, cases=(case,)
    )
    assert plan is not None
    return case, suite, plan


def test_engine_uses_the_sink_case_lifecycle_for_terminal_case_notification():
    terminal_cases = []

    class RecordingLifecycle(CaseLifecycle):
        async def teardown(self, result):
            terminal_cases.append(result)

    class RecordingSink:
        case_lifecycle = RecordingLifecycle

        def record_task_outcome(self, task_input, outcome):
            return None

        def checkpoint_case(self, case):
            pytest.fail("lifecycle-backed execution must not checkpoint a case twice")

        def checkpoint_report(self, report):
            return None

        def checkpoint_partial_report_evidence(self):
            return None

    case, suite, plan = _execution_fixture()

    EvaluationEngine(RecordingSink()).execute(
        plan=plan,
        suite=suite,
        cases=(case,),
        task=lambda task_input: Output(value="output"),
        evaluator_resolver=lambda configured: pytest.fail(
            f"unexpected evaluator resolution: {configured.name}"
        ),
    )

    assert [result.name for result in terminal_cases] == ["case@1"]


def test_engine_records_task_binding_outcomes_through_the_sink_contract():
    recorded_outcomes = []

    class RecordingSink:
        case_lifecycle = None

        def record_task_outcome(self, task_input, outcome):
            recorded_outcomes.append((task_input, outcome))

        def checkpoint_case(self, case):
            return None

        def checkpoint_report(self, report):
            return None

        def checkpoint_partial_report_evidence(self):
            return None

    case, suite, plan = _execution_fixture()
    binding = EvaluationTaskBinding(
        operation=lambda task_input: Output(value="output"),
        contract=suite.task_contract,
        input_model=Input,
        output_model=Output,
        metadata_model=Metadata,
    )

    EvaluationEngine(RecordingSink()).execute(
        plan=plan,
        suite=suite,
        cases=(case,),
        task_binding=binding,
        evaluator_resolver=lambda configured: pytest.fail(
            f"unexpected evaluator resolution: {configured.name}"
        ),
    )

    assert len(recorded_outcomes) == 1
    task_input, outcome = recorded_outcomes[0]
    assert task_input == Input(value="input")
    assert isinstance(outcome, TaskSuccess)
    assert outcome.output == Output(value="output")
