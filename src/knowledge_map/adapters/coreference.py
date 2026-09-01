import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from pydantic import ValidationError
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelRequest, RetryPromptPart
from pydantic_ai.usage import RunUsage, UsageLimits

from knowledge_map.config import settings
from knowledge_map.schemas import (
    CoreferenceResolutionRun,
    CriticVerdict,
    MentionSpan,
    MentionSpanDiscard,
    MentionSpanOutcome,
    ModelDeployment,
    NumberedSentenceRecord,
)
from knowledge_map.utils.models import DEFAULT_LOCAL_CHAT_MODEL, get_chat_model
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

    # Lookarounds rather than ``\\b`` so mentions ending in punctuation match.
    pattern = re.compile(rf"(?<!\w){re.escape(mention_text)}(?!\w)")
    return list(pattern.finditer(sentence_text))


def validate_mention_spans(
    content: str,
    sentences: Sequence[NumberedSentence],
    mention_spans: Sequence[MentionSpan],
) -> MentionSpanValidationResult:
    """Locate usable Mention Spans and report every deterministic discard.

    Overlaps resolve in input order: the first span keeps its range and the
    later one is discarded.
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


def unclaimed_occurrences(
    content: str,
    sentences: Sequence[NumberedSentence],
    located_spans: Sequence[LocatedMentionSpan],
) -> list[MentionSpan]:
    """Propose a Mention Span for every repeat occurrence left unclaimed.

    Each proposal inherits the entity of its already-resolved sibling, so the
    Coreference Critic still judges every one of them.
    """

    sentences_by_label = {sentence.label: sentence for sentence in sentences}
    claimed: dict[tuple[str, str], set[int]] = {}
    entities: dict[tuple[str, str], str] = {}
    for located in located_spans:
        mention_span = located.mention_span
        key = (mention_span.sentence_label, mention_span.mention_text)
        claimed.setdefault(key, set()).add(mention_span.occurrence)
        entities.setdefault(key, mention_span.canonical_entity_name)

    proposals: list[MentionSpan] = []
    for (sentence_label, mention_text), occurrences in claimed.items():
        sentence = sentences_by_label.get(sentence_label)
        if sentence is None:
            continue
        sentence_text = content[sentence.start_index : sentence.end_index]
        available = len(_mention_matches(sentence_text, mention_text))
        for occurrence in range(1, available + 1):
            if occurrence in occurrences:
                continue
            proposals.append(
                MentionSpan(
                    sentence_label=sentence_label,
                    mention_text=mention_text,
                    occurrence=occurrence,
                    canonical_entity_name=entities[(sentence_label, mention_text)],
                )
            )
    return proposals


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


def _get_model(deployment: ModelDeployment | None = None):
    """Build the coreference model from an explicit or local deployment."""

    if deployment is not None:
        return get_chat_model(deployment)
    return get_chat_model(DEFAULT_LOCAL_CHAT_MODEL)


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


@dataclass(frozen=True, slots=True)
class CoreferenceDeps:
    """The Source Article and the numbered sentences split from it.

    Taken as the dependency by both coreference agents.
    """

    content: str
    sentences: tuple[NumberedSentence, ...]

    @classmethod
    def for_content(cls, content: str) -> "CoreferenceDeps":
        """Split ``content`` into the numbered sentences shown to the agents."""

        return cls(
            content=content,
            sentences=tuple(split_into_numbered_sentences(content)),
        )


def numbered_article_instructions(ctx: RunContext[CoreferenceDeps]) -> str:
    """Render the numbered Source Article, for both agents and nowhere else."""

    return (
        "Numbered Source Article:\n"
        f"{format_numbered_sentences(ctx.deps.sentences)}"
    )


ANNOTATOR_INSTRUCTIONS = (
    "You are an expert Coreference Resolution annotator."
    "Identify ambiguous pronouns and referring expressions in the numbered Source Article and map each one to its canonical entity name.\n\n"
    "Return only a structured list of Mention Spans. For every Mention Span:\n"
    "- copy `sentence_label` from the label at the start of the sentence line;\n"
    "- copy `mention_text` verbatim, including its capitalization. Ensure `mention_text` contains only the pronoun, noun phrase, or referring expression itself, and never include adjacent verbs, prepositions, or non-referential words;\n"
    "- return a separate Mention Span for every occurrence of a mention, including repeats within one sentence: number them with `occurrence` 1, 2, 3 and so on in the order they appear. `occurrence` is one-based and must always be explicitly included in every Mention Span, even when it is 1. Occurrences are counted over the exact `mention_text`, so `He` and `he` are counted separately; and\n"
    "- provide the canonical, fully expanded `canonical_entity_name`.\n\n"
    "Return only Mention Spans; never return the Source Article itself. Return an empty list when there are no references to resolve.\n\n"
    "`canonical_entity_name` is an identifier, not a description. Every "
    "mention you give the same name to becomes the same thing, and every "
    "difference in spelling makes a new one, so write the name the same way "
    "every time it appears in this article.\n\n"
    "For a person, use their first name, their last name, and their middle "
    "name when the article gives one: `Gary K. Michelson`, `Sarah Hill`. Not "
    "`Michelson`, not `the donor`, and not a title or role.\n\n"
    "For an organisation, a ballot measure, or any other named thing, use the "
    "name the article gives it: `California Institute for Immunology and "
    "Immunotherapy`, `Proposition 38`, `UCLA`. Not `the institute`, not `the "
    "measure`, not `the $4.2 billion institute`.\n\n"
    "Do not copy the phrase out of the sentence you found the mention in, and "
    "do not add anything the name does not need. `the other half of the bond "
    "money` and `the $120 million contribution to the institute` are "
    "descriptions of a moment in the article, not names.\n\n"
    "Some entities genuinely have no name: `voters`, `the average voter`, "
    "`factory farms`. Name those with the shortest phrase that identifies the "
    "same thing everywhere it appears."
)


CRITIC_INSTRUCTIONS = (
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


ANNOTATION_PROMPT = (
    "Resolve the references in the Source Article shown above. It is "
    "presented as numbered sentences; copy a visible sentence label "
    "into each Mention Span."
)
"""What the annotator is asked for, in every path that asks it.

A module constant because the annotator is now called from two places.
An annotator-only run that asked for something subtly different would
not be a baseline for the loop below it; it would be a different task.
"""


def _unlocatable_retry_message(discards: Sequence[MentionSpanDiscard]) -> str:
    """Tell the annotator why nothing it returned could be located."""

    reported = "\n".join(
        f"{format_mention_spans([discard.mention_span])}\n  Reason: {discard.reason}"
        for discard in discards
    )
    return (
        "None of the Mention Spans you returned could be located in the "
        "numbered Source Article. Copy `sentence_label` from a label shown at "
        "the start of a sentence line, copy `mention_text` verbatim from that "
        "sentence, and set `occurrence` to a one-based index that exists "
        "there. Return the corrected Mention Spans.\n\n"
        "Unlocatable Mention Spans:\n"
        f"{reported}"
    )


def validate_annotator_output(
    ctx: RunContext[CoreferenceDeps],
    mention_spans: list[MentionSpan],
) -> list[MentionSpan]:
    """Ask the annotator again when nothing it returned can be located.

    Registered as the annotator's output validator.  Empty, partially
    locatable, and retry-exhausted answers pass through for the resolution
    loop to record.
    """

    if not mention_spans:
        return mention_spans

    validation = validate_mention_spans(
        ctx.deps.content,
        ctx.deps.sentences,
        mention_spans,
    )
    if validation.valid_spans or ctx.retry >= ctx.max_retries:
        return mention_spans

    raise ModelRetry(_unlocatable_retry_message(validation.discards))


def get_annotator_agent(
    deployment: ModelDeployment | None = None,
    *,
    defer_check: bool = True,
    retries: int = 3,
) -> Agent:
    agent = Agent(
        _get_model(deployment),
        name="coreference_annotator",
        deps_type=CoreferenceDeps,
        output_type=list[MentionSpan],
        instructions=[ANNOTATOR_INSTRUCTIONS, numbered_article_instructions],
        defer_model_check=defer_check,
        retries=retries,
    )
    agent.output_validator(validate_annotator_output)
    return agent


def get_critic_agent(
    deployment: ModelDeployment | None = None,
    *,
    defer_check: bool = True,
    retries: int = 3,
) -> Agent:
    return Agent(
        _get_model(deployment),
        name="coreference_critic",
        deps_type=CoreferenceDeps,
        output_type=list[CriticVerdict],
        instructions=[CRITIC_INSTRUCTIONS, numbered_article_instructions],
        defer_model_check=defer_check,
        retries=retries,
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
        # Carries the sentence table, Mention Spans and per-span outcomes
        # the run reached before failing.
        self.resolution_run = resolution_run
        super().__init__(f"Coreference resolution failed: {failure_type}")

def get_agent_metadata(agent: Agent | None, instructions: str = "") -> dict:
    """Describe the agent behind a failure for the Dead Letter Queue record.

    Callers pass the static instruction text; it cannot be read back off an
    agent whose instructions are rendered per run.  Never raises — an agent
    that will not name its model yields no metadata.
    """

    if agent is None:
        return {}

    try:
        model = agent.model
        model_name = getattr(model, "model_name", str(model)) if model else "unknown"
    except Exception:
        return {}

    return {
        "model": model_name,
        "prompt_version": "1.0",
        "system_prompt": instructions,
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


#: Caught by the resolver and recorded to the Dead Letter Queue as a
#: coreference validation failure.
MODEL_OUTPUT_FAILURES: tuple[type[Exception], ...] = (
    ValidationError,
    UnexpectedModelBehavior,
)


def _structured_output_failure(
    content: str,
    annotator_agent: Agent | None,
    error: Exception,
    resolution_run: CoreferenceResolutionRun | None = None,
) -> CoreferenceResolutionError:
    """Build the adapter error for invalid structured model output."""

    metadata = get_agent_metadata(annotator_agent, ANNOTATOR_INSTRUCTIONS)

    return CoreferenceResolutionError(
        original_text=content,
        validation_issues=_validation_issues_from_error(error),
        failure_type="coreference_validation_failure",
        retry_count=0 if resolution_run is None else resolution_run.retry_count,
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

    Called on a single annotator response, where such a collision means the
    annotator contradicted itself rather than corrected itself.
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


def _critic_prompt(mention_spans: Sequence[MentionSpan]) -> str:
    """Ask for one verdict per Mention Span; the article is in the instructions."""

    return (
        "Review each validated Mention Span against the numbered Source "
        "Article. Return one verdict per listed Mention Span and copy its "
        "identity fields exactly.\n\n"
        "Validated Mention Spans:\n"
        f"{format_mention_spans(mention_spans)}"
    )


def _retry_prompt(rejected_spans: Sequence[tuple[MentionSpan, str]]) -> str:
    """Ask the annotator to replace only the spans rejected by the critic."""

    # Each reason stays attached to its own Mention Span.
    rejected = "\n".join(
        f"{format_mention_spans([mention_span])}\n  Critic reason: {reason}"
        for mention_span, reason in rejected_spans
    )
    return (
        "Correct only the rejected Mention Spans listed below. Return only "
        "replacement Mention Spans for those targets, and do not return "
        "accepted or unrelated Mention Spans.\n\n"
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
            # Fail closed on an omitted verdict, with a reason the retry and
            # DLQ can tell apart from a validation discard.
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


def _count_retry_prompts(messages: Sequence[ModelMessage]) -> int:
    """Count the corrections asked for within one annotator conversation."""

    return sum(
        1
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, RetryPromptPart)
    )


@dataclass(slots=True)
class ResolutionState:
    """The state of one resolution loop.

    Outcomes are keyed by Mention Span identity, last write winning, so a run
    records each identity once with the decision it ended on.  Unrequested
    Mention Spans reach ``observed_spans`` only: they never enter the resolved
    text or the discard proportion.
    """

    deps: CoreferenceDeps
    observed_spans: list[MentionSpan] = field(default_factory=list)
    annotator_corrections: int = 0
    outcomes: dict[MentionSpanIdentity, MentionSpanOutcome] = field(
        default_factory=dict
    )
    accepted_spans: dict[MentionSpanIdentity, LocatedMentionSpan] = field(
        default_factory=dict
    )
    critic_rounds: int = 0

    @classmethod
    def for_deps(cls, deps: CoreferenceDeps) -> "ResolutionState":
        """Start an empty state over the article both agents are shown."""

        return cls(deps=deps)

    @property
    def content(self) -> str:
        """The Source Article content Mention Spans are located against."""

        return self.deps.content

    @property
    def sentence_records(self) -> list[NumberedSentenceRecord]:
        """The annotator's sentence table in the durable run schema."""

        return [
            NumberedSentenceRecord(
                label=sentence.label,
                text=sentence.text,
                start_index=sentence.start_index,
                end_index=sentence.end_index,
            )
            for sentence in self.deps.sentences
        ]

    @property
    def surviving_spans(self) -> list[LocatedMentionSpan]:
        """The located Mention Spans the Coreference Critic last accepted."""

        return list(self.accepted_spans.values())

    @property
    def resolved_text(self) -> str:
        """The Source Article with every surviving Mention Span applied."""

        return _substitute_located_mention_spans(self.content, self.surviving_spans)

    @property
    def discarded_proportion(self) -> float:
        """The share of final outcomes that did not survive resolution."""

        final_outcomes = list(self.outcomes.values())
        if not final_outcomes:
            return 0.0
        discarded = sum(not outcome.accepted for outcome in final_outcomes)
        return discarded / len(final_outcomes)

    def record_annotation(
        self,
        mention_spans: Sequence[MentionSpan],
    ) -> list[LocatedMentionSpan]:
        """Record the annotator's first answer and return its located spans."""

        self.observed_spans.extend(mention_spans)
        _log_contested_locations(mention_spans)
        return self._locate(mention_spans)

    def record_annotator_corrections(
        self,
        messages: Sequence[ModelMessage],
    ) -> None:
        """Count the corrections the annotator was asked for within one call.

        Pass the annotator's whole conversation; the count is replaced.
        """

        self.annotator_corrections = _count_retry_prompts(messages)

    def record_occurrence_sweep(
        self,
        located_spans: Sequence[LocatedMentionSpan],
    ) -> list[LocatedMentionSpan]:
        """Add the repeat occurrences ``located_spans`` left unclaimed.

        Called once, after the annotator's first answer and before the
        Coreference Critic sees anything.  Counts no round.
        """

        proposals = unclaimed_occurrences(
            self.content,
            self.deps.sentences,
            located_spans,
        )
        if not proposals:
            return []
        self.observed_spans.extend(proposals)
        logger.info(
            "Occurrence sweep proposed %d repeat Mention Span(s) the "
            "annotator left unclaimed",
            len(proposals),
        )
        return self._locate(proposals)

    def record_correction(
        self,
        mention_spans: Sequence[MentionSpan],
        retry_targets: Sequence[tuple[MentionSpan, str]],
    ) -> list[LocatedMentionSpan]:
        """Record a correction round, keeping only the spans it asked for.

        A correction changes only the canonical entity, so identities outside
        ``retry_targets`` are dropped.
        """

        self.critic_rounds += 1
        self.observed_spans.extend(mention_spans)

        target_identities = {
            MentionSpanIdentity.of(mention_span) for mention_span, _ in retry_targets
        }
        requested = [
            mention_span
            for mention_span in mention_spans
            if MentionSpanIdentity.of(mention_span) in target_identities
        ]
        unrequested = [
            MentionSpanIdentity.of(mention_span)
            for mention_span in mention_spans
            if MentionSpanIdentity.of(mention_span) not in target_identities
        ]
        if unrequested:
            logger.debug(
                "Dropping %d unrequested Mention Span(s) from the retry "
                "response: %s",
                len(unrequested),
                unrequested,
            )

        _log_contested_locations(requested)
        return self._locate(requested)

    def record_critic_round(
        self,
        located_spans: Sequence[LocatedMentionSpan],
        verdicts: Sequence[CriticVerdict],
    ) -> list[tuple[MentionSpan, str]]:
        """Record one round of verdicts and return the spans to correct."""

        accepted, rejected = _apply_critic_verdicts(located_spans, verdicts)

        for located in accepted:
            identity = MentionSpanIdentity.of(located.mention_span)
            self.accepted_spans[identity] = located
            self.outcomes[identity] = _outcome_for_critic(
                located.mention_span,
                accepted=True,
            )
        for mention_span, reason in rejected:
            identity = MentionSpanIdentity.of(mention_span)
            # A later rejection displaces an earlier acceptance of the same
            # identity.
            self.accepted_spans.pop(identity, None)
            self.outcomes[identity] = _outcome_for_critic(
                mention_span,
                accepted=False,
                reason=reason,
            )

        return rejected

    def record_validated(
        self,
        located_spans: Sequence[LocatedMentionSpan],
    ) -> None:
        """Accept located spans outright, for a run with no Coreference Critic.

        Annotator-only runs call this.  The outcomes it writes carry
        ``stage="validation"``, which is how a consumer tells an unreviewed
        span from a Critic-accepted one.
        """

        for located in located_spans:
            identity = MentionSpanIdentity.of(located.mention_span)
            self.accepted_spans[identity] = located
            self.outcomes[identity] = MentionSpanOutcome(
                mention_span=located.mention_span,
                stage="validation",
                outcome="accepted",
            )

    def to_run(self, failure_type: str | None = None) -> CoreferenceResolutionRun:
        """Convert the state into the Coreference Resolution Run it describes."""

        return CoreferenceResolutionRun(
            resolved_text=self.resolved_text,
            sentences=self.sentence_records,
            mention_spans=list(self.observed_spans),
            outcomes=list(self.outcomes.values()),
            discarded_proportion=self.discarded_proportion,
            # Every round the annotator was asked to answer again, whether
            # the Critic asked or the output validator did.
            retry_count=self.critic_rounds + self.annotator_corrections,
            failure_type=failure_type,
        )

    def _locate(
        self,
        mention_spans: Sequence[MentionSpan],
    ) -> list[LocatedMentionSpan]:
        """Locate spans against the article, recording every discard."""

        validation = validate_mention_spans(
            self.content,
            self.deps.sentences,
            mention_spans,
        )
        for discard in validation.discards:
            identity = MentionSpanIdentity.of(discard.mention_span)
            self.accepted_spans.pop(identity, None)
            self.outcomes[identity] = _outcome_for_discard(discard)
        return validation.valid_spans


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

    metadata = get_agent_metadata(annotator_agent, ANNOTATOR_INSTRUCTIONS)

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




def annotate_coreferences_run(
    text: str,
    annotator_agent: Agent | None = None,
    *,
    deployment: ModelDeployment | None = None,
) -> CoreferenceResolutionRun:
    """Resolve references with the Coreference Annotator alone.

    Evaluated as the baseline against ``resolve_coreferences_run``, so it
    raises the same failures on the same terms.
    """

    if annotator_agent is None:
        annotator_agent = get_annotator_agent(deployment)

    deps = CoreferenceDeps.for_content(text)
    state = ResolutionState.for_deps(deps)

    try:
        usage = RunUsage()
        usage_limits = UsageLimits(
            request_limit=settings.coreference.request_limit,
            total_tokens_limit=settings.coreference.total_tokens_limit,
        )

        run_result = annotator_agent.run_sync(
            ANNOTATION_PROMPT,
            deps=deps,
            usage=usage,
            usage_limits=usage_limits,
        )
        state.record_annotator_corrections(run_result.all_messages())
        located_spans = state.record_annotation(run_result.output)

        logger.info(
            "Annotator returned %d Mention Span(s); %d located, %d discarded "
            "in validation (no Coreference Critic)",
            len(state.observed_spans),
            len(located_spans),
            len(state.observed_spans) - len(located_spans),
        )

        # Swept here too, so the baseline is not short the repeats the loop
        # gets.
        located_spans = located_spans + state.record_occurrence_sweep(located_spans)

        if not state.observed_spans:
            raise _zero_survivor_failure(
                text,
                state.to_run("no_mentions_returned"),
                "no_mentions_returned",
                annotator_agent,
            )
        if not located_spans:
            raise _zero_survivor_failure(
                text,
                state.to_run("all_mentions_discarded"),
                "all_mentions_discarded",
                annotator_agent,
            )

        state.record_validated(located_spans)
        return state.to_run()
    except CoreferenceResolutionError:
        raise
    except MODEL_OUTPUT_FAILURES as error:
        raise _structured_output_failure(
            text,
            annotator_agent,
            error,
            resolution_run=state.to_run("coreference_validation_failure"),
        ) from error


def resolve_coreferences_run(
    text: str,
    annotator_agent: Agent | None = None,
    critic_agent: Agent | None = None,
    *,
    max_critic_rounds: int,
    deployment: ModelDeployment | None = None,
) -> CoreferenceResolutionRun:
    """Resolve references and retain one final outcome per Mention Span.

    Raises when no Mention Span survives.  ``max_critic_rounds`` bounds the
    correction rounds after the annotator's first pass, separately from the
    agents' own retry budgets; ``PydanticAICoreferenceAdapter`` passes the
    configured default.
    """

    if annotator_agent is None:
        annotator_agent = get_annotator_agent(deployment)
    if critic_agent is None:
        critic_agent = get_critic_agent(deployment)

    deps = CoreferenceDeps.for_content(text)
    state = ResolutionState.for_deps(deps)

    try:
        # One usage record, so the limits bound the article, not a call.
        usage = RunUsage()
        usage_limits = UsageLimits(
            request_limit=settings.coreference.request_limit,
            total_tokens_limit=settings.coreference.total_tokens_limit,
        )

        run_result = annotator_agent.run_sync(
            ANNOTATION_PROMPT,
            deps=deps,
            usage=usage,
            usage_limits=usage_limits,
        )
        # Carried into correction rounds so the annotator sees what it is
        # being asked to correct.
        annotator_messages = run_result.all_messages()
        state.record_annotator_corrections(annotator_messages)
        pending_spans = state.record_annotation(run_result.output)

        logger.info(
            "Annotator returned %d Mention Span(s); %d located, %d discarded "
            "in validation",
            len(state.observed_spans),
            len(pending_spans),
            len(state.observed_spans) - len(pending_spans),
        )

        # Before the Critic, so swept repeats are reviewed like any other.
        pending_spans = pending_spans + state.record_occurrence_sweep(pending_spans)

        if not state.observed_spans:
            raise _zero_survivor_failure(
                text,
                state.to_run("no_mentions_returned"),
                "no_mentions_returned",
                annotator_agent,
            )

        if not pending_spans:
            raise _zero_survivor_failure(
                text,
                state.to_run("all_mentions_discarded"),
                "all_mentions_discarded",
                annotator_agent,
            )

        while pending_spans:
            logger.info(
                "Sending %d Mention Span(s) to the Coreference Critic "
                "(round %d of %d)",
                len(pending_spans),
                state.critic_rounds + 1,
                max_critic_rounds,
            )
            critic_result = critic_agent.run_sync(
                _critic_prompt(
                    [located.mention_span for located in pending_spans],
                ),
                deps=deps,
                usage=usage,
                usage_limits=usage_limits,
            )
            rejected_spans = state.record_critic_round(
                pending_spans,
                critic_result.output,
            )
            logger.info(
                "Coreference Critic returned %d verdict(s): %d accepted, "
                "%d rejected",
                len(critic_result.output),
                len(pending_spans) - len(rejected_spans),
                len(rejected_spans),
            )

            if not rejected_spans or state.critic_rounds >= max_critic_rounds:
                if rejected_spans:
                    logger.warning(
                        "Critic rounds exhausted with %d Mention Span(s) still "
                        "rejected after %d round(s)",
                        len(rejected_spans),
                        state.critic_rounds,
                    )
                break

            logger.info(
                "Asking the annotator to correct %d rejected Mention Span(s)",
                len(rejected_spans),
            )
            retry_result = annotator_agent.run_sync(
                _retry_prompt(rejected_spans),
                deps=deps,
                message_history=annotator_messages,
                usage=usage,
                usage_limits=usage_limits,
            )
            annotator_messages = retry_result.all_messages()
            state.record_annotator_corrections(annotator_messages)
            pending_spans = state.record_correction(
                retry_result.output,
                rejected_spans,
            )

        if not state.surviving_spans:
            raise _zero_survivor_failure(
                text,
                state.to_run("all_mentions_rejected"),
                "all_mentions_rejected",
                annotator_agent,
            )

        return state.to_run()
    except CoreferenceResolutionError:
        raise
    except MODEL_OUTPUT_FAILURES as error:
        # Whatever the run reached travels with the failure, so a prompt fix
        # can be made against it.
        raise _structured_output_failure(
            text,
            annotator_agent,
            error,
            resolution_run=state.to_run("coreference_validation_failure"),
        ) from error


class PydanticAICoreferenceAdapter:
    """Concrete adapter for coreference resolution that conforms to the CoreferenceAdapter protocol."""

    def __init__(
        self,
        annotator_agent: Agent | None = None,
        critic_agent: Agent | None = None,
        max_critic_rounds: int | None = None,
        *,
        deployment: ModelDeployment | None = None,
    ) -> None:
        self.deployment = deployment
        self.annotator_agent = annotator_agent or get_annotator_agent(deployment)
        self.critic_agent = critic_agent or get_critic_agent(deployment)
        # The one place the configured critic round budget is read.
        self.max_critic_rounds = (
            settings.coreference.max_critic_rounds
            if max_critic_rounds is None
            else max_critic_rounds
        )

    def resolve(self, content: str) -> CoreferenceResolutionRun:
        annotator_agent: Agent | None = self.annotator_agent
        critic_agent: Agent | None = self.critic_agent
        try:
            return resolve_coreferences_run(
                content,
                annotator_agent=annotator_agent,
                critic_agent=critic_agent,
                max_critic_rounds=self.max_critic_rounds,
                deployment=self.deployment,
            )
        except CoreferenceResolutionError:
            raise
        except MODEL_OUTPUT_FAILURES as error:
            raise _structured_output_failure(
                content,
                annotator_agent,
                error,
            ) from error

    def health_check(self) -> bool:
        """Report whether the annotator can complete a trivial run.

        Any completed run is healthy, whatever it returned.
        """

        try:
            agent = self.annotator_agent
            result = agent.run_sync(
                "health_check",
                deps=CoreferenceDeps.for_content("health_check"),
                model_settings={"max_tokens": 1},
            )
            return result is not None
        except Exception:
            return False
