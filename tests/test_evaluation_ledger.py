import hashlib

from pydantic import BaseModel
import pytest

from knowledge_map.evaluation import (
    ConfiguredEvaluator,
    DeclaredArtifactReference,
    EvaluationCase,
    EvaluationCaseIdentity,
    EvaluationCaseRevisionReference,
    EvaluationGoldSet,
    EvaluationGoldSetIdentity,
    EvaluationGoldSetMembership,
    EvaluationMetricDefinition,
    EvaluationMetricReference,
    EvaluationMetricValueType,
    EvaluationSplit,
    EvaluationSuite,
    EvaluationSuiteIdentity,
    EvaluationTaskContract,
    NoComparisonOperation,
    SchemaReference,
)
from knowledge_map.evaluation.store import (
    EvaluationDefinitionKind,
    SQLiteAuthoredDefinitionCatalog,
    SQLiteEvaluationArtifactCatalog,
    SQLiteEvaluationExecutionStore,
    SQLiteEvaluationLedger,
    SQLiteEvaluationSchemaInstaller,
)


class Input(BaseModel):
    prompt: str


class Output(BaseModel):
    answer: str


class Metadata(BaseModel):
    source: str


class StructuredMetric(BaseModel):
    score: float


class AlternateInput(BaseModel):
    text: str


class AlternateOutput(BaseModel):
    label: str


class AlternateMetadata(BaseModel):
    annotator: str


def test_evaluation_ledger_uses_one_shared_connection_for_decomposed_capabilities(
    tmp_path,
):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        assert isinstance(ledger.schema_installer, SQLiteEvaluationSchemaInstaller)
        assert isinstance(ledger.definition_catalog, SQLiteAuthoredDefinitionCatalog)
        assert isinstance(ledger.execution_store, SQLiteEvaluationExecutionStore)
        assert isinstance(ledger.artifact_catalog, SQLiteEvaluationArtifactCatalog)
        assert {
            id(component.connection)
            for component in (
                ledger.schema_installer,
                ledger.definition_catalog,
                ledger.execution_store,
                ledger.artifact_catalog,
            )
        } == {id(ledger.connection)}


def test_schema_installer_creates_the_clean_current_run_schema(tmp_path):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        columns = {
            row["name"]
            for row in ledger.connection.execute("PRAGMA table_info(evaluation_runs)")
        }

    assert {
        "retry_of_run_id",
        "issues_json",
        "gate_outcomes_json",
        "frozen_aggregate_manifest_artifact_id",
        "finalization_claim_id",
        "finalization_claim_owner_id",
        "finalization_claim_acquired_at",
        "finalization_claim_expires_at",
    } <= columns


def make_case(answer: str = "relevant") -> EvaluationCase[Input, Output, Metadata]:
    return EvaluationCase(
        identity=EvaluationCaseIdentity(business_id="case-001", revision=1),
        input_schema=SchemaReference.for_model(Input, identity="tests.input", revision=1),
        expected_output_schema=SchemaReference.for_model(
            Output, identity="tests.output", revision=1
        ),
        metadata_schema=SchemaReference.for_model(
            Metadata, identity="tests.metadata", revision=1
        ),
        task_input=Input(prompt="classify"),
        expected_output=Output(answer=answer),
        metadata=Metadata(source="human"),
        description="A case for ledger tests.",
        tags=("relevance", "smoke"),
    )


def test_imported_authored_definition_is_queryable_and_idempotent(tmp_path):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")
    case = make_case()

    first = ledger.import_definition(case)
    second = ledger.import_definition(case)

    assert second == first
    assert first.record_id == case.identity.record_id
    assert first.business_id == "case-001"
    assert first.revision == 1
    assert first.content_hash == case.content_hash
    assert first.schema_references == (
        case.input_schema,
        case.expected_output_schema,
        case.metadata_schema,
    )
    assert first.metadata == {
        "description": "A case for ledger tests.",
        "tags": ["relevance", "smoke"],
    }
    assert ledger.get_definition(
        business_id="case-001", revision=1, kind="evaluation_case"
    ) == first
    assert ledger.list_definitions() == [first]
    assert ledger.find_definitions(tags=("smoke",)) == [first]


def test_imported_suite_inventory_includes_structured_metric_schemas(tmp_path):
    structured_schema = SchemaReference.for_model(
        StructuredMetric, identity="tests.structured-metric", revision=1
    )
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.quality",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=structured_schema,
        semantic_description="Structured quality details.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-001", revision=1),
        description="A suite with a structured metric.",
        task_contract=EvaluationTaskContract(
            input_schema=SchemaReference.for_model(
                Input, identity="tests.input", revision=1
            ),
            output_schema=SchemaReference.for_model(
                Output, identity="tests.output", revision=1
            ),
            metadata_schema=SchemaReference.for_model(
                Metadata, identity="tests.metadata", revision=1
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(
                name="quality",
                evaluator_revision=1,
                metrics=(EvaluationMetricReference.from_definition(metric),),
            ),
        ),
        metrics=(metric,),
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        record = ledger.import_suite(suite)
        stored_metric = ledger.get_metric_definition(
            namespaced_name=metric.namespaced_name,
            evaluator_revision=metric.evaluator_revision,
        )

    assert record.schema_references == (
        suite.task_contract.input_schema,
        suite.task_contract.output_schema,
        suite.task_contract.metadata_schema,
        structured_schema,
    )
    assert stored_metric is not None
    assert stored_metric.definition == metric


def test_imported_suite_publishes_its_metric_as_an_independently_queryable_record(
    tmp_path,
):
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.quality",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.BOOLEAN,
        semantic_description="Whether the output passed quality review.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-metric-record", revision=1),
        description="A suite with a canonical metric.",
        task_contract=EvaluationTaskContract(
            input_schema=SchemaReference.for_model(Input, identity="tests.input", revision=1),
            output_schema=SchemaReference.for_model(Output, identity="tests.output", revision=1),
            metadata_schema=SchemaReference.for_model(
                Metadata, identity="tests.metadata", revision=1
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(
                name="quality",
                evaluator_revision=1,
                metrics=(EvaluationMetricReference.from_definition(metric),),
            ),
        ),
        metrics=(metric,),
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        ledger.import_suite(suite)

        stored = ledger.get_metric_definition(
            namespaced_name=metric.namespaced_name,
            evaluator_revision=metric.evaluator_revision,
        )

        assert stored is not None
        assert stored.content_hash == metric.content_hash
        assert stored.definition == metric
        assert ledger.list_metric_definitions() == [stored]


def test_identical_metric_content_is_shared_across_suites_with_exact_relationships(
    tmp_path,
):
    metric = EvaluationMetricDefinition(
        namespaced_name="tests.shared-quality",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.BOOLEAN,
        semantic_description="Whether the output passed quality review.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )

    def make_suite(business_id: str, input_type: type[BaseModel], output_type: type[BaseModel], metadata_type: type[BaseModel]):
        return EvaluationSuite(
            identity=EvaluationSuiteIdentity(business_id=business_id, revision=1),
            description=f"Suite {business_id}.",
            task_contract=EvaluationTaskContract(
                input_schema=SchemaReference.for_model(
                    input_type, identity=f"tests.{business_id}.input", revision=1
                ),
                output_schema=SchemaReference.for_model(
                    output_type, identity=f"tests.{business_id}.output", revision=1
                ),
                metadata_schema=SchemaReference.for_model(
                    metadata_type, identity=f"tests.{business_id}.metadata", revision=1
                ),
            ),
            report_evaluators=(
                ConfiguredEvaluator(
                    name="quality",
                    evaluator_revision=1,
                    metrics=(EvaluationMetricReference.from_definition(metric),),
                ),
            ),
            metrics=(metric,),
        )

    first_suite = make_suite("suite-shared-first", Input, Output, Metadata)
    second_suite = make_suite(
        "suite-shared-second", AlternateInput, AlternateOutput, AlternateMetadata
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        first_record = ledger.import_suite(first_suite)
        second_record = ledger.import_suite(second_suite)

        assert len(ledger.list_metric_definitions()) == 1
        stored = ledger.list_metric_definitions()[0]
        assert ledger.list_suite_metrics(first_record.record_id) == [stored]
        assert ledger.list_suite_metrics(second_record.record_id) == [stored]


def test_reusing_a_metric_identity_with_different_content_is_rejected_across_suites(
    tmp_path,
):
    def make_metric(description: str) -> EvaluationMetricDefinition:
        return EvaluationMetricDefinition(
            namespaced_name="tests.conflicting-quality",
            evaluator_revision=1,
            value_type=EvaluationMetricValueType.BOOLEAN,
            semantic_description=description,
            comparison_operation=NoComparisonOperation(
                namespaced_name="tests.comparison.none", revision=1
            ),
        )

    def make_suite(business_id: str, metric: EvaluationMetricDefinition):
        return EvaluationSuite(
            identity=EvaluationSuiteIdentity(business_id=business_id, revision=1),
            description=f"Suite {business_id}.",
            task_contract=EvaluationTaskContract(
                input_schema=SchemaReference.for_model(Input, identity="tests.input", revision=1),
                output_schema=SchemaReference.for_model(Output, identity="tests.output", revision=1),
                metadata_schema=SchemaReference.for_model(
                    Metadata, identity="tests.metadata", revision=1
                ),
            ),
            report_evaluators=(
                ConfiguredEvaluator(
                    name="quality",
                    evaluator_revision=1,
                    metrics=(EvaluationMetricReference.from_definition(metric),),
                ),
            ),
            metrics=(metric,),
        )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        ledger.import_suite(make_suite("suite-conflict-first", make_metric("Passes review.")))

        with pytest.raises(ValueError, match="metric content changed"):
            ledger.import_suite(
                make_suite("suite-conflict-second", make_metric("Passes strict review."))
            )


def test_imported_suite_inventory_preserves_task_schemas_and_deduplicates_metrics(
    tmp_path,
):
    shared_schema = SchemaReference.for_model(
        StructuredMetric, identity="tests.shared-metric", revision=1
    )
    first_metric = EvaluationMetricDefinition(
        namespaced_name="tests.first-quality",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.STRUCTURED,
        structured_schema=shared_schema,
        semantic_description="First structured quality details.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    scalar_metric = EvaluationMetricDefinition(
        namespaced_name="tests.scalar-quality",
        evaluator_revision=1,
        value_type=EvaluationMetricValueType.BOOLEAN,
        semantic_description="Scalar quality result.",
        comparison_operation=NoComparisonOperation(
            namespaced_name="tests.comparison.none", revision=1
        ),
    )
    second_metric = first_metric.model_copy(
        update={"namespaced_name": "tests.second-quality"}
    )
    suite = EvaluationSuite(
        identity=EvaluationSuiteIdentity(business_id="suite-002", revision=1),
        description="A suite with repeated and scalar metrics.",
        task_contract=EvaluationTaskContract(
            input_schema=SchemaReference.for_model(
                Input, identity="tests.input", revision=1
            ),
            output_schema=SchemaReference.for_model(
                Output, identity="tests.output", revision=1
            ),
            metadata_schema=SchemaReference.for_model(
                Metadata, identity="tests.metadata", revision=1
            ),
        ),
        report_evaluators=(
            ConfiguredEvaluator(
                name="quality",
                evaluator_revision=1,
                metrics=tuple(
                    EvaluationMetricReference.from_definition(metric)
                    for metric in (first_metric, scalar_metric, second_metric)
                ),
            ),
        ),
        metrics=(first_metric, scalar_metric, second_metric),
    )

    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        record = ledger.import_suite(suite)

    assert record.schema_references == (
        suite.task_contract.input_schema,
        suite.task_contract.output_schema,
        suite.task_contract.metadata_schema,
        shared_schema,
    )
    serialized = record.model_dump(mode="json")
    assert serialized["schema_references"][-1] == shared_schema.model_dump(mode="json")
    assert "StructuredMetric" not in str(serialized)
    assert "import" not in str(serialized)


def test_import_rejects_a_business_revision_with_different_authored_bytes(tmp_path):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")
    ledger.import_definition(make_case())

    changed = make_case(answer="irrelevant")

    with pytest.raises(ValueError, match="without a new revision"):
        ledger.import_definition(changed)


def test_imported_gold_set_uses_relational_membership_rows(tmp_path):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")
    case = make_case()
    ledger.import_definition(case)
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-001", revision=1),
        description="Held-out cases.",
        task_contract=EvaluationTaskContract(
            input_schema=case.input_schema,
            output_schema=case.expected_output_schema,
            metadata_schema=case.metadata_schema,
        ),
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )

    gold_set_record = ledger.import_definition(gold_set)

    memberships = ledger.list_gold_set_memberships(gold_set_record.record_id)
    assert len(memberships) == 1
    assert memberships[0].gold_set_record_id == gold_set.identity.record_id
    assert memberships[0].case_record_id == case.identity.record_id
    assert memberships[0].case_content_hash == case.content_hash
    assert memberships[0].split is EvaluationSplit.HELD_OUT


def test_import_rejects_a_gold_set_reference_whose_case_content_changed(tmp_path):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")
    case = make_case()
    ledger.import_definition(case)
    forged_reference = EvaluationCaseRevisionReference.from_case(case).model_copy(
        update={"content_hash": "f" * 64}
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-forged", revision=1),
        description="A Gold Set with a forged case content hash.",
        task_contract=EvaluationTaskContract(
            input_schema=case.input_schema,
            output_schema=case.expected_output_schema,
            metadata_schema=case.metadata_schema,
        ),
        memberships=(
            EvaluationGoldSetMembership(
                case=forged_reference,
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )

    with pytest.raises(ValueError, match="exact Evaluation Case revision"):
        ledger.import_definition(gold_set)


def test_import_rejects_a_gold_set_whose_contract_the_stored_case_does_not_implement(
    tmp_path,
):
    """Import re-derives schemas from the stored case and checks the contract.

    The reference itself is honest — identity and content hash both match the
    imported case. Only the Gold Set's task contract is forged. Before
    `EvaluationCaseRevisionReference` was slimmed this was caught by forging a
    schema on the reference; that field is gone, so the check is now reached
    only through the stored case record. Per ADR 0006 this is where forgery
    detection lives.
    """
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")
    case = make_case()
    ledger.import_definition(case)
    forged_input_schema = SchemaReference.for_model(
        Input, identity="tests.other-input", revision=1
    )
    gold_set = EvaluationGoldSet(
        identity=EvaluationGoldSetIdentity(business_id="gold-set-contract", revision=1),
        description="A contract-mismatched gold set.",
        task_contract=EvaluationTaskContract(
            input_schema=forged_input_schema,
            output_schema=case.expected_output_schema,
            metadata_schema=case.metadata_schema,
        ),
        memberships=(
            EvaluationGoldSetMembership(
                case=EvaluationCaseRevisionReference.from_case(case),
                split=EvaluationSplit.HELD_OUT,
            ),
        ),
    )

    with pytest.raises(ValueError, match="implement the Gold Set task contract"):
        ledger.import_definition(gold_set)


def test_evaluation_case_manifest_schema_stores_identity_only(tmp_path):
    with SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite") as ledger:
        columns = {
            row["name"]
            for row in ledger.connection.execute(
                "PRAGMA table_info(evaluation_case_manifests)"
            )
        }

    assert "input_schema_json" not in columns
    assert "output_schema_json" not in columns
    assert "metadata_schema_json" not in columns


def test_artifact_catalog_deduplicates_bytes_and_preserves_immutable_metadata(tmp_path):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")

    first = ledger.register_artifact(
        b"task output",
        kind="task-output",
        media_type="text/plain",
        retention_class="run",
        sensitivity_classification="internal",
        redaction_classification="original",
    )
    second = ledger.register_artifact(
        b"task output",
        kind="task-output",
        media_type="text/plain",
        retention_class="run",
        sensitivity_classification="internal",
        redaction_classification="original",
    )

    assert second == first
    assert first.content_hash == hashlib.sha256(b"task output").hexdigest()
    assert first.byte_size == len(b"task output")
    assert first.kind == "task-output"
    assert first.media_type == "text/plain"
    assert first.retention_class == "run"
    assert first.sensitivity_classification == "internal"
    assert first.redaction_classification == "original"


def test_artifact_locations_are_replaceable_and_redaction_creates_lineage(tmp_path):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")
    source = ledger.register_artifact(
        b"private task output",
        kind="task-output",
        media_type="text/plain",
        retention_class="run",
        sensitivity_classification="sensitive",
    )

    first_location = ledger.put_artifact_location(
        source,
        "ci://run-1/output.txt",
        location_key="ci",
    )
    archive_location = ledger.put_artifact_location(
        source,
        "s3://archive/output.txt",
        location_key="archive",
        location_kind="object-storage",
    )
    replacement = ledger.put_artifact_location(
        source,
        "ci://run-2/output.txt",
        location_key="ci",
    )

    assert replacement.location_id == first_location.location_id
    assert replacement.uri == "ci://run-2/output.txt"
    assert [location.location_id for location in ledger.list_artifact_locations(source)] == [
        archive_location.location_id,
        first_location.location_id,
    ]

    derivative = ledger.register_redacted_derivative(
        source,
        b"redacted task output",
        kind="task-output",
        media_type="text/plain",
        retention_class="run",
        sensitivity_classification="internal",
    )

    assert derivative.artifact_id != source.artifact_id
    assert derivative.redaction_classification == "redacted"
    assert ledger.get_artifact_source(derivative) == source.artifact_id
    assert ledger.list_artifact_derivatives(source)[0].derivative_artifact_id == (
        derivative.artifact_id
    )


def test_artifact_hash_can_be_imported_without_bytes_and_metadata_conflicts_are_rejected(
    tmp_path,
):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")
    content_hash = hashlib.sha256(b"external bytes").hexdigest()
    artifact = ledger.register_artifact(
        content_hash=content_hash,
        byte_size=len(b"external bytes"),
        kind="prompt",
        media_type="application/json",
        retention_class="long-term",
        sensitivity="internal",
    )

    assert ledger.get_artifact(content_hash) == artifact
    with pytest.raises(ValueError, match="different metadata"):
        ledger.register_artifact(
            content_hash=content_hash,
            byte_size=len(b"external bytes"),
            kind="prompt",
            media_type="text/plain",
            retention_class="long-term",
            sensitivity="internal",
        )


def test_imported_definition_artifacts_are_linked_to_their_authored_producer(tmp_path):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")
    artifact = ledger.register_artifact(
        b"authored prompt",
        kind="prompt",
        media_type="text/plain",
        retention_class="long-term",
        sensitivity="internal",
    )
    case = make_case().model_copy(
        update={
            "artifacts": (
                DeclaredArtifactReference(
                    content_hash=artifact.content_hash,
                    role="evaluation.case.prompt",
                ),
            )
        }
    )

    ledger.import_case(case)

    links = ledger.list_definition_artifacts(case.identity.record_id)
    assert len(links) == 1
    assert links[0].artifact_id == artifact.artifact_id
    assert links[0].role == "evaluation.case.prompt"


def test_definition_catalog_directly_owns_sqlite_persistence_without_ledger_private_methods(
    tmp_path,
):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")

    # Assert legacy private methods are removed from SQLiteEvaluationLedger facade
    private_methods = (
        "_import_definition",
        "_import_metric_definition",
        "_get_definition",
        "_get_metric_definition",
        "_list_definitions",
        "_list_metric_definitions",
        "_list_suite_metric_definitions",
        "_list_gold_set_memberships",
    )
    for method in private_methods:
        assert not hasattr(
            ledger, method
        ), f"SQLiteEvaluationLedger should not define private method {method}"

    # Verify SQLiteAuthoredDefinitionCatalog methods work directly
    case = make_case()
    imported_case = ledger.definition_catalog.import_definition(case)
    assert imported_case.business_id == case.identity.business_id

    fetched = ledger.definition_catalog.get_definition(
        business_id=case.identity.business_id,
        revision=case.identity.revision,
        kind=EvaluationDefinitionKind.CASE,
    )
    assert fetched is not None
    assert fetched.content_hash == case.content_hash

    listed = ledger.definition_catalog.list_definitions(
        kind=EvaluationDefinitionKind.CASE
    )
    assert len(listed) == 1
    assert listed[0].record_id == imported_case.record_id


def test_sqlite_evaluation_artifact_catalog_owns_query_persistence(tmp_path):
    ledger = SQLiteEvaluationLedger(tmp_path / "evaluation.sqlite")

    # Assert legacy private methods are removed from SQLiteEvaluationLedger facade
    private_methods = (
        "_register_artifact",
        "_get_artifact",
        "_get_artifact_by_id",
        "_read_artifact",
        "_resolve_artifact",
        "_link_artifact",
        "_link_definition_artifact",
        "_list_artifact_links",
    )
    for method in private_methods:
        assert not hasattr(
            ledger, method
        ), f"SQLiteEvaluationLedger should not define private method {method}"

    # Verify SQLiteEvaluationArtifactCatalog methods work directly
    artifact = ledger.artifact_catalog.register_artifact(
        b"direct catalog artifact",
        kind="test-output",
        media_type="text/plain",
        retention_class="run",
        sensitivity_classification="internal",
    )
    assert artifact.byte_size == len(b"direct catalog artifact")

    fetched = ledger.artifact_catalog.get_artifact(artifact.content_hash)
    assert fetched == artifact

    fetched_by_id = ledger.artifact_catalog.get_artifact_by_id(artifact.artifact_id)
    assert fetched_by_id == artifact

