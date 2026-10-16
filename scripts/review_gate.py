"""Check the PR's review policy, feedback, and CI before an image build."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

REPOSITORY = "AkaiS/california-political-knowledge-map"
GREPTILE_APP_ID = 867647
GREPTILE_BOT_ID = 165735046
SKIP_GREPTILE_MARKER = "[skip greptile]"
ACTIONS_APP_ID = 15368
DOWNSTREAM_CHECKS = {
    "review-gate",
    "image-inputs",
    "container-build",
    "production-preflight",
    "release",
}
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class GateError(Exception):
    """A rejection safe to print without remote response bodies or tokens."""


class PendingReview(Exception):
    """Required evidence has not arrived yet."""


def valid_sha(value: Any) -> str:
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise GateError("GitHub returned an invalid commit identity.")
    return value


def timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (AttributeError, TypeError, ValueError):
        raise GateError("Required review timestamps are missing or invalid.") from None


class GitHub:
    def __init__(self, environment: Mapping[str, str]):
        self.environment = dict(environment)
        self.runs: dict[int, dict] = {}

    def api(self, endpoint: str, *, paginate: bool = False, fields=()) -> Any:
        command = ["gh", "api", endpoint]
        if paginate:
            command.extend(["--paginate", "--slurp"])
        for name, value in fields:
            command.extend(["-F", f"{name}={value}"])
        try:
            result = subprocess.run(
                command,
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=45,
                check=True,
            )
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise GateError(
                "Cannot read required GitHub evidence; output withheld."
            ) from None

    def pages(self, endpoint: str, key: str | None = None) -> list[dict]:
        pages = self.api(endpoint, paginate=True)
        return [item for page in pages for item in (page[key] if key else page)]

    def pull_request(self, number: int) -> dict:
        return self.api(f"repos/{REPOSITORY}/pulls/{number}")

    def checks(self, sha: str) -> list[dict]:
        checks = self.pages(
            f"repos/{REPOSITORY}/commits/{sha}/check-runs?filter=latest&per_page=100",
            "check_runs",
        )
        for check in checks:
            if is_app(check, ACTIONS_APP_ID, "github-actions") and check.get(
                "name"
            ) in DOWNSTREAM_CHECKS | {"tests"}:
                match = re.fullmatch(
                    r"https://github\.com/"
                    + re.escape(REPOSITORY)
                    + r"/actions/runs/([0-9]+)/job/[0-9]+",
                    check.get("details_url", ""),
                    flags=re.IGNORECASE,
                )
                if not match:
                    raise GateError("Cannot establish CI check workflow ownership.")
                run_id = int(match[1])
                if run_id not in self.runs:
                    self.runs[run_id] = self.api(
                        f"repos/{REPOSITORY}/actions/runs/{run_id}"
                    )
                run = self.runs[run_id]
                if (
                    run.get("head_sha") != sha
                    or run.get("repository", {}).get("full_name", "").lower()
                    != REPOSITORY.lower()
                ):
                    raise GateError(
                        "The CI workflow run does not belong to the candidate commit."
                    )
                check["ci_workflow"] = run.get("path") == ".github/workflows/ci.yml"
        return checks

    def statuses(self, sha: str) -> list[dict]:
        pages = self.api(
            f"repos/{REPOSITORY}/commits/{sha}/status?per_page=100", paginate=True
        )
        if any(page.get("sha") != sha for page in pages):
            raise GateError("Commit statuses do not belong to the candidate commit.")
        return [dict(status, sha=sha) for page in pages for status in page["statuses"]]

    def comments(self, number: int) -> list[dict]:
        return self.pages(f"repos/{REPOSITORY}/issues/{number}/comments?per_page=100")

    def reviews(self, number: int) -> list[dict]:
        return self.pages(f"repos/{REPOSITORY}/pulls/{number}/reviews?per_page=100")

    def threads(self, number: int) -> list[dict]:
        query = """
        query($number: Int!, $cursor: String) {
          repository(owner: "AkaiS", name: "california-political-knowledge-map") {
            pullRequest(number: $number) {
              reviewThreads(first: 100, after: $cursor) {
                nodes { isResolved isOutdated }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
        """
        cursor = None
        threads = []
        while True:
            fields = [("query", query), ("number", number)]
            if cursor is not None:
                fields.append(("cursor", cursor))
            response = self.api("graphql", fields=fields)
            if response.get("errors"):
                raise GateError("Cannot read all review threads.")
            page = response["data"]["repository"]["pullRequest"]["reviewThreads"]
            threads.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                return threads
            next_cursor = page["pageInfo"]["endCursor"]
            if not next_cursor or next_cursor == cursor:
                raise GateError("Review thread pagination did not advance.")
            cursor = next_cursor


def is_app(check: dict, app_id: int, slug: str) -> bool:
    return check.get("app", {}).get("id") == app_id and check["app"].get("slug") == slug


def other_checks_green(
    checks: list[dict], statuses: list[dict], sha: str, *, tested: bool = True
) -> None:
    # A merge commit reuses the tests of its identical reviewed tree, so CI
    # skips them there; every other check on it must still succeed.
    tests = not tested
    pending = False
    for check in checks:
        if check.get("head_sha") != sha:
            raise GateError("A check does not belong to the candidate commit.")
        actions = (
            is_app(check, ACTIONS_APP_ID, "github-actions")
            and check.get("ci_workflow") is True
        )
        if actions and check.get("name") in DOWNSTREAM_CHECKS:
            continue
        if actions and not tested and check.get("name") == "tests":
            continue
        if (
            is_app(check, GREPTILE_APP_ID, "greptile-apps")
            and check.get("name") == "Greptile Review"
        ):
            continue
        if actions and check.get("name") == "tests":
            tests = True
        if check.get("status") != "completed":
            pending = True
        elif check.get("conclusion") != "success":
            raise GateError("Another check did not succeed.")
    for status in statuses:
        if status.get("sha") != sha:
            raise GateError("A commit status does not belong to the candidate commit.")
        if status.get("state") == "pending":
            pending = True
        elif status.get("state") != "success":
            raise GateError("Another commit status did not succeed.")
    if not tests or pending:
        raise PendingReview("Waiting for other checks to complete successfully.")


def review_green(
    checks: list[dict],
    comments: list[dict],
    threads: list[dict],
    reviews: list[dict],
    sha: str,
) -> None:
    trusted_checks = [
        check
        for check in checks
        if is_app(check, GREPTILE_APP_ID, "greptile-apps")
        and check.get("name") == "Greptile Review"
        and check.get("head_sha") == sha
    ]
    if not trusted_checks:
        raise PendingReview("Waiting for the trusted Greptile check.")
    check = max(
        trusted_checks, key=lambda item: (timestamp(item["started_at"]), item["id"])
    )
    if check.get("status") != "completed":
        raise PendingReview("Waiting for Greptile to finish the current review.")
    if check.get("conclusion") != "success":
        raise GateError("The trusted Greptile check did not succeed.")
    timestamp(check.get("completed_at"))
    summaries = [
        comment
        for comment in comments
        if comment.get("user", {}).get("id") == GREPTILE_BOT_ID
        and comment["user"].get("login") == "greptile-apps[bot]"
        and "<!-- greptile_summary -->" in comment.get("body", "")
    ]
    if not summaries:
        raise PendingReview("Waiting for the trusted Greptile summary.")
    summary = max(
        summaries, key=lambda item: (timestamp(item["updated_at"]), item["id"])
    )
    body = summary["body"]
    reviewed = re.findall(
        r"Last reviewed commit:\s*\[[^\]\n]*\]\(https://github\.com/"
        + re.escape(REPOSITORY)
        + r"/commit/([0-9a-f]{40})\)",
        body,
        flags=re.IGNORECASE,
    )
    if reviewed != [sha] or timestamp(summary["updated_at"]) < timestamp(
        check["started_at"]
    ):
        raise PendingReview(
            "Waiting for a summary from this review of the current commit."
        )
    scores = re.findall(r"<!-- greptile_confidence_score:([0-5]) -->", body)
    if len(scores) != 1:
        raise PendingReview("Waiting for an unambiguous Greptile confidence score.")
    if scores != ["5"]:
        raise GateError("Greptile confidence is below the required 5/5.")
    feedback_green(threads, reviews)


def feedback_green(threads: list[dict], reviews: list[dict]) -> None:
    if any(thread.get("isResolved") is not True for thread in threads):
        raise GateError(
            "Review feedback remains unresolved, including outdated threads."
        )
    latest_reviews = {}
    for review in reviews:
        if review.get("state") != "COMMENTED":
            reviewer = review["user"]["id"]
            if (
                reviewer not in latest_reviews
                or review["id"] > latest_reviews[reviewer]["id"]
            ):
                latest_reviews[reviewer] = review
    if any(
        review.get("state") == "CHANGES_REQUESTED" for review in latest_reviews.values()
    ):
        raise GateError("A reviewer still requests changes.")


def greptile_skipped(pr: dict) -> bool:
    return any(
        SKIP_GREPTILE_MARKER in (pr.get(field) or "") for field in ("title", "body")
    )


def current_pr(
    api: GitHub, number: int, sha: str, *, merged_sha: str | None = None
) -> dict:
    pr = api.pull_request(number)
    if (
        pr["base"]["repo"]["full_name"].lower() != REPOSITORY.lower()
        or pr["base"]["ref"] != "main"
    ):
        raise GateError("The pull request must target this repository's main branch.")
    if valid_sha(pr["head"]["sha"]) != sha:
        raise GateError("The pull request head changed; run checks for the new commit.")
    if merged_sha is None and pr.get("state") != "open":
        raise GateError("The pull request is no longer open.")
    if merged_sha is not None and (
        not pr.get("merged") or pr.get("merge_commit_sha") != merged_sha
    ):
        raise GateError(
            "The main commit is not the verified pull request's merge commit."
        )
    return pr


def candidate(
    environment: Mapping[str, str], api: GitHub
) -> tuple[int, str, str | None]:
    if environment.get("GITHUB_REPOSITORY", "").lower() != REPOSITORY.lower():
        raise GateError("The review gate is restricted to its configured repository.")
    event = json.loads(Path(environment["GITHUB_EVENT_PATH"]).read_text())
    if environment.get("GITHUB_EVENT_NAME") == "pull_request":
        return (
            int(event["number"]),
            valid_sha(event["pull_request"]["head"]["sha"]),
            None,
        )
    if (
        environment.get("GITHUB_EVENT_NAME") != "push"
        or environment.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise GateError("The review gate requires a pull request or push to main.")
    merged_sha = valid_sha(environment.get("GITHUB_SHA"))
    associated = api.pages(
        f"repos/{REPOSITORY}/commits/{merged_sha}/pulls?per_page=100"
    )
    merged = [
        pr
        for pr in associated
        if pr.get("merged_at") and pr.get("merge_commit_sha") == merged_sha
    ]
    if len(merged) != 1:
        raise GateError("Main requires one merged pull request for this exact commit.")
    pr = merged[0]
    head = valid_sha(pr["head"]["sha"])
    merge_tree = api.api(f"repos/{REPOSITORY}/commits/{merged_sha}")["commit"]["tree"][
        "sha"
    ]
    head_tree = api.api(f"repos/{REPOSITORY}/commits/{head}")["commit"]["tree"]["sha"]
    if valid_sha(merge_tree) != valid_sha(head_tree):
        raise GateError(
            "The main commit's tree differs from the reviewed pull request head."
        )
    return int(pr["number"]), head, merged_sha


def wait_for_review(
    environment: Mapping[str, str], *, timeout: int = 1800, interval: int = 30
) -> str:
    api = GitHub(environment)
    number, sha, merged_sha = candidate(environment, api)
    deadline = time.monotonic() + timeout
    while True:
        pr = current_pr(api, number, sha, merged_sha=merged_sha)
        skip_greptile = greptile_skipped(pr)
        checks = api.checks(sha)
        comments = [] if skip_greptile else api.comments(number)
        threads = api.threads(number)
        reviews = api.reviews(number)
        statuses = api.statuses(sha)
        pr = current_pr(api, number, sha, merged_sha=merged_sha)
        try:
            if greptile_skipped(pr) != skip_greptile:
                raise PendingReview("The PR review policy changed; checking again.")
            if skip_greptile:
                feedback_green(threads, reviews)
            else:
                review_green(checks, comments, threads, reviews, sha)
            other_checks_green(checks, statuses, sha)
            if merged_sha is not None:
                other_checks_green(
                    api.checks(merged_sha),
                    api.statuses(merged_sha),
                    merged_sha,
                    tested=False,
                )
            pr = current_pr(api, number, sha, merged_sha=merged_sha)
            if greptile_skipped(pr) != skip_greptile:
                raise PendingReview("The PR review policy changed; checking again.")
            if skip_greptile:
                print(
                    f"Greptile requirement skipped by PR marker {SKIP_GREPTILE_MARKER}.",
                    flush=True,
                )
            return sha
        except PendingReview as pending:
            if time.monotonic() >= deadline:
                raise GateError(
                    "Timed out waiting for current review evidence and green checks."
                ) from None
            print(str(pending), flush=True)
            time.sleep(min(interval, max(0, deadline - time.monotonic())))


def main() -> int:
    try:
        sha = wait_for_review(os.environ)
    except GateError as error:
        print(f"Review gate rejected: {error}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError):
        print(
            "Review gate rejected: Required GitHub evidence is malformed.",
            file=sys.stderr,
        )
        return 1
    print(f"Review gate passed for commit {sha}: checks green and feedback resolved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
