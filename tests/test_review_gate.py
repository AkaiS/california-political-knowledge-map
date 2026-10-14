from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "review_gate", Path(__file__).parents[1] / "scripts/review_gate.py"
)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

HEAD = "a" * 40
MERGE = "b" * 40
TREE = "c" * 40
START = "2026-10-13T20:00:00Z"
FINISH = "2026-10-13T20:10:00Z"


def check(
    name="Greptile Review", app_id=gate.GREPTILE_APP_ID, slug="greptile-apps", **changes
):
    return {
        "id": 42,
        "name": name,
        "head_sha": HEAD,
        "app": {"id": app_id, "slug": slug},
        "status": "completed",
        "conclusion": "success",
        "started_at": START,
        "completed_at": FINISH,
        "ci_workflow": True,
        "details_url": f"https://github.com/{gate.REPOSITORY}/actions/runs/100/job/200",
        **changes,
    }


def summary(score=5, sha=HEAD, **changes):
    return {
        "id": 10,
        "user": {"id": gate.GREPTILE_BOT_ID, "login": "greptile-apps[bot]"},
        "body": (
            "<!-- greptile_summary -->\n"
            f"Confidence Score: {score}/5\n<!-- greptile_confidence_score:{score} -->\n"
            f'Last reviewed commit: ["Title"](https://github.com/akais/'
            f"california-political-knowledge-map/commit/{sha})"
        ),
        "updated_at": FINISH,
        **changes,
    }


def ci_tests_check(**changes):
    return check("tests", gate.ACTIONS_APP_ID, "github-actions", **changes)


def pr(**changes):
    return {
        "number": 41,
        "base": {"ref": "main", "repo": {"full_name": gate.REPOSITORY}},
        "head": {"sha": HEAD, "repo": {"full_name": "fork/repository"}},
        "state": "open",
        "merged": False,
        **changes,
    }


def test_requires_both_trusted_successful_review_and_current_score_five():
    gate.review_green([check()], [summary()], [], [], HEAD)
    with pytest.raises(gate.GateError, match="below"):
        gate.review_green([check()], [summary(3)], [], [], HEAD)


@pytest.mark.parametrize(
    "checks,comments",
    [
        ([], [summary()]),
        ([check(app_id=1)], [summary()]),
        ([check(slug="impostor")], [summary()]),
        ([check(head_sha=MERGE)], [summary()]),
        ([check(status="in_progress", conclusion=None)], [summary()]),
        ([check()], []),
        ([check()], [summary(user={"id": 1, "login": "greptile-apps[bot]"})]),
        ([check()], [summary(user={"id": gate.GREPTILE_BOT_ID, "login": "impostor"})]),
        ([check()], [summary(sha=MERGE)]),
        ([check()], [summary(updated_at="2026-10-13T19:00:00Z")]),
        ([check()], [summary(body="Confidence Score: 5/5")]),
        (
            [check()],
            [summary(body=summary()["body"] + "<!-- greptile_confidence_score:3 -->")],
        ),
    ],
)
def test_missing_stale_ambiguous_or_untrusted_evidence_waits(checks, comments):
    with pytest.raises(gate.PendingReview):
        gate.review_green(checks, comments, [], [], HEAD)


def test_latest_review_and_summary_win_over_old_success():
    rerun = check(id=43, started_at="2026-10-13T20:11:00Z", status="in_progress")
    with pytest.raises(gate.PendingReview):
        gate.review_green([check(), rerun], [summary()], [], [], HEAD)
    new_summary = summary(3, id=11, updated_at="2026-10-13T20:12:00Z")
    with pytest.raises(gate.GateError, match="below"):
        gate.review_green([check()], [summary(), new_summary], [], [], HEAD)


@pytest.mark.parametrize("outdated", [False, True])
def test_unresolved_threads_block_even_when_outdated(outdated):
    with pytest.raises(gate.GateError, match="unresolved"):
        gate.review_green(
            [check()],
            [summary()],
            [{"isResolved": False, "isOutdated": outdated}],
            [],
            HEAD,
        )
    gate.review_green(
        [check()], [summary()], [{"isResolved": True, "isOutdated": outdated}], [], HEAD
    )


def test_changes_requested_blocks_until_approved_or_dismissed():
    changes = {"id": 1, "user": {"id": 20}, "state": "CHANGES_REQUESTED"}
    comment = {"id": 2, "user": {"id": 20}, "state": "COMMENTED"}
    with pytest.raises(gate.GateError, match="requests changes"):
        gate.review_green([check()], [summary()], [], [changes, comment], HEAD)
    approved = {"id": 3, "user": {"id": 20}, "state": "APPROVED"}
    gate.review_green([check()], [summary()], [], [changes, comment, approved], HEAD)


@pytest.mark.parametrize(
    "conclusion", ["failure", "cancelled", "skipped", "neutral", "timed_out"]
)
def test_review_check_must_succeed(conclusion):
    with pytest.raises(gate.GateError, match="Greptile check"):
        gate.review_green([check(conclusion=conclusion)], [summary()], [], [], HEAD)


def test_tests_required_and_only_own_downstream_checks_are_excluded():
    skipped = [
        check(name, gate.ACTIONS_APP_ID, "github-actions", conclusion="skipped")
        for name in gate.DOWNSTREAM_CHECKS
    ]
    gate.other_checks_green([ci_tests_check(), check(), *skipped], [], HEAD)
    with pytest.raises(gate.PendingReview):
        gate.other_checks_green([check(), *skipped], [], HEAD)
    with pytest.raises(gate.GateError, match="Another check"):
        gate.other_checks_green(
            [
                ci_tests_check(),
                check("container-build", app_id=1, conclusion="failure"),
            ],
            [],
            HEAD,
        )
    with pytest.raises(gate.GateError, match="Another check"):
        gate.other_checks_green(
            [
                ci_tests_check(),
                check(
                    "container-build",
                    gate.ACTIONS_APP_ID,
                    "github-actions",
                    ci_workflow=False,
                    conclusion="failure",
                ),
            ],
            [],
            HEAD,
        )


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "neutral", "skipped"])
def test_any_other_non_green_check_blocks(conclusion):
    with pytest.raises(gate.GateError):
        gate.other_checks_green(
            [ci_tests_check(), check("security", conclusion=conclusion)], [], HEAD
        )


def test_pending_checks_and_legacy_statuses():
    with pytest.raises(gate.PendingReview):
        gate.other_checks_green([ci_tests_check(status="in_progress")], [], HEAD)
    for state, error in [
        ("pending", gate.PendingReview),
        ("failure", gate.GateError),
        ("error", gate.GateError),
    ]:
        with pytest.raises(error):
            gate.other_checks_green(
                [ci_tests_check()], [{"sha": HEAD, "state": state}], HEAD
            )
    gate.other_checks_green(
        [ci_tests_check()], [{"sha": HEAD, "state": "success"}], HEAD
    )


def test_status_adapter_validates_outer_sha_and_paginates(monkeypatch):
    api = gate.GitHub({})
    pages = [{"sha": HEAD, "statuses": [{"state": "success", "context": "legacy"}]}]
    monkeypatch.setattr(api, "api", lambda endpoint, **kwargs: pages)
    assert api.statuses(HEAD) == [
        {"sha": HEAD, "state": "success", "context": "legacy"}
    ]
    pages.append({"sha": MERGE, "statuses": []})
    with pytest.raises(gate.GateError, match="candidate"):
        api.statuses(HEAD)


def test_all_check_comment_and_thread_pages_are_read(monkeypatch):
    api = gate.GitHub({})
    requests = []

    def request(endpoint, **kwargs):
        requests.append((endpoint, kwargs))
        if endpoint == "graphql":
            second = ("cursor", "next") in kwargs["fields"]
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [
                                    {"isResolved": not second, "isOutdated": second}
                                ],
                                "pageInfo": {
                                    "hasNextPage": not second,
                                    "endCursor": None if second else "next",
                                },
                            }
                        }
                    }
                }
            }
        if "/check-runs" in endpoint:
            assert kwargs["paginate"] is True
            return [{"check_runs": [ci_tests_check()]}, {"check_runs": [check()]}]
        if "/actions/runs/" in endpoint:
            return {
                "head_sha": HEAD,
                "repository": {"full_name": gate.REPOSITORY},
                "path": ".github/workflows/ci.yml",
            }
        return [[summary()], [summary(3, id=11)]]

    monkeypatch.setattr(api, "api", request)
    assert len(api.checks(HEAD)) == 2
    assert len(api.comments(41)) == 2
    threads = api.threads(41)
    assert len(threads) == 2
    with pytest.raises(gate.GateError, match="unresolved"):
        gate.review_green([check()], [summary()], threads, [], HEAD)
    assert len(requests) == 5


@pytest.mark.parametrize(
    "path", [".github/workflows/ci.yml", ".github/workflows/another.yml"]
)
def test_check_exclusions_require_authoritative_workflow_identity(monkeypatch, path):
    api = gate.GitHub({})
    response = check("container-build", gate.ACTIONS_APP_ID, "github-actions")

    def request(endpoint, **kwargs):
        if "/check-runs" in endpoint:
            return [{"check_runs": [response]}]
        return {
            "head_sha": HEAD,
            "repository": {"full_name": gate.REPOSITORY},
            "path": path,
        }

    monkeypatch.setattr(api, "api", request)
    checks = api.checks(HEAD)
    assert checks[0]["ci_workflow"] is (path == ".github/workflows/ci.yml")


@pytest.fixture
def event_environment(tmp_path):
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"number": 41, "pull_request": pr()}))
    return {
        "GITHUB_REPOSITORY": gate.REPOSITORY,
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_REF": "refs/pull/41/merge",
        "GITHUB_SHA": MERGE,
    }


def test_fork_pr_uses_base_repository_review_and_event_head(event_environment):
    assert gate.candidate(event_environment, gate.GitHub({})) == (41, HEAD, None)
    api = gate.GitHub({})
    api.pull_request = lambda number: pr()
    gate.current_pr(api, 41, HEAD)
    api.pull_request = lambda number: pr(head={"sha": MERGE})
    with pytest.raises(gate.GateError, match="head changed"):
        gate.current_pr(api, 41, HEAD)


@pytest.mark.parametrize(
    "change",
    [
        {"GITHUB_EVENT_NAME": "workflow_dispatch"},
        {"GITHUB_REPOSITORY": "fork/repository"},
        {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/other"},
    ],
)
def test_untrusted_event_rejected(event_environment, change):
    event_environment.update(change)
    with pytest.raises(gate.GateError):
        gate.candidate(event_environment, gate.GitHub({}))


@pytest.mark.parametrize("failure", [None, "direct", "wrong_merge", "different_tree"])
def test_main_push_requires_exact_merged_pr_and_same_reviewed_tree(
    event_environment, monkeypatch, failure
):
    event_environment.update(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main")
    api = gate.GitHub({})
    merged = pr(merged=True, merged_at=FINISH, state="closed", merge_commit_sha=MERGE)
    if failure == "wrong_merge":
        merged["merge_commit_sha"] = HEAD
    monkeypatch.setattr(
        api, "pages", lambda endpoint: [] if failure == "direct" else [merged]
    )
    monkeypatch.setattr(
        api,
        "api",
        lambda endpoint: {
            "commit": {
                "tree": {
                    "sha": HEAD
                    if failure == "different_tree" and endpoint.endswith(MERGE)
                    else TREE
                }
            }
        },
    )
    if failure:
        with pytest.raises(gate.GateError):
            gate.candidate(event_environment, api)
    else:
        assert gate.candidate(event_environment, api) == (41, HEAD, MERGE)


def test_poll_rechecks_head_and_times_out_without_success(
    event_environment, monkeypatch
):
    api = gate.GitHub({})
    calls = []
    monkeypatch.setattr(gate, "GitHub", lambda environment: api)
    monkeypatch.setattr(
        api, "pull_request", lambda number: calls.append(number) or pr()
    )
    monkeypatch.setattr(api, "checks", lambda sha: [ci_tests_check(), check()])
    monkeypatch.setattr(api, "comments", lambda number: [summary(sha=MERGE)])
    monkeypatch.setattr(api, "threads", lambda number: [])
    monkeypatch.setattr(api, "reviews", lambda number: [])
    monkeypatch.setattr(api, "statuses", lambda sha: [])
    with pytest.raises(gate.GateError, match="Timed out"):
        gate.wait_for_review(event_environment, timeout=0)
    assert len(calls) == 2
    monkeypatch.setattr(api, "comments", lambda number: [summary()])
    assert gate.wait_for_review(event_environment, timeout=0) == HEAD
    assert len(calls) == 5


def test_poll_rejects_head_change_while_fetching_review(event_environment, monkeypatch):
    api = gate.GitHub({})
    heads = iter([pr(), pr(head={"sha": MERGE})])
    monkeypatch.setattr(gate, "GitHub", lambda environment: api)
    monkeypatch.setattr(api, "pull_request", lambda number: next(heads))
    monkeypatch.setattr(api, "checks", lambda sha: [ci_tests_check(), check()])
    monkeypatch.setattr(api, "comments", lambda number: [summary()])
    monkeypatch.setattr(api, "threads", lambda number: [])
    monkeypatch.setattr(api, "reviews", lambda number: [])
    monkeypatch.setattr(api, "statuses", lambda sha: [])
    with pytest.raises(gate.GateError, match="head changed"):
        gate.wait_for_review(event_environment, timeout=0)


def test_api_error_withholds_remote_output_and_tokens(monkeypatch):
    def run(command, **kwargs):
        assert "private-token" not in str(command)
        assert kwargs["env"]["GH_TOKEN"] == "private-token"
        assert kwargs["capture_output"] is True
        raise subprocess.CalledProcessError(
            1, command, stderr="private-token remote body"
        )

    monkeypatch.setattr(gate.subprocess, "run", run)
    with pytest.raises(gate.GateError) as error:
        gate.GitHub({"GH_TOKEN": "private-token"}).checks(HEAD)
    assert "private-token" not in str(error.value)


def test_workflow_build_and_preflight_require_successful_review():
    import yaml

    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text()
    )
    jobs = workflow["jobs"]
    assert jobs["review-gate"]["needs"] == "tests"
    assert set(jobs["container-build"]["needs"]) == {"tests", "review-gate"}
    assert set(jobs["production-preflight"]["needs"]) == {
        "tests",
        "review-gate",
        "container-build",
    }
    assert "if" not in jobs["container-build"]
    assert "always()" not in jobs["production-preflight"]["if"]
    assert "environment" not in jobs["review-gate"]
    assert all(value == "read" for value in jobs["review-gate"]["permissions"].values())
    revision = "${{ github.event.pull_request.head.sha || github.sha }}"
    for name in ("tests", "review-gate", "container-build"):
        assert jobs[name]["steps"][0]["with"]["ref"] == revision
        assert jobs[name]["steps"][0]["with"]["persist-credentials"] is False
    assert jobs["container-build"]["steps"][1]["env"]["APP_REVISION"] == revision
    assert (
        jobs["production-preflight"]["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    )
    release = jobs["release"]
    assert set(release["needs"]) == {
        "tests",
        "review-gate",
        "container-build",
        "production-preflight",
    }
    assert release["if"] == jobs["production-preflight"]["if"]
    assert release["environment"] == "production-release"
    assert release["concurrency"]["cancel-in-progress"] is False
    assert release["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    assert release["steps"][0]["with"]["persist-credentials"] is False
