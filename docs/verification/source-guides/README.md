# Source Guides verification evidence

The project-local verification workflow is [.agents/skills/verify-source-guides/SKILL.md](../../../.agents/skills/verify-source-guides/SKILL.md). Its four-feature map records browser and HTTP paths separately.

- [2026-10-12 proof](2026-10-12-proof/manifest.json) passed the real HTTP missing-reference assessment, saved-list, reopening, SQLite, restart, and cleanup checks. [Terminal response](2026-10-12-proof/terminal.json), [restart response](2026-10-12-proof/persisted.json), and [cleanup](2026-10-12-proof/cleanup.json) retain the results. The user explicitly authorized production Logfire telemetry before this run.
- [Initial preflight failure](2026-10-12-generation/cleanup.json) records cleanup after the sandbox denied loopback binding. It is a failed attempt, not user-journey proof.
- `build-result.json` records the successful wheel and source-distribution build, with hashes of the temporary outputs before they were removed.

Browser behavior, successful article retrieval and reading, multiple independent questions, updates, cancellation, and interruption remain untested. Existing Neo4j and model services supplied the runtime. This evidence does not establish first-install readiness or complete telemetry delivery during shutdown.
