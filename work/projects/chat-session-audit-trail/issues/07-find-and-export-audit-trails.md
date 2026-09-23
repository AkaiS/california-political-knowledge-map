# 07 — Find and export Chat Session Audit Trails

Labels: ready-for-agent

## Parent

[Chat Session Audit Trail](../PRD.md)

## What to build

Give maintainers a CLI for locating and exporting saved trails across sessions. Filters support comparisons by time, Retrieval Answer presence, code revision, Model Deployment, and failed stage. JSON export preserves the records that SQLite actually saved, without adding a completion or failure claim to a trail that lacks a Retrieval Answer.

## Acceptance criteria

- [ ] The CLI lists saved session IDs with their observation times and can filter by time, Retrieval Answer presence, code revision, Model Deployment, and failed stage.
- [ ] The CLI shows one session's saved stage names, times, results, and stage-specific metadata without a fabricated sequence number for parallel stages.
- [ ] JSON export retains the application session ID, unique stage IDs, stage metadata, and any Retrieval Answer snapshot without inventing missing records.
- [ ] Read commands work without starting chat, models, Neo4j, or Logfire; they do not initialize or mutate the database while inspecting it.
- [ ] An absent or unreadable audit database produces a clear error without changing that database.
- [ ] CLI-dispatch tests use a temporary audit database containing multiple sessions and a trail without a Retrieval Answer to cover list, filters, show, and export.

## Blocked by

- [01 — Open and inspect a Chat Session Audit Trail](01-open-and-inspect-a-chat-session-audit-trail.md).
