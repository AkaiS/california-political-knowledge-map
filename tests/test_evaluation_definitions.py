from dataclasses import dataclass

from pydantic import BaseModel, SecretStr, ValidationError
from pydantic_evals.evaluators import (
    Evaluator,
    EvaluatorContext,
    ReportEvaluator,
    ReportEvaluatorContext,
)
from pydantic_evals.reporting.analyses import ScalarResult
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
from knowledge_map.evaluation.suites import (
    CustomComparisonOperation,
    ConfiguredEvaluator,
    EvaluationComparisonResult,
    EvaluationMetricDefinition,
    EvaluationMetricReference,
    EvaluationMetricValueType,
    EvaluationRubricRevisionReference,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    NoComparisonOperation,
    OrderedComparisonOperation,
)


class RelevanceInput(BaseModel):
    headline: str


class RelevanceOutput(BaseModel):
    is_relevant: bool


class RelevanceMetadata(BaseModel):
    source: str


class RelevanceBreakdown(BaseModel):
    true_positives: int
    false_negatives: int


class ProviderSettings(BaseModel):
    model: str
    auth_value: SecretStr


@dataclass
class ExactRelevanceOutput(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output == ctx.expected_output


@dataclass
class CountEvaluatedCases(ReportEvaluator):
    def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        return ScalarResult(title="Evaluated cases", value=len(ctx.report.cases))


def test_number_metric_compares_values_under_its_revisioned_ordering_contract():
    operation = OrderedComparisonOperation(
        namespaced_name="ca-map.comparison.ordered-scalar",
        revision=1,
        higher_is_better=True,
    )
    metric = EvaluationMetricDefinition(
        namespaced_name="ca-map.relevance.accuracy",
        evaluator_revision=2,
        value_type=EvaluationMetricValueType.NUMBER,
        semantic_description="Fraction of relevance classifications that match review.",
        comparison_operation=operation,
    )

    assert metric.identity == ("ca-map.relevance.accuracy", 2)
    assert operation.identity == ("ca-map.comparison.ordered-scalar", 1)
    assert metric.compare(candidate=0.92, baseline=0.87) is EvaluationComparisonResult.BETTER
    assert metric.compare(candidate=0.87, baseline=0.87) is EvaluationComparisonResult.EQUIVALENT
    assert metric.compare(candidate=0.83, baseline=0.87) is EvaluationComparisonResult.WORSE


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (EvaluationMetricValueType.NUMBER, 0.5),
        (EvaluationMetricValueType.INTEGER, 3),
        (EvaluationMetricValueType.BOOLEAN, True),
        (EvaluationMetricValueType.STRING, "review-needed"),
    ],
)
def test_metric_definition_validates_each_declared_scalar_value_type(value_type, value):
    metric = EvaluationMetricDefinition(
        namespaced_name="ca-map.relevance.deterministic-check",
        evaluator_revision=1,
        value_type=value_type,
        semantic_description="A deterministic suite-local evaluation result.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="ca-map.comparison.none", revision=1
        ),
    )

    assert metric.validate_value(value) == value
    assert (
        metric.compare(candidate=value, baseline=value)
        is EvaluationComparisonResult.INCOMPARABLE
    )


def test_structured_metric_values_must_match_their_exact_schema_revision():
    metric = EvaluationMetricDefinition(
        namespaced_name="ca-map.relevance.error-breakdown",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=SchemaReference.for_model(
            RelevanceBreakdown, identity="ca-map.relevance.error-breakdown", revision=1
        ),
        semantic_description="Counts of reviewed relevance classification errors.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="ca-map.comparison.none", revision=1
        ),
    )

    value = RelevanceBreakdown(true_positives=8, false_negatives=2)

    assert metric.validate_value(value) == value
    with pytest.raises(ValueError, match="exact Pydantic schema"):
        metric.validate_value(RelevanceOutput(is_relevant=True))


def test_structured_metric_can_use_its_evaluator_owned_comparison_operation():
    metric = EvaluationMetricDefinition(
        namespaced_name="ca-map.relevance.error-breakdown",
        evaluator_revision=2,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=SchemaReference.for_model(
            RelevanceBreakdown, identity="ca-map.relevance.error-breakdown", revision=1
        ),
        semantic_description="Counts of reviewed relevance classification errors.",
        comparison_operation=CustomComparisonOperation(
            namespaced_name="ca-map.comparison.relevance-errors",
            revision=1,
            configuration={"minimum_improvement": 1},
        ),
    )

    comparison = metric.compare(
        candidate=RelevanceBreakdown(true_positives=9, false_negatives=1),
        baseline=RelevanceBreakdown(true_positives=8, false_negatives=2),
        custom_comparator=lambda candidate, baseline, operation: (
            EvaluationComparisonResult.BETTER
            if candidate.false_negatives < baseline.false_negatives
            else EvaluationComparisonResult.EQUIVALENT
        ),
    )

    assert comparison is EvaluationComparisonResult.BETTER


def test_evaluation_suite_validates_compatible_cases_and_its_serialized_evaluators():
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
        identity=EvaluationCaseIdentity(business_id="relevance-002", revision=1),
        input_schema=input_schema,
        expected_output_schema=output_schema,
        metadata_schema=metadata_schema,
        task_input=RelevanceInput(headline="California budget negotiations continue"),
        expected_output=RelevanceOutput(is_relevant=True),
        metadata=RelevanceMetadata(source="human-reviewed"),
        description="A California political headline is relevant.",
    )
    rubric = EvaluationRubric(
        identity=EvaluationRubricIdentity(business_id="relevance-rubric", revision=1),
        description="Judge California political relevance.",
        criteria=("The headline concerns California politics or public policy.",),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="relevance-suite", revision=1),
        description="Deterministic relevance evaluation.",
        task_contract=EvaluationTaskContract(
            input_schema=input_schema,
            output_schema=output_schema,
            metadata_schema=metadata_schema,
        ),
        case_evaluators=(
            ConfiguredEvaluator(
                name="exact-output",
                evaluator_revision=1,
                configuration={"kind": "exact-output"},
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(
                name="case-count",
                evaluator_revision=1,
                configuration={"kind": "case-count"},
            ),
        ),
        rubrics=(EvaluationRubricRevisionReference.from_rubric(rubric),),
        metrics=(
            EvaluationMetricDefinition(
                namespaced_name="ca-map.relevance.exact-match",
                evaluator_revision=1,
                value_type=EvaluationMetricValueType.BOOLEAN,
                semantic_description="Whether the output matches the reviewed decision.",
                comparison_operation=NoComparisonOperation(
                    namespaced_name="ca-map.comparison.none", revision=1
                ),
            ),
        ),
    )

    assert suite.validate_cases((authored_case,)) == (authored_case,)
    assert suite.case_evaluators[0].configuration_fingerprint == configuration_fingerprint(
        {"kind": "exact-output"}
    )


def test_suite_executes_deterministic_task_and_evaluators_through_pydantic_evals():
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
        identity=EvaluationCaseIdentity(business_id="relevance-003", revision=1),
        input_schema=input_schema,
        expected_output_schema=output_schema,
        metadata_schema=metadata_schema,
        task_input=RelevanceInput(headline="California budget negotiations continue"),
        expected_output=RelevanceOutput(is_relevant=True),
        metadata=RelevanceMetadata(source="human-reviewed"),
        description="A California political headline is relevant.",
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="relevance-suite", revision=2),
        description="Deterministic relevance evaluation.",
        task_contract=EvaluationTaskContract(
            input_schema=input_schema,
            output_schema=output_schema,
            metadata_schema=metadata_schema,
        ),
        case_evaluators=(
            ConfiguredEvaluator(
                name="exact-output", evaluator_revision=1, configuration={}
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(
                name="case-count", evaluator_revision=1, configuration={}
            ),
        ),
    )

    report = suite.execute(
        cases=(authored_case,),
        task=lambda input: RelevanceOutput(is_relevant="California" in input.headline),
        evaluator_resolver=lambda configured: {
            "exact-output": ExactRelevanceOutput(),
            "case-count": CountEvaluatedCases(),
        }[configured.name],
    )

    assert report.cases[0].assertions["ExactRelevanceOutput"].value is True
    assert report.analyses[0].value == 1


def test_suite_rejects_a_revision_without_a_report_evaluator():
    with pytest.raises(ValidationError, match="report_evaluators"):
        EvaluationSuite(
            identity=EvaluationSuiteIdentity(business_id="relevance-suite", revision=3),
            description="Incomplete deterministic relevance evaluation.",
            task_contract=EvaluationTaskContract(
                input_schema=SchemaReference.for_model(
                    RelevanceInput, identity="ca-map.relevance.input", revision=1
                ),
                output_schema=SchemaReference.for_model(
                    RelevanceOutput, identity="ca-map.relevance.output", revision=1
                ),
                metadata_schema=SchemaReference.for_model(
                    RelevanceMetadata, identity="ca-map.relevance.metadata", revision=1
                ),
            ),
            report_evaluators=(),
        )


@pytest.mark.parametrize("forbidden_setting", [{"provider": "openai"}, {"model": "gpt-5"}])
def test_suite_evaluator_configuration_rejects_provider_and_model_settings(forbidden_setting):
    with pytest.raises(ValueError, match="provider or model"):
        ConfiguredEvaluator(
            name="judge",
            evaluator_revision=1,
            configuration=forbidden_setting,
        )


def test_suite_rejects_a_case_with_an_incompatible_schema_before_task_execution():
    suite_input_schema = SchemaReference.for_model(
        RelevanceInput, identity="ca-map.relevance.input", revision=1
    )
    incompatible_case = EvaluationCase[RelevanceInput, RelevanceOutput, RelevanceMetadata](
        identity=EvaluationCaseIdentity(business_id="relevance-004", revision=1),
        input_schema=SchemaReference.for_model(
            RelevanceInput, identity="other-component.input", revision=1
        ),
        expected_output_schema=SchemaReference.for_model(
            RelevanceOutput, identity="ca-map.relevance.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            RelevanceMetadata, identity="ca-map.relevance.metadata", revision=1
        ),
        task_input=RelevanceInput(headline="California budget negotiations continue"),
        expected_output=RelevanceOutput(is_relevant=True),
        metadata=RelevanceMetadata(source="human-reviewed"),
        description="A California political headline is relevant.",
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="relevance-suite", revision=4),
        description="Deterministic relevance evaluation.",
        task_contract=EvaluationTaskContract(
            input_schema=suite_input_schema,
            output_schema=SchemaReference.for_model(
                RelevanceOutput, identity="ca-map.relevance.output", revision=1
            ),
            metadata_schema=SchemaReference.for_model(
                RelevanceMetadata, identity="ca-map.relevance.metadata", revision=1
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(name="case-count", evaluator_revision=1, configuration={}),
        ),
    )

    with pytest.raises(ValueError, match="case input schema"):
        suite.execute(
            cases=(incompatible_case,),
            task=lambda _: pytest.fail("the incompatible case must never execute"),
            evaluator_resolver=lambda _: pytest.fail(
                "evaluator resolution must happen after case validation"
            ),
        )


def test_suite_rejects_evaluator_rubric_and_metric_revisions_it_does_not_declare():
    rubric = EvaluationRubric(
        identity=EvaluationRubricIdentity(business_id="relevance-rubric", revision=1),
        description="Judge California political relevance.",
        criteria=("The headline concerns California politics or public policy.",),
    )
    incompatible_rubric = EvaluationRubric(
        identity=EvaluationRubricIdentity(business_id="relevance-rubric", revision=2),
        description="A materially revised relevance rubric.",
        criteria=("Require California political relevance.",),
    )
    metric = EvaluationMetricDefinition(
        namespaced_name="ca-map.relevance.exact-match",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.BOOLEAN,
        semantic_description="Whether the output matches the reviewed decision.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="ca-map.comparison.none", revision=1
        ),
    )

    with pytest.raises(ValueError, match="rubric or metric revision"):
        EvaluationSuite(
            identity=EvaluationSuiteIdentity(business_id="relevance-suite", revision=5),
            description="Deterministic relevance evaluation.",
            task_contract=EvaluationTaskContract(
                input_schema=SchemaReference.for_model(
                    RelevanceInput, identity="ca-map.relevance.input", revision=1
                ),
                output_schema=SchemaReference.for_model(
                    RelevanceOutput, identity="ca-map.relevance.output", revision=1
                ),
                metadata_schema=SchemaReference.for_model(
                    RelevanceMetadata, identity="ca-map.relevance.metadata", revision=1
                ),
            ),
            report_evaluators=(
                ConfiguredEvaluator(
                    name="case-count",
                    evaluator_revision=1,
                    configuration={},
                    rubrics=(
                        EvaluationRubricRevisionReference.from_rubric(incompatible_rubric),
                    ),
                    metrics=(
                        EvaluationMetricReference(
                            namespaced_name=metric.namespaced_name, evaluator_revision=2
                        ),
                    ),
                ),
            ),
            rubrics=(EvaluationRubricRevisionReference.from_rubric(rubric),),
            metrics=(metric,),
        )


def test_executable_suite_contract_is_available_from_the_evaluation_package():
    from knowledge_map.evaluation import EvaluationSuite as PublicEvaluationSuite

    assert PublicEvaluationSuite is EvaluationSuite


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
        task_contract=EvaluationTaskContract(
            input_schema=authored_case.input_schema,
            output_schema=authored_case.expected_output_schema,
            metadata_schema=authored_case.metadata_schema,
        ),
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


def test_gold_set_binds_one_exact_task_contract_and_rejects_a_mismatched_member():
    authored_case = EvaluationCase[RelevanceInput, RelevanceOutput, RelevanceMetadata](
        identity=EvaluationCaseIdentity(business_id="relevance-contract-001", revision=1),
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
    contract = EvaluationTaskContract(
        input_schema=authored_case.input_schema,
        output_schema=authored_case.expected_output_schema,
        metadata_schema=authored_case.metadata_schema,
    )

    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(
            business_id="relevance-contract-gold", revision=1
        ),
        description="Reviewed relevance examples.",
        task_contract=contract,
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(authored_case),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )

    assert gold_set.task_contract == contract

    incompatible_contract = contract.model_copy(
        update={
            "input_schema": SchemaReference.for_model(
                RelevanceInput, identity="other.operation.input", revision=1
            )
        }
    )
    with pytest.raises(ValueError, match="input schema"):
        EvaluationGoldSet(
            identity=EvaluationGoldSetIdentity(
                business_id="relevance-contract-gold", revision=2
            ),
            description="An incompatible population.",
            task_contract=incompatible_contract,
            memberships=gold_set.memberships,
        )


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
