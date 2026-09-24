# Product requirements: Logfire Chat Session Audit Trail

Labels: completed

## Problem Statement

A maintainer can inspect the Retrieval Answer produced by a live Chat Session, but cannot reliably follow the application's decisions from the original question to that answer after the session ends. Pydantic AI already sends model calls, messages, retries, token use, and failures to Logfire. It does not identify which Query Rewrite Proposal the person approved, which retrieval candidates survived fusion, why Evidence Assembly omitted a passage, or the exact answer the application prepared for the browser. A previous implementation used a separate local audit database and inspection CLI, duplicating some operational telemetry and creating another capture path to maintain.

The maintainer needs a searchable account of one political question across preparation, correction, approval, concurrent retrieval, Evidence Assembly, and any Retrieval Answer. It must connect application decisions with the existing model traces, show partial progress when a session ends early, and state honestly what a missing observation means. Audit instrumentation must not change the person's question or answer flow.

## Solution

Capture the Chat Session Audit Trail through Logfire and OpenTelemetry. Give each accepted first question one application-generated Chat Session ID. Put that ID on the manual spans and events for every application decision. Preparation, correction, and approval may occur in separate HTTP requests, so their traces are joined by this ID rather than by a span held open while a person responds. Native trace and span IDs identify individual operations; Query Rewrite Proposals also carry an attempt number so later assessments, corrections, and approval refer to the right proposal.

Use manual spans around work whose duration and child operations matter. Record instantaneous decisions as structured Logfire events. Pydantic AI instrumentation continues to own model calls, retries, messages, and token usage. Add application attributes only for facts it cannot derive: effective run settings, approved wording, retrieval branch outcomes, candidate selection, structural construction, Evidence Assembly decisions, and the rendered Retrieval Answer with its selected stored passages and citations. A failed or abandoned session shows only observations that reached Logfire. No terminal outcome is inferred from the absence of a Retrieval Answer.

For this version, Logfire is the only audit destination and its configured project retention is the trail's retention. Maintainers find a Chat Session by its ID in Logfire and inspect its spans and events there. A saved query may support recurring searches and comparisons. Long-term archival, a local database, and a custom audit CLI are separate work if retention or offline inspection later requires them.

## User Stories

1. As a maintainer, I want one application Chat Session ID assigned to the first accepted question, so that observations across separate requests can be found together.
2. As a maintainer, I want the original question and its observation time recorded, so that I can judge later decisions against what the person asked and when they asked it.
3. As a maintainer, I want the effective code revision and dirty-worktree state recorded, so that I can distinguish code changes from retrieval changes.
4. As a maintainer, I want the resolved Model Deployments recorded by role, so that I can compare sessions using different models or endpoints without exposing credentials.
5. As a maintainer, I want prompt revisions recorded, so that a change in instructions is visible without copying the same instructions into every application span.
6. As a maintainer, I want effective fusion weights, candidate limits, and Evidence Assembly limits recorded, so that I can interpret the rankings and omissions a session produced.
7. As a maintainer, I want the available Coverage Description and its observation time recorded from already measured startup data, so that later corpus changes do not masquerade as the session's original coverage.
8. As a maintainer, I want each Query Rewrite Proposal identified by its attempt number, so that successive proposals remain distinguishable after corrections.
9. As a maintainer, I want each proposal's question and relational route recorded, so that I can see what the Query Rewriter proposed.
10. As a maintainer, I want the question-policy and coverage assessment tied to its proposal, so that Declined and Deferred outcomes have an explicit recorded cause.
11. As a maintainer, I want corrections and the approved Query Rewrite tied to the relevant proposal, so that I can see which wording actually entered retrieval.
12. As a maintainer, I want an unavailable Query Rewriter or failed assessment recorded at the point it happened, so that an early stop is not confused with a missing answer.
13. As a maintainer, I want full-text search terms and observed index identity and state recorded, so that I can investigate how the approved wording reached the index.
14. As a maintainer, I want independent spans for full-text, dense, and structural retrieval, so that I can see their overlap without inventing a completion order.
15. As a maintainer, I want each retrieval branch's result status and returned candidate count recorded, so that an empty result is distinguishable from a failure and from a fusion limit.
16. As a maintainer, I want a skipped structural branch represented explicitly for a non-relational question, so that its absence is not mistaken for a failure.
17. As a maintainer, I want structural schema filtering and typed selection recorded, so that I can see which ontology pieces the question used.
18. As a maintainer, I want structural wiring, binding, validated query text, and bound values recorded, so that I can investigate a zero-result or rejected graph query.
19. As a maintainer, I want structural execution and hydration outcomes recorded separately, so that construction failures can be distinguished from database and evidence failures.
20. As a maintainer, I want the ordered Article Chunk IDs eligible from each retrieval branch and the ordered fused IDs recorded, so that I can see where candidates entered or left the ranking.
21. As a maintainer, I want Evidence Assembly's selected and omitted Article Chunk IDs with omission reasons recorded, so that I can explain why a fused candidate did not reach the Chat Agent.
22. As a maintainer, I want applied context limits and measured use recorded, so that passage omissions can be interpreted against the actual budget.
23. As a maintainer, I want a failed Evidence Assembly identified at that stage, so that it does not appear to be a completed Retrieval Answer.
24. As a maintainer, I want the Chat Agent guidance operation visible alongside its existing model spans, so that I can distinguish a valid Evidence Package from a guidance failure.
25. As a maintainer, I want the exact rendered browser answer recorded when a Retrieval Answer is prepared, so that I can inspect what the application attempted to send after models or data have changed.
26. As a maintainer, I want the selected stored Article Chunk passages, their provenance markers, and Source Article citations snapshotted with that answer, so that changed graph contents or dead links do not erase its recorded basis.
27. As a maintainer, I want a zero-passage Retrieval Answer recorded, so that an empty but completed answer is distinct from an interrupted session.
28. As a maintainer, I want safe failure kinds on application stages and deeper operational detail in their related Logfire traces, so that I can investigate a failure without duplicating raw exception text in custom audit attributes.
29. As a maintainer, I want to find all application observations for a Chat Session ID, so that I can follow the question across preparation and approval requests.
30. As a maintainer, I want to compare sessions by observation time, code revision, Model Deployment, answer presence, and failed stage using Logfire queries, so that I can identify changes in retrieval behavior.
31. As a maintainer, I want the trace and span relationships preserved around agent calls, so that I can move from a recorded application decision to the relevant model activity.
32. As a maintainer, I want the retention and best-effort nature of the trail documented, so that I do not mistake an absent or expired span for proof that an operation never happened.
33. As a person using chat, I want telemetry export trouble after startup to leave my question and answer behavior unchanged, so that observation does not become part of the product result.

## Implementation Decisions

- Build from the pre-audit branch point with `main`. The prior local audit implementation is preserved on a backup branch; its SQLite store, audit writer, audit schema, audit CLI, and tests are absent from this implementation baseline.
- Use the existing one-question Chat Session as the identity boundary. Generate an application ID only after a first question is accepted. Put the same searchable ID on every manual application span and event. Do not use a browser conversation ID or a Logfire trace ID as the cross-request identity.
- Keep one manual root span per preparation, correction, or approval operation. Close each span when its operation ends; a pending human approval creates no long-lived span. Nest stage spans under these roots so Pydantic AI agent spans appear beneath the work that invoked them.
- Use stable stage names and structured attributes. Native span IDs and timestamps distinguish concurrent work. Only Query Rewrite Proposals receive a one-based attempt number; assessment, correction, and approval refer to that attempt. Do not add a global step sequence.
- Capture session-start settings once, using values already resolved or measured for the Chat Session. Include the original question, code revision and dirty state, resolved Model Deployments, prompt hashes, fusion settings, context limits, Coverage Description, and coverage observation time. Do not query Neo4j solely for telemetry.
- Instrument the varying application results: proposal, question assessment, correction, approval, each retrieval branch, structural construction and execution, fusion, Evidence Assembly, Chat Agent guidance, and the prepared Retrieval Answer. A returned failure or skip needs an explicit status attribute because it may not raise an exception. Use a stable failure kind and safe diagnostic on custom spans; existing operational telemetry keeps detailed exceptions.
- Leave model request spans, messages, retries, and token usage to existing Pydantic AI instrumentation. Leave low-level HTTPX body capture disabled. Do not copy raw provider request and response bodies, embedding vectors, raw branch scores, or every returned candidate into custom audit attributes.
- For fusion, record per-branch eligible ID counts and ordered IDs plus the ordered fused IDs. For Evidence Assembly, record selected IDs, omitted IDs and reasons, applied limits, measured use, and relevant coverage. Order carries rank without a duplicate rank field.
- For structural retrieval, record the validated application outputs and query parameters at their existing decision boundaries. Model messages remain in Pydantic AI spans. Distinguish schema filtering, typed selection, wiring, binding, validation, database execution, and hydration when those stages occur.
- Emit the final answer observation after rendering and before yielding its text to the browser. Include exact rendered text and selected stored passages and Source Article citations. Preserve each passage's `stored_chunk` provenance marker; do not claim the stored wording is a verbatim quotation from a Publication. The observation proves preparation for emission, not browser receipt or reading.
- A missing final observation has no inferred cause. A Declined question, unavailable rewrite, abandoned approval, Evidence Assembly failure, or export gap can produce a partial trail. Do not invent a closing status to explain absence.
- Keep Logfire as the only audit destination in this version. Query its records by application session ID, then follow trace and span relationships for model detail. Do not build a local store or an audit-specific read service. Add a saved Logfire query for common session and cohort inspection; a Query API client is deferred until a concrete need appears.
- Record a schema version on custom audit spans and events, and use bounded, explicit attribute shapes. Check representative answer snapshots against Logfire ingest limits and preserve exact text when the accepted payload fits. If a required snapshot cannot fit, treat that as a specification problem rather than silently truncating it.
- Keep current telemetry startup policy separate from audit behavior. A missing token already has an application policy; this project does not add another startup gate. Export failures after startup must not alter chat results. Do not claim guaranteed delivery, exactly-once recording, or tamper evidence.
- Revise the domain glossary so Chat Session Audit Trail means the Logfire-backed, retention-bounded record of observed application stages. Remove the previous implication that every trail is locally durable or independently inspectable during a Logfire outage. Keep the distinction between a Chat Session, a Retrieval Answer, and operational model telemetry.

## Testing Decisions

- Test observable chat behavior and emitted telemetry at the existing ASGI Chat Session seam. Drive real coordination with scripted agents and fake retrieval dependencies, then inspect captured Logfire spans and events without sending data to a live project. Prefer this seam to separate tests of each tracing helper.
- Use the existing chat web answer and lifecycle tests as prior art for request sequences and approval behavior. Use the existing Chat Session, retrieval coordinator, fusion, and Evidence Assembly tests as prior art for scripted models and branch outcomes. Use Logfire's `capfire` fixture or an equivalent in-process exporter for telemetry assertions.
- First run a narrow proof of one preparation and approval cycle. Confirm that separate request traces share the application ID, agent spans are children of their application stage spans, and the expected attributes are readable through Logfire's record shape before expanding instrumentation.
- Cover a corrected rewrite with multiple attempts, policy Declined and Deferred outcomes, an unavailable rewrite, approval, and an abandoned approval. Assert references to the right proposal attempt and the presence or absence of subsequent stages.
- Cover concurrent retrieval branches in different completion orders, duplicates and branch limits, a skipped structural branch, a failed branch, fusion order, Evidence Assembly selection and omission, and structural construction failures. Assert captured decisions match the actual typed results, without asserting a total order for parallel spans.
- Cover a successful Retrieval Answer, a zero-passage answer, an Evidence Assembly failure, and a Chat Agent failure. Assert the rendered text and selected evidence snapshot match the result prepared for the browser; do not assert that the browser received or read it.
- Keep tests deterministic and offline. Do not require a live model provider, Neo4j, Logfire project, browser automation, or timing sleeps. Assert stage names, shared identity, parent-child relationships, statuses, and decision attributes rather than private helper calls or exact exporter timing.
- Verify that instrumentation leaves existing browser output and Chat Session lifecycle unchanged. Inspect one representative large answer for attribute serialization and size before accepting the full snapshot contract.

## Out of Scope

- A local SQLite audit store, audit-specific CLI, browser audit view, or user-facing audit API.
- Durable retention beyond the configured Logfire project policy, automatic archival, backup management, or offline inspection during a Logfire outage.
- Guaranteed telemetry delivery, exactly-once capture, cryptographic tamper evidence, or regulatory compliance claims.
- A single trace held open across human approval or a total sequence number for concurrent retrieval branches.
- Persistent or resumable Chat Sessions, pending approvals, or browser transcripts.
- Claims that the browser received, displayed, or read an answer.
- Raw provider request and response bodies, embedding vectors, full branch score lists, or candidate retrieval routes in custom audit attributes.
- Changes to question policy, retrieval algorithms, fusion ranking, Evidence Assembly selection, answer wording, or existing browser presentation contracts.
- Conversion of trails into Evaluation Data Sets, a run comparison dashboard, or a custom Query API client without a demonstrated need.

## Further Notes

This project deliberately uses Logfire for the application trail and for model and transport diagnostics. ADR 0017 assigns Logfire/OpenTelemetry operational request details in evaluation work; this Chat Session trail does not create an Evaluation Run or a second evaluation versioning system.

The existing Logfire configuration already instruments Pydantic AI and HTTPX, and the CLI forwards structured operational logs. The new work should instrument application decisions that those integrations cannot derive, without repeating every model request or token count.

Logfire documents [manual spans and structured attributes](https://pydantic.dev/docs/logfire/instrument/add-manual-tracing), [Pydantic AI instrumentation](https://pydantic.dev/docs/logfire/integrations/llms/pydanticai/), [SQL and the Query API](https://pydantic.dev/docs/logfire/manage/query-api/), [ingest limits](https://pydantic.dev/docs/logfire/reference/limits/), and [retention](https://pydantic.dev/docs/logfire/manage/logfire-costs/). If long-term retention later becomes required, OpenTelemetry can [export the same captured data to an archive](https://pydantic.dev/docs/logfire/guides/otel-collector/s3-backup/) without adding another application stage-capture path.
