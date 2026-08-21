import logging

import pytest
from pydantic_ai import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from knowledge_map.adapters.coreference import (
    ANNOTATOR_INSTRUCTIONS,
    CoreferenceDeps,
    CoreferenceResolutionError,
    PydanticAICoreferenceAdapter,
    get_annotator_agent,
    get_critic_agent,
)
from knowledge_map.schemas import CriticVerdict, MentionSpan


def rendered_request(messages) -> str:
    """Return everything the model is shown for the request being answered.

    The numbered Source Article is rendered by an instructions function, so it
    reaches the model through the request's instructions rather than its final
    user part.  Prompt assertions read this whole rendered request.
    """

    request = messages[-1]
    assert isinstance(request, ModelRequest)
    sections = [request.instructions or ""]
    sections.extend(
        part.content
        for part in request.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    )
    return "\n\n".join(section for section in sections if section)


def mention_response(info, spans: list[dict]) -> ModelResponse:
    """Build the structured output tool call used by the annotator tests."""

    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"response": spans},
                tool_call_id="call_1",
            )
        ]
    )


def critic_response(info, verdicts: list[dict]) -> ModelResponse:
    """Build the structured output tool call used by critic tests."""

    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"response": verdicts},
                tool_call_id="call_critic_1",
            )
        ]
    )


def test_both_agents_render_the_numbered_article_from_their_dependencies():
    """One instructions function shows both agents the same numbered article.

    The Source Article travels as a typed dependency together with the
    sentences split from it, so neither agent can be shown sentences that came
    from different text.
    """

    content = "Gavin Newsom signed a bill. He was happy."
    deps = CoreferenceDeps.for_content(content)
    requests: list[str] = []

    def mock_annotator(messages, info):
        requests.append(rendered_request(messages))
        return mention_response(info, [])

    def mock_critic(messages, info):
        requests.append(rendered_request(messages))
        return critic_response(info, [])

    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    with annotator_agent.override(model=FunctionModel(mock_annotator)):
        annotator_agent.run_sync("Resolve the references.", deps=deps)
    with critic_agent.override(model=FunctionModel(mock_critic)):
        critic_agent.run_sync("Judge the Mention Spans.", deps=deps)

    assert len(requests) == 2
    for request in requests:
        assert "[1] Gavin Newsom signed a bill." in request
        assert "[2] He was happy." in request
        assert request.count("Gavin Newsom signed a bill.") == 1


def test_get_annotator_agent_returns_structured_mention_spans():
    agent = get_annotator_agent(defer_check=True)
    assert agent.output_type == list[MentionSpan]

    def mock_model(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    with agent.override(model=FunctionModel(mock_model)):
        result = agent.run_sync(
            "Resolve the references in the Source Article shown above.",
            deps=CoreferenceDeps.for_content(
                "Gavin Newsom signed a bill. He was happy."
            ),
        )

    assert result.output == [
        MentionSpan(
            sentence_label="2",
            mention_text="He",
            canonical_entity_name="Gavin Newsom",
        )
    ]


def test_get_critic_agent_returns_per_mention_verdicts():
    agent = get_critic_agent(defer_check=True)
    assert agent.output_type == list[CriticVerdict]

    def mock_model(messages, info):
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "accepted": True,
                }
            ],
        )

    with agent.override(model=FunctionModel(mock_model)):
        result = agent.run_sync(
            "Validated Mention Spans:\n"
            '- sentence_label="2", mention_text="He", occurrence=1, '
            'canonical_entity_name="Gavin Newsom"',
            deps=CoreferenceDeps.for_content(
                "Gavin Newsom signed a bill. He was happy."
            ),
        )

    assert result.output == [
        CriticVerdict(
            sentence_label="2",
            mention_text="He",
            accepted=True,
        )
    ]


def test_adapter_numbers_sentences_and_applies_structured_mentions():
    content = "Gavin Newsom signed a bill. He was happy."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    prompts: list[str] = []

    def mock_annotator(messages, info):
        prompts.append(rendered_request(messages))
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    def mock_critic(messages, info):
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "accepted": True,
                }
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
        ).resolve(content).resolved_text

    assert result == "Gavin Newsom signed a bill. Gavin Newsom was happy."
    assert len(prompts) == 1
    assert "[1] Gavin Newsom signed a bill. " in prompts[0]
    assert "[2] He was happy." in prompts[0]
    assert "Original text:" not in prompts[0]
    assert "Annotated text:" not in prompts[0]


def test_critic_rejects_one_span_while_accepted_neighbour_survives():
    content = "Gavin Newsom signed a bill. He thanked the committee, and it passed."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    critic_prompts: list[str] = []

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                },
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "canonical_entity_name": "the committee",
                },
            ],
        )

    def mock_critic(messages, info):
        critic_prompts.append(rendered_request(messages))
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "accepted": True,
                },
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "accepted": False,
                    "reason": "It refers to the bill, not the committee.",
                },
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
            max_critic_rounds=0,
        ).resolve(content).resolved_text

    assert result == (
        "Gavin Newsom signed a bill. Gavin Newsom thanked the committee, and it passed."
    )
    assert len(critic_prompts) == 1
    assert critic_prompts[0].count("Gavin Newsom signed a bill.") == 1
    assert "Validated Mention Spans:" in critic_prompts[0]
    assert "Annotated text:" not in critic_prompts[0]


def test_missing_or_hallucinated_critic_verdicts_cannot_apply_spans():
    content = "Gavin Newsom signed a bill. He thanked the committee, and it passed."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                },
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "canonical_entity_name": "the bill",
                },
            ],
        )

    def mock_critic(messages, info):
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "accepted": True,
                },
                {
                    "sentence_label": "99",
                    "mention_text": "it",
                    "accepted": True,
                },
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
            max_critic_rounds=0,
        ).resolve(content).resolved_text

    assert result == (
        "Gavin Newsom signed a bill. Gavin Newsom thanked the committee, and it passed."
    )


def test_retry_reannotates_only_rejected_spans_and_preserves_accepted_spans():
    content = "Gavin Newsom signed a bill. He thanked the committee, and it passed."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    annotator_prompts: list[str] = []
    critic_calls = 0

    def mock_annotator(messages, info):
        annotator_prompts.append(rendered_request(messages))
        if len(annotator_prompts) == 1:
            return mention_response(
                info,
                [
                    {
                        "sentence_label": "2",
                        "mention_text": "He",
                        "canonical_entity_name": "Gavin Newsom",
                    },
                    {
                        "sentence_label": "2",
                        "mention_text": "it",
                        "canonical_entity_name": "the committee",
                    },
                ],
            )
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "canonical_entity_name": "the bill",
                }
            ],
        )

    def mock_critic(messages, info):
        nonlocal critic_calls
        critic_calls += 1
        if critic_calls == 1:
            return critic_response(
                info,
                [
                    {
                        "sentence_label": "2",
                        "mention_text": "He",
                        "accepted": True,
                    },
                    {
                        "sentence_label": "2",
                        "mention_text": "it",
                        "accepted": False,
                        "reason": "It refers to the bill, not the committee.",
                    },
                ],
            )
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "accepted": True,
                }
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        run = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
            max_critic_rounds=1,
        ).resolve(content)

    assert run.resolved_text == (
        "Gavin Newsom signed a bill. Gavin Newsom thanked the committee, and the bill passed."
    )
    # A span rejected in round one and corrected in round two is recorded once,
    # with the decision the run ended on, so retrying cannot inflate the metric.
    assert [outcome.outcome for outcome in run.outcomes] == ["accepted", "accepted"]
    assert run.discarded_proportion == 0.0
    assert run.retry_count == 1
    assert len(annotator_prompts) == 2
    assert "Rejected Mention Spans and Critic Reasons:" in annotator_prompts[1]
    # The rejected span is rendered by ``format_mention_spans`` and its own
    # Critic reason stays attached directly underneath it.
    assert (
        "- sentence_label='2', mention_text='it', occurrence=1, "
        "canonical_entity_name='the committee'\n"
        "  Critic reason: It refers to the bill, not the committee."
    ) in annotator_prompts[1]
    # The accepted neighbour is not resent for correction.
    assert "mention_text='He'" not in annotator_prompts[1].split(
        "Rejected Mention Spans and Critic Reasons:"
    )[1]
    assert critic_calls == 2


def test_retries_stop_at_the_configured_budget():
    content = "Gavin Newsom signed a bill. He thanked the committee, and it passed."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    annotator_calls = 0
    critic_calls = 0

    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                },
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "canonical_entity_name": "the committee",
                },
            ],
        )

    def mock_critic(messages, info):
        nonlocal critic_calls
        critic_calls += 1
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "accepted": True,
                },
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "accepted": False,
                    "reason": "The proposed entity is not the bill.",
                },
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
            max_critic_rounds=1,
        ).resolve(content).resolved_text

    assert result == (
        "Gavin Newsom signed a bill. Gavin Newsom thanked the committee, and it passed."
    )
    assert annotator_calls == 2
    assert critic_calls == 2


def test_critic_accepts_a_validated_mention_span():
    content = "Gavin Newsom signed a bill. He was happy."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    def mock_critic(messages, info):
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "accepted": True,
                }
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
        ).resolve(content).resolved_text

    assert result == "Gavin Newsom signed a bill. Gavin Newsom was happy."


def test_invalid_annotator_text_is_a_structured_output_failure():
    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_annotator(messages, info):
        return ModelResponse(
            parts=[TextPart(content="Gavin Newsom signed a bill. He was happy.")]
        )

    with annotator_agent.override(model=FunctionModel(mock_annotator)):
        with pytest.raises(CoreferenceResolutionError) as exc_info:
            PydanticAICoreferenceAdapter(
                annotator_agent=annotator_agent,
            ).resolve("Gavin Newsom signed a bill. He was happy.")

    error = exc_info.value
    assert error.failure_type == "coreference_validation_failure"
    assert error.validation_issues


def test_discarded_mention_does_not_block_neighbouring_valid_mention():
    content = "Gavin Newsom signed a bill. He thanked her."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                },
                {
                    "sentence_label": "2",
                    "mention_text": "her",
                    "canonical_entity_name": "the committee",
                    "occurrence": 2,
                },
            ],
        )

    def mock_critic(messages, info):
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "accepted": True,
                }
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
        ).resolve(content).resolved_text

    assert result == "Gavin Newsom signed a bill. Gavin Newsom thanked her."


def test_health_check_keeps_the_adapter_contract():
    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_model(messages, info):
        return ModelResponse(parts=[TextPart(content="ok")])

    with annotator_agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAICoreferenceAdapter(annotator_agent=annotator_agent)
        assert adapter.health_check() is True


def test_health_check_returns_false_when_the_model_fails():
    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_model(messages, info):
        raise RuntimeError("LLM connection failed")

    with annotator_agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAICoreferenceAdapter(annotator_agent=annotator_agent)
        assert adapter.health_check() is False


def test_unrequested_retry_span_is_neither_substituted_nor_recorded():
    """A retry may only correct the spans the Critic actually rejected.

    A correction keeps the span's identity and changes only its canonical
    entity, so a returned identity outside the retry targets is one the prompt
    never requested and the Critic never reviewed.  It must not reach the text,
    and it must stay out of ``outcomes`` so it cannot move the discard metric.
    """

    content = "Gavin Newsom signed a bill. He thanked the committee, and it passed."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    annotator_calls = 0
    critic_calls = 0

    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        if annotator_calls == 1:
            return mention_response(
                info,
                [
                    {
                        "sentence_label": "2",
                        "mention_text": "it",
                        "canonical_entity_name": "the committee",
                    }
                ],
            )
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "canonical_entity_name": "the bill",
                },
                # Never rejected, so never requested.
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Someone Else",
                },
            ],
        )

    def mock_critic(messages, info):
        nonlocal critic_calls
        critic_calls += 1
        if critic_calls == 1:
            return critic_response(
                info,
                [
                    {
                        "sentence_label": "2",
                        "mention_text": "it",
                        "accepted": False,
                        "reason": "It refers to the bill, not the committee.",
                    }
                ],
            )
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "accepted": True,
                }
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        run = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
            max_critic_rounds=1,
        ).resolve(content)

    assert run.resolved_text == (
        "Gavin Newsom signed a bill. He thanked the committee, and the bill passed."
    )
    assert "Someone Else" not in run.resolved_text
    # Absent from the outcomes, so it cannot inflate the discard metric.
    assert [outcome.mention_span.mention_text for outcome in run.outcomes] == ["it"]
    assert run.discarded_proportion == 0.0
    # Still present in the raw record of everything the model returned.
    assert [span.mention_text for span in run.mention_spans] == ["it", "it", "He"]


def test_contested_location_is_logged_not_recorded_as_a_discard(caplog):
    """One location claimed by two entities is an annotator-quality signal.

    ``MentionSpanIdentity`` excludes the canonical entity name, so both spans
    share one key in the run's outcome map and only one outcome survives. That
    collapse is intended, but the contradiction must stay visible somewhere.
    """

    from knowledge_map.adapters.coreference import _log_contested_locations

    contested = [
        MentionSpan(
            sentence_label="2",
            mention_text="He",
            occurrence=1,
            canonical_entity_name="Gavin Newsom",
        ),
        MentionSpan(
            sentence_label="2",
            mention_text="He",
            occurrence=1,
            canonical_entity_name="Joe Biden",
        ),
    ]

    with caplog.at_level(
        logging.DEBUG, logger="knowledge_map.adapters.coreference"
    ):
        _log_contested_locations(contested)

    assert "Gavin Newsom" in caplog.text
    assert "Joe Biden" in caplog.text
    assert "'He'" in caplog.text


def test_distinct_occurrences_are_not_contested(caplog):
    """The same mention text at two occurrences is two locations, not a clash."""

    from knowledge_map.adapters.coreference import _log_contested_locations

    with caplog.at_level(
        logging.DEBUG, logger="knowledge_map.adapters.coreference"
    ):
        _log_contested_locations(
            [
                MentionSpan(
                    sentence_label="1",
                    mention_text="He",
                    occurrence=1,
                    canonical_entity_name="Alice",
                ),
                MentionSpan(
                    sentence_label="1",
                    mention_text="He",
                    occurrence=2,
                    canonical_entity_name="Bob",
                ),
            ]
        )

    assert caplog.text == ""


def test_correction_round_continues_the_annotators_own_conversation():
    """The annotator is asked to correct answers it can still see.

    A correction round carries the annotator's prior messages, so its own
    earlier Mention Spans are in front of it, and the new request still names
    only the spans the Coreference Critic rejected.
    """

    content = "Gavin Newsom signed a bill. He thanked the committee, and it passed."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    annotator_calls = 0
    correction_history: list = []

    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        if annotator_calls == 1:
            return mention_response(
                info,
                [
                    {
                        "sentence_label": "2",
                        "mention_text": "it",
                        "canonical_entity_name": "the committee",
                    }
                ],
            )
        correction_history.extend(messages[:-1])
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "canonical_entity_name": "the bill",
                }
            ],
        )

    def mock_critic(messages, info):
        return critic_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "it",
                    "accepted": annotator_calls > 1,
                    "reason": "It refers to the bill, not the committee.",
                }
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        run = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
            max_critic_rounds=1,
        ).resolve(content)

    assert run.resolved_text == (
        "Gavin Newsom signed a bill. He thanked the committee, and the bill passed."
    )
    # The annotator's first answer is in front of it during the correction.
    returned_spans = [
        span
        for message in correction_history
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
        for span in part.args_as_dict().get("response", [])
    ]
    assert {
        "sentence_label": "2",
        "mention_text": "it",
        "canonical_entity_name": "the committee",
    } in returned_spans


def test_resolution_state_keeps_one_final_outcome_per_mention_span_identity():
    """The state, not the loop's ordering, enforces the invariant.

    A Mention Span rejected in one Coreference Critic round and corrected in
    the next is recorded once, with the decision the run ended on, and the
    discard proportion is computed by the state that holds the outcomes.
    """

    from knowledge_map.adapters.coreference import ResolutionState

    content = "Gavin Newsom signed a bill. He thanked the committee, and it passed."
    state = ResolutionState.for_deps(CoreferenceDeps.for_content(content))

    located = state.record_annotation(
        [
            MentionSpan(
                sentence_label="2",
                mention_text="it",
                canonical_entity_name="the committee",
            )
        ]
    )
    rejected = state.record_critic_round(
        located,
        [
            CriticVerdict(
                sentence_label="2",
                mention_text="it",
                accepted=False,
                reason="It refers to the bill, not the committee.",
            )
        ],
    )
    assert [span.mention_text for span, _ in rejected] == ["it"]

    corrected = state.record_correction(
        [
            MentionSpan(
                sentence_label="2",
                mention_text="it",
                canonical_entity_name="the bill",
            )
        ],
        rejected,
    )
    state.record_critic_round(
        corrected,
        [
            CriticVerdict(
                sentence_label="2",
                mention_text="it",
                accepted=True,
            )
        ],
    )

    run = state.to_run()
    assert run.resolved_text == (
        "Gavin Newsom signed a bill. He thanked the committee, and the bill passed."
    )
    assert [outcome.outcome for outcome in run.outcomes] == ["accepted"]
    assert run.discarded_proportion == 0.0
    assert run.retry_count == 1
    # Every raw span the annotator returned stays in the audit trail.
    assert [span.canonical_entity_name for span in run.mention_spans] == [
        "the committee",
        "the bill",
    ]
    assert run.sentences[0].text == "Gavin Newsom signed a bill. "


def test_critic_round_budget_is_a_coreference_setting():
    """The budget that bounds correction rounds is configured, not literal.

    It names the critic rounds it counts, so it cannot be confused with the
    agents' structured-output retry budget, and it lives in the coreference
    settings block beside the run's usage limits.
    """

    from knowledge_map.config import settings

    assert settings.coreference.max_critic_rounds >= 0
    assert settings.coreference.request_limit > 0
    assert settings.coreference.total_tokens_limit > 0
    assert (
        PydanticAICoreferenceAdapter().max_critic_rounds
        == settings.coreference.max_critic_rounds
    )


def test_failure_metadata_comes_from_a_stable_source():
    """The Dead Letter Queue's agent metadata does not scrape the agent.

    It reports the static instruction text, the prompt version and the
    resolved model name, and no temperature, because no coreference agent
    configures model settings.
    """

    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_annotator(messages, info):
        return mention_response(info, [])

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        pytest.raises(CoreferenceResolutionError) as exc_info,
    ):
        PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=get_critic_agent(defer_check=True),
        ).resolve("Gavin Newsom signed a bill. He was happy.")

    metadata = exc_info.value.metadata
    assert metadata["system_prompt"] == ANNOTATOR_INSTRUCTIONS
    assert metadata["prompt_version"] == "1.0"
    assert metadata["model"] == annotator_agent.model.model_name
    assert "temperature" not in metadata
