# 10. `ca-map heal-selectors` CLI (`--retry`, `--context`)

Status: ready-for-agent

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Add a `ca-map heal-selectors` subcommand giving developers the loop-exhaustion escape hatches from the PRD:

- `--retry --publication <id>`: fetch the publication's failed Selector Proposal from the database, mark it `REJECTED` (with `resolved_at`), and re-run the Generator/Critic loop on the failed article, passing the previously failed selectors to the Generator as negative context so it avoids regenerating them.
- `--publication <id> --context "..."`: re-run the loop with developer-supplied guidance appended to the Generator's prompt.

Any manual invocation implicitly bypasses the unresolved-proposal check and resets/bypasses the `healing_in_progress` flag for that Publication, so developers never have to resolve rows or clear flags by hand before retrying. Missing or unknown publication ids fail with a clear error.

## Acceptance criteria

- [ ] `--retry` resolves the old proposal as `REJECTED` and re-runs healing with the failed selectors injected as negative context
- [ ] `--context` propagates the developer's hint into the Generator prompt verbatim
- [ ] Manual invocations bypass the unresolved-proposal guard and stale `healing_in_progress` flags
- [ ] Invalid or missing `--publication` values produce a clear CLI error
- [ ] Tests cover parser options, negative-context and custom-context propagation (mocked LLM), guard bypasses, and error handling

## Blocked by

- [08-selector-healing-pipeline.md](./08-selector-healing-pipeline.md)
