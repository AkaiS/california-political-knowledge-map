import os
import re
from typing import List
from pydantic_ai import Agent
from knowledge_map.utils.models import get_ollama_model
from knowledge_map.schemas import CriticValidation

def replace_tags_with_entities(annotated_text: str) -> str:
    # Pattern to match <ref entity="Canonical Name">pronoun</ref>
    # Supports single or double quotes, and matches case-insensitively
    pattern = r"<ref\s+entity=['\"](.*?)['\"]>(.*?)</ref>"
    return re.sub(pattern, r"\1", annotated_text, flags=re.DOTALL | re.IGNORECASE)

def strip_ref_tags(annotated_text: str) -> str:
    # Pattern to match <ref entity="Canonical Name">pronoun</ref>
    # Supports single/double quotes, spaces around '=' and attributes, case-insensitive
    pattern = r"<ref\s+entity\s*=\s*['\"](.*?)['\"]\s*>(.*?)</ref>"
    return re.sub(pattern, r"\2", annotated_text, flags=re.DOTALL | re.IGNORECASE)

def normalize_whitespace(text: str) -> str:
    # Collapses multiple consecutive whitespace/newline characters into single spaces
    # and trims leading/trailing whitespace
    return re.sub(r"\s+", " ", text).strip()

def check_structural_identity(original_text: str, annotated_text: str) -> bool:
    normalized_original = normalize_whitespace(original_text)
    stripped_annotated = strip_ref_tags(annotated_text)
    normalized_annotated = normalize_whitespace(stripped_annotated)
    return normalized_original == normalized_annotated


def _get_model():
    return get_ollama_model("8k-gemma-e4b-extraction", "OLLAMA_MODEL_COREFERENCE")

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

class CoreferenceResolutionError(Exception):
    def __init__(
        self,
        original_text: str,
        annotated_text: str,
        validation_issues: List[str],
        failure_type: str,
        retry_count: int,
        metadata: dict
    ) -> None:
        self.original_text = original_text
        self.annotated_text = annotated_text
        self.validation_issues = validation_issues
        self.failure_type = failure_type
        self.retry_count = retry_count
        self.metadata = metadata
        super().__init__(f"Coreference resolution failed: {failure_type}")

def get_agent_metadata(agent: Agent | None) -> dict:
    if agent is None:
        return {}
    
    model_name = "unknown"
    if agent.model:
        model_name = getattr(agent.model, "model_name", str(agent.model))
        
    system_prompt = ""
    # Safe resolution of static and dynamic instructions from Pydantic AI Agent
    if hasattr(agent, "_instructions") and agent._instructions:
        parts = []
        for inst in agent._instructions:
            if isinstance(inst, str):
                parts.append(inst)
            elif callable(inst):
                try:
                    parts.append(inst())
                except Exception:
                    parts.append(str(inst))
        system_prompt = "\n\n".join(parts)
                
    return {
        "model": model_name,
        "temperature": 0.0,
        "prompt_version": "1.0",
        "system_prompt": system_prompt
    }

def resolve_coreferences(
    text: str,
    annotator_agent: Agent | None = None,
    critic_agent: Agent | None = None,
    max_retries: int = 3,
    raise_on_failure: bool = False
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
        # Check structural identity immediately after annotator runs
        if not check_structural_identity(text, annotated_text):
            if retry_count < max_retries:
                retry_count += 1
                feedback = (
                    "Structural mismatch detected: the annotated text structure must exactly match "
                    "the original text structure (excluding <ref> tags). Do not add, remove, or modify "
                    "any other words or punctuation. Please output the complete updated annotated text."
                )
                run_result = annotator_agent.run_sync(feedback, message_history=run_result.all_messages())
                annotated_text = clean_annotated_text(run_result.output)
                continue
            else:
                # Reached max retries, fall back or raise
                if raise_on_failure:
                    raise CoreferenceResolutionError(
                        original_text=text,
                        annotated_text=annotated_text,
                        validation_issues=["Structural mismatch detected: annotated text structure must exactly match original text structure (excluding <ref> tags)."],
                        failure_type="structural_mismatch",
                        retry_count=retry_count,
                        metadata=get_agent_metadata(annotator_agent)
                    )
                return text

        # Critic validation pass (bypassed if structural check fails)
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
            # Reached max retries, fall back or raise
            if raise_on_failure:
                raise CoreferenceResolutionError(
                    original_text=text,
                    annotated_text=annotated_text,
                    validation_issues=validation.issues,
                    failure_type="critic_rejection",
                    retry_count=retry_count,
                    metadata=get_agent_metadata(annotator_agent)
                )
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
        try:
            annotated_text = resolve_coreferences(
                content,
                annotator_agent=self.annotator_agent,
                critic_agent=self.critic_agent,
                max_retries=self.max_retries,
                raise_on_failure=True
            )
            return replace_tags_with_entities(annotated_text)
        except CoreferenceResolutionError:
            raise
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
            try:
                metadata = get_agent_metadata(self.annotator_agent)
            except Exception:
                pass

            raise CoreferenceResolutionError(
                original_text=content,
                annotated_text="",
                validation_issues=validation_issues,
                failure_type="coreference_validation_failure",
                retry_count=self.max_retries,
                metadata=metadata
            )

    def health_check(self) -> bool:
        try:
            agent = self.annotator_agent or get_annotator_agent()
            result = agent.run_sync(
                "health_check",
                output_type=str,
                model_settings={"max_tokens": 1}
            )
            return bool(result and result.output)
        except Exception:
            return False




