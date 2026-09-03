# Secrets

Credentials are never committed and never written to `.env`. They live in the
OS keychain, which survives worktrees, does not travel in a diff, and does not
appear in the process table or shell history.

## Logfire

The Logfire write token is what makes a run inspectable afterwards. A run
without one produces no trace, so `setup_telemetry()` raises
`TelemetryNotConfiguredError` and the command stops before it does any work.
This is deliberate: an unobservable pipeline or Evaluation Run teaches nothing
and has to be repeated anyway.

Store the token once, with `keyring`'s own CLI:

```bash
uv run keyring set logfire dev-telemetry
```

Check where a token is coming from, or whether one is found at all:

```bash
uv run ca-map telemetry status
```

`ca-map telemetry` is the only command exempt from the check, because it is what
you run when the check has stopped everything else.

### Resolution order

1. `LOGFIRE_TOKEN` in the environment — for CI and one-off shells.
2. The OS keychain, under service `logfire`, username `dev-telemetry`.
3. `.logfire/logfire_credentials.json` written by `logfire projects use`. This
   one is read relative to the working directory, which is why it is the last
   resort rather than the first: a command issued from a subdirectory or a
   fresh worktree silently loses it.

The resolved token is passed to `logfire.configure()` explicitly, so the
directory a command runs from cannot change whether it is observed.

The token and the project it reports to are resolved once, at startup, and
kept for the life of the process — a report is written long after the run
began, and re-reading the sources then could name a project the run never
reported to. They are resolved together, from one source. A credentials file names the project for its own token; a token from
the environment or the keychain has no project of its own and takes the one
`LOGFIRE_PROJECT_URL` declares, or none. They are never mixed: a stale
credentials file naming a different project would otherwise make reports
advertise a trace under a project it was never sent to.

### Running without observability

`KNOWLEDGE_MAP_ALLOW_UNTRACED=1` skips the check for a single run. Use it for
an offline machine, and expect no trace to inspect afterwards.

### `LOGFIRE_PROJECT_URL`

Not a secret, and belongs in `.env`. It is a fallback, not the source of
truth: Logfire validates the write token against the API and learns which
project it belongs to, and that answer — being the token's own — wins over
this one. The declaration only matters when Logfire could not establish the
project, such as on a machine that cannot reach the API. It is asserted by
whoever set it and is never checked, so a wrong value can only ever produce a
link where Logfire itself supplied none.

Without any of them a run is still traced, but a report records only the bare
`trace_id` and nothing can turn that id into a link.

`ca-map telemetry status` prints the project a run would link to, so a blank
one is visible before a run rather than after.

## OpenRouter

`OPENROUTER_API_KEY` is supplied from the environment at launch. It is
deliberately absent from `.env`.
