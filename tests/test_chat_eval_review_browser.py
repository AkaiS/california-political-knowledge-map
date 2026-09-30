"""Opt-in browser workflow checks: RUN_REVIEW_BROWSER_TESTS=1 uv run pytest this-file."""

import json
import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from test_chat_eval_review import review_server

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REVIEW_BROWSER_TESTS") != "1",
    reason="Opt in after installing Chromium with uv run playwright install chromium",
)


@pytest.fixture
def reviewer(tmp_path, monkeypatch):
    monkeypatch.setattr(review_server, "REPOSITORY", tmp_path)
    (tmp_path / "reference.json").write_text(
        json.dumps(
            {
                "interpretation": "Stored retrieval, not a Gold Set.",
                "cases": [
                    {
                        "id": "source-a",
                        "rows": [
                            {
                                "title": "Reference article",
                                "url": "https://example.org/reference",
                            }
                        ],
                    },
                    {"id": "other", "rows": []},
                ],
            }
        )
    )
    markdown = """A **useful** answer with [a citation](https://example.org/article).

| Measure | Status |
| --- | --- |
| AB 1 | Recorded |

- First item
- Second item

```python
print("hello")
```

<script>window.pwned = true</script>
<img src="https://tracker.invalid/pixel" onerror="window.pwned=true">
![tracking](https://tracker.invalid/markdown)
[bad](javascript:alert(1))
"""
    messages = [
        {
            "kind": "request",
            "parts": [
                {
                    "part_kind": "user-prompt",
                    "content": "Please **review** this question.",
                }
            ],
        },
        {
            "kind": "response",
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "retrieve",
                    "tool_call_id": "call-1",
                    "args": '{"question":"**Housing**"}',
                }
            ],
        },
        {
            "kind": "request",
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "retrieve",
                    "tool_call_id": "call-1",
                    "content": {
                        "rows": [
                            {
                                "title": "Retrieved article",
                                "url": "https://example.org/tool",
                            }
                        ]
                    },
                }
            ],
        },
        {"kind": "response", "parts": [{"part_kind": "text", "content": markdown}]},
    ]
    report = {"task": "chat", "report": {"cases": []}}
    for name in ("case-a", "case-b", "case-c"):
        report["report"]["cases"].append(
            {
                "name": name,
                "inputs": {"question": f"Question {name}"},
                "metadata": {
                    "cohort": "populated_graph",
                    "scope_note": "Review **recorded** reporting.",
                    "grounding": "evidence-grounded",
                    "source_case_id": "source-a",
                    "reference_artifact": "reference.json",
                },
                "attributes": {
                    "stage_observations": [
                        {
                            "name": "structural retrieval",
                            "attributes": {
                                "validated_query": "MATCH (a:Article) RETURN a",
                                "bound_values": {"limit": 3},
                            },
                        }
                    ]
                },
                "expected_output": {"answer": "Expected **result**"}
                if name == "case-b"
                else None,
                "output": {
                    "rendered_text": markdown,
                    "messages": [
                        {
                            "component": "chat",
                            "request_index": i,
                            "status": "succeeded",
                            "run_id": "run-1",
                            "request_parameters": {
                                "instruction_parts": [
                                    {"content": "System **instructions**"}
                                ]
                            },
                            "messages": messages,
                        }
                        for i in (0, 1)
                    ],
                    "answer": {
                        "evidence": {
                            "sources": [
                                {
                                    "citation": {
                                        "title": "Stored article",
                                        "url": "https://example.org/source",
                                    },
                                    "passages": [
                                        {
                                            "text": "## Literal heading\n**Stored article wording**",
                                            "candidate": {},
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                },
            }
        )
    (tmp_path / "run.json").write_text(json.dumps(report))
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        review_server.make_handler(
            tmp_path,
            (scripts / "chat_eval_runs.html").read_bytes(),
            (scripts / "chat_eval_review.html").read_bytes(),
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/runs/run", tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def browser_page(reviewer):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(reviewer[0])
        playwright.expect(page.locator("#position")).to_have_text("Case 1 of 3")
        yield page, playwright.expect
        assert errors == []
        browser.close()


def saved(page, expect, directory, name, verdict, note=""):
    expect(page.locator("#save-status")).to_have_text("Saved to review file")
    reviews = json.loads((directory / "run.reviews.json").read_text())
    assert reviews[name] == {"verdict": verdict, "note": note}


def blur(page):
    page.locator("#question").click()


def test_annotation_workflow_and_shortcuts(browser_page, reviewer):
    page, expect = browser_page
    directory = reviewer[1]
    page.get_by_role("button", name="Pass", exact=True).click()
    saved(page, expect, directory, "case-a", "pass")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator("#position")).to_have_text("Case 2 of 3")
    page.get_by_role("button", name="Fail", exact=True).click()
    page.locator("#note").fill("Citation does not support the claim.")
    page.keyboard.press("Control+s")
    saved(
        page,
        expect,
        directory,
        "case-b",
        "fail",
        "Citation does not support the claim.",
    )
    assert page.locator("#note").evaluate("el => el === document.activeElement")
    # Annotation shortcuts must not interpret text in the note as verdicts.
    page.locator("#note").fill("")
    page.keyboard.type("12du")
    page.keyboard.press("ArrowLeft")
    expect(page.locator("#position")).to_have_text("Case 2 of 3")
    page.keyboard.press("Meta+s")
    saved(page, expect, directory, "case-b", "fail", "12du")
    page.keyboard.press("Control+Enter")
    expect(page.locator("#position")).to_have_text("Case 3 of 3")
    page.get_by_role("button", name="Defer", exact=True).click()
    saved(page, expect, directory, "case-c", "defer")
    page.get_by_role("button", name="Previous", exact=True).click()
    expect(page.locator("#position")).to_have_text("Case 2 of 3")
    blur(page)
    page.keyboard.press("ArrowLeft")
    expect(page.locator("#position")).to_have_text("Case 1 of 3")
    page.keyboard.press("2")
    saved(page, expect, directory, "case-a", "fail")
    page.keyboard.press("u")
    saved(page, expect, directory, "case-a", "pass")
    page.keyboard.press("d")
    saved(page, expect, directory, "case-a", "defer")
    page.keyboard.press("1")
    saved(page, expect, directory, "case-a", "pass")
    page.locator("#note").fill("New observation")
    page.keyboard.press("Control+s")
    saved(page, expect, directory, "case-a", "pass", "New observation")
    blur(page)
    page.keyboard.press("u")
    saved(page, expect, directory, "case-a", "pass", "")
    page.keyboard.press("ArrowRight")
    expect(page.locator("#position")).to_have_text("Case 2 of 3")
    expect(page.locator("#note")).to_have_value("12du")
    expect(page.locator("#progress")).to_have_text("3 reviewed · 0 remaining")
    page.reload()
    expect(page.locator('[data-verdict="pass"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator("#note")).to_have_value("12du")
    page.locator("#reference-panel > summary").click()
    expect(page.locator("#reference")).to_contain_text("Expected result")


def test_native_rendering_and_trace_access(browser_page):
    page, expect = browser_page
    expect(page.locator("#answer strong")).to_have_text("useful")
    expect(page.locator("#answer table")).to_be_visible()
    expect(page.locator("#answer ul li")).to_have_count(2)
    expect(page.locator("#answer .code-highlight span").first).to_be_visible()
    assert (
        page.locator(
            "#answer img, #answer script, #answer a[href^='javascript:']"
        ).count()
        == 0
    )
    assert page.evaluate("window.pwned") is None
    expect(page.locator(".passage")).to_have_text(
        "## Literal heading\n**Stored article wording**"
    )
    page.locator("#reference-panel > summary").click()
    expect(page.locator("#reference strong").first).to_have_text("recorded")
    expect(page.locator("#reference")).to_contain_text("Reference article")
    expect(page.locator("#reference")).not_to_contain_text('"id": "other"')
    for panel in page.locator("#raw > details").all()[:2]:
        panel.locator(":scope > summary").click()
        expect(panel.locator(".message.system")).not_to_have_attribute("open", "")
        panel.locator(".message.system > summary").click()
        expect(panel.locator(".message.system strong")).to_have_text("instructions")
        expect(panel.locator(".tool-group")).to_have_count(1)
        panel.locator(".tool-group > summary").click()
        expect(panel.locator(".tool-group .message")).to_have_count(2)
        for summary in panel.locator(".tool-group .message > details > summary").all():
            if summary.inner_text() in ("Arguments", "Content"):
                summary.click()
        expect(
            panel.locator(".tool-group strong").filter(has_text="Housing")
        ).to_have_count(1)
        expect(panel.locator(".tool-group table")).to_be_visible()
        panel.locator(":scope > summary").click()
    page.locator("#stages").get_by_text(
        "Recorded decisions and IDs", exact=True
    ).click()
    expect(page.locator("#stages .code-highlight")).to_be_visible()
    expect(page.locator("#stages")).to_contain_text("bound values")
    screenshots = Path(__file__).resolve().parents[1] / ".scratch/review-interface"
    screenshots.mkdir(parents=True, exist_ok=True)
    page.locator(".trace-pane").evaluate("el => el.scrollTop = 0")
    page.locator("main").evaluate("el => el.scrollTop = 0")
    page.screenshot(path=str(screenshots / "fixture-desktop.png"))
    page.set_viewport_size({"width": 820, "height": 900})
    page.screenshot(path=str(screenshots / "fixture-tablet.png"))
    for selector in ("#note", "#retry-save", ".review-box .meta"):
        bounds = page.locator(selector).bounding_box()
        assert bounds["y"] + bounds["height"] <= 900
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(screenshots / "fixture-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    expect(page.locator("#note")).to_be_visible()
    expect(page.get_by_role("button", name="Pass", exact=True)).to_be_visible()


def test_failed_save_recovery_and_immediate_reload(browser_page, reviewer):
    page, expect = browser_page
    pattern = "**/api/runs/run/reviews"

    def reject_writes(route):
        if route.request.method == "POST":
            route.fulfill(status=503, body="Unavailable")
        else:
            route.continue_()

    page.route(pattern, reject_writes)
    page.locator("#note").fill("Recover this edit")
    # Reload before the note debounce can post; draft was stored synchronously.
    page.reload()
    expect(page.locator("#note")).to_have_value("Recover this edit")
    expect(page.locator("#save-status")).to_contain_text("Save failed: 503")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator("#position")).to_have_text("Case 1 of 3")
    expect(page.locator("#save-status")).to_contain_text("Edits kept in this browser")
    page.unroute(pattern, reject_writes)
    page.get_by_role("button", name="Save / retry", exact=True).click()
    saved(page, expect, reviewer[1], "case-a", None, "Recover this edit")
    page.reload()
    expect(page.locator("#note")).to_have_value("Recover this edit")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator("#position")).to_have_text("Case 2 of 3")


def test_navigation_waits_for_edits_made_during_a_save(browser_page, reviewer):
    page, expect = browser_page
    delayed = []

    def hold_first_write(route):
        if route.request.method == "POST" and not delayed:
            delayed.append(route)
        else:
            route.continue_()

    page.route("**/api/runs/run/reviews", hold_first_write)
    page.locator("#note").fill("First version")
    page.keyboard.press("Control+s")
    expect(page.locator("#save-status")).to_have_text("Saving to review file…")
    page.locator("#note").fill("Latest version")
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator("#position")).to_have_text("Case 1 of 3")
    delayed[0].continue_()
    expect(page.locator("#position")).to_have_text("Case 2 of 3")
    assert (
        json.loads((reviewer[1] / "run.reviews.json").read_text())["case-a"]["note"]
        == "Latest version"
    )


@pytest.mark.parametrize("replacement", ["directory", "contents"])
def test_drafts_do_not_overwrite_another_report(
    browser_page, reviewer, monkeypatch, replacement
):
    page, expect = browser_page
    directory = reviewer[1]
    pattern = "**/api/runs/run/reviews"

    def reject_writes(route):
        if route.request.method == "POST":
            route.fulfill(status=503, body="Unavailable")
        else:
            route.continue_()

    page.route(pattern, reject_writes)
    page.locator("#note").fill("Draft for the original report")
    expect(page.locator("#save-status")).to_contain_text("Save failed: 503")
    content = (directory / "run.json").read_text()
    if replacement == "directory":
        destination = directory / "different-reports"
        destination.mkdir()
        (destination / "run.json").write_text(content)
        original_run_path = review_server.run_path
        monkeypatch.setattr(
            review_server,
            "run_path",
            lambda _reports_dir, run_id: original_run_path(destination, run_id),
        )
    else:
        destination = directory
        report = json.loads(content)
        report["report"]["cases"][0]["output"]["rendered_text"] = "Replacement answer"
        (destination / "run.json").write_text(json.dumps(report))
    existing = {"case-a": {"verdict": "pass", "note": "Review of the new report"}}
    (destination / "run.reviews.json").write_text(json.dumps(existing))
    page.unroute(pattern, reject_writes)
    page.get_by_role("button", name="Save / retry", exact=True).click()
    expect(page.locator("#save-status")).to_contain_text("report changed")
    assert json.loads((destination / "run.reviews.json").read_text()) == existing

    page.reload()

    expect(page.locator("#note")).to_have_value("Review of the new report")
    page.get_by_role("button", name="Fail", exact=True).click()
    saved(page, expect, destination, "case-a", "fail", "Review of the new report")
    assert page.evaluate(
        "Object.values(localStorage).some(value => value.includes('Draft for the original report'))"
    )
    if replacement == "directory":
        monkeypatch.setattr(review_server, "run_path", original_run_path)
        page.reload()
        expect(page.locator("#note")).to_have_value("Draft for the original report")
        saved(page, expect, directory, "case-a", None, "Draft for the original report")


def test_malformed_reference_does_not_block_annotation(browser_page, reviewer):
    page, expect = browser_page
    (reviewer[1] / "reference.json").write_text(json.dumps({"cases": [None]}))

    page.reload()

    expect(page.locator("#position")).to_have_text("Case 1 of 3")
    page.locator("#reference-panel > summary").click()
    expect(page.locator("#reference .empty")).to_contain_text("Reference")
    page.get_by_role("button", name="Pass", exact=True).click()
    saved(page, expect, reviewer[1], "case-a", "pass")


@pytest.mark.parametrize("width,height", [(820, 480), (960, 600)])
def test_short_tablet_can_scroll_to_annotation_controls(browser_page, width, height):
    page, expect = browser_page
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#question").evaluate(
        """el => { el.textContent = 'Which other organizations are recorded as lobbying for AB 186 alongside Walt Disney in the 2025–2026 session?'; }"""
    )
    page.mouse.move(width - 10, height - 10)
    page.mouse.wheel(0, 10000)
    for selector in ("#retry-save", ".review-box .meta", "#note"):
        expect(page.locator(selector)).to_be_in_viewport(ratio=1)
    screenshots = Path(__file__).resolve().parents[1] / ".scratch/review-interface"
    screenshots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshots / f"review-fix-tablet-{width}-{height}.png"))
    page.mouse.wheel(0, -10000)
    expect(page.locator("#position")).to_be_in_viewport(ratio=1)


@pytest.mark.parametrize("control", ["arrows", "buttons"])
def test_rapid_navigation_retains_each_action(browser_page, control):
    page, expect = browser_page
    delayed = []

    def hold_first_write(route):
        if route.request.method == "POST" and not delayed:
            delayed.append(route)
        else:
            route.continue_()

    page.route("**/api/runs/run/reviews", hold_first_write)
    page.locator("#note").fill("Pending note")
    page.keyboard.press("Control+s")
    expect(page.locator("#save-status")).to_have_text("Saving to review file…")
    blur(page)
    for _ in range(2):
        if control == "arrows":
            page.keyboard.press("ArrowRight")
        else:
            page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator("#position")).to_have_text("Case 1 of 3")
    delayed[0].continue_()

    expect(page.locator("#position")).to_have_text("Case 3 of 3")
