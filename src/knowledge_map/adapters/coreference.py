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
    NumberedSentenceRecord,
)
from knowledge_map.utils.models import get_chat_model
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
    return get_chat_model("8k-gemma-e4b-extraction", "OLLAMA_MODEL_COREFERENCE")


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

    Both coreference agents take this as their dependency, so the sentences an
    agent is shown always came from the content beside them.
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

    An unknown sentence label, or a mention text that does not occur where it
    was claimed, is exactly the mistake an annotator can fix when told, so the
    deterministic validation runs here as well as in the resolution loop.

    Three answers pass straight through.  An empty list is a real outcome, so
    ``no_mentions_returned`` stays a distinct failure rather than a correction
    target.  A partially locatable answer passes, so one unlocatable Mention
    Span never costs the neighbours that validated cleanly and its discards are
    recorded by the loop as before.  And the last answer the agent's
    structured-output retry budget allows passes, so a persistently unlocatable
    annotator reaches the Dead Letter Queue as ``all_mentions_discarded``
    carrying what it returned, rather than as an exhausted retry budget.
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


def get_annotator_agent(defer_check: bool = True, retries: int = 3) -> Agent:
    agent = Agent(
        _get_model(),
        name="coreference_annotator",
        deps_type=CoreferenceDeps,
        output_type=list[MentionSpan],
        instructions=[ANNOTATOR_INSTRUCTIONS, numbered_article_instructions],
        defer_model_check=defer_check,
        retries=retries,
    )
    agent.output_validator(validate_annotator_output)
    return agent


def get_critic_agent(defer_check: bool = True, retries: int = 3) -> Agent:
    return Agent(
        _get_model(),
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
        # Consumers that need the sentence table, the Mention Spans or the
        # per-span outcomes unpack them from the run itself.
        self.resolution_run = resolution_run
        super().__init__(f"Coreference resolution failed: {failure_type}")

def get_agent_metadata(agent: Agent | None, instructions: str = "") -> dict:
    """Describe the agent behind a failure for the Dead Letter Queue record.

    The instruction text is passed in rather than scraped off the agent: an
    instructions function that renders a dependency cannot be called without a
    run to supply it, and the static text is the part worth recording anyway.
    No coreference agent configures model settings, so no temperature is
    reported.

    Describing the agent is decoration on a record that is only being written
    because something already failed, so an agent that will not name its model
    yields no metadata rather than displacing the failure being recorded.
    Reading the name is the part that can fail — an agent holding no model
    attribute, or a ``model_name`` the provider computes — so only that read is
    guarded, and every caller gets the swallow from here rather than repeating
    it.
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


#: What the resolver is willing to call a coreference validation failure.
#:
#: Both members describe model output: a Pydantic ``ValidationError`` is
#: output that does not fit the agent's output type, and pydantic-ai's
#: ``UnexpectedModelBehavior`` covers the rest — a text answer where a tool
#: call was required, an exhausted structured-output retry budget.  Everything
#: else escaping the resolver is an infrastructure failure, and the Dead Letter
#: Queue is the corpus prompt work is done against.
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

    # The Critic's reason is per-span feedback, so it stays attached to the
    # rendering of its own Mention Span rather than being pooled.
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


@dataclass(slots=True)
class ResolutionState:
    """The state of one resolution loop, and the rules that state must obey.

    Outcomes are keyed by Mention Span identity with the last write winning, so
    a Mention Span rejected in one Coreference Critic round and corrected in the
    next is recorded once, with the decision the run ended on.  The loop used to
    obey that rule by the order in which it assigned five local variables; here
    the recording operations enforce it, which is also why the discard
    proportion is computed by the state that holds the outcomes rather than
    beside it.

    A Mention Span the annotator returned without being asked for it is kept out
    of ``outcomes`` and out of ``accepted_spans`` entirely, so it can neither
    reach the resolved text nor move the discard proportion.  It still appears
    in ``observed_spans``, which is the raw record of everything the model
    returned.
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

        The output validator's corrections happen inside a single agent run, so
        they are invisible to the loop; the annotator's own conversation is
        where they are recorded.  The count is read from the whole conversation
        rather than accumulated, because a correction round carries the earlier
        messages forward and would otherwise be counted twice.
        """

        self.annotator_corrections = sum(
            1
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, RetryPromptPart)
        )

    def record_correction(
        self,
        mention_spans: Sequence[MentionSpan],
        retry_targets: Sequence[tuple[MentionSpan, str]],
    ) -> list[LocatedMentionSpan]:
        """Record a correction round, keeping only the spans it asked for.

        A correction preserves a Mention Span's identity and changes only its
        canonical entity, so a returned identity outside the retry targets is
        one the prompt never requested and the Coreference Critic never
        reviewed.
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
            # identity, so the resolved text can only carry the decision the
            # run ended on.
            self.accepted_spans.pop(identity, None)
            self.outcomes[identity] = _outcome_for_critic(
                mention_span,
                accepted=False,
                reason=reason,
            )

        return rejected

    def to_run(self, failure_type: str | None = None) -> CoreferenceResolutionRun:
        """Convert the state into the Coreference Resolution Run it describes."""

        return CoreferenceResolutionRun(
            resolved_text=self.resolved_text,
            sentences=self.sentence_records,
            mention_spans=list(self.observed_spans),
            outcomes=list(self.outcomes.values()),
            discarded_proportion=self.discarded_proportion,
            # Every round the annotator was asked to answer again, whether the
            # Coreference Critic asked or the output validator did, so a run
            # that exhausted its corrections is not read as a first-response
            # failure in the Dead Letter Queue.
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




def resolve_coreferences_run(
    text: str,
    annotator_agent: Agent | None = None,
    critic_agent: Agent | None = None,
    *,
    max_critic_rounds: int,
) -> CoreferenceResolutionRun:
    """Resolve references and retain one final outcome per Mention Span.

    The loop reads the model, calls the agents and decides when to stop; every
    rule about what is recorded belongs to ``ResolutionState``.  Zero-survivor
    runs always raise: silently returning the source text would hide the
    failure.  ``max_critic_rounds`` bounds the Coreference Critic rounds beyond
    the annotator's first pass — one per correction round — and is unrelated to
    the agents' own structured-output retry budget.  Its caller chooses it;
    ``PydanticAICoreferenceAdapter`` is where the configured default is read.
    """

    if annotator_agent is None:
        annotator_agent = get_annotator_agent()
    if critic_agent is None:
        critic_agent = get_critic_agent()

    deps = CoreferenceDeps.for_content(text)
    state = ResolutionState.for_deps(deps)

    try:
        # One usage record for the whole resolution, so the limits below bound
        # the article rather than any single model call.
        usage = RunUsage()
        usage_limits = UsageLimits(
            request_limit=settings.coreference.request_limit,
            total_tokens_limit=settings.coreference.total_tokens_limit,
        )

        annotation_prompt = (
            "Resolve the references in the Source Article shown above. It is "
            "presented as numbered sentences; copy a visible sentence label "
            "into each Mention Span."
        )
        run_result = annotator_agent.run_sync(
            annotation_prompt,
            deps=deps,
            usage=usage,
            usage_limits=usage_limits,
        )
        # The annotator's own conversation, carried into a correction round so
        # that it sees the Mention Spans it is being asked to correct.
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
        # Only model output is a failure at this seam.  In particular, never
        # treat a text response as resolved text.  Anything else -- an
        # exhausted transport retry, a usage limit, a programming error --
        # propagates to the Story Pipeline as a system error.
        #
        # The state is built before the loop so that whatever the run reached
        # travels with the failure: the Mention Spans the annotator returned
        # and the sentence table it worked from are what a prompt fix is made
        # against.
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
    ) -> None:
        self.annotator_agent = annotator_agent
        self.critic_agent = critic_agent
        # The one place the configured critic round budget is read.  The
        # resolution loop takes the number its caller chose.
        self.max_critic_rounds = (
            settings.coreference.max_critic_rounds
            if max_critic_rounds is None
            else max_critic_rounds
        )

    def resolve(self, content: str) -> CoreferenceResolutionRun:
        annotator_agent: Agent | None = self.annotator_agent
        try:
            annotator_agent = annotator_agent or get_annotator_agent()
            critic_agent = self.critic_agent or get_critic_agent()
            return resolve_coreferences_run(
                content,
                annotator_agent=annotator_agent,
                critic_agent=critic_agent,
                max_critic_rounds=self.max_critic_rounds,
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

        The probe uses the annotator's own output type rather than overriding
        it with plain text: an agent carrying an output validator cannot be
        given a different output type per run, and the health of the agent is
        the health of the contract it actually runs under.  A completed run is
        healthy whatever it returned, since a trivial article legitimately
        yields no Mention Spans.
        """

        try:
            agent = self.annotator_agent or get_annotator_agent()
            result = agent.run_sync(
                "health_check",
                deps=CoreferenceDeps.for_content("health_check"),
                model_settings={"max_tokens": 1},
            )
            return result is not None
        except Exception:
            return False
