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

### Running without observability

`KNOWLEDGE_MAP_ALLOW_UNTRACED=1` skips the check for a single run. Use it for
an offline machine, and expect no trace to inspect afterwards.

### `LOGFIRE_PROJECT_URL`

Not a secret, and belongs in `.env`. Without it a report still records the
`trace_id` of the run, but nothing can turn that id into a link.

## OpenRouter

`OPENROUTER_API_KEY` is supplied from the environment at launch. It is
deliberately absent from `.env`.
