import logging

import httpx
import pytest
from pydantic_ai import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.function import FunctionModel

import knowledge_map.adapters.coreference as coreference_adapter_module
from knowledge_map.adapters.coreference import (
    ANNOTATOR_INSTRUCTIONS,
    CoreferenceDeps,
    CoreferenceResolutionError,
    AnnotatorBudgetExceeded,
    PydanticAICoreferenceAdapter,
    annotator_output_tokens,
    annotator_span_budget,
    get_annotator_agent,
    get_critic_agent,
)
from knowledge_map.config import settings
from knowledge_map.schemas import (
    CriticVerdict,
    DeploymentKind,
    MentionSpan,
    ModelDeployment,
    ModelRequestSettings,
)


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


def local_deployment() -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="explicit-coreference-model",
        endpoint="http://explicit-coreference.test:9999",
        request_settings=ModelRequestSettings(
            temperature=0.0,
            thinking=False,
            max_attempts=2,
            rate_limit_wait_cap=5.0,
        ),
    )


def test_production_resolution_binds_one_explicit_deployment_to_both_agents(
    monkeypatch,
):
    seen: list[object] = []
    calls = 0

    def model_factory(requested):
        nonlocal calls
        seen.append(requested)
        assert isinstance(requested, ModelDeployment)

        def respond(messages, info):
            nonlocal calls
            calls += 1
            if calls == 1:
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

        return FunctionModel(respond)

    monkeypatch.setenv("LLAMA_CPP_MODEL", "ambient-local-model")
    monkeypatch.setattr(coreference_adapter_module, "get_chat_model", model_factory)
    deployment = local_deployment()
    adapter = PydanticAICoreferenceAdapter(deployment=deployment)
    run = adapter.resolve("Gavin Newsom signed a bill. He was happy.")

    assert run.resolved_text == "Gavin Newsom signed a bill. Gavin Newsom was happy."
    assert seen == [deployment, deployment]


def test_default_coreference_model_uses_the_single_local_chat_model(
    monkeypatch,
):
    monkeypatch.setenv("LLAMA_CPP_MODEL", "configured/local-model")

    agent = get_annotator_agent(defer_check=True)

    assert agent.model.model_name == "configured/local-model"


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
        # The probe runs under the annotator's own output type, so a healthy
        # model answers it the way it answers an annotation request.
        return mention_response(info, [])

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


def test_a_transport_failure_is_not_a_coreference_validation_failure():
    """A socket timeout that outlives its retries escapes the resolver.

    The transport owns HTTP retries, so a timeout reaching this seam has
    already exhausted them.  It is an infrastructure failure, not a statement
    about what the annotator wrote, and the Story Pipeline handles it as a
    system error rather than the Dead Letter Queue archiving it as a
    prompt-quality problem.
    """

    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_annotator(messages, info):
        raise httpx.ReadTimeout("The read operation timed out")

    with annotator_agent.override(model=FunctionModel(mock_annotator)):
        with pytest.raises(httpx.ReadTimeout):
            PydanticAICoreferenceAdapter(
                annotator_agent=annotator_agent,
                critic_agent=get_critic_agent(defer_check=True),
            ).resolve("Gavin Newsom signed a bill. He was happy.")


def test_a_model_output_failure_carries_the_partial_run_to_the_dead_letter_queue():
    """What the run reached before the model failed is still archived.

    The annotator's Mention Spans and the sentence table it worked from are
    the material a prompt fix is made against, so a Coreference Critic that
    answers with prose does not throw them away.
    """

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
        return ModelResponse(parts=[TextPart(content="Looks fine to me.")])

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
        pytest.raises(CoreferenceResolutionError) as exc_info,
    ):
        PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
        ).resolve(content)

    error = exc_info.value
    assert error.failure_type == "coreference_validation_failure"
    run = error.resolution_run
    assert run is not None
    assert [span.mention_text for span in run.mention_spans] == ["He"]
    assert [sentence.label for sentence in run.sentences] == ["1", "2"]
    # No verdict was ever recorded, so nothing reached the resolved text.
    assert run.resolved_text == content


def retry_prompts(messages) -> list[str]:
    """Return what the model was told when it was asked to answer again.

    An output validator's ``ModelRetry`` reaches the model as a retry part
    rather than a user part, so the discard reasons are read from there.
    """

    from pydantic_ai.messages import RetryPromptPart

    return [
        part.content if isinstance(part.content, str) else str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, RetryPromptPart)
    ]


def test_an_annotator_citing_an_unknown_sentence_label_is_asked_again():
    """A recoverable mistake is corrected rather than archived.

    Every Mention Span in the first answer names a sentence label that does not
    exist, so nothing can be located.  The annotator is told why and answers
    again, and the corrected Mention Span reaches the resolved text.
    """

    content = "Gavin Newsom signed a bill. He was happy."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    annotator_calls = 0
    corrections: list[str] = []

    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        corrections.extend(retry_prompts(messages[-1:]))
        if annotator_calls == 1:
            return mention_response(
                info,
                [
                    {
                        "sentence_label": "99",
                        "mention_text": "He",
                        "canonical_entity_name": "Gavin Newsom",
                    }
                ],
            )
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
        run = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
        ).resolve(content)

    assert run.resolved_text == "Gavin Newsom signed a bill. Gavin Newsom was happy."
    assert annotator_calls == 2
    # The annotator was told which deterministic check its answer failed.
    assert len(corrections) == 1
    assert "99" in corrections[0]


def test_a_resolution_that_exceeds_its_request_limit_fails(monkeypatch):
    """The ceiling stops the run, and it is not a model-output failure.

    An annotator returning Mention Spans faster than the Coreference Critic
    can retire them is stopped by the configured limit rather than by
    patience.  Exhausting a ceiling says nothing about what the annotator
    wrote, so it escapes to the Story Pipeline as a system error instead of
    being archived as a prompt-quality problem.
    """

    from pydantic_ai.exceptions import UsageLimitExceeded

    from knowledge_map.config import settings

    # One request buys the annotation; the Coreference Critic round is over
    # the ceiling.
    monkeypatch.setattr(settings.coreference, "request_limit", 1)

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
        raise AssertionError("the ceiling should have stopped the resolution")

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        with pytest.raises(UsageLimitExceeded):
            PydanticAICoreferenceAdapter(
                annotator_agent=annotator_agent,
                critic_agent=critic_agent,
            ).resolve("Gavin Newsom signed a bill. He was happy.")


def test_a_resolution_that_exceeds_its_token_limit_fails(monkeypatch):
    """The token ceiling stops the run as the request ceiling does."""

    from pydantic_ai.exceptions import UsageLimitExceeded

    from knowledge_map.config import settings

    monkeypatch.setattr(settings.coreference, "total_tokens_limit", 1)

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
        raise AssertionError("the ceiling should have stopped the resolution")

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        with pytest.raises(UsageLimitExceeded):
            PydanticAICoreferenceAdapter(
                annotator_agent=annotator_agent,
                critic_agent=critic_agent,
            ).resolve("Gavin Newsom signed a bill. He was happy.")


def test_a_bracketed_sentence_label_names_the_same_sentence_as_a_bare_one():
    """The sentence table displays ``[2]``, so an annotator may echo it back."""

    bracketed = MentionSpan(
        sentence_label="[2]",
        mention_text="He",
        canonical_entity_name="Gavin Newsom",
    )
    bare = MentionSpan(
        sentence_label="2",
        mention_text="He",
        canonical_entity_name="Gavin Newsom",
    )

    assert bracketed.sentence_label == "2"
    assert bracketed == bare

    bracketed_verdict = CriticVerdict(
        sentence_label="[2]",
        mention_text="He",
        accepted=True,
    )
    bare_verdict = CriticVerdict(
        sentence_label="2",
        mention_text="He",
        accepted=True,
    )

    assert bracketed_verdict.sentence_label == "2"
    assert bracketed_verdict == bare_verdict


def test_a_bracketed_label_from_the_annotator_still_substitutes():
    content = "Gavin Newsom signed a bill. He was happy."
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "[2]",
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
                    "sentence_label": "[2]",
                    "mention_text": "He",
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
        ).resolve(content)

    assert run.resolved_text == "Gavin Newsom signed a bill. Gavin Newsom was happy."
    assert run.discarded_count == 0


class TestTheAnnotatorSpanBudgetScalesWithTheArticle:
    """What the annotator may return is a rate, not a constant.

    Mentions scale with the article, so a constant budget is slack on a
    short article and a real limit on a long one.  A runaway answer sits
    far above the rate at any size, which is what the budget separates.
    """

    def test_the_budget_grows_with_the_article(self):
        short = annotator_span_budget(" ".join(["word"] * 400))
        long = annotator_span_budget(" ".join(["word"] * 1600))

        assert long == 4 * short

    def test_a_short_article_still_gets_the_floor(self):
        """A budget below the floor would fail an article for being brief."""

        budget = annotator_span_budget("Gavin Newsom signed it.")

        assert budget == settings.coreference.min_span_budget

    def test_the_budget_clears_the_densest_article_observed(self):
        """14.83 spans per 100 words is the worst of 104 observed runs."""

        content = " ".join(["word"] * 1000)

        assert annotator_span_budget(content) > 149

    def test_the_budget_refuses_a_runaway_answer(self):
        """The runaways returned ~1000 spans on articles this size."""

        assert annotator_span_budget(" ".join(["word"] * 1083)) < 1003
        assert annotator_span_budget(" ".join(["word"] * 1644)) < 1007

    def test_the_token_ceiling_carries_the_span_budget(self):
        content = " ".join(["word"] * 1200)

        assert annotator_output_tokens(content) == (
            annotator_span_budget(content) * settings.coreference.tokens_per_span
        )


def test_the_annotator_is_told_the_articles_output_ceiling():
    """Only a token ceiling stops a runaway while it is still generating.

    A span count checked after the answer arrives has already paid for the
    tokens; this is the limit the model itself enforces.
    """

    content = "Gavin Newsom signed a bill. " + " ".join(["word"] * 1200)
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    seen: list[dict] = []

    def mock_annotator(messages, info):
        seen.append(dict(info.model_settings or {}))
        return mention_response(
            info,
            [
                {
                    "sentence_label": "1",
                    "mention_text": "Gavin Newsom",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    def mock_critic(messages, info):
        return critic_response(
            info,
            [
                {
                    "sentence_label": "1",
                    "mention_text": "Gavin Newsom",
                    "accepted": True,
                }
            ],
        )

    with (
        annotator_agent.override(model=FunctionModel(mock_annotator)),
        critic_agent.override(model=FunctionModel(mock_critic)),
    ):
        PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
        ).resolve(content)

    assert seen
    assert seen[0]["max_tokens"] == annotator_output_tokens(content)


def truncated_annotator_response(info):
    """A tool call cut off mid-arguments, as max_tokens leaves it."""

    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args='{"response":[{"sentence_label":"1","mention_text":"He","occ',
            )
        ],
        finish_reason="length",
    )


class TestAnExhaustedBudgetFailsOnTheFirstAnswer:
    """Truncation is not a mistake the annotator can correct.

    Pydantic AI treats a truncated tool call as unparseable arguments and
    spends the whole output-retry budget re-asking before it diagnoses the
    truncation.  Nothing about the request changes between those attempts,
    so each one truncates again at the same ceiling.
    """

    def test_the_run_ends_after_one_truncated_answer(self):
        agent = get_annotator_agent(defer_check=True)
        deps = CoreferenceDeps.for_content("Gavin Newsom signed a bill. He was happy.")
        calls = []

        def truncating_model(messages, info):
            calls.append(1)
            return truncated_annotator_response(info)

        with agent.override(model=FunctionModel(truncating_model)):
            with pytest.raises(AnnotatorBudgetExceeded):
                agent.run_sync("Resolve the references.", deps=deps)

        assert len(calls) == 1

    def test_the_failure_carries_the_budget_that_was_reached(self):
        content = " ".join(["word"] * 800)
        agent = get_annotator_agent(defer_check=True)
        deps = CoreferenceDeps.for_content(content)

        with agent.override(model=FunctionModel(lambda m, i: truncated_annotator_response(i))):
            with pytest.raises(AnnotatorBudgetExceeded) as caught:
                agent.run_sync("Resolve the references.", deps=deps)

        assert caught.value.word_count == 800
        assert caught.value.span_budget == annotator_span_budget(content)
        assert caught.value.max_tokens == annotator_output_tokens(content)

    def test_it_is_dead_lettered_under_its_own_failure_type(self):
        """The Dead Letter Queue names the failure in the record and filename.

        A budget this system set and can raise is a different thing to
        diagnose than output the annotator simply malformed.
        """

        annotator_agent = get_annotator_agent(defer_check=True)
        critic_agent = get_critic_agent(defer_check=True)

        with (
            annotator_agent.override(
                model=FunctionModel(lambda m, i: truncated_annotator_response(i))
            ),
            critic_agent.override(
                model=FunctionModel(lambda m, i: truncated_annotator_response(i))
            ),
        ):
            with pytest.raises(CoreferenceResolutionError) as caught:
                PydanticAICoreferenceAdapter(
                    annotator_agent=annotator_agent,
                    critic_agent=critic_agent,
                ).resolve("Gavin Newsom signed a bill. He was happy.")

        assert caught.value.failure_type == "coreference_budget_exceeded"
        assert caught.value.metadata["span_budget"] == settings.coreference.min_span_budget
        assert isinstance(caught.value.__cause__, AnnotatorBudgetExceeded)

    def test_a_complete_answer_is_untouched_by_the_hook(self):
        """Only a truncated answer is refused; a finished one passes through."""

        agent = get_annotator_agent(defer_check=True)
        deps = CoreferenceDeps.for_content("Gavin Newsom signed a bill. He was happy.")

        def complete_model(messages, info):
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

        with agent.override(model=FunctionModel(complete_model)):
            result = agent.run_sync("Resolve the references.", deps=deps)

        assert result.output[0].canonical_entity_name == "Gavin Newsom"
