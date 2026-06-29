import os
import re
from typing import List
from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from dotenv import load_dotenv
from knowledge_map.schemas import CriticValidation

def replace_tags_with_entities(annotated_text: str) -> str:
    # Pattern to match <ref entity="Canonical Name">pronoun</ref>
    # Supports single or double quotes, and matches case-insensitively
    pattern = r"<ref\s+entity=['\"](.*?)['\"]>(.*?)</ref>"
    return re.sub(pattern, r"\1", annotated_text, flags=re.DOTALL | re.IGNORECASE)

def _get_model():
    load_dotenv()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = os.environ.get("OLLAMA_MODEL", "8k-gemma-e4b-extraction")
    
    base_url = ollama_base_url
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
        
    provider = OllamaProvider(
        base_url=base_url,
    )
    
    return OllamaModel(
        model_name=ollama_model,
        provider=provider,
    )

def get_annotator_agent(defer_check: bool = True) -> Agent:
    model = _get_model()
    
    instructions = (
        "You are an expert Coreference Resolution annotator.\n"
        "Your task is to identify ambiguous pronouns (like 'he', 'she', 'it', 'they', 'him', 'her', 'them', 'his', 'their', 'the governor', 'the company', 'the senator', etc.) and referring expressions in the text and wrap them in XML tags referencing their canonical entity name:\n"
        "<ref entity=\"Canonical Entity Name\">pronoun</ref>\n\n"
        "Guidelines:\n"
        "1. ONLY wrap ambiguous references. Do NOT wrap nouns that are already clear and unambiguous in the local context.\n"
        "2. The entity name in the `entity` attribute MUST be the canonical, fully expanded name of the person, organization, or object being referred to (e.g. 'Gavin Newsom', not just 'he' or 'Newsom').\n"
        "3. Keep the original text structure exactly the same. Do not add, remove, or modify any other parts of the text.\n"
        "4. Output the full text with the tags embedded in it. Do not wrap the output in markdown code blocks. Do not include any introductory or concluding conversational text.\n\n"
        "Example:\n"
        "Input: Newsom visited the school today. He gave a speech there.\n"
        "Output: Newsom visited the school today. <ref entity=\"Gavin Newsom\">He</ref> gave a speech there."
    )
    
    return Agent(
        model,
        output_type=str,
        instructions=instructions,
        defer_model_check=defer_check,
    )

def get_critic_agent(defer_check: bool = True) -> Agent:
    model = _get_model()
    
    instructions = (
        "You are a Coreference Critic.\n"
        "Your task is to review an annotated article containing <ref entity=\"Entity Name\">pronoun</ref> tags and validate if the references are correct and accurate.\n\n"
        "You must:\n"
        "1. Verify that the `entity` attribute in each <ref> tag is the correct canonical name of the entity being referred to by the pronoun/expression.\n"
        "2. Check for any hallucinated, incorrect, or mismatched entity assignments (e.g., if a pronoun referring to a school is mapped to a person).\n"
        "3. Check if any tag is improperly formatted or incomplete.\n\n"
        "You must return a structured response:\n"
        "- `is_valid` (boolean): True if all annotations are correct and valid, False otherwise.\n"
        "- `issues` (list of strings): A list of specific issues or errors found in the annotations. If `is_valid` is True, this list must be empty."
    )
    
    return Agent(
        model,
        output_type=CriticValidation,
        instructions=instructions,
        defer_model_check=defer_check,
    )

def clean_annotated_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
    return text

def resolve_coreferences(
    text: str,
    annotator_agent: Agent | None = None,
    critic_agent: Agent | None = None,
    max_retries: int = 3
) -> str:
    if annotator_agent is None:
        annotator_agent = get_annotator_agent()
    if critic_agent is None:
        critic_agent = get_critic_agent()
        
    # Initial annotation pass
    run_result = annotator_agent.run_sync(text)
    annotated_text = clean_annotated_text(run_result.output)
    
    retry_count = 0
    while True:
        # Critic validation pass
        critic_input = f"Please review the annotated text against the original text.\n\nOriginal text:\n{text}\n\nAnnotated text:\n{annotated_text}"
        critic_result = critic_agent.run_sync(critic_input)
        validation = critic_result.output
        
        if validation.is_valid:
            return annotated_text
            
        if retry_count < max_retries:
            retry_count += 1
            # Feed back issues to annotator
            feedback = (
                f"The Coreference Critic found the following issues in your previous annotation:\n"
                + "\n".join(f"- {issue}" for issue in validation.issues)
                + "\n\nPlease correct these issues and output the complete updated annotated text."
            )
            run_result = annotator_agent.run_sync(feedback, message_history=run_result.all_messages())
            annotated_text = clean_annotated_text(run_result.output)
        else:
            # Reached max retries, fall back to the original text
            return text


class PydanticAICoreferenceAdapter:
    """Concrete adapter for coreference resolution that conforms to the CoreferenceAdapter protocol."""

    def __init__(
        self,
        annotator_agent: Agent | None = None,
        critic_agent: Agent | None = None,
        max_retries: int = 3
    ) -> None:
        self.annotator_agent = annotator_agent
        self.critic_agent = critic_agent
        self.max_retries = max_retries

    def resolve(self, content: str) -> str:
        annotated_text = resolve_coreferences(
            content,
            annotator_agent=self.annotator_agent,
            critic_agent=self.critic_agent,
            max_retries=self.max_retries
        )
        return replace_tags_with_entities(annotated_text)


