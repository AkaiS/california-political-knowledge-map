# 07 — Inspect and compare Chat Session trails

Labels: ready-for-agent

## Parent

[Logfire Chat Session Audit Trail](../PRD.md)

## What to build

Give maintainers a documented way to find one Chat Session's application observations in Logfire, follow the related model traces, and compare sessions across code and configuration changes. The inspection guidance distinguishes saved facts from missing or expired telemetry and makes the configured retention visible. It does not add another audit store or command-line read path.

## Acceptance criteria

- [ ] Document a Logfire SQL search by application Chat Session ID that returns named application stages with their times, statuses, and trace IDs, allowing navigation into each request trace.
- [ ] Document queries or filters for observation time, code revision, Model Deployment, Retrieval Answer presence, and failed stage. The query contract uses attributes emitted by the preceding tickets.
- [ ] Explain that separate preparation and approval traces share an application ID, while parallel retrieval branches have no total completion order.
- [ ] Explain Logfire's configured retention and best-effort delivery. A missing Retrieval Answer observation receives no inferred closing cause or browser-delivery claim.
- [ ] Describe how a maintainer can save the useful search in Logfire. No custom Query API client, local audit database, or audit CLI is introduced.
- [ ] Offline tests or captured-span assertions verify the fields and identities that the documented queries depend on. No live Logfire project, browser, or computer-use verification is required.

## Blocked by

- [04 — Trace structural construction](04-trace-structural-construction.md).
- [06 — Trace the prepared Retrieval Answer](06-trace-the-prepared-retrieval-answer.md).
