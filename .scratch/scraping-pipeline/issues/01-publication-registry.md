# 01. Publication Registry table & `register-publication` CLI

Status: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Create the Publication Registry: the `publications` SQLite table (schema in the PRD's "Registry & Selector Store SQLite Schema" section) holding publication identity, Politeness Policy fields (crawl delay, max concurrency, robots.txt conformance), discovery configuration JSON, archive cutoff, and circuit-breaker state columns (`validation_paused`, `failure_points`, `healing_in_progress`).

Add a `ca-map register-publication` subcommand (following the existing argparse subparser pattern) that registers a new Publication in the database from CLI arguments. The Publication Bootstrapper trigger is stubbed with a clear seam — its design is deferred to a separate PRD.

Table creation belongs with the existing database initialization so a fresh database gets the new schema. All `DATETIME` columns store ISO 8601 text per the PRD note.

## Acceptance criteria

- [x] `publications` table is created on database initialization with the exact PRD schema, including circuit-breaker columns and defaults
- [x] `ca-map register-publication` registers a Publication with id, name, base URL, politeness fields, and discovery config, and is idempotent-safe (re-registering an existing id fails with a clear error rather than silently overwriting)
- [x] Registered Publications can be queried back with all fields intact
- [x] Bootstrapper invocation point exists as a stub with a note referencing its deferral
- [x] Tests cover table creation, CLI parsing, successful registration, and duplicate-id handling

## Blocked by

None - can start immediately
