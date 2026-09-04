"""The coreference evaluators score the four things they claim to score."""

import pytest
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_evals.evaluators import EvaluatorContext

import knowledge_map.adapters.coreference as coreference_adapter_module
import knowledge_map.evaluation.tasks.coreference as coreference_task_module
from knowledge_map.evaluation.scoring import UNSCORED
from knowledge_map.evaluation.tasks import task_named
from knowledge_map.evaluation.tasks.coreference import (
    AgreedOnTheCanonicalEntity,
    CoreferenceExpectation,
    CoreferenceInput,
    CoreferenceOutput,
    FoundTheSilverMentionSpans,
    MatchedTheSilverClustering,
    RejectedOnlyTheWrongMentionSpans,
    ResolvedWithoutFailing,
    entity_by_identity,
    normalize_entity_name,
)
from knowledge_map.schemas import (
    DeploymentKind,
    MentionSpan,
    MentionSpanOutcome,
    ModelDeployment,
    ModelRequestSettings,
)


def _span(label: str, text: str, entity: str, occurrence: int = 1) -> MentionSpan:
    return MentionSpan(
        sentence_label=label,
        mention_text=text,
        occurrence=occurrence,
        canonical_entity_name=entity,
    )


def _context(expected: list[MentionSpan], output: CoreferenceOutput):
    """One EvaluatorContext holding a silver answer and a model answer."""

    return EvaluatorContext(
        name="case",
        inputs=CoreferenceInput(url="https://example.test/a", title="A", content="a"),
        metadata=None,
        expected_output=CoreferenceExpectation(mention_spans=expected),
        output=output,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def _scored(evaluator, expected, produced, **output_kwargs):
    return evaluator.evaluate(
        _context(expected, CoreferenceOutput(mention_spans=produced, **output_kwargs))
    )


def _local_deployment() -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="explicit-evaluation-coreference-model",
        endpoint="http://explicit-evaluation-coreference.test:9999",
        request_settings=ModelRequestSettings(thinking=False),
    )


def _response(info, spans: list[dict]) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"response": spans},
                tool_call_id="call-1",
            )
        ]
    )


def test_full_task_binds_one_explicit_deployment_to_both_coreference_agents(
    monkeypatch,
):
    seen: list[object] = []
    calls = 0
    deployment = _local_deployment()

    def model_factory(requested, *args, **kwargs):
        nonlocal calls
        seen.append(requested)
        assert isinstance(requested, ModelDeployment)
        assert not args
        assert not kwargs

        def respond(messages, info):
            nonlocal calls
            calls += 1
            if calls == 1:
                return _response(
                    info,
                    [
                        {
                            "sentence_label": "2",
                            "mention_text": "He",
                            "canonical_entity_name": "Gavin Newsom",
                        }
                    ],
                )
            return _response(
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

    resolve = coreference_task_module.build_task(deployment, None)
    output = resolve(
        CoreferenceInput(
            url="https://example.test/coreference",
            title="A story",
            content="Gavin Newsom signed a bill. He was happy.",
        )
    )

    assert [span.canonical_entity_name for span in output.mention_spans] == [
        "Gavin Newsom"
    ]
    assert seen == [deployment, deployment]


def test_annotator_task_binds_its_explicit_deployment_without_stage_lookup(
    monkeypatch,
):
    seen: list[object] = []
    deployment = _local_deployment()

    def model_factory(requested, *args, **kwargs):
        seen.append(requested)
        assert isinstance(requested, ModelDeployment)
        assert not args
        assert not kwargs
        return FunctionModel(
            lambda messages, info: _response(
                info,
                [
                    {
                        "sentence_label": "2",
                        "mention_text": "He",
                        "canonical_entity_name": "Gavin Newsom",
                    }
                ],
            )
        )

    monkeypatch.setenv("LLAMA_CPP_MODEL", "ambient-local-model")
    monkeypatch.setattr(coreference_adapter_module, "get_chat_model", model_factory)

    annotate = coreference_task_module.build_annotator_task(deployment, None)
    output = annotate(
        CoreferenceInput(
            url="https://example.test/coreference",
            title="A story",
            content="Gavin Newsom signed a bill. He was happy.",
        )
    )

    assert [span.canonical_entity_name for span in output.mention_spans] == [
        "Gavin Newsom"
    ]
    assert seen == [deployment]


# --- the task is registered and reachable from the CLI -----------------------


def test_coreference_is_a_registered_task_with_its_five_evaluators() -> None:
    task = task_named("coreference")

    assert task.name == "coreference"
    assert task.collect is None
    assert task.data_set_stem == "coreference"
    assert [type(evaluator).__name__ for evaluator in task.evaluators] == [
        "FoundTheSilverMentionSpans",
        "AgreedOnTheCanonicalEntity",
        "MatchedTheSilverClustering",
        "ResolvedWithoutFailing",
        "RejectedOnlyTheWrongMentionSpans",
    ]


def test_the_annotator_task_reads_the_same_silver_set_and_omits_the_critic() -> None:
    """The baseline has to be the same cases, or it is not a baseline."""

    pipeline = task_named("coreference")
    annotator = task_named("coreference_annotator")

    assert annotator.data_set_stem == "coreference"
    assert annotator.input_type is pipeline.input_type
    assert annotator.output_type is pipeline.output_type
    assert annotator.metadata_type is pipeline.metadata_type
    assert annotator.default_model == pipeline.default_model

    # The four agreement evaluators, and not the Critic one: no outcome in an
    # annotator-only run carries a `critic` stage for it to read.
    assert [type(evaluator).__name__ for evaluator in annotator.evaluators] == [
        "FoundTheSilverMentionSpans",
        "AgreedOnTheCanonicalEntity",
        "MatchedTheSilverClustering",
        "ResolvedWithoutFailing",
    ]


def test_the_two_tasks_do_not_share_a_build() -> None:
    assert task_named("coreference").build is not task_named(
        "coreference_annotator"
    ).build


# --- span detection ----------------------------------------------------------


def test_an_identical_answer_scores_one_everywhere() -> None:
    spans = [_span("1", "He", "Steve Hilton"), _span("2", "Cameron", "David Cameron")]

    assert _scored(FoundTheSilverMentionSpans(), spans, list(spans)) == {
        "span_precision": 1.0,
        "span_recall": 1.0,
        "span_f1": 1.0,
    }


def test_a_missed_mention_costs_recall_and_leaves_precision_whole() -> None:
    expected = [_span("1", "He", "X"), _span("2", "him", "X")]

    scored = _scored(FoundTheSilverMentionSpans(), expected, [_span("1", "He", "X")])

    assert scored["span_precision"] == 1.0
    assert scored["span_recall"] == 0.5


def test_a_spurious_mention_costs_precision_and_leaves_recall_whole() -> None:
    expected = [_span("1", "He", "X")]
    produced = [_span("1", "He", "X"), _span("3", "they", "Y")]

    scored = _scored(FoundTheSilverMentionSpans(), expected, produced)

    assert scored["span_recall"] == 1.0
    assert scored["span_precision"] == 0.5


def test_the_occurrence_is_part_of_the_location() -> None:
    """The second "He" in a sentence is a different mention from the first."""

    expected = [_span("1", "He", "X", occurrence=2)]

    scored = _scored(
        FoundTheSilverMentionSpans(), expected, [_span("1", "He", "X", occurrence=1)]
    )

    assert scored["span_recall"] == 0.0


def test_the_entity_name_is_not_part_of_the_location() -> None:
    """Detection is scored before naming, so a wrong entity still counts."""

    scored = _scored(
        FoundTheSilverMentionSpans(),
        [_span("1", "He", "Steve Hilton")],
        [_span("1", "He", "David Cameron")],
    )

    assert scored["span_recall"] == 1.0
    assert scored["span_precision"] == 1.0


def test_a_failed_run_scores_zero_rather_than_disappearing() -> None:
    scored = _scored(
        FoundTheSilverMentionSpans(),
        [_span("1", "He", "X")],
        [],
        failure_type="all_mentions_rejected",
    )

    assert scored == {"span_precision": 0.0, "span_recall": 0.0, "span_f1": 0.0}


# --- entity naming -----------------------------------------------------------


def test_naming_is_scored_only_over_the_mentions_both_sides_found() -> None:
    expected = [_span("1", "He", "Steve Hilton"), _span("2", "him", "Steve Hilton")]
    produced = [_span("1", "He", "Steve Hilton")]

    # 1 of 1 shared, not 1 of 2: the mention it never found is a detection
    # miss and is charged to recall, not to naming.
    assert _scored(AgreedOnTheCanonicalEntity(), expected, produced) == {
        "entity_accuracy": 1.0
    }


def test_a_wrong_entity_on_a_found_mention_is_scored_as_disagreement() -> None:
    expected = [_span("1", "He", "Steve Hilton"), _span("2", "He", "Steve Hilton")]
    produced = [_span("1", "He", "Steve Hilton"), _span("2", "He", "David Cameron")]

    assert _scored(AgreedOnTheCanonicalEntity(), expected, produced) == {
        "entity_accuracy": 0.5
    }


@pytest.mark.parametrize("written", ["Steve Hilton", "steve hilton", "Steve  Hilton"])
def test_case_and_whitespace_are_not_a_disagreement(written: str) -> None:
    assert _scored(
        AgreedOnTheCanonicalEntity(),
        [_span("1", "He", "Steve Hilton")],
        [_span("1", "He", written)],
    ) == {"entity_accuracy": 1.0}


def test_a_shortened_name_is_a_disagreement_here() -> None:
    """Left to the clustering evaluator, which reads no names at all."""

    assert _scored(
        AgreedOnTheCanonicalEntity(),
        [_span("1", "He", "Steve Hilton")],
        [_span("1", "He", "Hilton")],
    ) == {"entity_accuracy": 0.0}


def test_no_shared_mention_is_unscored_rather_than_zero() -> None:
    """Unscored is `UNSCORED`: `pydantic-evals` fails the case on `None`."""

    assert (
        _scored(
            AgreedOnTheCanonicalEntity(),
            [_span("1", "He", "X")],
            [_span("9", "they", "Y")],
        )
        == UNSCORED
    )


# --- clustering --------------------------------------------------------------


def test_renaming_every_cluster_consistently_still_matches_the_partition() -> None:
    expected = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "him", "Steve Hilton"),
        _span("3", "Cameron", "David Cameron"),
    ]
    produced = [
        _span("1", "He", "Hilton"),
        _span("2", "him", "Hilton"),
        _span("3", "Cameron", "Cameron"),
    ]

    assert _scored(MatchedTheSilverClustering(), expected, produced) == {
        "cluster_precision": 1.0,
        "cluster_recall": 1.0,
        "cluster_f1": 1.0,
    }
    # The same answer, scored by name, looks like a total failure.
    assert _scored(AgreedOnTheCanonicalEntity(), expected, produced) == {
        "entity_accuracy": 0.0
    }


def test_merging_two_people_into_one_cluster_costs_precision() -> None:
    expected = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "him", "Steve Hilton"),
        _span("3", "Cameron", "David Cameron"),
    ]
    produced = [
        _span("1", "He", "Hilton"),
        _span("2", "him", "Hilton"),
        _span("3", "Cameron", "Hilton"),
    ]

    scored = _scored(MatchedTheSilverClustering(), expected, produced)

    # Every mention is in one predicted cluster of 3.  Precision per mention:
    # 2/3, 2/3, 1/3.  Recall: the silver clusters are recovered whole.
    assert scored["cluster_precision"] == pytest.approx(5 / 9)
    assert scored["cluster_recall"] == 1.0


def test_splitting_one_person_across_two_clusters_costs_recall() -> None:
    expected = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "him", "Steve Hilton"),
        _span("3", "his", "Steve Hilton"),
    ]
    produced = [
        _span("1", "He", "Hilton"),
        _span("2", "him", "Hilton"),
        _span("3", "his", "The candidate"),
    ]

    scored = _scored(MatchedTheSilverClustering(), expected, produced)

    assert scored["cluster_precision"] == 1.0
    assert scored["cluster_recall"] == pytest.approx(5 / 9)


def test_clustering_ignores_mentions_only_one_side_found() -> None:
    """A mention the model never proposed belongs to no predicted cluster."""

    expected = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "him", "Steve Hilton"),
        _span("7", "she", "Rachel Whetstone"),
    ]
    produced = [_span("1", "He", "Hilton"), _span("2", "him", "Hilton")]

    assert _scored(MatchedTheSilverClustering(), expected, produced) == {
        "cluster_precision": 1.0,
        "cluster_recall": 1.0,
        "cluster_f1": 1.0,
    }


def test_clustering_is_unscored_when_nothing_overlaps() -> None:
    assert (
        _scored(MatchedTheSilverClustering(), [_span("1", "He", "X")], [])
        == UNSCORED
    )


# --- run health --------------------------------------------------------------


def test_a_run_that_produced_spans_resolved() -> None:
    assert _scored(ResolvedWithoutFailing(), [], [_span("1", "He", "X")]) is True


def test_a_run_that_raised_did_not_resolve() -> None:
    assert (
        _scored(
            ResolvedWithoutFailing(),
            [_span("1", "He", "X")],
            [],
            failure_type="coreference_validation_failure",
        )
        is False
    )


def test_an_empty_answer_that_did_not_fail_still_counts_as_resolved() -> None:
    """A Story with no references legitimately yields no Mention Spans."""

    assert _scored(ResolvedWithoutFailing(), [], []) is True


# --- indexing ----------------------------------------------------------------


def test_two_entities_claiming_one_location_collapse_to_the_last() -> None:
    """Matching `ResolutionState`, whose outcome map does the same thing."""

    indexed = entity_by_identity(
        [_span("1", "He", "Steve Hilton"), _span("1", "He", "David Cameron")]
    )

    assert len(indexed) == 1
    assert next(iter(indexed.values())) == normalize_entity_name("David Cameron")


# --- what the Coreference Critic's rejections were worth ---------------------


def _critic(span: MentionSpan, *, accepted: bool) -> MentionSpanOutcome:
    return MentionSpanOutcome(
        mention_span=span,
        stage="critic",
        outcome="accepted" if accepted else "rejected",
        reason=None if accepted else "wrong entity",
    )


def _critic_scored(expected: list[MentionSpan], outcomes: list[MentionSpanOutcome]):
    return RejectedOnlyTheWrongMentionSpans().evaluate(
        _context(expected, CoreferenceOutput(outcomes=outcomes))
    )


def test_a_critic_that_rejects_only_wrong_spans_scores_one_everywhere() -> None:
    silver = [_span("1", "He", "Steve Hilton"), _span("2", "He", "David Cameron")]
    outcomes = [
        _critic(_span("1", "He", "Steve Hilton"), accepted=True),
        _critic(_span("2", "He", "Someone Else"), accepted=False),
    ]

    assert _critic_scored(silver, outcomes) == {
        "critic_rejection_precision": 1.0,
        "critic_rejection_recall": 1.0,
        "critic_kept_correct_spans": 1.0,
    }


def test_a_critic_that_deletes_correct_work_is_visible_as_that() -> None:
    """The failure the pipeline score alone cannot show: net-negative critic."""

    silver = [_span("1", "He", "Steve Hilton"), _span("2", "She", "Kamala Harris")]
    outcomes = [
        _critic(_span("1", "He", "Steve Hilton"), accepted=False),
        _critic(_span("2", "She", "Kamala Harris"), accepted=False),
    ]

    scores = _critic_scored(silver, outcomes)

    # It threw away two spans and neither deserved it.
    assert scores["critic_rejection_precision"] == 0.0
    assert scores["critic_kept_correct_spans"] == 0.0
    # It was shown no wrong spans, so there is no recall to report.
    assert "critic_rejection_recall" not in scores


def test_a_critic_that_waves_everything_through_has_no_recall() -> None:
    silver = [_span("1", "He", "Steve Hilton"), _span("2", "She", "Kamala Harris")]
    outcomes = [
        _critic(_span("1", "He", "Steve Hilton"), accepted=True),
        _critic(_span("2", "She", "Somebody Wrong"), accepted=True),
    ]

    scores = _critic_scored(silver, outcomes)

    assert scores["critic_rejection_recall"] == 0.0
    assert scores["critic_kept_correct_spans"] == 1.0
    # It rejected nothing, so there is no rejection precision to report.
    assert "critic_rejection_precision" not in scores


def test_a_span_silver_never_annotated_is_skipped_not_counted_wrong() -> None:
    """Silver's silence is not evidence, so it cannot make the Critic look bad."""

    silver = [_span("1", "He", "Steve Hilton")]
    outcomes = [
        _critic(_span("1", "He", "Steve Hilton"), accepted=True),
        _critic(_span("9", "They", "Some Group"), accepted=False),
    ]

    scores = _critic_scored(silver, outcomes)

    # Only the judgeable span counted; the rejection of the unannotated one
    # neither helped nor hurt.
    assert scores["critic_kept_correct_spans"] == 1.0
    assert "critic_rejection_precision" not in scores


def test_validation_discards_are_not_critic_decisions() -> None:
    """A span the Critic never saw cannot be scored as its judgement."""

    silver = [_span("1", "He", "Steve Hilton")]
    outcomes = [
        MentionSpanOutcome(
            mention_span=_span("1", "He", "Steve Hilton"),
            stage="validation",
            outcome="discarded",
            reason="mention text does not occur in sentence '1'",
        )
    ]

    assert _critic_scored(silver, outcomes) == UNSCORED


def test_an_annotator_only_run_reports_no_critic_scores() -> None:
    """Its outcomes are all `validation`, so the evaluator stays silent."""

    silver = [_span("1", "He", "Steve Hilton")]
    outcomes = [
        MentionSpanOutcome(
            mention_span=_span("1", "He", "Steve Hilton"),
            stage="validation",
            outcome="accepted",
        )
    ]

    assert _critic_scored(silver, outcomes) == UNSCORED


def test_a_run_with_no_outcomes_reports_nothing() -> None:
    assert _critic_scored([_span("1", "He", "Steve Hilton")], []) == UNSCORED


def test_a_half_right_critic_scores_a_half() -> None:
    silver = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "He", "David Cameron"),
        _span("3", "She", "Kamala Harris"),
        _span("4", "She", "Katie Porter"),
    ]
    outcomes = [
        # correct, kept -> good
        _critic(_span("1", "He", "Steve Hilton"), accepted=True),
        # correct, rejected -> deleted good work
        _critic(_span("2", "He", "David Cameron"), accepted=False),
        # wrong, rejected -> caught
        _critic(_span("3", "She", "Nobody At All"), accepted=False),
        # wrong, kept -> missed
        _critic(_span("4", "She", "Nobody At All"), accepted=True),
    ]

    assert _critic_scored(silver, outcomes) == {
        "critic_rejection_precision": 0.5,
        "critic_rejection_recall": 0.5,
        "critic_kept_correct_spans": 0.5,
    }


def test_critic_scoring_folds_case_and_whitespace_like_the_other_evaluators() -> None:
    silver = [_span("1", "He", "Steve Hilton")]
    outcomes = [_critic(_span("1", "He", "steve  hilton"), accepted=True)]

    assert _critic_scored(silver, outcomes)["critic_kept_correct_spans"] == 1.0
