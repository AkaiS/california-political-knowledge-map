# Inspect Chat Session trails

The Chat Session Audit Trail consists of the application's observations that
reached Logfire. Use the application-generated `chat_session_id` to find one
political question across preparation, correction, approval, and any prepared
Retrieval Answer. It differs from the browser conversation ID and native trace
IDs. The queries below use audit schema version 1.

## Find one question

Open the application's Logfire project and its SQL Workbench. Choose a time
window that covers the question and the later approval. Replace
`<chat-session-id>` with the ID from a `chat_session.started` record, then run
this query. If the ID is unknown, use the cohort search below to find the
original question and its observation time. A scrubbed question may not be
searchable by its wording.

```sql
-- single-session
SELECT
    start_timestamp,
    end_timestamp,
    span_name,
    attributes->>'chat_session_id' AS chat_session_id,
    attributes->>'status' AS status,
    attributes->>'branch' AS branch,
    attributes->>'stage' AS structural_stage,
    attributes->>'failure_stage' AS failure_stage,
    attributes->>'failure_kind' AS failure_kind,
    attributes->>'proposal_attempt' AS proposal_attempt,
    trace_id,
    span_id,
    parent_span_id
FROM records
WHERE span_name LIKE 'chat_session.%'
  AND CAST(attributes->>'audit_schema_version' AS INTEGER) = 1
  AND attributes->>'chat_session_id' = '<chat-session-id>'
ORDER BY start_timestamp, span_id
LIMIT 500
```

`span_name` names the application operation. `branch` distinguishes full-text,
dense, and structural retrieval; `structural_stage` distinguishes construction,
execution, and hydration. A NULL status means that record does not declare an
outcome. Start, approval, and answer events and the enclosing request operations
do not declare a status. Stage records carry outcomes such as `proposed`,
`allowed`, `deferred`, `declined`, `unavailable`, `succeeded`, `failed`, or `skipped`.
Keep these meanings instead of interpreting every completed span as success.

Click a returned `trace_id` to open its native trace, then expand the application
stage to inspect its Pydantic AI children. A `span_id` link identifies the
individual record. The SQL Workbench also supports copying a trace ID into the
Live view filter, for example `trace_id = '<trace-id>'`.
See Logfire's [trace navigation](https://pydantic.dev/docs/logfire/observe/explore/#cross-linking-with-live-view)
and [record columns](https://pydantic.dev/docs/logfire/reference/sql/#span-tree).

Preparation, each correction, and approval close their own operation spans.
Their separate traces share the application ID; no span stays open while a
person considers approval. The start and prepared-answer events can also have
their own traces because they occur outside those operations. Native model
spans need not carry `chat_session_id`, so follow their trace ancestry rather
than expecting the application-only query to return every model call.

The three retrieval branches run concurrently. Their native start/end times
and parent IDs show overlap. Sorting rows is a display choice, not a total
completion order or a causal sequence. Proposal attempt numbers refer only to
Query Rewrite Proposals and their assessment, correction, and approval.

If the query returns 500 rows, increase the limit before interpreting an absent
stage. Inspect a record's attributes for its full decisions, including fusion
IDs, Evidence Assembly omissions, or the prepared answer's `rendered_text` and
`selected_sources`. Structural fields are described in
[structural retrieval](structural-retrieval.md#chat-session-observations).

## Compare sessions

Replace `<window-start>` and `<window-end>` with UTC timestamps such as
`2026-09-24T00:00:00+00:00` and `2026-09-25T00:00:00+00:00`. Set the Workbench
time picker to cover the same range. The window includes its start and excludes
its end. This query returns one row per observed session start, with settings
captured when that question began and any prepared-answer observations inside
the same window.

```sql
-- session-cohort
WITH observations AS (
    SELECT start_timestamp, span_name, trace_id, attributes
    FROM records
    WHERE span_name LIKE 'chat_session.%'
      AND CAST(attributes->>'audit_schema_version' AS INTEGER) = 1
      AND start_timestamp >= '<window-start>'
      AND start_timestamp < '<window-end>'
), answers AS (
    SELECT
        attributes->>'chat_session_id' AS chat_session_id,
        COUNT(*) AS answer_records,
        MIN(start_timestamp) AS first_answer_observed_at
    FROM observations
    WHERE span_name = 'chat_session.answer_prepared'
    GROUP BY attributes->>'chat_session_id'
), cohort AS (
    SELECT
        s.start_timestamp,
        s.attributes->>'observed_at' AS observed_at,
        s.attributes->>'chat_session_id' AS chat_session_id,
        s.attributes->>'original_question' AS original_question,
        s.attributes->>'code_revision' AS code_revision,
        s.attributes->>'worktree_dirty' AS worktree_dirty,
        s.attributes->'model_deployments' AS model_deployments,
        s.attributes->'model_deployments'->'chat_agent'->>'kind' AS chat_deployment_kind,
        s.attributes->'model_deployments'->'chat_agent'->>'model' AS chat_model,
        s.attributes->'model_deployments'->'chat_agent'->>'endpoint' AS chat_endpoint,
        COALESCE(a.answer_records, 0) > 0 AS answer_observed_in_window,
        COALESCE(a.answer_records, 0) AS answer_records,
        a.first_answer_observed_at,
        s.trace_id
    FROM observations s
    LEFT JOIN answers a ON a.chat_session_id = s.attributes->>'chat_session_id'
    WHERE s.span_name = 'chat_session.started'
)
SELECT
    start_timestamp, observed_at, chat_session_id, original_question,
    code_revision, worktree_dirty, model_deployments,
    chat_deployment_kind, chat_model, chat_endpoint,
    answer_observed_in_window, answer_records, first_answer_observed_at, trace_id
FROM cohort
WHERE 1 = 1
ORDER BY observed_at DESC, chat_session_id
LIMIT 100
```

Add any of these predicates below the final `WHERE 1 = 1`, before `ORDER BY`.
Use your actual revision and Model Deployment values.

| Comparison | Additional predicate |
| --- | --- |
| Original question's observation time | `AND observed_at >= '2026-09-24T12:00:00+00:00'` |
| Code revision | `AND code_revision = '<git-commit>'` |
| Chat Agent Model Deployment | `AND chat_deployment_kind = 'local' AND chat_model = '<model>' AND chat_endpoint = '<endpoint>'` |
| Prepared Retrieval Answer observed | `AND answer_observed_in_window = TRUE` |
| No prepared Retrieval Answer observed in this window | `AND answer_observed_in_window = FALSE` |

`observed_at` is the application's UTC session-start observation time.
`start_timestamp` is the native timestamp used for the scan window. Session
settings are recorded once on `chat_session.started`; joining them to later
observations requires the application ID, not a shared trace ID. A missing
start record excludes that session from this cohort, but the single-session
query can still find its surviving observations.

The flattened deployment columns select the Chat Agent role. Inspect the full
`model_deployments` object to compare `query_rewriter`, `chat_agent`,
`structural_ontology_filter`, `structural_selector`, `structural_wiring`, or
`structural_binder`. Change the `'chat_agent'` JSON path to select another role.
Model name alone does not describe a Model Deployment. Compare its kind,
endpoint, request settings, and any OpenRouter provider policy as well.
The start record also holds `prompt_hashes`, `embedding_settings`,
`fusion_settings`, `evidence_limits`, `coverage`, and `coverage_observed_at`.
Use these to distinguish configuration and corpus observations from code
changes. Unknown code revision or dirty state remains unknown.

`answer_records` counts observations, not browser deliveries or unique results.
A zero-passage Retrieval Answer still sets `answer_observed_in_window` to true.
False means no matching record was found within this query's window. In
particular, an approval after the window can produce an answer that this query
cannot see. Widen the window and use the single-session query before drawing
conclusions about a partial trail.

## Find a failed stage

This query finds failures even when the start or answer record is absent. It
includes returned rewrite unavailability, which carries `status=unavailable`.
An operational exception flag alone misses returned failures.

```sql
-- failed-stages
SELECT
    start_timestamp,
    end_timestamp,
    attributes->>'chat_session_id' AS chat_session_id,
    span_name,
    attributes->>'branch' AS branch,
    attributes->>'stage' AS structural_stage,
    attributes->>'status' AS status,
    attributes->>'failure_stage' AS failure_stage,
    attributes->>'failure_kind' AS failure_kind,
    attributes->>'diagnostic' AS diagnostic,
    attributes->>'proposal_attempt' AS proposal_attempt,
    trace_id,
    span_id,
    parent_span_id
FROM records
WHERE span_name LIKE 'chat_session.%'
  AND CAST(attributes->>'audit_schema_version' AS INTEGER) = 1
  AND start_timestamp >= '<window-start>'
  AND start_timestamp < '<window-end>'
  AND attributes->>'status' IN ('failed', 'unavailable')
ORDER BY start_timestamp DESC, span_id
LIMIT 100
```

Narrow this query before `ORDER BY`, for example with
`AND span_name = 'chat_session.guidance'` or
`AND attributes->>'failure_stage' = 'schema_filtering'`. Add
`AND attributes->>'branch' = 'dense'` to inspect dense branch failures.
Preparation, fusion, Evidence Assembly, and guidance identify the failed stage
through `span_name`; their `failure_stage` can be NULL. Structural observations
also expose `stage`, while branch failures identify their cause in
`failure_stage`. Use `failure_kind` and the safe `diagnostic` to orient the
investigation, then follow the trace for stage ancestry, model timing, and retries.

Each row is an observation. A structural failure can appear both on its stage
and on the enclosing branch. A rejected structural validation can be corrected
later within the same branch. A failed branch can coexist with a prepared
Retrieval Answer from surviving evidence. Do not count these rows as failed
sessions; use their application IDs to inspect the surrounding observations.
Declined and Deferred assessments are question decisions and are excluded from
this failure search.

## Save a useful search

On the project's Live page, open **Search & filter with SQL**. Paste this
predicate with the real application ID, then click **Run**:

```sql
-- live-session-filter
span_name LIKE 'chat_session.%'
AND CAST(attributes->>'audit_schema_version' AS INTEGER) = 1
AND attributes->>'chat_session_id' = '<chat-session-id>'
```

The Live editor accepts a predicate, so use the complete SELECT queries above
in SQL Workbench. For a reusable search across sessions, remove the final ID
predicate. Add `AND attributes->>'status' IN ('failed', 'unavailable')` to save
the failure search instead.

Click **Save**, name the search, choose **Private** or **Public** visibility,
and save it. Public searches are visible to project members. Reopen it from the
**Saved** tab, edit the ID when following another question, and check the time
window on each run. These steps follow Logfire's
[Saved Searches guide](https://pydantic.dev/docs/logfire/observe/saved-searches/).
Saving a search retains its query, not a snapshot of matching observations.

## Retention and missing observations

The trail lasts only as long as the destination Logfire project's configured
retention. This repository does not set that period or record it in a Chat
Session. Check the selected project's organization under **Billing & usage**
for its plan, then confirm the applicable retention with the project owner if
the organization has custom terms. Record the project, confirmed retention
period, and query window in any investigation notes so another maintainer can
interpret the result. Do not assume a fixed period from this guide. Logfire's
[retention and usage documentation](https://pydantic.dev/docs/logfire/manage/logfire-costs/#export-data-via-api-for-longer-retention)
describes plan-dependent pruning and extended retention.

Delivery is best effort. Export trouble after startup must leave the chat
result unchanged. Missing, delayed, expired, or filtered observations cannot
establish that an operation never happened. Confirm the destination project,
retention, time window, and row limit before treating a result as the available
trail. The existing token startup policy is described in
[secrets guidance](agents/secrets.md#logfire).

An absent `chat_session.answer_prepared` has no inferred closing cause. A
Declined question, unavailable rewrite, abandoned approval, stage failure, or
export gap can leave a partial trail; only recorded decisions support those
specific explanations. An observed prepared answer proves that the application
rendered its text before attempting emission. It proves no browser receipt,
display, or reading. Its stored passages retain `stored_chunk` provenance and
are not a claim of verbatim Publication quotations.

Logfire's default scrubber applies to all audit attributes except the
application-generated `chat_session_id`. It may redact an entire question,
answer, selected source field, Article Chunk ID, or structural query when it
matches a word such as `session`. This includes benign legislative wording.
Inspect `logfire.scrubbed` before treating a field as an exact snapshot. The
scrubber can miss an unlabelled secret, so a field without a scrub note is not
proof that it contains no private data. Pydantic AI spans retain model timing,
retries, and token use, but omit prompt, completion, and tool content. Exception
events are suppressed because Logfire does not scrub their fields. Logfire's
span status description may still contain an exception message, including
private text, so these traces need an export filter before they can be treated
as free of private data.

Logfire is the only audit destination for this version. The application has no
local audit database, audit CLI, or custom Query API client. Saved searches do
not extend retention, provide offline inspection during an outage, or guarantee
delivery, exactly-once capture, or tamper evidence.

## Offline verification

`tests/test_chat_trail_queries.py` drives `POST /api/chat` with real Chat Session
coordination, scripted models, fake graph and transport boundaries, and the
offline Logfire exporter. It reads the SQL blocks above and executes their
portable SQL/JSON subset against a test-only in-memory projection of captured
records. It checks the field paths and identities, separate request traces,
statuses, changed startup settings, window-bounded answer presence, and both
returned and raised stage failures.

These tests do not emulate Logfire ingestion or certify its query engine or
current UI. SQL syntax and navigation were checked against the linked official
documentation on 2026-09-24. No live project or browser verification is needed.
The existing `test_chat_*_trail.py` tests cover concurrent branches, corrected
proposals, native model ancestry, safe answer snapshots, and exporter failures.
