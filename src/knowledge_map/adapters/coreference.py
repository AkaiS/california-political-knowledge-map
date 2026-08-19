import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from pydantic import TypeAdapter
from pydantic_ai import Agent

from knowledge_map.schemas import (
    CoreferenceResolutionRun,
    CriticVerdict,
    MentionSpan,
    MentionSpanDiscard,
    MentionSpanOutcome,
    NumberedSentenceRecord,
)
from knowledge_map.utils.models import get_ollama_model
from knowledge_map.utils.sentences import (
    NumberedSentence,
    split_into_numbered_sentences,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LocatedMentionSpan:
    """A Mention Span with a character range derived from source content."""

    mention_span: MentionSpan
    start_index: int
    end_index: int


class MentionSpanValidationResult(NamedTuple):
    """Validated Mention Spans and the ones rejected with their reasons."""

    valid_spans: list[LocatedMentionSpan]
    discards: list[MentionSpanDiscard]


class MentionSpanSubstitutionResult(NamedTuple):
    """Resolved content together with validation discards."""

    resolved_text: str
    discards: list[MentionSpanDiscard]


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

class CoreferenceResolutionError(Exception):
    def __init__(
        self,
        original_text: str,
        validation_issues: list[str] | None = None,
        failure_type: str = "coreference_validation_failure",
        retry_count: int = 0,
        metadata: dict | None = None,
        resolution_run: CoreferenceResolutionRun | None = None,
    ) -> None:
        self.original_text = original_text
        self.validation_issues = validation_issues or []
        self.failure_type = failure_type
        self.retry_count = retry_count
        self.metadata = metadata or {}
        # Consumers that need the sentence table, the Mention Spans or the
        # per-span outcomes unpack them from the run itself.
        self.resolution_run = resolution_run
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


def _structured_output_failure(
    content: str,
    annotator_agent: Agent | None,
    error: Exception,
    resolution_run: CoreferenceResolutionRun | None = None,
) -> CoreferenceResolutionError:
    """Build the adapter error for invalid structured model output."""

    try:
        metadata = get_agent_metadata(annotator_agent)
    except Exception:
        metadata = {}

    return CoreferenceResolutionError(
        original_text=content,
        validation_issues=_validation_issues_from_error(error),
        failure_type="coreference_validation_failure",
        retry_count=0,
        metadata=metadata,
        resolution_run=resolution_run,
    )


@dataclass(frozen=True, slots=True)
class MentionSpanIdentity:
    """The model-visible identity shared by a Mention Span and its verdict."""

    sentence_label: str
    mention_text: str
    occurrence: int

    @classmethod
    def of(cls, span: "MentionSpan | CriticVerdict") -> "MentionSpanIdentity":
        """Build an identity from anything carrying the three identity fields."""

        return cls(
            sentence_label=span.sentence_label,
            mention_text=span.mention_text,
            occurrence=span.occurrence,
        )


def _log_contested_locations(mention_spans: Sequence[MentionSpan]) -> None:
    """Report one text location claimed by more than one canonical entity.

    ``MentionSpanIdentity`` deliberately excludes the canonical entity name, so
    two Mention Spans naming the same location with different entities share one
    key in the run's outcome map and only the last one survives there.  That
    collapse is intended for a span corrected across retries; when it happens
    inside a single response it means the annotator contradicted itself, which
    is a signal about annotator quality rather than a resolution outcome.
    """

    entities_by_identity: dict[MentionSpanIdentity, list[str]] = {}
    for mention_span in mention_spans:
        entities_by_identity.setdefault(
            MentionSpanIdentity.of(mention_span), []
        ).append(mention_span.canonical_entity_name)

    for identity, entity_names in entities_by_identity.items():
        if len(set(entity_names)) > 1:
            logger.debug(
                "Annotator claimed one location for %d different canonical "
                "entities: sentence %r, mention %r, occurrence %d -> %s",
                len(set(entity_names)),
                identity.sentence_label,
                identity.mention_text,
                identity.occurrence,
                sorted(set(entity_names)),
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

    # The Critic's reason is per-span feedback, so it stays attached to the
    # rendering of its own Mention Span rather than being pooled.
    rejected = "\n".join(
        f"{format_mention_spans([mention_span])}\n  Critic reason: {reason}"
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
) -> dict[MentionSpanIdentity, CriticVerdict]:
    """Keep only verdicts whose identity was sent to the Coreference Critic."""

    sent_identities = {
        MentionSpanIdentity.of(located.mention_span) for located in mention_spans
    }
    matching: dict[MentionSpanIdentity, CriticVerdict] = {}
    for verdict in verdicts:
        identity = MentionSpanIdentity.of(verdict)
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
            MentionSpanIdentity.of(located.mention_span)
        )
        if verdict is None:
            # Fail closed when the Critic omits a Mention Span's verdict, and
            # retain the reason so the retry and DLQ can distinguish it from a
            # validation discard.
            rejected.append(
                (
                    located.mention_span,
                    "Coreference Critic returned no verdict for this Mention Span",
                )
            )
            continue
        if verdict.accepted:
            accepted.append(located)
        else:
            rejected.append(
                (
                    located.mention_span,
                    verdict.reason or "Coreference Critic rejected this Mention Span",
                )
            )

    return accepted, rejected


def _sentence_records(
    sentences: Sequence[NumberedSentence],
) -> list[NumberedSentenceRecord]:
    """Copy the annotator's sentence table into the durable run schema."""

    return [
        NumberedSentenceRecord(
            label=sentence.label,
            text=sentence.text,
            start_index=sentence.start_index,
            end_index=sentence.end_index,
        )
        for sentence in sentences
    ]


def _build_resolution_run(
    text: str,
    sentences: Sequence[NumberedSentence],
    mention_spans: Sequence[MentionSpan],
    outcomes: Mapping["MentionSpanIdentity", MentionSpanOutcome],
    retry_count: int,
    *,
    resolved_text: str | None = None,
    failure_type: str | None = None,
) -> CoreferenceResolutionRun:
    """Build a serializable run record and calculate its discard metric.

    ``outcomes`` is keyed by Mention Span identity, so the run holds exactly one
    final outcome per span and the discard metric cannot be inflated by a span
    that was rejected in one round and corrected in a later one.
    """

    final_outcomes = list(outcomes.values())
    discarded_count = sum(not outcome.accepted for outcome in final_outcomes)
    total_outcomes = len(final_outcomes)
    return CoreferenceResolutionRun(
        resolved_text=text if resolved_text is None else resolved_text,
        sentences=_sentence_records(sentences),
        mention_spans=list(mention_spans),
        outcomes=final_outcomes,
        discarded_proportion=(
            discarded_count / total_outcomes if total_outcomes else 0.0
        ),
        retry_count=retry_count,
        failure_type=failure_type,
    )


def _outcome_for_discard(discard: MentionSpanDiscard) -> MentionSpanOutcome:
    """Convert deterministic validation output into a run outcome."""

    return MentionSpanOutcome(
        mention_span=discard.mention_span,
        stage="validation",
        outcome="discarded",
        reason=discard.reason,
    )


def _outcome_for_critic(
    mention_span: MentionSpan,
    *,
    accepted: bool,
    reason: str | None = None,
) -> MentionSpanOutcome:
    """Convert a Critic decision into the audit shape."""

    return MentionSpanOutcome(
        mention_span=mention_span,
        stage="critic",
        outcome="accepted" if accepted else "rejected",
        reason=reason,
    )


def _failure_issues(outcomes: Sequence[MentionSpanOutcome]) -> list[str]:
    """Return readable outcome details for the legacy DLQ issue field."""

    issues: list[str] = []
    for outcome in outcomes:
        if outcome.accepted:
            continue
        mention = outcome.mention_span
        identity = (
            f"sentence {mention.sentence_label!r}, "
            f"mention {mention.mention_text!r}, "
            f"occurrence {mention.occurrence}"
        )
        issues.append(f"{identity}: {outcome.reason}")
    return issues


def _zero_survivor_failure(
    text: str,
    run: CoreferenceResolutionRun,
    failure_type: str,
    annotator_agent: Agent | None,
) -> CoreferenceResolutionError:
    """Create the DLQ-worthy error for a run with no accepted spans."""

    try:
        metadata = get_agent_metadata(annotator_agent)
    except Exception:
        metadata = {}

    issues = _failure_issues(run.outcomes)
    if not issues and failure_type == "no_mentions_returned":
        issues = ["The annotator returned no Mention Spans"]

    return CoreferenceResolutionError(
        original_text=text,
        validation_issues=issues,
        failure_type=failure_type,
        retry_count=run.retry_count,
        metadata=metadata,
        resolution_run=run,
    )




def resolve_coreferences_run(
    text: str,
    annotator_agent: Agent | None = None,
    critic_agent: Agent | None = None,
    max_retries: int = 3,
) -> CoreferenceResolutionRun:
    """Resolve references and retain one final outcome per Mention Span.

    ``outcomes`` accumulates by Mention Span identity with last write winning,
    so a span rejected in one round and corrected in the next is recorded once,
    with the decision the run actually ended on.  Zero-survivor runs always
    raise: silently returning the source text would hide the failure.
    """

    if annotator_agent is None:
        annotator_agent = get_annotator_agent()
    if critic_agent is None:
        critic_agent = get_critic_agent()

    current_run: CoreferenceResolutionRun | None = None

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

        all_mention_spans = list(mention_spans)
        _log_contested_locations(mention_spans)
        validation = validate_mention_spans(text, sentences, mention_spans)
        outcomes: dict[MentionSpanIdentity, MentionSpanOutcome] = {
            MentionSpanIdentity.of(discard.mention_span): _outcome_for_discard(
                discard
            )
            for discard in validation.discards
        }

        if not mention_spans:
            current_run = _build_resolution_run(
                text,
                sentences,
                all_mention_spans,
                outcomes,
                retry_count=0,
                failure_type="no_mentions_returned",
            )
            raise _zero_survivor_failure(
                text,
                current_run,
                "no_mentions_returned",
                annotator_agent,
            )

        if not validation.valid_spans:
            current_run = _build_resolution_run(
                text,
                sentences,
                all_mention_spans,
                outcomes,
                retry_count=0,
                failure_type="all_mentions_discarded",
            )
            raise _zero_survivor_failure(
                text,
                current_run,
                "all_mentions_discarded",
                annotator_agent,
            )

        pending_spans = validation.valid_spans
        accepted_spans: dict[MentionSpanIdentity, LocatedMentionSpan] = {}
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

            for located in newly_accepted:
                identity = MentionSpanIdentity.of(located.mention_span)
                accepted_spans[identity] = located
                outcomes[identity] = _outcome_for_critic(
                    located.mention_span,
                    accepted=True,
                )
            for mention_span, reason in rejected_spans:
                identity = MentionSpanIdentity.of(mention_span)
                accepted_spans.pop(identity, None)
                outcomes[identity] = _outcome_for_critic(
                    mention_span,
                    accepted=False,
                    reason=reason,
                )

            if not rejected_spans or retry_count >= max_retries:
                break

            retry_count += 1
            retry_result = annotator_agent.run_sync(
                _retry_prompt(sentences, rejected_spans)
            )
            retry_mentions = TypeAdapter(list[MentionSpan]).validate_python(
                retry_result.output
            )
            # Every raw span the model returned stays in the run's audit trail,
            # including the ones dropped just below.
            all_mention_spans.extend(retry_mentions)

            # A correction preserves the span's identity and changes only its
            # canonical entity, so a returned identity that is not among the
            # retry targets is one this prompt never asked for and the Critic
            # never reviewed.  Such a span is dropped from substitution, and
            # deliberately kept out of ``outcomes`` so that a chatty annotator
            # cannot inflate the discard metric with spans nobody requested.
            retry_targets = {
                MentionSpanIdentity.of(mention_span)
                for mention_span, _ in rejected_spans
            }
            requested_retry_mentions = [
                mention_span
                for mention_span in retry_mentions
                if MentionSpanIdentity.of(mention_span) in retry_targets
            ]
            unrequested = [
                MentionSpanIdentity.of(mention_span)
                for mention_span in retry_mentions
                if MentionSpanIdentity.of(mention_span) not in retry_targets
            ]
            if unrequested:
                logger.debug(
                    "Dropping %d unrequested Mention Span(s) from the retry "
                    "response: %s",
                    len(unrequested),
                    unrequested,
                )

            _log_contested_locations(requested_retry_mentions)
            retry_validation = validate_mention_spans(
                text,
                sentences,
                requested_retry_mentions,
            )
            for discard in retry_validation.discards:
                outcomes[MentionSpanIdentity.of(discard.mention_span)] = (
                    _outcome_for_discard(discard)
                )
            pending_spans = retry_validation.valid_spans

        surviving = list(accepted_spans.values())
        resolved_text = _substitute_located_mention_spans(text, surviving)
        if not surviving:
            current_run = _build_resolution_run(
                text,
                sentences,
                all_mention_spans,
                outcomes,
                retry_count=retry_count,
                resolved_text=resolved_text,
                failure_type="all_mentions_rejected",
            )
            raise _zero_survivor_failure(
                text,
                current_run,
                "all_mentions_rejected",
                annotator_agent,
            )

        return _build_resolution_run(
            text,
            sentences,
            all_mention_spans,
            outcomes,
            retry_count=retry_count,
            resolved_text=resolved_text,
        )
    except CoreferenceResolutionError:
        raise
    except Exception as error:
        # Structured-output parsing and model failures are failures at this
        # seam.  In particular, never treat a text response as resolved text.
        raise _structured_output_failure(
            text,
            annotator_agent,
            error,
            resolution_run=current_run,
        ) from error


def resolve_coreferences(
    text: str,
    annotator_agent: Agent | None = None,
    critic_agent: Agent | None = None,
    max_retries: int = 3,
) -> str:
    """Resolve references and return only the resolved content."""

    return resolve_coreferences_run(
        text,
        annotator_agent=annotator_agent,
        critic_agent=critic_agent,
        max_retries=max_retries,
    ).resolved_text


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

    def resolve(self, content: str) -> CoreferenceResolutionRun:
        annotator_agent: Agent | None = self.annotator_agent
        try:
            annotator_agent = annotator_agent or get_annotator_agent()
            critic_agent = self.critic_agent or get_critic_agent()
            return resolve_coreferences_run(
                content,
                annotator_agent=annotator_agent,
                critic_agent=critic_agent,
                max_retries=self.max_retries,
            )
        except CoreferenceResolutionError:
            raise
        except Exception as error:
            raise _structured_output_failure(
                content,
                annotator_agent,
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
