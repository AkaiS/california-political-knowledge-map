"""What a report says about the prompt a run actually sent.

The commit cannot answer that question -- it moves for every change in the
repository, and says nothing at all when the worktree is dirty -- so a run
digests its own instructions and carries the digest into the report.
"""

import argparse
from pathlib import Path
from types import SimpleNamespace

from pydantic_evals.reporting import EvaluationReport, ReportCase

from knowledge_map.cli import evaluate
from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.data_set import EvaluationCase, EvaluationDataSet
from knowledge_map.evaluation.tasks import EvaluationTask, task_named, task_names
from knowledge_map.evaluation.tasks.relevance import RELEVANCE_HEADLINE


def _task(prompts) -> EvaluationTask:
    return EvaluationTask(
        name="fixture",
        input_type=dict,
        output_type=dict,
        build=lambda deployment, data_set: lambda case_input: {},
        evaluators=(),
        default_model="fixture/model",
        label_quality=LabelQuality.SILVER,
        headline=RELEVANCE_HEADLINE,
        prompts=prompts,
    )


def test_the_same_instructions_digest_the_same():
    first = _task(lambda: {"annotator": "resolve the pronouns"})
    second = _task(lambda: {"annotator": "resolve the pronouns"})

    assert first.prompt_digests() == second.prompt_digests()


def test_one_edited_word_changes_the_digest():
    before = _task(lambda: {"annotator": "resolve the pronouns"})
    after = _task(lambda: {"annotator": "resolve every pronoun"})

    assert before.prompt_digests() != after.prompt_digests()


def test_each_agent_is_digested_apart():
    """A two-agent loop names which half moved, not merely that one did."""
    task = _task(lambda: {"annotator": "annotate", "critic": "criticize"})

    digests = task.prompt_digests()

    assert set(digests) == {"annotator", "critic"}
    assert digests["annotator"] != digests["critic"]


def test_instructions_are_read_when_the_run_starts_not_at_import():
    """A prompt read from a file or rendered from the ontology is digested
    as the run will send it, not as it stood when the module was imported."""
    text = ["first"]
    task = _task(lambda: {"extraction": text[0]})

    before = task.prompt_digests()
    text[0] = "second"

    assert task.prompt_digests() != before


def test_a_task_that_declares_no_prompt_digests_nothing():
    assert _task(dict).prompt_digests() == {}


def test_every_registered_task_declares_the_prompt_it_runs():
    """A registered task without this is a report that cannot be attributed."""
    for name in task_names():
        assert task_named(name).prompt_digests(), name


def test_the_run_command_carries_the_digests_into_experiment_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}
    data_set_path = tmp_path / "relevance.yaml"
    data_set_path.write_text("placeholder")

    task = SimpleNamespace(
        name="relevance",
        data_set_stem="relevance",
        label_quality=LabelQuality.GOLD,
        headline=RELEVANCE_HEADLINE,
        input_type=dict,
        output_type=dict,
        metadata_type=dict,
        build=lambda deployment, data_set: lambda case_input: {},
        evaluators=(),
        prompt_digests=lambda: {"relevance": "sha256:0123456789ab"},
    )
    report = EvaluationReport(
        name="relevance",
        cases=[
            ReportCase(
                name="case",
                inputs={},
                expected_output={},
                metadata=None,
                output={},
                metrics={},
                attributes={},
                scores={},
                labels={},
                assertions={},
                task_duration=0.0,
                total_duration=0.0,
            )
        ],
    )

    def capture(*args, **kwargs):
        captured["metadata"] = kwargs["experiment_metadata"]
        return report

    monkeypatch.setattr(evaluate, "task_named", lambda name: task)
    monkeypatch.setattr(
        evaluate,
        "load_data_set",
        lambda *args, **kwargs: EvaluationDataSet(
            task="relevance",
            description="test",
            cases=(
                EvaluationCase(
                    id="case",
                    description="test",
                    task_input={},
                    expected_output={},
                ),
            ),
        ),
    )
    monkeypatch.setattr(evaluate, "run_data_set", capture)
    monkeypatch.setattr(evaluate, "write_report", lambda *a, **k: tmp_path / "r.json")

    evaluate.dispatch(
        argparse.Namespace(
            eval_action="run",
            task="relevance",
            data_set=data_set_path,
            deployment="local",
            model="local/model",
            split=None,
            max_concurrency=1,
            no_report=False,
        )
    )

    assert captured["metadata"]["prompts"] == {"relevance": "sha256:0123456789ab"}
