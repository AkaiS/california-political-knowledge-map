from typing import Dict, Any, List
from knowledge_map.schemas import ExtractionResult

import os
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from dotenv import load_dotenv
from pydantic_ai.capabilities import Hooks
from pydantic_ai.models.openai import OpenAIChatModel

# monkey patch to get around content ollama rejecting content = <nil> on retries 
_original = OpenAIChatModel._MapModelResponseContext._into_message_param

def _patched(self):
    result = _original(self)
    if result is not None and result.get("content") is None:
        result["content"] = ""
    return result

OpenAIChatModel._MapModelResponseContext._into_message_param = _patched

PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources",
    "extraction_prompt.txt"
)

hooks = Hooks()

@hooks.on.output_validate_error
def log_model_retries(ctx: RunContext, /, *, output_context: Any, output: Any, error: Exception):
    import json
    print(f"Model validation failed and retried due to error: {error}")
    if isinstance(output, dict):
        try:
            print(f"Model response (raw): {json.dumps(output, indent=2)}")
        except Exception:
            print(f"Model response (raw): {output}")
    else:
        print(f"Model response (raw): {output}")
    raise error

def load_instructions() -> str:
    if os.path.exists(PROMPT_PATH):
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    else:
        return "Extract entities and relationships from California politics stories."

def get_extraction_agent(defer_check: bool = True, retries: int = 3) -> Agent:
    load_dotenv()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = os.environ.get("OLLAMA_MODEL", "gemma4:31b")
    
    base_url = ollama_base_url
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
        
    provider = OllamaProvider(
        base_url=base_url,
    )
    
    model = OllamaModel(
        model_name=ollama_model,
        provider=provider,
    )
    
    instructions = load_instructions()
    
    return Agent(
        model,
        output_type=ExtractionResult,
        instructions=instructions,
        defer_model_check=defer_check,
        retries=retries,
        capabilities=[hooks],
    )

def extract_entities(text: str, agent: Agent | None = None) -> ExtractionResult:
    if agent is None:
        agent = get_extraction_agent()
    
    result = agent.run_sync(text)
    return result.output


class ExtractionError(Exception):
    def __init__(
        self,
        original_text: str,
        validation_issues: list[str],
        failure_type: str,
        retry_count: int,
        metadata: dict
    ) -> None:
        self.original_text = original_text
        self.validation_issues = validation_issues
        self.failure_type = failure_type
        self.retry_count = retry_count
        self.metadata = metadata
        super().__init__(f"Entity extraction failed: {failure_type}")


class PydanticAIEntityExtractionAdapter:
    """Concrete adapter for entity extraction that conforms to the EntityExtractionAdapter protocol."""

    def __init__(self, agent: Agent | None = None) -> None:
        self.agent = agent or get_extraction_agent()

    def extract(self, chunk_text: str) -> ExtractionResult:
        try:
            return extract_entities(chunk_text, agent=self.agent)
        except Exception as e:
            validation_issues = []
            if hasattr(e, "errors") and callable(e.errors):
                try:
                    for err in e.errors():
                        loc_str = " -> ".join(str(loc) for loc in err.get("loc", []))
                        msg = err.get("msg", "Validation error")
                        validation_issues.append(f"{loc_str}: {msg}")
                except Exception:
                    validation_issues = [str(e)]
            if not validation_issues:
                validation_issues = [str(e)]

            metadata = {}
            if hasattr(self.agent, "model"):
                try:
                    from knowledge_map.adapters.coreference import get_agent_metadata
                    metadata = get_agent_metadata(self.agent)
                except Exception:
                    pass

            raise ExtractionError(
                original_text=chunk_text,
                validation_issues=validation_issues,
                failure_type="extraction_validation_failure",
                retry_count=getattr(self.agent, "retries", 0),
                metadata=metadata
            )

    def health_check(self) -> bool:
        try:
            agent = self.agent or get_extraction_agent()
            result = agent.run_sync(
                "health_check",
                output_type=str,
                model_settings={"max_tokens": 1}
            )
            return bool(result and result.output)
        except Exception:
            return False





