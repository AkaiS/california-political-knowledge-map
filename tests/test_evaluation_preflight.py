from pydantic import BaseModel
import pytest

from knowledge_map.evaluation import (
    ConfiguredEvaluator,
    ConfiguredEvaluatorReference,
    EvaluationCase,
    EvaluationCaseIdentity,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationRequirementCatalog,
    EvaluationRequirement,
    EvaluationRequirementBinding,
    EvaluationPreflightError,
    EvaluationRunConfiguration,
    EvaluationRunner,
    EvaluationSplit,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    SchemaReference,
    construct_evaluation_gold_set,
    preflight_selected_cases,
)
from knowledge_map.evaluation.store import SQLiteEvaluationLedger


TEST_SPLIT_RATIO = {
    EvaluationSplit.TRAINING: 0.6,
    EvaluationSplit.CALIBRATION: 0.2,
    EvaluationSplit.HELD_OUT: 0.2,
}


class Input(BaseModel):
    value: str


class Output(BaseModel):
    label: str


class Metadata(BaseModel):
    source: str


def test_preflight_builds_a_plan_with_suite_wide_evaluator_for_selected_case():
    case = EvaluationCase[Input, Output, Metadata](
        identity=EvaluationCaseIdentity(business_id="case-1", revision=3),
        input_schema=SchemaReference.for_model(Input, identity="input", revision=1),
        expected_output_schema=SchemaReference.for_model(
            Output, identity="output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="metadata", revision=1
        ),
        task_input=Input(value="one"),
        expected_output=Output(label="one"),
        metadata=Metadata(source="human"),
        description="A selected case.",
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite", revision=4),
        description="A suite.",
        task_contract=EvaluationTaskContract(
            input_schema=case.input_schema,
            output_schema=case.expected_output_schema,
            metadata_schema=case.metadata_schema,
        ),
        requirement_catalog=EvaluationRequirementCatalog(),
        case_evaluators=(ConfiguredEvaluator(name="exact", evaluator_revision=2),),
        suite_case_evaluators=(ConfiguredEvaluatorReference(name="exact"),),
        report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
    )
    gold_set = construct_evaluation_gold_set(
        identity=EvaluationGoldSetIdentity(business_id="gold", revision=2),
        description="A gold set.",
        task_contract=EvaluationTaskContract(
            input_schema=case.input_schema,
            output_schema=case.expected_output_schema,
            metadata_schema=case.metadata_schema,
        ),
        cases=(case,),
        split_ratio=TEST_SPLIT_RATIO,
        pinned_splits={case.identity.business_id: EvaluationSplit.HELD_OUT},
    ).gold_set

    plan = preflight_selected_cases(
        suite=suite,
        gold_set=gold_set,
        cases=(case,),
    )

    assert plan.suite.business_id == "suite"
    assert plan.suite.revision == 4
    assert plan.gold_set.revision == 2
    assert len(plan.cases) == 1
    planned_case = plan.cases[0]
    assert planned_case.case == EvaluationCaseRevisionReference.from_case(case)
    assert planned_case.requirements == ()
    assert planned_case.evaluators[0].reference == ConfiguredEvaluatorReference(
        name="exact", evaluator_revision=2
    )
    assert planned_case.evaluators[0].provenance == ("suite-wide",)
    second_plan = preflight_selected_cases(
        suite=suite,
        gold_set=gold_set,
        cases=(case,),
    )
    assert plan.canonical_json == second_plan.canonical_json
    assert plan.readable_json != plan.canonical_json


def _case(
    business_id: str,
    *,
    requirements: tuple[str, ...] = (),
    input_schema: SchemaReference | None = None,
) -> EvaluationCase[Input, Output, Metadata]:
    return EvaluationCase(
        identity=EvaluationCaseIdentity(business_id=business_id, revision=1),
        input_schema=input_schema
        or SchemaReference.for_model(Input, identity="input", revision=1),
        expected_output_schema=SchemaReference.for_model(
            Output, identity="output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="metadata", revision=1
        ),
        task_input=Input(value=business_id),
        expected_output=Output(label=business_id),
        metadata=Metadata(source="human"),
        description=f"Case {business_id}.",
        requirements=requirements,
    )


def _gold_set(cases: tuple[EvaluationCase[Input, Output, Metadata], ...]) -> EvaluationGoldSet:
    return construct_evaluation_gold_set(
        identity=EvaluationGoldSetIdentity(business_id="gold", revision=1),
        description="A gold set.",
        task_contract=EvaluationTaskContract(
            input_schema=cases[0].input_schema,
            output_schema=cases[0].expected_output_schema,
            metadata_schema=cases[0].metadata_schema,
        ),
        cases=cases,
        split_ratio=TEST_SPLIT_RATIO,
    ).gold_set


def _suite(
    *,
    cases: tuple[ConfiguredEvaluator, ...] = (),
    suite_wide: tuple[ConfiguredEvaluatorReference, ...] = (),
    catalog: EvaluationRequirementCatalog | None = None,
    bindings: tuple[EvaluationRequirementBinding, ...] = (),
) -> EvaluationSuite:
    input_schema = SchemaReference.for_model(Input, identity="input", revision=1)
    output_schema = SchemaReference.for_model(Output, identity="output", revision=1)
    metadata_schema = SchemaReference.for_model(Metadata, identity="metadata", revision=1)
    return EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite", revision=1),
        description="A suite.",
        task_contract=EvaluationTaskContract(
            input_schema=input_schema,
            output_schema=output_schema,
            metadata_schema=metadata_schema,
        ),
        requirement_catalog=catalog or EvaluationRequirementCatalog(),
        case_evaluators=cases,
        suite_case_evaluators=suite_wide,
        requirement_bindings=bindings,
        report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
    )


def test_preflight_unions_all_relevant_bindings_once_and_retains_provenance():
    case = _case("case-1", requirements=("grounding", "tone"))
    exact = ConfiguredEvaluator(name="exact", evaluator_revision=1)
    grounding = ConfiguredEvaluator(name="grounding", evaluator_revision=2)
    tone = ConfiguredEvaluator(name="tone", evaluator_revision=3)
    suite = _suite(
        cases=(exact, grounding, tone),
        suite_wide=(ConfiguredEvaluatorReference(name="exact"),),
        catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(key="grounding", semantic_description="Source grounding."),
                EvaluationRequirement(key="tone", semantic_description="Tone judgment."),
            )
        ),
        bindings=(
            EvaluationRequirementBinding(
                requirement="grounding",
                evaluators=(
                    ConfiguredEvaluatorReference(name="exact"),
                    ConfiguredEvaluatorReference(name="grounding"),
                ),
            ),
            EvaluationRequirementBinding(
                requirement="tone",
                evaluators=(
                    ConfiguredEvaluatorReference(name="exact"),
                    ConfiguredEvaluatorReference(name="tone"),
                ),
            ),
        ),
    )

    plan = preflight_selected_cases(suite=suite, gold_set=_gold_set((case,)), cases=(case,))

    assert [entry.reference.name for entry in plan.cases[0].evaluators] == [
        "exact",
        "grounding",
        "tone",
    ]
    assert plan.cases[0].evaluators[0].provenance == (
        "suite-wide",
        "grounding",
        "tone",
    )
    assert plan.cases[0].evaluators[1].provenance == ("grounding",)
    assert plan.cases[0].evaluators[2].provenance == ("tone",)


def test_preflight_raises_once_with_every_distinct_compatibility_issue():
    first = _case(
        "first",
        input_schema=SchemaReference.for_model(
            Input, identity="other-input", revision=1
        ),
    )
    second = _case("second", requirements=("unknown",)).model_copy(
        update={
            "metadata_schema": SchemaReference.for_model(
                Metadata, identity="other-metadata", revision=1
            )
        }
    )
    gold_set = _gold_set((_case("member"),)).model_copy(
        update={
            "memberships": (
                EvaluationGoldSetMembership(
                    case=EvaluationCaseRevisionReference.from_case(first),
                    split=EvaluationSplit.HELD_OUT,
                ),
                EvaluationGoldSetMembership(
                    case=EvaluationCaseRevisionReference.from_case(second),
                    split=EvaluationSplit.HELD_OUT,
                ),
            )
        }
    )

    with pytest.raises(EvaluationPreflightError) as raised:
        preflight_selected_cases(
            suite=_suite(),
            gold_set=gold_set,
            cases=(first, second),
        )

    assert {
        (
            issue.category,
            issue.case_business_id,
            issue.schema_role,
            issue.requirement,
        )
        for issue in raised.value.issues
    } == {
        ("task_contract", "first", "input", None),
        ("task_contract", "second", "metadata", None),
        ("unknown_requirement", "second", None, "unknown"),
    }


def test_validate_cases_rejects_a_case_contract_mismatch_before_selection():
    compatible = _case("compatible")
    unknown = _case("unknown", requirements=("not-in-catalog",))
    incompatible = _case(
        "incompatible",
        requirements=("grounding",),
        input_schema=SchemaReference.for_model(Input, identity="other-input", revision=1),
    )
    suite = _suite(
        catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(key="grounding", semantic_description="Source grounding."),
            )
        )
    )
    # Construction does not check member-versus-contract schemas: the slimmed
    # EvaluationCaseRevisionReference carries none. validate_cases is the seam.
    incompatible_gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold", revision=1),
        description="A gold set.",
        task_contract=EvaluationTaskContract(
            input_schema=compatible.input_schema,
            output_schema=compatible.expected_output_schema,
            metadata_schema=compatible.metadata_schema,
        ),
        memberships=tuple(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(evaluation_case),
                split=EvaluationSplit.HELD_OUT,
            )
            for evaluation_case in (compatible, unknown, incompatible)
        ),
    )

    with pytest.raises(ValueError, match="input schema"):
        incompatible_gold_set.validate_cases((compatible, unknown, incompatible))

    gold_set = _gold_set((compatible, unknown))

    with pytest.raises(EvaluationPreflightError) as raised:
        preflight_selected_cases(
            suite=suite,
            gold_set=gold_set,
            cases=(compatible, unknown),
        )
    subset_plan = preflight_selected_cases(
        suite=suite,
        gold_set=gold_set,
        cases=(compatible, unknown),
        selection={"compatible"},
    )

    assert {
        (issue.category, issue.case_business_id, issue.requirement)
        for issue in raised.value.issues
    } == {
        ("unknown_requirement", "unknown", "not-in-catalog")
    }
    assert [entry.case.business_id for entry in subset_plan.cases] == ["compatible"]


@pytest.mark.parametrize("mismatched_field", ("input", "output", "metadata"))
def test_preflight_rejects_suite_and_gold_set_contract_mismatch_before_selection(
    mismatched_field,
):
    case = _case("compatible")
    gold_set = _gold_set((case,))
    mismatched_schema = SchemaReference.for_model(
        {"input": Input, "output": Output, "metadata": Metadata}[mismatched_field],
        identity=f"different-{mismatched_field}",
        revision=1,
    )
    contract_schemas = {
        "input_schema": case.input_schema,
        "output_schema": case.expected_output_schema,
        "metadata_schema": case.metadata_schema,
    }
    contract_schemas[f"{mismatched_field}_schema"] = mismatched_schema
    suite = _suite().model_copy(
        update={
            "task_contract": EvaluationTaskContract(
                **contract_schemas,
            )
        }
    )

    with pytest.raises(EvaluationPreflightError) as raised:
        preflight_selected_cases(
            suite=suite,
            gold_set=gold_set,
            cases=(case,),
            selection={"does-not-select-any-case"},
        )

    assert any(issue.category == "task_contract" for issue in raised.value.issues)
    assert any("Gold Set" in issue.message for issue in raised.value.issues)


def test_incompatible_preflight_cannot_produce_a_plan_for_run_creation():
    first = _case("first", requirements=("grounding",))
    second = _case("second", requirements=("unknown",))
    suite = _suite(
        catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(key="grounding", semantic_description="Grounding."),
            )
        )
    )
    gold_set = _gold_set((first, second))

    with pytest.raises(EvaluationPreflightError) as raised:
        preflight_selected_cases(
            suite=suite,
            gold_set=gold_set,
            cases=(first, second),
        )

    assert {issue.requirement for issue in raised.value.issues} == {
        "grounding",
        "unknown",
    }


def test_incompatible_preflight_leaves_no_evaluation_run_in_the_ledger(tmp_path):
    """An incompatible preflight must not accumulate a run, per ADR 0005.

    `EvaluationRunner.run` now requires a Resolved Evaluation Plan, and an
    incompatible preflight produces none. Preflight is therefore the fence the
    runner used to be, and it is only worth anything if the ledger stays empty
    afterwards — which is what this asserts.
    """
    first = _case("first", requirements=("grounding",))
    second = _case("second", requirements=("unknown",))
    suite = _suite(
        catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(key="grounding", semantic_description="Grounding."),
            )
        )
    )
    gold_set = _gold_set((first, second))

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        runner = EvaluationRunner(ledger)

        with pytest.raises(EvaluationPreflightError) as raised:
            preflight_selected_cases(
                suite=suite,
                gold_set=gold_set,
                cases=(first, second),
            )

        # Preflight raised instead of returning, so there is no plan to hand
        # to the runner and no run can be created.
        assert raised.value.issues
        assert ledger.list_evaluation_runs() == []


def test_a_resolved_evaluation_plan_cannot_be_constructed_outside_preflight():
    """Only preflight may resolve a plan, so the fence cannot be walked around.

    A plan asserts its cases were checked against the Suite task contract and
    the runner does not re-check, so hand-building one would reach execution
    with unchecked cases.
    """
    from knowledge_map.evaluation.preflight import (
        EvaluationDefinitionRevisionReference,
        ResolvedEvaluationPlan,
    )

    reference = EvaluationDefinitionRevisionReference(
        record_id="00000000-0000-0000-0000-000000000001",
        business_id="fabricated",
        revision=1,
        content_hash="a" * 64,
    )

    with pytest.raises(TypeError, match="cannot be constructed directly"):
        ResolvedEvaluationPlan(suite=reference, gold_set=reference, cases=())

    # model_validate is not a way around it either.
    with pytest.raises(TypeError, match="cannot be constructed directly"):
        ResolvedEvaluationPlan.model_validate(
            {
                "suite": reference.model_dump(mode="json"),
                "gold_set": reference.model_dump(mode="json"),
                "cases": [],
            }
        )


def test_a_frozen_plan_rehydrates_from_its_own_stored_bytes():
    """The ledger must still read back plan bytes it froze, fence notwithstanding."""
    from knowledge_map.evaluation.preflight import ResolvedEvaluationPlan

    case = _case("first")
    plan = preflight_selected_cases(
        suite=_suite(), gold_set=_gold_set((case,)), cases=(case,)
    )

    rehydrated = ResolvedEvaluationPlan.from_frozen_json(plan.canonical_json)

    assert rehydrated == plan
