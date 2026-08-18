import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from pydantic import TypeAdapter
from pydantic_ai import Agent

from knowledge_map.schemas import CriticVerdict, MentionSpan, MentionSpanDiscard
from knowledge_map.utils.models import get_ollama_model
from knowledge_map.utils.sentences import (
    NumberedSentence,
    split_into_numbered_sentences,
)


@dataclass(frozen=True, slots=True)
class LocatedMentionSpan:
    """A Mention Span with a character range derived from source content."""

    mention_span: MentionSpan
    start_index: int
    end_index: int

    @property
    def start(self) -> int:
        """Return the inclusive start position of the located mention."""

        return self.start_index

    @property
    def end(self) -> int:
        """Return the exclusive end position of the located mention."""

        return self.end_index


class MentionSpanValidationResult(NamedTuple):
    """Validated Mention Spans and the ones rejected with their reasons."""

    valid_spans: list[LocatedMentionSpan]
    discards: list[MentionSpanDiscard]

    @property
    def surviving_spans(self) -> list[LocatedMentionSpan]:
        """Return the spans that can safely be substituted."""

        return self.valid_spans


class MentionSpanSubstitutionResult(NamedTuple):
    """Resolved content together with validation discards."""

    resolved_text: str
    discards: list[MentionSpanDiscard]

    @property
    def text(self) -> str:
        """Return the resolved content using the short result name."""

        return self.resolved_text


def _mention_matches(sentence_text: str, mention_text: str) -> list[re.Match[str]]:
    """Find exact mention-text matches whose outer edges are word boundaries."""

    # ``(?<!\\w)`` and ``(?!\\w)`` express the useful part of ``\\b`` while
    # also handling mentions ending in punctuation, such as ``U.S.``.
    pattern = re.compile(rf"(?<!\w){re.escape(mention_text)}(?!\w)")
    return list(pattern.finditer(sentence_text))


def validate_mention_spans(
    content: str,
    sentences: Sequence[NumberedSentence],
    mention_spans: Sequence[MentionSpan],
) -> MentionSpanValidationResult:
    """Locate usable Mention Spans and report every deterministic discard.

    Sentence ranges are the only source of positional information.  For each
    Mention Span this function searches the source slice identified by its
    sentence label, selects its one-based occurrence, and offsets the match by
    the sentence's recorded start.  The first span in input order wins when
    two located ranges overlap; the later span is reported as discarded.
    """

    sentences_by_label = {sentence.label: sentence for sentence in sentences}
    located: list[LocatedMentionSpan] = []
    discards: list[MentionSpanDiscard] = []

    for mention_span in mention_spans:
        sentence = sentences_by_label.get(mention_span.sentence_label)
        if sentence is None:
            discards.append(
                MentionSpanDiscard(
                    mention_span=mention_span,
                    reason=(
                        f"unknown sentence label {mention_span.sentence_label!r}"
                    ),
                )
            )
            continue

        sentence_text = content[sentence.start_index : sentence.end_index]
        matches = _mention_matches(sentence_text, mention_span.mention_text)
        if not matches:
            discards.append(
                MentionSpanDiscard(
                    mention_span=mention_span,
                    reason=(
                        f"mention text {mention_span.mention_text!r} does not occur "
                        f"in sentence {sentence.label!r}"
                    ),
                )
            )
            continue

        occurrence_index = mention_span.occurrence - 1
        if occurrence_index >= len(matches):
            discards.append(
                MentionSpanDiscard(
                    mention_span=mention_span,
                    reason=(
                        f"occurrence {mention_span.occurrence} exceeds the "
                        f"{len(matches)} match(es) available in sentence "
                        f"{sentence.label!r}"
                    ),
                )
            )
            continue

        match = matches[occurrence_index]
        candidate = LocatedMentionSpan(
            mention_span=mention_span,
            start_index=sentence.start_index + match.start(),
            end_index=sentence.start_index + match.end(),
        )

        if any(
            candidate.start_index < existing.end_index
            and existing.start_index < candidate.end_index
            for existing in located
        ):
            discards.append(
                MentionSpanDiscard(
                    mention_span=mention_span,
                    reason="character range overlaps an earlier Mention Span",
                )
            )
            continue

        located.append(candidate)

    return MentionSpanValidationResult(valid_spans=located, discards=discards)


def _substitute_located_mention_spans(
    content: str,
    located_spans: Sequence[LocatedMentionSpan],
) -> str:
    """Apply located spans from right to left so ranges stay source-relative."""

    resolved = content
    for located in sorted(
        located_spans,
        key=lambda span: span.start_index,
        reverse=True,
    ):
        resolved = (
            resolved[: located.start_index]
            + located.mention_span.canonical_entity_name
            + resolved[located.end_index :]
        )
    return resolved


def substitute_mention_spans(
    content: str,
    sentences: Sequence[NumberedSentence],
    mention_spans: Sequence[MentionSpan],
) -> MentionSpanSubstitutionResult:
    """Validate Mention Spans and substitute the survivors into ``content``."""

    validation = validate_mention_spans(content, sentences, mention_spans)
    return MentionSpanSubstitutionResult(
        resolved_text=_substitute_located_mention_spans(
            content,
            validation.valid_spans,
        ),
        discards=validation.discards,
    )


# These names describe the same deterministic seam in caller-oriented terms.
resolve_mention_spans = substitute_mention_spans
apply_mention_spans = substitute_mention_spans

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


def format_numbered_sentences(sentences: Sequence[NumberedSentence]) -> str:
    """Render the sentence table in the form shown to the annotator."""

    return "\n".join(
        f"[{sentence.label}] {sentence.text}" for sentence in sentences
    )


def format_mention_spans(mention_spans: Sequence[MentionSpan]) -> str:
    """Render Mention Spans as the compact input to the Coreference Critic."""

    return "\n".join(
        "- "
        f"sentence_label={mention_span.sentence_label!r}, "
        f"mention_text={mention_span.mention_text!r}, "
        f"occurrence={mention_span.occurrence}, "
        f"canonical_entity_name={mention_span.canonical_entity_name!r}"
        for mention_span in mention_spans
    )


def get_annotator_agent(defer_check: bool = True) -> Agent:
    model = _get_model()

    instructions = (
        "You are an expert Coreference Resolution annotator.\n"
        "Identify ambiguous pronouns and referring expressions in the numbered "
        "Source Article and map each one to its canonical entity name.\n\n"
        "Return only a structured list of Mention Spans. For every Mention Span:\n"
        "- copy `sentence_label` from the label at the start of the sentence line;\n"
        "- copy `mention_text` verbatim, including its capitalization;\n"
        "- use `occurrence` only when the same mention text appears more than "
        "once in that sentence (it is one-based and defaults to 1); and\n"
        "- provide the canonical, fully expanded `canonical_entity_name`.\n\n"
        "Return only Mention Spans; never return the Source Article itself. "
        "Return an empty list when there are no references to resolve."
    )

    return Agent(
        model,
        name="coreference_annotator",
        output_type=list[MentionSpan],
        instructions=instructions,
        defer_model_check=defer_check,
    )

def get_critic_agent(defer_check: bool = True) -> Agent:
    model = _get_model()

    instructions = (
        "You are a Coreference Critic.\n"
        "Review the numbered Source Article and the validated Mention Spans "
        "listed below it. The Source Article appears exactly once. Judge each "
        "listed Mention Span independently.\n\n"
        "You must:\n"
        "1. Return one verdict for every validated Mention Span;\n"
        "2. copy its `sentence_label`, `mention_text`, and `occurrence` exactly;\n"
        "3. set `accepted` to true only when its canonical entity is correct; and\n"
        "4. provide a short, specific `reason` whenever `accepted` is false.\n\n"
        "Return only the structured list of per-Mention-Span verdicts. Do not "
        "return an article-level pass/fail value, and do not invent verdicts "
        "for Mention Spans that were not listed."
    )

    return Agent(
        model,
        name="coreference_critic",
        output_type=list[CriticVerdict],
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
        validation_issues: list[str],
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


def _validation_issues_from_error(error: Exception) -> list[str]:
    """Return useful, provider-neutral details for an annotator failure."""

    issues: list[str] = []
    errors = getattr(error, "errors", None)
    if callable(errors):
        try:
            for detail in errors():
                location = " -> ".join(str(item) for item in detail.get("loc", []))
                message = detail.get("msg", "Validation error")
                issues.append(f"{location}: {message}" if location else message)
        except Exception:
            issues = []

    return issues or [str(error) or "Annotator output could not be parsed"]


def _annotator_failure(
    content: str,
    annotator_agent: Agent,
    error: Exception,
) -> CoreferenceResolutionError:
    """Build the existing adapter error for invalid structured output."""

    try:
        metadata = get_agent_metadata(annotator_agent)
    except Exception:
        metadata = {}

    return CoreferenceResolutionError(
        original_text=content,
        annotated_text="",
        validation_issues=_validation_issues_from_error(error),
        failure_type="coreference_validation_failure",
        retry_count=0,
        metadata=metadata,
    )


def _mention_span_identity(mention_span: MentionSpan) -> tuple[str, str, int]:
    """Return the model-visible identity of a Mention Span."""

    return (
        mention_span.sentence_label,
        mention_span.mention_text,
        mention_span.occurrence,
    )


def _critic_prompt(
    sentences: Sequence[NumberedSentence],
    mention_spans: Sequence[MentionSpan],
) -> str:
    """Build the one-copy source plus compact Mention Span critic prompt."""

    return (
        "Review each validated Mention Span against the numbered Source Article. "
        "The Source Article is included exactly once. Return one verdict per "
        "listed Mention Span and copy its identity fields exactly.\n\n"
        "Numbered Source Article:\n"
        f"{format_numbered_sentences(sentences)}\n\n"
        "Validated Mention Spans:\n"
        f"{format_mention_spans(mention_spans)}"
    )


def _retry_prompt(
    sentences: Sequence[NumberedSentence],
    rejected_spans: Sequence[tuple[MentionSpan, str]],
) -> str:
    """Ask the annotator to replace only the spans rejected by the critic."""

    rejected = "\n".join(
        "- "
        f"sentence_label={mention_span.sentence_label!r}, "
        f"mention_text={mention_span.mention_text!r}, "
        f"occurrence={mention_span.occurrence}, "
        f"previous_canonical_entity_name={mention_span.canonical_entity_name!r}\n"
        f"  Critic reason: {reason}"
        for mention_span, reason in rejected_spans
    )
    return (
        "Correct only the rejected Mention Spans listed below. Read the numbered "
        "Source Article for context, return only replacement Mention Spans for "
        "those targets, and do not return accepted or unrelated Mention Spans.\n\n"
        "Numbered Source Article:\n"
        f"{format_numbered_sentences(sentences)}\n\n"
        "Rejected Mention Spans and Critic Reasons:\n"
        f"{rejected}"
    )


def _matching_critic_verdicts(
    mention_spans: Sequence[LocatedMentionSpan],
    verdicts: Sequence[CriticVerdict],
) -> dict[tuple[str, str, int], CriticVerdict]:
    """Keep only verdicts whose identity was sent to the Coreference Critic."""

    sent_identities = {
        _mention_span_identity(located.mention_span) for located in mention_spans
    }
    matching: dict[tuple[str, str, int], CriticVerdict] = {}
    for verdict in verdicts:
        identity = _mention_span_identity(verdict)
        if identity in sent_identities:
            matching.setdefault(identity, verdict)
    return matching


def _apply_critic_verdicts(
    located_spans: Sequence[LocatedMentionSpan],
    verdicts: Sequence[CriticVerdict],
) -> tuple[list[LocatedMentionSpan], list[tuple[MentionSpan, str]]]:
    """Separate accepted spans from rejected spans with retry feedback."""

    matching_verdicts = _matching_critic_verdicts(located_spans, verdicts)
    accepted: list[LocatedMentionSpan] = []
    rejected: list[tuple[MentionSpan, str]] = []

    for located in located_spans:
        verdict = matching_verdicts.get(
            _mention_span_identity(located.mention_span)
        )
        if verdict is None:
            # Fail closed when the Critic omits a Mention Span's verdict.
            continue
        if verdict.accepted:
            accepted.append(located)
        else:
            rejected.append((located.mention_span, verdict.reason))

    return accepted, rejected


def resolve_coreferences(
    text: str,
    annotator_agent: Agent | None = None,
    critic_agent: Agent | None = None,
    max_retries: int = 3,
    raise_on_failure: bool = False
) -> str:
    """Resolve references through per-Mention-Span Critic verdicts."""

    if annotator_agent is None:
        annotator_agent = get_annotator_agent()
    if critic_agent is None:
        critic_agent = get_critic_agent()
    # ``raise_on_failure`` remains part of the adapter compatibility surface;
    # zero-survivor failure handling belongs to the following issue.
    _ = raise_on_failure

    try:
        sentences = split_into_numbered_sentences(text)
        annotation_prompt = (
            "Resolve the references in the following Source Article. The article "
            "is shown as numbered sentences; copy a visible sentence label into "
            "each Mention Span.\n\n"
            "Numbered Source Article:\n"
            f"{format_numbered_sentences(sentences)}"
        )
        run_result = annotator_agent.run_sync(annotation_prompt)
        mention_spans = TypeAdapter(list[MentionSpan]).validate_python(
            run_result.output
        )

        validation = validate_mention_spans(text, sentences, mention_spans)
        pending_spans = validation.valid_spans
        accepted_spans: list[LocatedMentionSpan] = []
        retry_count = 0

        while pending_spans:
            critic_prompt = _critic_prompt(
                sentences,
                [located.mention_span for located in pending_spans],
            )
            critic_result = critic_agent.run_sync(critic_prompt)
            verdicts = TypeAdapter(list[CriticVerdict]).validate_python(
                critic_result.output
            )
            newly_accepted, rejected_spans = _apply_critic_verdicts(
                pending_spans,
                verdicts,
            )
            accepted_spans.extend(newly_accepted)

            if not rejected_spans or retry_count >= max_retries:
                break

            retry_count += 1
            retry_result = annotator_agent.run_sync(
                _retry_prompt(sentences, rejected_spans)
            )
            retry_mentions = TypeAdapter(list[MentionSpan]).validate_python(
                retry_result.output
            )
            retry_targets = {
                _mention_span_identity(mention_span)
                for mention_span, _ in rejected_spans
            }
            retry_mentions = [
                mention_span
                for mention_span in retry_mentions
                if _mention_span_identity(mention_span) in retry_targets
            ]
            pending_spans = validate_mention_spans(
                text,
                sentences,
                retry_mentions,
            ).valid_spans

        return _substitute_located_mention_spans(text, accepted_spans)
    except CoreferenceResolutionError:
        raise
    except Exception as error:
        # Structured-output parsing and model failures are failures at this
        # seam.  In particular, never treat a text response as resolved text.
        raise _annotator_failure(text, annotator_agent, error) from error


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
            return resolve_coreferences(
                content,
                annotator_agent=self.annotator_agent,
                critic_agent=self.critic_agent,
                max_retries=self.max_retries,
                raise_on_failure=True
            )
        except CoreferenceResolutionError:
            raise
        except Exception as error:
            raise _annotator_failure(
                content,
                self.annotator_agent or get_annotator_agent(),
                error,
            ) from error

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
