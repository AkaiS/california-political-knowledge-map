import pytest
from dataclasses import dataclass
from pydantic import BaseModel, ValidationError
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, ReportEvaluator, ReportEvaluatorContext
from pydantic_evals.reporting.analyses import ScalarResult

from knowledge_map.evaluation import (
    EvaluationCase,
    EvaluationCaseIdentity,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationSplit,
    EvaluationRequirement,
    EvaluationRequirementCatalog,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    EvaluationTaskBinding,
    EvaluationRunConfiguration,
    EvaluationRunner,
    InMemoryEvaluationEvidenceBuffer,
    SchemaRegistry,
    ConfiguredEvaluator,
    ConfiguredEvaluatorReference,
    EvaluationRequirementBinding,
    assert_same_revision_content,
    SchemaReference,
)


class RequirementInput(BaseModel):
    text: str


class RequirementOutput(BaseModel):
    label: str


class RequirementMetadata(BaseModel):
    source: str


@dataclass
class RequirementEvaluator(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return True


@dataclass
class RequirementReportEvaluator(ReportEvaluator):
    def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        return ScalarResult(title="Cases", value=len(ctx.report.cases))


@dataclass
class RecordingEvaluator(Evaluator):
    calls: list[str]

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        self.calls.append(ctx.name or "")
        return True


@dataclass
class RecordingReportEvaluator(ReportEvaluator):
    case_counts: list[int]

    def evaluate(self, ctx: ReportEvaluatorContext) -> ScalarResult:
        self.case_counts.append(len(ctx.report.cases))
        return ScalarResult(title="Cases", value=len(ctx.report.cases))


def test_catalog_and_case_preserve_stable_requirement_keys_and_descriptions():
    catalog = EvaluationRequirementCatalog(
        requirements=(
            EvaluationRequirement(
                key="source-grounding",
                semantic_description="The answer must be grounded in the source text.",
            ),
        )
    )

    case = EvaluationCase(
        identity=EvaluationCaseIdentity(business_id="case-1", revision=1),
        input_schema=SchemaReference.for_model(
            RequirementInput, identity="test.input", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            RequirementMetadata, identity="test.metadata", revision=1
        ),
        task_input=RequirementInput(text="source text"),
        metadata=RequirementMetadata(source="metadata"),
        description="A grounded answer.",
        requirements=("source-grounding",),
    )

    assert catalog.requirements[0].key == "source-grounding"
    assert catalog.description_for("source-grounding") == (
        "The answer must be grounded in the source text."
    )
    assert case.requirements == ("source-grounding",)


def test_catalog_rejects_duplicate_keys_and_unknown_case_requirements():
    with pytest.raises(ValidationError, match="duplicate"):
        EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(key="grounding", semantic_description="First."),
                EvaluationRequirement(key="grounding", semantic_description="Second."),
            )
        )


def test_suite_rejects_a_case_requirement_unknown_to_its_component_catalog():
    catalog = EvaluationRequirementCatalog(
        requirements=(
            EvaluationRequirement(
                key="source-grounding",
                semantic_description="The answer must be grounded in the source text.",
            ),
        )
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-1", revision=1),
        description="Requirement validation suite.",
        requirement_catalog=catalog,
        task_contract=EvaluationTaskContract(
            input_schema=SchemaReference.for_model(
                RequirementInput, identity="test.input", revision=1
            ),
            output_schema=SchemaReference.for_model(
                RequirementOutput, identity="test.output", revision=1
            ),
            metadata_schema=SchemaReference.for_model(
                RequirementMetadata, identity="test.metadata", revision=1
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(name="report", evaluator_revision=1),
        ),
    )
    case = EvaluationCase(
        identity=EvaluationCaseIdentity(business_id="case-2", revision=1),
        input_schema=SchemaReference.for_model(
            RequirementInput, identity="test.input", revision=1
        ),
        expected_output_schema=SchemaReference.for_model(
            RequirementOutput, identity="test.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            RequirementMetadata, identity="test.metadata", revision=1
        ),
        task_input=RequirementInput(text="source text"),
        expected_output=RequirementOutput(label="grounded"),
        metadata=RequirementMetadata(source="metadata"),
        description="An unknown requirement must be rejected.",
        requirements=("unknown-requirement",),
    )

    with pytest.raises(ValueError, match="unknown.*requirement"):
        suite.validate_cases((case,))


def test_requirement_binding_resolves_only_to_declared_case_evaluators():
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-2", revision=1),
        description="Requirement binding suite.",
        requirement_catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(
                    key="source-grounding",
                    semantic_description="The answer must be grounded in the source text.",
                ),
            )
        ),
        task_contract=EvaluationTaskContract(
            input_schema=SchemaReference.for_model(
                RequirementInput, identity="test.input", revision=1
            ),
            output_schema=SchemaReference.for_model(
                RequirementOutput, identity="test.output", revision=1
            ),
            metadata_schema=SchemaReference.for_model(
                RequirementMetadata, identity="test.metadata", revision=1
            ),
        ),
        case_evaluators=(
            ConfiguredEvaluator(name="grounding", evaluator_revision=2),
        ),
        report_evaluators=(
            ConfiguredEvaluator(name="report", evaluator_revision=1),
        ),
        requirement_bindings=(
            EvaluationRequirementBinding(
                requirement="source-grounding",
                evaluators=(ConfiguredEvaluatorReference(name="grounding"),),
            ),
        ),
    )
    case = EvaluationCase(
        identity=EvaluationCaseIdentity(business_id="case-3", revision=1),
        input_schema=SchemaReference.for_model(
            RequirementInput, identity="test.input", revision=1
        ),
        expected_output_schema=SchemaReference.for_model(
            RequirementOutput, identity="test.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            RequirementMetadata, identity="test.metadata", revision=1
        ),
        task_input=RequirementInput(text="source text"),
        expected_output=RequirementOutput(label="grounded"),
        metadata=RequirementMetadata(source="metadata"),
        description="A grounded answer.",
        requirements=("source-grounding",),
    )

    assert suite.resolve_case_evaluators(case) == suite.case_evaluators


def test_requirement_selected_evaluators_run_only_for_cases_that_declare_them():
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-3", revision=1),
        description="Requirement execution suite.",
        requirement_catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(
                    key="source-grounding",
                    semantic_description="The answer must be grounded in the source text.",
                ),
            )
        ),
        task_contract=EvaluationTaskContract(
            input_schema=SchemaReference.for_model(
                RequirementInput, identity="test.input", revision=1
            ),
            output_schema=SchemaReference.for_model(
                RequirementOutput, identity="test.output", revision=1
            ),
            metadata_schema=SchemaReference.for_model(
                RequirementMetadata, identity="test.metadata", revision=1
            ),
        ),
        case_evaluators=(
            ConfiguredEvaluator(name="grounding", evaluator_revision=2),
        ),
        suite_case_evaluators=(),
        requirement_bindings=(
            EvaluationRequirementBinding(
                requirement="source-grounding",
                evaluators=(ConfiguredEvaluatorReference(name="grounding"),),
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(name="report", evaluator_revision=1),
        ),
    )
    case = EvaluationCase(
        identity=EvaluationCaseIdentity(business_id="case-4", revision=1),
        input_schema=SchemaReference.for_model(
            RequirementInput, identity="test.input", revision=1
        ),
        expected_output_schema=SchemaReference.for_model(
            RequirementOutput, identity="test.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            RequirementMetadata, identity="test.metadata", revision=1
        ),
        task_input=RequirementInput(text="source text"),
        expected_output=RequirementOutput(label="grounded"),
        metadata=RequirementMetadata(source="metadata"),
        description="A grounded answer.",
        requirements=("source-grounding",),
    )

    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="suite-3-gold", revision=1),
        description="Requirement-selected cases.",
        task_contract=suite.task_contract,
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )
    plan = suite.preflight_selected_cases(
        gold_set=gold_set, cases=(case,)
    ).plan
    assert plan is not None
    schemas = SchemaRegistry()
    schemas.register(case.input_schema, RequirementInput)
    schemas.register(case.expected_output_schema, RequirementOutput)
    schemas.register(case.metadata_schema, RequirementMetadata)
    with InMemoryEvaluationEvidenceBuffer() as evidence:
        result = EvaluationRunner(evidence).run(
            plan=plan,
            suite=suite,
            gold_set=gold_set,
            cases=(case,),
            task=lambda _: RequirementOutput(label="grounded"),
            evaluator_resolver=lambda configured: (
                RequirementEvaluator()
                if configured.name == "grounding"
                else RequirementReportEvaluator()
            ),
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
            schemas=schemas,
        )
        report = evidence.materialize_aggregate_report(result.run.run_id, schemas)

    assert report.cases[0].assertions["grounding"].value is True


def test_shared_engine_executes_a_frozen_plan_as_one_multi_case_report():
    schemas = {
        "input_schema": SchemaReference.for_model(
            RequirementInput, identity="test.input", revision=1
        ),
        "expected_output_schema": SchemaReference.for_model(
            RequirementOutput, identity="test.output", revision=1
        ),
        "metadata_schema": SchemaReference.for_model(
            RequirementMetadata, identity="test.metadata", revision=1
        ),
    }
    cases = tuple(
        EvaluationCase(
            identity=EvaluationCaseIdentity(business_id=f"engine-case-{number}", revision=1),
            **schemas,
            task_input=RequirementInput(text=f"text-{number}"),
            expected_output=RequirementOutput(label=f"label-{number}"),
            metadata=RequirementMetadata(source="fixture"),
            description="A shared-engine case.",
            requirements=("source-grounding",) if number == 1 else (),
        )
        for number in (1, 2)
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="shared-engine-suite", revision=1),
        description="A suite executed through the shared engine.",
        requirement_catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(
                    key="source-grounding",
                    semantic_description="The answer must be grounded in the source text.",
                ),
            )
        ),
        task_contract=EvaluationTaskContract(
            input_schema=schemas["input_schema"],
            output_schema=schemas["expected_output_schema"],
            metadata_schema=schemas["metadata_schema"],
        ),
        case_evaluators=(
            ConfiguredEvaluator(name="universal", evaluator_revision=1),
            ConfiguredEvaluator(name="grounding", evaluator_revision=1),
        ),
        suite_case_evaluators=(ConfiguredEvaluatorReference(name="universal"),),
        requirement_bindings=(
            EvaluationRequirementBinding(
                requirement="source-grounding",
                evaluators=(
                    ConfiguredEvaluatorReference(name="universal"),
                    ConfiguredEvaluatorReference(name="grounding"),
                ),
            ),
        ),
        report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="shared-engine-gold", revision=1),
        description="The shared-engine population.",
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
    plan_result = suite.preflight_selected_cases(gold_set=gold_set, cases=cases)
    assert plan_result.plan is not None

    universal_calls: list[str] = []
    grounding_calls: list[str] = []
    report_case_counts: list[int] = []
    binding = EvaluationTaskBinding(
        operation=lambda task_input: RequirementOutput(
            label=task_input.text.replace("text", "label")
        ),
        contract=suite.task_contract,
        input_model=RequirementInput,
        output_model=RequirementOutput,
        metadata_model=RequirementMetadata,
    )
    registry = SchemaRegistry()
    registry.register(cases[0].input_schema, RequirementInput)
    registry.register(cases[0].expected_output_schema, RequirementOutput)
    registry.register(cases[0].metadata_schema, RequirementMetadata)
    with InMemoryEvaluationEvidenceBuffer() as evidence:
        result = EvaluationRunner(evidence).run(
            plan=plan_result.plan,
            suite=suite,
            gold_set=gold_set,
            cases=cases,
            task_binding=binding,
            evaluator_resolver=lambda configured: {
                "universal": RecordingEvaluator(universal_calls),
                "grounding": RecordingEvaluator(grounding_calls),
                "report": RecordingReportEvaluator(report_case_counts),
            }[configured.name],
            configuration=EvaluationRunConfiguration(
                provider="deterministic", model="fixture"
            ),
            schemas=registry,
        )
        report = evidence.materialize_aggregate_report(result.run.run_id, registry)
        checkpoint_count = len(evidence.checkpoints)

    assert [case.name for case in report.cases] == [
        "engine-case-1@1",
        "engine-case-2@1",
    ]
    assert universal_calls == ["engine-case-1@1", "engine-case-2@1"]
    assert grounding_calls == ["engine-case-1@1"]
    assert report_case_counts == [2]
    assert checkpoint_count == 2


def test_case_requirements_are_authored_content_but_suite_judging_is_not_case_content():
    schemas = {
        "input_schema": SchemaReference.for_model(
            RequirementInput, identity="test.input", revision=1
        ),
        "expected_output_schema": SchemaReference.for_model(
            RequirementOutput, identity="test.output", revision=1
        ),
        "metadata_schema": SchemaReference.for_model(
            RequirementMetadata, identity="test.metadata", revision=1
        ),
    }
    base_case = EvaluationCase(
        identity=EvaluationCaseIdentity(business_id="case-5", revision=1),
        **schemas,
        task_input=RequirementInput(text="source text"),
        expected_output=RequirementOutput(label="grounded"),
        metadata=RequirementMetadata(source="metadata"),
        description="A grounded answer.",
    )
    requirement_case = EvaluationCase(
        identity=EvaluationCaseIdentity(business_id="case-5", revision=2),
        **schemas,
        task_input=base_case.task_input,
        expected_output=base_case.expected_output,
        metadata=base_case.metadata,
        description=base_case.description,
        requirements=("source-grounding",),
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-5", revision=1),
        description="A reviewed case population.",
        task_contract=EvaluationTaskContract(
            input_schema=base_case.input_schema,
            output_schema=base_case.expected_output_schema,
            metadata_schema=base_case.metadata_schema,
        ),
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(base_case),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )
    catalog = EvaluationRequirementCatalog(
        requirements=(
            EvaluationRequirement(
                key="source-grounding",
                semantic_description="The answer must be grounded in the source text.",
            ),
        )
    )
    suite_v1 = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-5", revision=1),
        description="Judge the task.",
        requirement_catalog=catalog,
        task_contract=EvaluationTaskContract(
            input_schema=schemas["input_schema"],
            output_schema=schemas["expected_output_schema"],
            metadata_schema=schemas["metadata_schema"],
        ),
        case_evaluators=(
            ConfiguredEvaluator(
                name="grounding", evaluator_revision=1, configuration={"version": 1}
            ),
        ),
        requirement_bindings=(
            EvaluationRequirementBinding(
                requirement="source-grounding",
                evaluators=(ConfiguredEvaluatorReference(name="grounding"),),
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(name="report", evaluator_revision=1),
        ),
    )
    suite_v2 = EvaluationSuite(
        **suite_v1.model_dump(
            exclude={"identity", "case_evaluators", "content_hash"}
        ),
        identity=EvaluationSuiteIdentity(business_id="suite-5", revision=2),
        case_evaluators=(
            ConfiguredEvaluator(
                name="grounding", evaluator_revision=1, configuration={"version": 2}
            ),
        ),
    )

    assert requirement_case.content_hash != base_case.content_hash
    with pytest.raises(ValueError, match="content changed without a new revision"):
        assert_same_revision_content(
            base_case,
            requirement_case.model_copy(update={"identity": base_case.identity}),
        )
    assert gold_set.memberships[0].case.content_hash == base_case.content_hash
    assert suite_v2.content_hash != suite_v1.content_hash


def test_suite_rejects_invalid_binding_references_and_allows_dormant_bindings():
    with pytest.raises(ValidationError):
        EvaluationRequirementBinding(requirement="grounding", evaluators=())
    with pytest.raises(ValidationError, match="repeat"):
        EvaluationRequirementBinding(
            requirement="grounding",
            evaluators=(
                ConfiguredEvaluatorReference(name="judge"),
                ConfiguredEvaluatorReference(name="judge"),
            ),
        )

    contract = EvaluationTaskContract(
        input_schema=SchemaReference.for_model(
            RequirementInput, identity="test.input", revision=1
        ),
        output_schema=SchemaReference.for_model(
            RequirementOutput, identity="test.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            RequirementMetadata, identity="test.metadata", revision=1
        ),
    )
    with pytest.raises(ValueError, match="undeclared"):
        EvaluationSuite(
            identity=EvaluationSuiteIdentity(business_id="suite-invalid", revision=1),
            description="Invalid references.",
            task_contract=contract,
            suite_case_evaluators=(ConfiguredEvaluatorReference(name="missing"),),
            report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
        )
    with pytest.raises(ValueError, match="report evaluator"):
        EvaluationSuite(
            identity=EvaluationSuiteIdentity(business_id="suite-invalid", revision=2),
            description="Invalid references.",
            task_contract=contract,
            case_evaluators=(ConfiguredEvaluator(name="judge", evaluator_revision=1),),
            suite_case_evaluators=(ConfiguredEvaluatorReference(name="report"),),
            report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
        )
    with pytest.raises(ValueError, match="every configured case evaluator"):
        EvaluationSuite(
            identity=EvaluationSuiteIdentity(business_id="suite-invalid", revision=3),
            description="Dead configuration.",
            task_contract=contract,
            requirement_catalog=EvaluationRequirementCatalog(
                requirements=(
                    EvaluationRequirement(
                        key="grounding", semantic_description="Ground the answer in source text."
                    ),
                )
            ),
            case_evaluators=(ConfiguredEvaluator(name="judge", evaluator_revision=1),),
            suite_case_evaluators=(),
            report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
        )

    dormant = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-dormant", revision=1),
        description="A suite supporting another selection.",
        requirement_catalog=EvaluationRequirementCatalog(
            requirements=(
                EvaluationRequirement(
                    key="grounding", semantic_description="Ground the answer in source text."
                ),
            )
        ),
        task_contract=contract,
        case_evaluators=(ConfiguredEvaluator(name="judge", evaluator_revision=1),),
        suite_case_evaluators=(),
        requirement_bindings=(
            EvaluationRequirementBinding(
                requirement="grounding",
                evaluators=(ConfiguredEvaluatorReference(name="judge"),),
            ),
        ),
        report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
    )

    assert dormant.requirement_bindings[0].requirement == "grounding"


def test_legacy_suite_evaluator_application_round_trips_without_losing_scope():
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-round-trip", revision=1),
        description="A suite with universally applied case judging.",
        task_contract=EvaluationTaskContract(
            input_schema=SchemaReference.for_model(
                RequirementInput, identity="test.input", revision=1
            ),
            output_schema=SchemaReference.for_model(
                RequirementOutput, identity="test.output", revision=1
            ),
            metadata_schema=SchemaReference.for_model(
                RequirementMetadata, identity="test.metadata", revision=1
            ),
        ),
        case_evaluators=(ConfiguredEvaluator(name="judge", evaluator_revision=1),),
        report_evaluators=(ConfiguredEvaluator(name="report", evaluator_revision=1),),
    )

    restored = EvaluationSuite.model_validate_json(suite.model_dump_json())

    assert restored.suite_wide_case_evaluator_references == (
        ConfiguredEvaluatorReference(name="judge"),
    )
