from pydantic import BaseModel, SecretStr, ValidationError
import pytest

from knowledge_map.evaluation import (
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationRubric,
    EvaluationRubricIdentity,
    EvaluationSplit,
    EvaluationCase,
    EvaluationCaseIdentity,
    AuthoredDefinitionConflictError,
    DeclaredArtifactReference,
    SchemaReference,
    assert_same_revision_content,
    canonical_configuration_json,
    configuration_fingerprint,
)


class RelevanceInput(BaseModel):
    headline: str


class RelevanceOutput(BaseModel):
    is_relevant: bool


class RelevanceMetadata(BaseModel):
    source: str


class ProviderSettings(BaseModel):
    model: str
    auth_value: SecretStr


def test_authored_evaluation_case_round_trips_with_its_exact_typed_contract():
    input_schema = SchemaReference.for_model(
        RelevanceInput, identity="ca-map.relevance.input", revision=1
    )
    output_schema = SchemaReference.for_model(
        RelevanceOutput, identity="ca-map.relevance.output", revision=1
    )
    metadata_schema = SchemaReference.for_model(
        RelevanceMetadata, identity="ca-map.relevance.metadata", revision=1
    )
    authored_case = EvaluationCase[RelevanceInput, RelevanceOutput, RelevanceMetadata](
        identity=EvaluationCaseIdentity(business_id="relevance-001", revision=1),
        input_schema=input_schema,
        expected_output_schema=output_schema,
        metadata_schema=metadata_schema,
        task_input=RelevanceInput(headline="Governor proposes housing bill"),
        expected_output=RelevanceOutput(is_relevant=True),
        metadata=RelevanceMetadata(source="human-reviewed"),
        description="A California policy headline is relevant.",
        tags=("held-out", "housing"),
        artifacts=(
            DeclaredArtifactReference(
                content_hash="a" * 64,
                role="case.source-article",
            ),
        ),
    )

    restored_case = EvaluationCase[
        RelevanceInput, RelevanceOutput, RelevanceMetadata
    ].model_validate_json(authored_case.model_dump_json())

    assert restored_case == authored_case
    assert restored_case.content_hash == authored_case.content_hash
    assert restored_case.identity.record_id.version == 7
    assert restored_case.task_input == RelevanceInput(
        headline="Governor proposes housing bill"
    )
    assert restored_case.artifacts[0].role == "case.source-article"


def test_gold_set_membership_freezes_an_exact_case_revision_and_owns_its_split():
    authored_case = EvaluationCase[RelevanceInput, RelevanceOutput, RelevanceMetadata](
        identity=EvaluationCaseIdentity(business_id="relevance-001", revision=1),
        input_schema=SchemaReference.for_model(
            RelevanceInput, identity="ca-map.relevance.input", revision=1
        ),
        expected_output_schema=SchemaReference.for_model(
            RelevanceOutput, identity="ca-map.relevance.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            RelevanceMetadata, identity="ca-map.relevance.metadata", revision=1
        ),
        task_input=RelevanceInput(headline="Governor proposes housing bill"),
        expected_output=RelevanceOutput(is_relevant=True),
        metadata=RelevanceMetadata(source="human-reviewed"),
        description="A California policy headline is relevant.",
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="relevance-gold", revision=1),
        description="Reviewed relevance examples.",
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(authored_case),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )

    restored_gold_set = EvaluationGoldSet.model_validate_json(gold_set.model_dump_json())

    assert restored_gold_set == gold_set
    assert gold_set.memberships[0].case.content_hash == authored_case.content_hash
    assert gold_set.memberships[0].split is EvaluationSplit.HELD_OUT


def test_reusing_a_case_business_identity_and_revision_for_changed_content_is_rejected():
    schema_references = {
        "input_schema": SchemaReference.for_model(
            RelevanceInput, identity="ca-map.relevance.input", revision=1
        ),
        "expected_output_schema": SchemaReference.for_model(
            RelevanceOutput, identity="ca-map.relevance.output", revision=1
        ),
        "metadata_schema": SchemaReference.for_model(
            RelevanceMetadata, identity="ca-map.relevance.metadata", revision=1
        ),
    }
    existing_case = EvaluationCase[RelevanceInput, RelevanceOutput, RelevanceMetadata](
        identity=EvaluationCaseIdentity(business_id="relevance-001", revision=1),
        **schema_references,
        task_input=RelevanceInput(headline="Governor proposes housing bill"),
        expected_output=RelevanceOutput(is_relevant=True),
        metadata=RelevanceMetadata(source="human-reviewed"),
        description="A California policy headline is relevant.",
    )
    changed_case = EvaluationCase[RelevanceInput, RelevanceOutput, RelevanceMetadata](
        identity=EvaluationCaseIdentity(business_id="relevance-001", revision=1),
        **schema_references,
        task_input=RelevanceInput(headline="Governor proposes housing bill"),
        expected_output=RelevanceOutput(is_relevant=False),
        metadata=RelevanceMetadata(source="human-reviewed"),
        description="A California policy headline is relevant.",
    )

    with pytest.raises(
        AuthoredDefinitionConflictError,
        match="content changed without a new revision",
    ):
        assert_same_revision_content(existing_case, changed_case)


def test_canonical_configuration_removes_credentials_before_serialization_and_hashing():
    first_configuration = {
        "provider": "openai",
        "model": "gpt-5",
        "credentials": {"api_key": "first-secret"},
        "parameters": {"temperature": 0},
    }
    second_configuration = {
        "provider": "openai",
        "model": "gpt-5",
        "credentials": {"api_key": "rotated-secret"},
        "parameters": {"temperature": 0},
    }

    serialized = canonical_configuration_json(first_configuration)

    assert "first-secret" not in serialized
    assert "api_key" not in serialized
    assert configuration_fingerprint(first_configuration) == configuration_fingerprint(
        second_configuration
    )


def test_canonical_configuration_omits_typed_secrets_even_with_a_nonstandard_name():
    serialized = canonical_configuration_json(
        ProviderSettings(model="gpt-5", auth_value=SecretStr("a-secret"))
    )

    assert "a-secret" not in serialized
    assert "auth_value" not in serialized


def test_rubric_round_trips_as_an_immutable_authored_revision():
    rubric = EvaluationRubric(
        identity=EvaluationRubricIdentity(business_id="relevance-rubric", revision=2),
        description="Judge the political relevance of California headlines.",
        criteria=("The headline concerns California politics or public policy.",),
        assertions=("Do not treat generic California geography as sufficient.",),
    )

    restored_rubric = EvaluationRubric.model_validate_json(rubric.model_dump_json())

    assert restored_rubric == rubric
    assert restored_rubric.content_hash == rubric.content_hash


def test_schema_references_require_exact_identity_and_revision_not_similar_structure():
    first_reference = SchemaReference.for_model(
        RelevanceInput, identity="ca-map.relevance.input", revision=1
    )
    differently_identified_reference = SchemaReference.for_model(
        RelevanceInput, identity="other-component.input", revision=1
    )

    assert not first_reference.is_exactly_compatible_with(
        differently_identified_reference
    )


def test_case_rejects_evaluator_configuration_as_non_authored_case_data():
    with pytest.raises(ValidationError, match="evaluator_configuration"):
        EvaluationCase[RelevanceInput, RelevanceOutput, RelevanceMetadata](
            identity=EvaluationCaseIdentity(business_id="relevance-001", revision=1),
            input_schema=SchemaReference.for_model(
                RelevanceInput, identity="ca-map.relevance.input", revision=1
            ),
            expected_output_schema=SchemaReference.for_model(
                RelevanceOutput, identity="ca-map.relevance.output", revision=1
            ),
            metadata_schema=SchemaReference.for_model(
                RelevanceMetadata, identity="ca-map.relevance.metadata", revision=1
            ),
            task_input=RelevanceInput(headline="Governor proposes housing bill"),
            expected_output=RelevanceOutput(is_relevant=True),
            metadata=RelevanceMetadata(source="human-reviewed"),
            description="A California policy headline is relevant.",
            evaluator_configuration={"provider": "not allowed"},
        )
