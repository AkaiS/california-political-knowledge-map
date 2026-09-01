"""Repository-level contract for the two configured chat deployments."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]


def test_example_environment_declares_one_local_and_one_openrouter_chat_model():
    example = (REPOSITORY_ROOT / ".env.example").read_text()
    values = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert values["LLAMA_CPP_MODEL"] == "gemma4:26b"
    assert values["OPENROUTER_API_KEY"]
    assert values["OPENROUTER_MODEL"] == "google/gemma-4-26b-a4b-it:free"
    assert tuple(
        provider.strip() for provider in values["OPENROUTER_PROVIDERS"].split(",")
    ) == ("google-ai-studio", "openai")


def test_active_chat_surfaces_have_no_obsolete_model_environment_names():
    obsolete_name = "OLLAMA_" + "MODEL"
    active_paths = [
        *REPOSITORY_ROOT.joinpath("src").rglob("*.py"),
        *REPOSITORY_ROOT.joinpath("tests").rglob("*.py"),
        REPOSITORY_ROOT / ".env.example",
        REPOSITORY_ROOT / "README.md",
        REPOSITORY_ROOT / "work" / "README.md",
    ]

    matches = [
        str(path.relative_to(REPOSITORY_ROOT))
        for path in active_paths
        if obsolete_name in path.read_text()
    ]

    assert matches == []


def test_operator_instructions_use_current_model_deployment_vocabulary():
    operator_paths = [
        *REPOSITORY_ROOT.joinpath("scripts").glob("*.sh"),
        REPOSITORY_ROOT / "chat-templates" / "README.md",
    ]

    stale_terms = [
        str(path.relative_to(REPOSITORY_ROOT))
        for path in operator_paths
        if "Ollama" in path.read_text()
        or ("OLLAMA_" + "MODEL") in path.read_text()
    ]

    assert stale_terms == []
