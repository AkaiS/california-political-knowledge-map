import pytest
from pydantic import BaseModel

from knowledge_map.evaluation import (
    ConfiguredEvaluator,
    EvaluationCase,
    EvaluationCaseIdentity,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationRequirement,
    EvaluationRequirementCatalog,
    EvaluationSplit,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    SchemaReference,
    evaluate_compatibility,
)


class Input(BaseModel):
    text: str


class Output(BaseModel):
    label: str


class Metadata(BaseModel):
    source: str


def _schema(model: type[BaseModel], role: str) -> SchemaReference:
    return SchemaReference.for_model(model, identity=f"tests.{role}", revision=1)


def _case(
    business_id: str = "case-1",
    **updates: object,
) -> EvaluationCase:
    values = {
        "identity": EvaluationCaseIdentity(business_id=business_id, revision=1),
        "input_schema": _schema(Input, "input"),
        "expected_output_schema": _schema(Output, "output"),
        "metadata_schema": _schema(Metadata, "metadata"),
        "task_input": Input(text="example"),
        "expected_output": Output(label="relevant"),
        "metadata": Metadata(source="human"),
        "description": "A compatibility example.",
    }
    values.update(updates)
    return EvaluationCase(**values)


def _definitions(case: EvaluationCase) -> tuple[EvaluationSuite, EvaluationGoldSet]:
    contract = EvaluationTaskContract(
        input_schema=_schema(Input, "input"),
        output_schema=_schema(Output, "output"),
        metadata_schema=_schema(Metadata, "metadata"),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite", revision=1),
        description="Compatibility suite.",
        task_contract=contract,
        report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold", revision=1),
        description="Compatibility Gold Set.",
        task_contract=contract,
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )
    return suite, gold_set


@pytest.mark.parametrize(
    ("schema_role", "case_field", "model_type"),
    (
        ("input", "input_schema", Input),
        ("expected_output", "expected_output_schema", Output),
        ("metadata", "metadata_schema", Metadata),
    ),
)
def test_compatibility_reports_each_case_schema_mismatch(
    schema_role: str,
    case_field: str,
    model_type: type[BaseModel],
):
    member = _case()
    suite, gold_set = _definitions(member)
    incompatible = _case(
        **{
            case_field: SchemaReference.for_model(
                model_type,
                identity=f"tests.other-{schema_role}",
                revision=1,
            )
        }
    )

    issues = evaluate_compatibility(suite, gold_set, (incompatible,))

    assert len(issues) == 1
    assert issues[0].category == "contract_schema_mismatch"
    assert issues[0].case_business_id == "case-1"
    assert issues[0].case_revision == 1
    assert issues[0].schema_role == schema_role
    assert issues[0].actual_schema == getattr(incompatible, case_field)
    assert issues[0].expected_schema == getattr(
        suite.task_contract,
        "output_schema" if schema_role == "expected_output" else f"{schema_role}_schema",
    )


def test_compatibility_reports_an_unknown_evaluation_requirement_distinctly():
    member = _case()
    suite, gold_set = _definitions(member)
    suite = suite.model_copy(
        update={
            "requirement_catalog": EvaluationRequirementCatalog(
                requirements=(
                    EvaluationRequirement(
                        key="grounding",
                        semantic_description="The output must be grounded.",
                    ),
                )
            )
        }
    )
    unknown = _case(requirements=("tone",))

    issues = evaluate_compatibility(suite, gold_set, (unknown,))

    assert len(issues) == 1
    assert issues[0].category == "unknown_requirement"
    assert issues[0].case_business_id == "case-1"
    assert issues[0].case_revision == 1
    assert issues[0].requirement == "tone"
    assert issues[0].schema_role is None


def test_compatibility_accepts_a_case_without_an_expected_output_schema():
    member = _case()
    suite, gold_set = _definitions(member)
    unlabeled = _case(
        expected_output=None,
        expected_output_schema=None,
    )

    assert evaluate_compatibility(suite, gold_set, (unlabeled,)) == ()


def test_compatibility_accumulates_schema_and_requirement_issues_across_cases():
    member = _case("member")
    suite, gold_set = _definitions(member)
    first = _case(
        "first",
        input_schema=SchemaReference.for_model(
            Input, identity="tests.other-input", revision=1
        ),
        requirements=("unknown-one",),
    )
    second = _case(
        "second",
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="tests.other-metadata", revision=1
        ),
        requirements=("unknown-two",),
    )

    issues = evaluate_compatibility(suite, gold_set, (first, second))

    assert [
        (issue.category, issue.case_business_id, issue.schema_role, issue.requirement)
        for issue in issues
    ] == [
        ("contract_schema_mismatch", "first", "input", None),
        ("unknown_requirement", "first", None, "unknown-one"),
        ("contract_schema_mismatch", "second", "metadata", None),
        ("unknown_requirement", "second", None, "unknown-two"),
    ]
