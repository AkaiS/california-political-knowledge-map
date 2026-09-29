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

Open one report in the local reviewer:

```bash
uv run python scripts/review_chat_eval.py evals/reports/chat/<report-file>.json
```

Then visit `http://127.0.0.1:8765/`. The reviewer displays one case at a time.
Use the list or arrow keys to move between cases, search by question or ID, and
filter by review verdict. It saves each **Pass**, **Fail**, or **Defer** verdict
and free-text critique to `<report-file>.reviews.json`. `1`, `2`, `D`, and `U`
set Pass, Fail, Defer, and clear the verdict. The note saves as you type. Use
`--reviews <path>` to choose another review file and `--port <port>` to change
the local port. The reviewer binds to loopback.

## Read one case

Read the case from the voter's question outward:

1. **Answer shown to the voter.** Did the response direct the reader to useful sources, state coverage limits, and avoid claims its citations do not support? A Declined or Deferred control may have no retrieval answer.
2. **Question preparation.** Did the Query Rewrite preserve the named people, measures, relationship, time scope, and requested result? Was the policy and coverage assessment appropriate?
3. **Retrieval branches.** Check the full-text, dense, and structural outcomes. The report lists only the top full-text candidates up to the number returned by dense retrieval. It records the total full-text count and aggregate scores and rank range for candidates left off that list. Expand retained candidates to see ranks and routes. Selected Grounding Evidence keeps its own candidate contributions even when a supporting passage came from below the list cutoff. A failed branch can coexist with a prepared answer from other branches.
4. **Selected Grounding Evidence.** Read the stored passages under each Source Article citation. Check whether the specific passage supports the answer's wording, and whether relevant material was dropped by Evidence Assembly's context limit.
5. **Application stages and model messages.** Expand stage observations for the rewrite, assessment, branch work, fusion, Evidence Assembly, and guidance. Model messages show the requests and responses captured for this evaluation case, including retries or failed requests where available.

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
