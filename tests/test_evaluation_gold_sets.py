from __future__ import annotations

from collections import Counter
from random import Random

from pydantic import BaseModel
import pytest

from knowledge_map.evaluation import (
    DeclaredArtifactReference,
    EvaluationCase,
    EvaluationCaseIdentity,
    EvaluationGoldSetConstructionError,
    EvaluationGoldSetIdentity,
    EvaluationSplit,
    EvaluationTaskContract,
    SQLiteEvaluationLedger,
    SchemaReference,
    construct_evaluation_gold_set,
    revise_evaluation_gold_set,
)


class Input(BaseModel):
    prompt: str


class Output(BaseModel):
    answer: str


class Metadata(BaseModel):
    source: str


class AlternateInput(BaseModel):
    text: str


class AlternateOutput(BaseModel):
    label: str


class AlternateMetadata(BaseModel):
    annotator: str


INPUT_SCHEMA = SchemaReference.for_model(Input, identity="tests.input", revision=1)
OUTPUT_SCHEMA = SchemaReference.for_model(Output, identity="tests.output", revision=1)
METADATA_SCHEMA = SchemaReference.for_model(
    Metadata, identity="tests.metadata", revision=1
)
TASK_CONTRACT = EvaluationTaskContract(
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    metadata_schema=METADATA_SCHEMA,
)
DEFAULT_RATIO = {
    EvaluationSplit.TRAINING: 0.6,
    EvaluationSplit.CALIBRATION: 0.2,
    EvaluationSplit.HELD_OUT: 0.2,
}


def make_case(
    business_id: str,
    *,
    input_schema: SchemaReference = INPUT_SCHEMA,
    expected_output_schema: SchemaReference | None = OUTPUT_SCHEMA,
    metadata_schema: SchemaReference = METADATA_SCHEMA,
) -> EvaluationCase:
    return EvaluationCase(
        identity=EvaluationCaseIdentity(business_id=business_id, revision=1),
        input_schema=input_schema,
        expected_output_schema=expected_output_schema,
        metadata_schema=metadata_schema,
        task_input=(
            Input(prompt=business_id)
            if input_schema == INPUT_SCHEMA
            else AlternateInput(text=business_id)
        ),
        expected_output=(
            None
            if expected_output_schema is None
            else Output(answer=business_id)
            if expected_output_schema == OUTPUT_SCHEMA
            else AlternateOutput(label=business_id)
        ),
        metadata=(
            Metadata(source="test")
            if metadata_schema == METADATA_SCHEMA
            else AlternateMetadata(annotator="test")
        ),
        description=f"Case {business_id}",
    )


def construct(cases, **overrides):
    arguments = {
        "identity": EvaluationGoldSetIdentity(business_id="gold-set", revision=1),
        "description": "A constructed Gold Set.",
        "task_contract": TASK_CONTRACT,
        "cases": cases,
        "split_ratio": DEFAULT_RATIO,
    }
    arguments.update(overrides)
    return construct_evaluation_gold_set(**arguments)


def assignments(result):
    return {
        membership.case.business_id: membership.split
        for membership in result.gold_set.memberships
    }


def revise(previous, **overrides):
    arguments = {
        "previous": previous.gold_set,
        "split_ratio": DEFAULT_RATIO,
    }
    arguments.update(overrides)
    return revise_evaluation_gold_set(**arguments)


def test_constructs_references_and_reports_actual_split_counts():
    cases = tuple(make_case(f"case-{index}") for index in range(12))

    result = construct(cases)

    assert tuple(membership.case.record_id for membership in result.gold_set.memberships) == tuple(
        evaluation_case.identity.record_id
        for evaluation_case in sorted(cases, key=lambda item: item.identity.business_id)
    )
    assert result.split_counts == {
        split: Counter(membership.split for membership in result.gold_set.memberships)[split]
        for split in EvaluationSplit
    }
    with pytest.raises(Exception, match="frozen"):
        result.gold_set.description = "changed"


def test_reports_every_schema_mismatch_in_one_error():
    cases = (
        make_case(
            "wrong-input",
            input_schema=SchemaReference.for_model(
                AlternateInput, identity="tests.alternate-input", revision=1
            ),
        ),
        make_case(
            "wrong-output",
            expected_output_schema=SchemaReference.for_model(
                AlternateOutput, identity="tests.alternate-output", revision=1
            ),
        ),
        make_case(
            "wrong-metadata",
            metadata_schema=SchemaReference.for_model(
                AlternateMetadata, identity="tests.alternate-metadata", revision=1
            ),
        ),
    )

    with pytest.raises(EvaluationGoldSetConstructionError) as raised:
        construct(cases)

    assert [(issue.case_business_id, issue.schema_role) for issue in raised.value.issues] == [
        ("wrong-input", "input"),
        ("wrong-output", "expected_output"),
        ("wrong-metadata", "metadata"),
    ]
    assert "wrong-input@1" in str(raised.value)
    assert "expected-output schema" in str(raised.value)


def test_accepts_a_case_without_an_expected_output():
    unlabeled = make_case("unlabeled", expected_output_schema=None)

    result = construct((unlabeled,))

    assert result.gold_set.memberships[0].case.content_hash == unlabeled.content_hash


def test_assignment_is_independent_of_order_and_population_membership():
    cases = [make_case(f"case-{index}") for index in range(40)]
    shuffled = list(cases)
    Random(7).shuffle(shuffled)

    original = construct(cases)
    reordered = construct(shuffled)
    expanded = construct((*cases, make_case("one-more")))

    assert original.gold_set.memberships == reordered.gold_set.memberships
    assert original.gold_set.content_hash == reordered.gold_set.content_hash
    assert assignments(original) == {
        business_id: split
        for business_id, split in assignments(expanded).items()
        if business_id != "one-more"
    }


def test_realized_proportions_approximate_the_requested_ratio():
    cases = tuple(make_case(f"population-{index}") for index in range(10_000))

    result = construct(cases)

    for split, requested_share in DEFAULT_RATIO.items():
        assert result.split_counts[split] / len(cases) == pytest.approx(
            requested_share, abs=0.015
        )


def test_ratio_validation_and_zero_share():
    case = make_case("only-case")

    with pytest.raises(ValueError, match="sum to one"):
        construct(
            (case,),
            split_ratio={
                EvaluationSplit.TRAINING: 0.5,
                EvaluationSplit.CALIBRATION: 0.3,
                EvaluationSplit.HELD_OUT: 0.3,
            },
        )

    result = construct(
        (case,),
        split_ratio={
            EvaluationSplit.TRAINING: 0.0,
            EvaluationSplit.CALIBRATION: 0.0,
            EvaluationSplit.HELD_OUT: 1.0,
        },
    )
    assert result.split_counts == {
        EvaluationSplit.TRAINING: 0,
        EvaluationSplit.CALIBRATION: 0,
        EvaluationSplit.HELD_OUT: 1,
    }


def test_pinned_cases_override_assignment_without_changing_other_cases():
    pinned = make_case("pinned")
    ordinary = make_case("ordinary")
    unpinned_result = construct((pinned, ordinary))

    pinned_result = construct(
        (pinned, ordinary),
        pinned_splits={"pinned": EvaluationSplit.HELD_OUT},
    )

    assert assignments(pinned_result)["pinned"] is EvaluationSplit.HELD_OUT
    assert assignments(pinned_result)["ordinary"] is assignments(unpinned_result)[
        "ordinary"
    ]


def test_artifacts_pass_through_unresolved_and_remain_ledger_checked(tmp_path):
    case = make_case("artifact-case")
    artifact = DeclaredArtifactReference(content_hash="a" * 64, role="source")
    result = construct((case,), artifacts=(artifact,))

    assert result.gold_set.artifacts == (artifact,)
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        ledger.import_case(case)
        with pytest.raises(KeyError, match="unknown Evaluation Artifact"):
            ledger.import_gold_set(result.gold_set)


def test_factory_built_gold_set_imports_with_expected_memberships(tmp_path):
    cases = (make_case("first"), make_case("second"))
    result = construct(
        cases,
        pinned_splits={
            "first": EvaluationSplit.TRAINING,
            "second": EvaluationSplit.CALIBRATION,
        },
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        for evaluation_case in cases:
            ledger.import_case(evaluation_case)
        ledger.import_gold_set(result.gold_set)
        rows = ledger.list_gold_set_memberships(result.gold_set.identity.record_id)

    assert {row.case_business_id: row.split for row in rows} == assignments(result)


def test_identical_inputs_produce_identical_content_hashes():
    cases = (make_case("first"), make_case("second"))
    identity = EvaluationGoldSetIdentity(business_id="stable", revision=1)

    first = construct(cases, identity=identity)
    second = construct(cases, identity=identity)

    assert first.gold_set.content_hash == second.gold_set.content_hash


@pytest.mark.parametrize(
    ("cases_to_add", "case_business_ids_to_remove", "expected_business_ids"),
    [
        ((make_case("added"),), (), {"added", "first", "second"}),
        ((), ("first",), {"second"}),
        ((make_case("added"),), ("first",), {"added", "second"}),
    ],
)
def test_revision_adds_and_removes_cases_while_preserving_surviving_splits(
    cases_to_add,
    case_business_ids_to_remove,
    expected_business_ids,
):
    previous = construct(
        (make_case("first"), make_case("second")),
        pinned_splits={
            "first": EvaluationSplit.CALIBRATION,
            "second": EvaluationSplit.HELD_OUT,
        },
    )

    revised = revise(
        previous,
        cases_to_add=cases_to_add,
        case_business_ids_to_remove=case_business_ids_to_remove,
    )

    assert revised.gold_set.identity.business_id == previous.gold_set.identity.business_id
    assert revised.gold_set.identity.revision == previous.gold_set.identity.revision + 1
    assert set(assignments(revised)) == expected_business_ids
    if "second" in expected_business_ids:
        assert assignments(revised)["second"] is EvaluationSplit.HELD_OUT
    if "first" in expected_business_ids:
        assert assignments(revised)["first"] is EvaluationSplit.CALIBRATION


def test_revision_assigns_only_new_cases_by_the_construction_rule():
    survivor = make_case("survivor")
    added = make_case("added")
    previous = construct(
        (survivor,),
        pinned_splits={"survivor": EvaluationSplit.HELD_OUT},
    )
    all_training = {
        EvaluationSplit.TRAINING: 1.0,
        EvaluationSplit.CALIBRATION: 0.0,
        EvaluationSplit.HELD_OUT: 0.0,
    }

    revised = revise(
        previous,
        cases_to_add=(added,),
        split_ratio=all_training,
    )
    independently_constructed = construct((added,), split_ratio=all_training)

    assert assignments(revised)["survivor"] is EvaluationSplit.HELD_OUT
    assert assignments(revised)["added"] is assignments(independently_constructed)[
        "added"
    ]


def test_removal_only_revision_needs_no_split_ratio():
    previous = construct(
        (make_case("first"), make_case("second")),
        pinned_splits={
            "first": EvaluationSplit.CALIBRATION,
            "second": EvaluationSplit.HELD_OUT,
        },
    )

    revised = revise_evaluation_gold_set(
        previous=previous.gold_set,
        case_business_ids_to_remove=("first",),
    )

    assert assignments(revised) == {"second": EvaluationSplit.HELD_OUT}


def test_revision_rejects_added_cases_without_a_split_ratio():
    previous = construct((make_case("first"),))

    with pytest.raises(ValueError, match="split ratio is required"):
        revise_evaluation_gold_set(
            previous=previous.gold_set,
            cases_to_add=(make_case("added"),),
        )


def test_revision_rejects_a_no_op_and_unknown_removals():
    previous = construct((make_case("first"),))

    with pytest.raises(ValueError, match="must add or remove"):
        revise(previous)
    with pytest.raises(ValueError, match="absent from the previous"):
        revise(previous, case_business_ids_to_remove=("unknown",))


def test_revision_offers_no_seam_to_change_the_task_contract():
    previous = construct((make_case("first"),))
    changed_contract = EvaluationTaskContract(
        input_schema=INPUT_SCHEMA,
        output_schema=SchemaReference.for_model(
            AlternateOutput, identity="tests.alternate-output", revision=1
        ),
        metadata_schema=METADATA_SCHEMA,
    )

    with pytest.raises(TypeError, match="task_contract"):
        revise(
            previous,
            cases_to_add=(make_case("added"),),
            task_contract=changed_contract,
        )

    revised = revise(previous, cases_to_add=(make_case("added"),))
    assert revised.gold_set.task_contract == previous.gold_set.task_contract


def test_revision_accumulates_added_case_compatibility_issues():
    previous = construct((make_case("first"),))
    incompatible_cases = (
        make_case(
            "wrong-input",
            input_schema=SchemaReference.for_model(
                AlternateInput, identity="tests.alternate-input", revision=1
            ),
        ),
        make_case(
            "wrong-metadata",
            metadata_schema=SchemaReference.for_model(
                AlternateMetadata, identity="tests.alternate-metadata", revision=1
            ),
        ),
    )

    with pytest.raises(EvaluationGoldSetConstructionError) as raised:
        revise(previous, cases_to_add=incompatible_cases)

    assert [(issue.case_business_id, issue.schema_role) for issue in raised.value.issues] == [
        ("wrong-input", "input"),
        ("wrong-metadata", "metadata"),
    ]


def test_revision_result_is_frozen_and_inherits_authored_metadata():
    artifact = DeclaredArtifactReference(content_hash="a" * 64, role="source")
    previous = construct(
        (make_case("first"),),
        description="Original description.",
        tags=("stable",),
        artifacts=(artifact,),
    )

    revised = revise(previous, cases_to_add=(make_case("added"),))

    assert revised.gold_set.description == previous.gold_set.description
    assert revised.gold_set.tags == previous.gold_set.tags
    assert revised.gold_set.artifacts == previous.gold_set.artifacts
    assert revised.gold_set.task_contract == previous.gold_set.task_contract
    with pytest.raises(Exception, match="frozen"):
        revised.gold_set.description = "changed"
