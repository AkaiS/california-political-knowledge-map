"""Repository contracts for the Model Deployment documentation."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text()


def _read_normalized(relative_path: str) -> str:
    return " ".join(_read(relative_path).split())


def test_model_deployment_glossary_distinguishes_local_and_openrouter() -> None:
    context = _read("CONTEXT.md")
    definition_start = context.index("**Model Deployment**:")
    definition_end = context.index("**OpenRouter Admission Gate**:")
    definition = context[definition_start:definition_end]

    assert "local Model Deployment" in definition
    assert "llama.cpp" in definition
    assert "OpenRouter" in definition
    assert "distinct" in definition
    assert "directional evidence" in definition


def test_adr_0017_records_structured_provenance_without_remote_run_state() -> None:
    adr = _read("docs/adr/0017-git-is-the-evaluation-versioning-system.md")

    assert "structured Model Deployment" in adr
    assert "request provenance" in adr.lower()
    assert "There is no Evaluation Ledger" in adr
    assert "no remote run identity" in adr.lower()
    assert "no resumption" in adr.lower()


def test_adr_0019_keeps_local_structured_output_and_explains_chat_rename() -> None:
    adr = _read("docs/adr/0019-llama-cpp-serves-chat-so-tool-calls-are-enforced.md")

    assert "This record covers only the local Model Deployment" in adr
    assert "OpenRouter is a separate chat Model Deployment" in adr
    assert "Every agent that returns structured output talks" not in adr
    assert "default_structured_output_mode=\"native\"" in adr
    assert "response_format: json_schema" in adr
    assert "InlineDefsJsonSchemaTransformer" in adr
    obsolete_chat_name = "OLLAMA_" + "MODEL_*"
    assert obsolete_chat_name in adr
    assert "were removed from runtime" in adr
    assert "historical" in adr.lower()


def test_operator_guide_covers_selection_configuration_and_reactive_limits() -> None:
    guide = _read_normalized("docs/model-deployments.md")

    for phrase in (
        "`ca-map eval run <task>`",
        "`ca-map ingest`",
        "OpenRouter by default",
        "local deployment by default",
        "`--deployment local|openrouter`",
        "`--model MODEL`",
        "LLAMA_CPP_MODEL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_PROVIDERS",
        "ordered",
        "exclusive",
        "BYOK",
        "funded",
        "429",
        "Retry-After",
        "one `OpenRouter Probe`",
        "bounded",
    ):
        assert phrase in guide


def test_report_guidance_describes_routes_and_telemetry_ownership() -> None:
    guide = _read_normalized("docs/model-deployments.md")

    for field in (
        "model_routes",
        "response_model",
        "downstream_provider",
        "request_count",
    ):
        assert field in guide

    assert "Pydantic Evals owns" in guide
    assert "Logfire/OpenTelemetry owns request-level diagnostics" in guide
    assert "retired Request Provenance shape" in guide
    assert "OpenRouter Evaluation Run is directional evidence" in guide
    assert "not proof" in guide
    assert "deployment-equivalence claim" in guide


def test_guide_states_local_embeddings_and_missing_control_planes() -> None:
    guide = _read_normalized("docs/model-deployments.md").lower()

    assert "embeddings remain local" in guide
    assert "no fixed request quota" in guide
    assert "token scheduler" in guide
    assert "application spending ceiling" in guide


def test_operator_guide_uses_canonical_rate_control_terms() -> None:
    guide = _read_normalized("docs/model-deployments.md")

    assert "OpenRouter Admission Gate" in guide
    assert "OpenRouter Probe" in guide
    assert "controller" not in guide
