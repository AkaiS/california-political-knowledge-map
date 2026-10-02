# Review Chat Session answers

The first chat Evaluation Data Set is an **unlabeled training set**. It runs 25
concrete questions from the populated-graph query-construction targets and 11
Declined or Deferred controls from the broader [Target Question Set](../../work/initiatives/useful-graph-retrieval/question-set.md). The concrete cases have retrievable subjects and executed reference queries; some broader targets still depend on data that has not been ingested or use placeholders. Those broader targets remain the source for future cases. No case has an expected answer or an automatic answer-quality score.

The driver uses the production Chat Session coordination and automatically
approves its first Query Rewrite Proposal. The reviewer must judge whether that
proposal preserved the original question. It does not simulate a person
correcting or rejecting the proposal.

## Run and open a report

Start the project's configured Neo4j, embedding, Chat Agent, and Query Rewriter
dependencies. Then run:

```bash
uv run ca-map eval run chat --deployment local
```

The command writes a JSON report under `evals/reports/chat/`. Use
`--deployment openrouter` for a configured OpenRouter Chat Agent and structural
models. The Query Rewriter uses its independently configured deployment. Use
repeatable `--case <case-id>` options to run a review subset; the selected IDs
are recorded in the report. The report records the Data Set,
commit and dirty state, Model Deployment, each case's output and metadata, and
the run and case trace IDs. A case can finish with a stage failure; that failure
is part of the review material, not a pass/fail answer grade.

Start the local reviewer:

```bash
uv run python scripts/review_chat_eval.py
```

Then visit `http://127.0.0.1:8765/`. The landing page lists recent chat
evaluation runs from `evals/reports/chat/`, newest first, with the number of
cases reviewed and Pass, Fail, and Defer counts. Select a run to open its case
reviewer. The list discovers new reports while the server is running and reads
saved review files when opened, so returning to the list shows current progress.
The reviewer displays one case at a time.
Use the list or arrow keys to move between cases, search by question or ID, and
filter by review verdict. It saves each **Pass**, **Fail**, or **Defer** verdict
and free-text critique to `<report-file>.reviews.json`. `1`, `2`, `D`, and `U`
set Pass, Fail, Defer, and undo the last annotation action. Undo restores the
previous verdict or note, including an action on another case, during the current
page session. The separate Clear verdict button keeps the note. Cmd/Ctrl+S saves
while the note field is focused, and Cmd/Ctrl+Enter saves and advances. Plain
annotation and arrow shortcuts leave text entry alone.
Rapid arrow, button, or save-and-advance navigation applies each action in order
after saving. Undo selects the case whose annotation it restores and cancels
navigation requested before that Undo, including navigation waiting for a save.

The note saves as you type. Each edit also creates a synchronous browser-local
draft, so reloading or closing before the file save finishes preserves the edit.
Reopening the same report at the same server address recovers and retries those
drafts. Recovery requires the same resolved file path and file contents, so
switching report directories or replacing a report cannot apply another report's
drafts. Previous drafts remain stored for their original report version. Older
drafts without a report identity are retained but are not recovered automatically.
The server also rejects saves from an open page after its report changes; reload
to review the current report. Saved review files remain the durable review
artifact. If a file save fails, the interface shows the affected case IDs,
retains browser drafts, and keeps the selected case until Save / retry succeeds.
A browser storage failure
warns you to keep the page open until the file save succeeds.

Use
`--reports-dir <path>` to browse a different report directory and `--port
<port>` to change the local port. The reviewer binds to loopback.

## Read one case

For component-level retrieval scores over the existing 25 Cypher cases, see
[Evaluate retrieval evidence](retrieval.md). That guide also defines separate
faithfulness and relevance observations for the critique below.

Read the case from the voter's question outward:

1. **Prepared answer.** This evaluation does not verify browser delivery. Did the response direct the reader to useful sources, state coverage limits, and avoid claims its citations do not support? A Declined or Deferred control may have no retrieval answer.
2. **Question preparation.** Did the Query Rewrite preserve the named people, measures, relationship, time scope, and requested result? Was the policy and coverage assessment appropriate?
3. **Retrieval branches.** Check the full-text, dense, and structural outcomes. The report lists only the top full-text candidates up to the number returned by dense retrieval. It records the total full-text count and aggregate scores and rank range for candidates left off that list. Expand retained candidates to see ranks and routes. Selected Grounding Evidence keeps its own candidate contributions even when a supporting passage came from below the list cutoff. A failed branch can coexist with a prepared answer from other branches.
4. **Selected Grounding Evidence.** Read the stored passages under each Source Article citation. Check whether the specific passage supports the answer's wording, and whether relevant material was dropped by Evidence Assembly's context limit.
5. **Application stages and model messages.** Expand stage observations for the rewrite, assessment, branch work, fusion, Evidence Assembly, and guidance. Recorded decisions have structured views, with syntax highlighting for validated structural queries and a separate raw record. Model messages show the requests and responses captured for this Evaluation Case, including retries or failed requests where available. System instructions have their own collapsed section. Tool calls and results share a group by call ID within each captured request, so repeated message history stays attached to its request.
6. **Case reference and scope.** Open the reference panel for the authored scope note and grounding type. Repository-relative reference artifacts show their contents; a reference containing case records selects the authored source case ID. The current reference query results describe the stored graph and are not a Gold Set. An expected output appears only when the report actually supplies one.

Mark the **whole case** Pass, Fail, or Defer. Write what happened and where the
failure seems to arise. For example: "The structural branch retrieved the right
bill, but the selected passage only mentions a proposal and the answer calls it
enacted." Keep the note descriptive. Build recurring failure categories from
the reviewed cases before adding answer evaluators. This follows the
[case-level experiment notes](../../work/initiatives/model-evaluation/research/alignment-is-recoverable-after-the-fact.md): record observed facts separately from hypotheses and state what a small sample cannot show.

## Follow a native Logfire trace

The reviewer links to the case's native Logfire trace and, when the project URL
is configured, to its Chat Session ID search. The local report is the place to
read answer text, model messages, retrieved candidates, evidence, and your
review together. The native trace is useful for timing, parent-child spans,
concurrent retrieval, model attempts, token usage, and operational failures.
Logfire may scrub content and its observations have the project's retention
limit. The report's local message capture supplies content for this evaluation
without changing the application's Logfire content policy.

In live browser chat, preparation, correction, and approval can be separate
native traces joined by one Chat Session ID. Open the session link or use the
queries in [Inspect Chat Session trails](../chat-session-trails.md) when a
single trace does not show the full interaction. A prepared Retrieval Answer
means the application rendered it before emission; it does not prove the
browser displayed it.

The JSON report and review file are local artifacts. Review their captured
question, passage, and model-message content before sharing them. Commit a
report and its associated review when it becomes evidence for a later change,
so a reader can compare cases and critiques against the exact run.

The local reviewer also applies this display limit when opening an older report
that stored every full-text candidate. It leaves the committed report and its
existing review notes unchanged.

## Verify the reviewer

Prepared answers and model text render Markdown, tables, links, and highlighted
fenced code through markdown-it-py and Pygments on the local server. The renderer
strips model HTML and images, and permits only HTTP/HTTPS links. Stored Article
Chunk passages remain literal source text. Structured message arguments and
results have readable fields and tables, with raw JSON available separately.
The reviewer does not require a CDN or a network connection to render content.

[`chat_eval_review_editing.mjs`](../../scripts/chat_eval_review_editing.mjs)
owns review values, selected Evaluation Case, local draft recovery, the
350-millisecond note debounce, serialized saves, save-before-navigation, and
Undo. The page calls its public commands and renders copied state. The page
owns filter matching, keyboard handling, focus, and trace rendering, and supplies
the module's persistence, browser storage, and scheduling dependencies.

Use Node 22 and prepare the Python environment from the repository root:

```bash
uv python install
uv sync --locked --dev
```

Run the deterministic editing checks with Node's built-in test runner:

```bash
uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs
```

These tests use the same editing interface as the page. Controlled saves,
scheduling, and draft storage cover recovery, failures, stale completions,
navigation ordering, and Undo without a browser or npm packages. Normal
pull-request CI installs Node 22 explicitly and requires these checks to pass.

Run the focused server, rendering, module-delivery, and Evaluation Run checks:

```bash
uv run --no-sync pytest -q tests/test_chat_eval_review.py tests/test_chat_eval_task.py
```

Run the full deterministic Python suite, also required by normal CI:

```bash
uv run --no-sync pytest -q tests
```

These deterministic checks require no browser, model service, or database
service. Keep browser and live-service opt-in variables unset when running the
full suite. HTTP tests start temporary loopback servers, so a restricted sandbox
must allow local socket binding.

The deterministic tests do not establish browser focus and caret preservation,
keyboard event handling, filter controls, DOM updates, trace presentation, or
viewport layout. Those behaviors still require browser verification. The
retained Playwright workflows are opt-in because the default suite does not
install browser binaries. For a separately requested browser check, install
Chromium and run:

```bash
uv run playwright install chromium
RUN_REVIEW_BROWSER_TESTS=1 uv run pytest tests/test_chat_eval_review_browser.py
```

These tests use temporary reports and review files. They cover verdicts, notes,
undo, navigation, focused save shortcuts, counters, reload persistence,
instructions and tool exchanges, safe rendering, and recovery after save failures.
They also save desktop and narrow screenshots under `.scratch/review-interface/`.
Regression checks cover report replacement and directory changes, malformed
reference records, short tablet viewports, queued navigation during a save, and
Undo while navigation is waiting for a save.
