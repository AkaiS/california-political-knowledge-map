import hashlib
import json
import logging
import os
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Hooks

from knowledge_map.adapters.coreference import get_agent_metadata
from knowledge_map.ontology.extraction_conformance import (
    ConformanceDrop,
    conform_extraction_result,
)
from knowledge_map.ontology.extraction_prompt import render_extraction_ontology
from knowledge_map.schemas import AdherenceReport, ExtractionResult
from knowledge_map.utils.models import get_chat_model

logger = logging.getLogger(__name__)

PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources",
    "extraction_prompt.txt"
)
ONTOLOGY_PLACEHOLDER = "{{NEWS_ONTOLOGY}}"

hooks = Hooks()

@hooks.on.output_validate_error
def log_model_retries(ctx: RunContext, /, *, output_context: Any, output: Any, error: Exception):
    logger.debug(f"Model validation failed and retried due to error: {error}")
    if isinstance(output, dict):
        try:
            logger.debug(f"Model response (raw): {json.dumps(output, indent=2)}")
        except Exception:
            logger.debug(f"Model response (raw): {output}")
    else:
        logger.debug(f"Model response (raw): {output}")
    raise error

def load_instructions() -> str:
    if os.path.exists(PROMPT_PATH):
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            prompt = f.read()
        if prompt.count(ONTOLOGY_PLACEHOLDER) != 1:
            raise ValueError(
                f"Extraction prompt must contain exactly one {ONTOLOGY_PLACEHOLDER} placeholder"
            )
        return prompt.replace(ONTOLOGY_PLACEHOLDER, render_extraction_ontology())
    else:
        return "Extract entities and relationships from California politics stories."

def get_extraction_agent(defer_check: bool = True, retries: int = 3) -> Agent:
    model = get_chat_model("gemma4:31b", "OLLAMA_MODEL_EXTRACTION")
    
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
        self.reset_adherence_report()

    def reset_adherence_report(self) -> None:
        self._adherence_report = AdherenceReport()

    @property
    def adherence_report(self) -> AdherenceReport:
        return self._adherence_report.model_copy(deep=True)

    def _record_drop(self, drop: ConformanceDrop) -> None:
        self._adherence_report.record(drop.category, drop.value, drop.chunk_id)
        logger.warning(
            "Dropped extraction item (%s=%s, chunk=%s): %s",
            drop.category,
            drop.value,
            drop.chunk_id,
            drop.reason,
        )

    def _conform(self, result: ExtractionResult, chunk_text: str) -> ExtractionResult:
        chunk_id = f"sha256:{hashlib.sha256(chunk_text.encode('utf-8')).hexdigest()}"
        outcome = conform_extraction_result(result, chunk_id)
        for drop in outcome.drops:
            self._record_drop(drop)
        return outcome.result

    def extract(self, chunk_text: str) -> ExtractionResult:
        try:
            result = extract_entities(chunk_text, agent=self.agent)
            return self._conform(result, chunk_text)
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

            # ``get_agent_metadata`` already yields ``{}`` for an agent that
            # will not name its model.  Reading the instruction text off disk
            # is the remaining call that can fail here, and failing to
            # describe the prompt must not displace the extraction failure
            # being raised.
            try:
                instructions = load_instructions()
            except Exception:
                instructions = ""
            metadata = get_agent_metadata(self.agent, instructions)

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



