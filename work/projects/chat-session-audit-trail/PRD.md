# Product requirements: Chat Session Audit Trail

Labels: completed

## Problem Statement

A maintainer can ask one political question in local chat and inspect the immediate Retrieval Answer, but the application does not retain a durable account of how it reached that answer. Browser history is not a server record, Chat Sessions disappear when they finish or the process restarts, and Logfire telemetry does not provide the local, stage-by-stage record needed to compare retrieval behavior across code and configuration changes.

The maintainer needs to see where a candidate entered or left the pipeline, which Query Rewrite the person approved, what each retrieval branch returned, what fusion and Evidence Assembly selected, and exactly what answer the browser was sent. Failed or abandoned sessions should leave whatever stage observations were successfully saved. Audit trouble must not prevent a person from using chat.

## Solution

Create a Chat Session Audit Trail for each first question. An application-generated session ID joins immutable Audit Stage Records. A session-start record captures the original question and the resolved run settings. Each named stage starts a direct background insert into a separate local SQLite database when it finishes. Query Rewrite proposals alone carry attempt numbers. Concurrent retrieval stages have separate IDs and timestamps, with no fabricated global step order.

Stage records hold the outcomes and compact metadata needed to investigate the pipeline. Retrieval branches record returned candidate counts. Fusion records the ordered Article Chunk IDs eligible from each branch and its ordered result. Evidence Assembly records selection, omission, context use, and failure. Structural construction records its selected ontology pieces and validated query with bindings. A Retrieval Answer gets one final record with the exact browser answer text and a snapshot of selected stored passages and citations. Other stages record their own failures; no extra session-closing outcome is invented.

The maintainer can list, filter, inspect, and export trails through a CLI. Saved records remain until an operator manages the database outside this feature. Audit inserts never gate chat, and no record claims that a browser received or read an answer. A missing Retrieval Answer record may mean the session stopped earlier, the person left, or an audit insert failed.

## User Stories

1. As a maintainer, I want one audit ID assigned when a person first asks a question, so that every later observation can be found together.
2. As a maintainer, I want the original question saved with that ID, so that I can judge whether the Query Rewrite preserved the person's intent.
3. As a maintainer, I want the session-start time saved, so that I can compare a trail with the state of the corpus and deployment at that time.
4. As a maintainer, I want the code revision and dirty-worktree state saved, so that I know which application code handled the question.
5. As a maintainer, I want the resolved Model Deployments saved, so that I can compare runs made with different models and provider settings.
6. As a maintainer, I want effective prompt revisions saved, so that a changed Query Rewriter or Chat Agent instruction is visible in comparisons.
7. As a maintainer, I want fusion weights and limits saved, so that I can interpret candidate order under the settings actually used.
8. As a maintainer, I want Evidence Assembly context limits saved, so that omissions can be interpreted against the applied budget.
9. As a maintainer, I want the available collection counts and their observation time saved, so that a later corpus change is not mistaken for the state at question time.
10. As a maintainer, I want each named operation to have its own stage ID, so that parallel work can be distinguished without imposing an order it did not have.
11. As a maintainer, I want stage start and end times, so that I can compare latency and see which retrieval branches overlapped.
12. As a maintainer, I want each stage's result status and safe failure kind, so that a missing candidate can be traced to a result rather than guessed at from an absent row.
13. As a maintainer, I want model token usage on stages that make model calls, so that changes in cost and work are visible.
14. As a maintainer, I want successive Query Rewrite proposals numbered within their Chat Session, so that corrections and later proposals can be followed in order.
15. As a maintainer, I want the proposed question and relational route retained for each rewrite attempt, so that I can inspect what changed after feedback.
16. As a maintainer, I want policy and coverage assessments retained, including Declined and Deferred decisions, so that an early stop or limited answer has an explicit cause when its record was saved.
17. As a maintainer, I want approvals and corrections recorded, so that I can identify the Query Rewrite that actually entered retrieval and the feedback that led to it. Later numbered proposals make earlier rejections implicit.
18. As a maintainer, I want the terms used by full-text search recorded, so that I can see how the approved question became a search input.
19. As a maintainer, I want the index identities and states observed by retrieval recorded, so that an index problem is visible without an extra audit-only database query.
20. As a maintainer, I want each retrieval branch's returned candidate count, so that I can distinguish the search result size from the fusion limit.
21. As a maintainer, I want the count and ordered IDs eligible for fusion from each branch, so that a branch limit can be distinguished from search failure.
22. As a maintainer, I want the ordered fused Article Chunk IDs, so that I can see where the combined ranking changed.
23. As a maintainer, I want structural schema filtering and typed selection results recorded, so that I can inspect which graph vocabulary the question used.
24. As a maintainer, I want structural wiring, binding, validated query text, and bound values recorded, so that a zero-result or failed graph query can be investigated.
25. As a maintainer, I want structural execution and hydration results recorded, so that query construction can be distinguished from database and evidence failures.
26. As a maintainer, I want Evidence Assembly's selected IDs, omitted IDs and reasons, and measured context use recorded, so that I can explain why a fused candidate did not reach the Chat Agent.
27. As a maintainer, I want the Chat Agent guidance stage recorded, so that a valid evidence package can be distinguished from a final model failure.
28. As a maintainer, I want the exact rendered browser answer saved when a Retrieval Answer exists, so that I can inspect what the application attempted to send after models or data have changed.
29. As a maintainer, I want selected stored Article Chunk passages and Source Article citations snapshotted with that answer, so that changed graph contents or dead links do not erase the basis of that answer.
30. As a maintainer, I want answers with zero selected passages recorded as Retrieval Answers, so that an empty result is not confused with an interrupted session.
31. As a maintainer, I want Evidence Assembly failures in their own stage records, so that they do not masquerade as Retrieval Answers.
32. As a maintainer, I want a trail with no Retrieval Answer to show the stages that were saved, so that I can inspect it without the CLI inventing a closing reason.
33. As a person using chat, I want audit database trouble to leave my question and answer flow working, so that diagnostics do not become a product dependency.
34. As a maintainer, I want audit write failures reported through operational logging, so that missing records are visible when the application can report them.
35. As a maintainer, I want committed records to survive application restarts, so that I can compare a past run with a later one.
36. As a maintainer, I want a CLI list of saved trails, so that I can locate the session I need to inspect.
37. As a maintainer, I want to filter trails by time, answer presence, code revision, Model Deployment, and failed stage, so that I can compare cohorts rather than open each trail manually.
38. As a maintainer, I want to show one trail's recorded stages in time order without claiming a total order for concurrent work, so that the execution is readable without changing its meaning.
39. As a maintainer, I want to export a trail as JSON, so that I can analyze or compare it with other runs outside the CLI.
40. As a maintainer, I want audit inspection to work without starting chat, models, Neo4j, or Logfire, so that past records remain inspectable during an outage.
41. As a maintainer, I want the session ID on Logfire telemetry, so that I can move from a local record to deeper operational traces when available.
42. As a maintainer, I want records to exclude raw provider request and response bodies and embedding vectors, so that the audit stays focused on pipeline decisions and avoids storing high-volume payloads indefinitely.

## Implementation Decisions

- Use the existing Chat Session as the one-question boundary. Generate the audit ID at the first accepted question and carry it across rewrite, correction, approval, retrieval, and answer presentation. It is an application ID, not a Logfire trace ID or browser conversation ID. Attach it to Logfire activity for correlation.
- Store Audit Stage Records in a separate, locally configured SQLite database. Records are insert-only and have a unique stage ID, session ID, canonical stage name, start and end times, result status, schema version, and stage-specific metadata. A conflicting reuse of a stage ID is rejected. Only Query Rewrite proposals have an attempt number. Parallel stages have no global ordinal; their times and names carry their relationship.
- Start a direct background SQLite insert when a stage completes. There is no queue, delivery acknowledgment, retry subsystem, or audit dependency that stops chat. Start the Retrieval Answer insert before emitting its browser text. A successful commit is durable; an in-flight insert may be lost on process exit. Log write errors through the existing operational telemetry and continue serving chat.
- A session-start stage is dispatched when the first question arrives. Capture the original question, observation time, code revision and dirty state, resolved Model Deployments and prompt revisions, fusion configuration, Evidence Assembly limits, and the available Coverage Description counts already measured at startup with their observation time. Do not make a new corpus or index query solely to fill audit metadata.
- Record a stage for each varying result in Query Rewrite, question assessment, approval or correction, full-text search, dense search, structural construction and execution, fusion, Evidence Assembly, and Chat Agent guidance. Structural stages include schema filtering, typed selection, wiring, binding, validated query construction, execution, and hydration. A failure is represented at the stage that failed; no separate session-end record is required.
- Query Rewrite Proposal stage metadata includes the proposed text, relational route, and proposal attempt number. Separate assessment, correction, and approval records refer to the proposal stage ID. A later numbered proposal makes an earlier rejection implicit; no separate rejection record is needed. Retrieval uses only the approved Query Rewrite. Stage records for Declined and unavailable rewrites stand on their own when no retrieval occurs.
- Retrieval branch records include search terms where applicable, observed index identity and state, result or failure, and returned candidate count. Fusion records per-branch eligible ID counts and ordered IDs, plus the ordered fused output IDs. Order represents rank; do not copy every returned ID, duplicate rank in another field, or add branch raw scores and candidate retrieval routes to this audit.
- Structural stage records retain selected ontology pieces, wiring and binding decisions, the validated query text and bound values, and database and hydration outcomes. Do not store raw provider messages or raw model output alongside these validated stage results.
- Evidence Assembly records selected IDs, omitted IDs and reasons, applied context limits and measured use, relevant coverage, and any failure. The passage text is retained in the Retrieval Answer snapshot when an answer exists. Stored Article Chunk wording must keep its existing provenance marker; it is not claimed as a verbatim quotation from the Publication.
- Only a Retrieval Answer produces the final answer record. It contains the exact rendered browser answer text and snapshots the selected stored passages and Source Article citations. A zero-passage Retrieval Answer still gets one. An Evidence Assembly failure is recorded at Evidence Assembly, and an unexpected failure is recorded at the failing stage when possible. A missing final record receives no inferred reason or status.
- Exclude raw provider request and response bodies and embedding vectors from the SQLite audit. Failure records include a stable stage and failure kind with a safe diagnostic, not raw exception text or secrets. Deeper exception detail remains in Logfire where available.
- Provide a maintainer CLI to list and filter trails, show one trail with its saved stages, and export JSON. Read commands are independent of model, graph, and Logfire startup and do not perform schema initialization or mutation while inspecting. The first version has no browser audit view, automatic expiry, or deletion command.
- Preserve the existing typed Retrieval Answer, Evidence Package, retrieval branch outcomes, and browser presentation contracts. Audit capture observes their boundaries; it does not change retrieval ranking, answer generation, approval rules, or user-facing Search details.

## Testing Decisions

- Test externally visible behavior and the persisted audit values at the highest useful seams. Do not assert private helper calls, exact scheduling order among parallel branches, or the implementation of the SQLite background task.
- Drive a real Chat Session through the existing ASGI application entry point with scripted agents, fake retrieval dependencies, and a temporary audit database. Cover first question, corrected rewrite, approval, concurrent branch outcomes, fusion, Evidence Assembly, and a Retrieval Answer. Assert that saved stage records share one session ID, have unique stage IDs, and carry the agreed stage-specific values.
- At the same ASGI seam, assert that the browser receives the same answer when an audit insert fails. Use controlled task completion rather than sleeps to observe background writes. Assert only dispatch-before-answer ordering, not a commit-before-delivery guarantee.
- Cover a Declined question, unavailable rewrite, Evidence Assembly failure, zero-passage Retrieval Answer, and abandoned approval. Assert the recorded stages and the absence or presence of a Retrieval Answer record without inventing a terminal status.
- Exercise candidate count and ordered-ID capture with branch outputs containing duplicates, more than the fusion limit, and concurrent completion in different orders. Assert the eligible IDs and fused order match the actual retrieval result, with no raw score or route duplication in the audit.
- Exercise stage timing and token usage with scripted model calls, and safe failure metadata with controlled branch and model failures. No live model, Neo4j, CDN, or browser automation is needed.
- Invoke the CLI dispatcher against a temporary audit database to verify list, filters, show, and JSON export, including a trace without a Retrieval Answer. Confirm read operations work without telemetry or chat dependencies and do not mutate the database.
- Existing chat web answer and lifecycle tests provide prior art for ASGI request sequences and approval behavior. Existing Chat Session, retrieval coordinator, fusion, and Evidence Assembly tests provide scripted model and fake branch patterns. Existing chat CLI tests provide prior art for command-dispatch assertions.

## Out of Scope

- A browser-facing audit history or a user-facing audit API.
- Persistent or resumable Chat Sessions, pending approvals, or browser transcripts.
- A queue, cache, distributed store, delivery acknowledgment, guaranteed completeness, or exactly-once audit capture.
- Blocking an answer because an audit insert failed or has not committed.
- Claiming that a browser received, displayed, or read an answer.
- A total sequence number for parallel stages or an attempt number outside successive Query Rewrite proposals.
- Raw provider request or response bodies, embedding vectors, raw branch scores, and candidate retrieval routes in the local audit.
- Automatic expiry, an audit deletion command, remote replication, or backup management.
- Cryptographic tamper evidence, regulatory compliance claims, or user identity and access management.
- Changing search algorithms, fusion weights, Evidence Assembly selection, answer wording, or the existing retrieval and answer contracts.
- Converting saved trails into Evaluation Data Sets or adding a run comparison dashboard.

## Further Notes

The glossary defines Chat Session Audit Trail and Audit Stage Record. The existing Retrieval Answer retains the full typed Evidence Package for the live request, but it is not persisted today. The browser's Search details are presentation data; the audit records the selected stage decisions and the rendered answer without altering that feature.

This is a best-effort local audit. SQLite commit makes an individual record durable, while a background insert may still be running when a response is sent or the process exits. A gap in the trail is therefore evidence only that a record is absent. The CLI should display saved facts and avoid labeling the cause of absence.
