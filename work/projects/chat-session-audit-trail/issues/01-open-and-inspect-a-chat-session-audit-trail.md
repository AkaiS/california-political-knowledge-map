# 01 — Open and inspect a Chat Session Audit Trail

Labels: ready-for-agent

## Parent

[Chat Session Audit Trail](../PRD.md)

## What to build

When a person asks the first question in a Chat Session, assign one application audit ID and start a session-start Audit Stage Record in a separate local SQLite database. Let a maintainer show that saved record by audit ID through the CLI. The record captures the original question, observation time, effective code and prompt revisions, resolved Model Deployments, fusion and context settings, and the available coverage snapshot. Audit storage must not become a condition for using chat.

## Acceptance criteria

- [ ] A first valid question starts one trail with an application-generated ID that remains available to later Chat Session stages and Logfire correlation.
- [ ] The session-start record captures the effective values named above, including the observation time of coverage counts already measured at startup. It makes no extra corpus or index query for auditing.
- [ ] The separate SQLite store accepts insert-only Audit Stage Records with unique stage IDs, a session ID, name, start and end times, result status, schema version, and stage-specific metadata. Conflicting ID reuse is rejected.
- [ ] Each record starts a direct background SQLite insert. There is no queue, commit wait on the chat path, retry subsystem, or audit failure that prevents the question from proceeding.
- [ ] An insert or audit-store initialization failure is reported operationally while chat remains usable. A committed record survives application restart; an in-flight insert has no durability claim.
- [ ] A maintainer can show one saved trail by ID through the CLI without starting chat, models, Neo4j, or Logfire and without mutating the database while reading.
- [ ] ASGI-level tests drive a real Chat Session with scripted agents and a temporary audit database. CLI-dispatch tests show the saved session-start record. Background completion is controlled without timing sleeps.

## Blocked by

- None — can start immediately.
