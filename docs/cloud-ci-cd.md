# Production CI and authentication preflight

`main` is the production branch. Pull requests and pushes to `main` run the
same deterministic Python and Node checks in `.github/workflows/ci.yml`.
They also build the production Dockerfile, including its pinned llama.cpp
binary, dependency installation and build metadata. The image stays on the
temporary runner. A cold build has a 60-minute limit.

The required branch checks are `tests` and `container-build`. Configure the
`main` branch to require a pull request and both successful checks, require
the branch to be up to date, and enforce the rules for administrators without
a bypass. The workflow alone cannot enforce repository settings.

After both jobs succeed on a push to `main`, `production-preflight` checks out
that push's exact `github.sha`. It uses the `production` GitHub environment.
That environment must allow deployments only from `main`. The job shares the
`production` concurrency group and does not cancel an in-progress run.
GitHub's concurrency queue can replace an older pending run with a newer one;
it does not guarantee that every queued push runs.

This phase validates credentials. It runs `bottle app status` and SSH `true`.
It has no application deploy, stop, reload, shutdown or rollback command.
GitHub may describe environment jobs as deployments, but this job does not
release application code. Its summary reports the candidate SHA separately
from the current checkout SHA observed through Bottle. An unavailable current
SHA is reported as unavailable. A successful status read does not establish
application health or release readiness.

## Production environment configuration

Store these values in the GitHub environment named `production`:

| Kind | Name | Purpose |
| --- | --- | --- |
| Variable | `BOTTLE_INSTANCE_HOSTNAME` | `akaisenghor.bottle.cloud`, a bare DNS hostname |
| Variable | `BOTTLE_APP_NAME` | `california-knowledge-map` |
| Secret | `BOTTLE_API_TOKEN` | Dedicated owner-scoped Bottle API credential for the preflight |
| Secret | `BOTTLE_SSH_PRIVATE_KEY` | Dedicated CI Ed25519 private key authorized for the sudo-enabled host account |
| Secret | `BOTTLE_SSH_KNOWN_HOSTS` | Verified OpenSSH host-key entries for the same instance hostname |

Dedicated credentials make rotation and revocation independent of the owner's
local login. They do not limit authority to this application. Bottle's owner
API credential covers the zone, and the host account has sudo access. The
workflow uses that authority only for read-only status and SSH `true`. The
user explicitly approved these broad credential scopes. Both variables and
all three secrets are configured in the `production` GitHub environment.

The dedicated 90-day API token is named
`ca-map-github-production-2026-10-13`, token ID `2`, and expires at
`2027-01-11T19:55:25Z`. Authenticated local checks with the new token confirmed
the expected app. The new Ed25519 key's restricted public-key entry was
installed on the host, and SSH `true` succeeded with the verified host key.
The hosted GitHub Actions production preflight has not run yet. Local
credential checks do not establish a successful hosted workflow or release.

Obtain the host key through an already authenticated channel or compare its
fingerprint with the instance administrator. An unverified `ssh-keyscan`
response is insufficient. SSH targets `host@BOTTLE_INSTANCE_HOSTNAME` on port
22, matching Bottle's host-user convention. It requires the stored host key,
disables password and interactive authentication, and executes only `true`.

Keep provider credentials and runtime secret grants in Bottle. This workflow
does not need OpenRouter, Logfire, Typesafe or Neo4j credentials. It does not
run paid model evaluations. Production continues to use
`google/gemma-4-26b-a4b-it` with exclusive provider `deepinfra/fp8`.

The Bottle CLI is installed through uv from commit
`6ea27634d1cbfc1b29caec29b53b76d919201b97`. That CLI loads credentials from
`~/.cloud_in_a_bottle_cli/compute_space_cli.toml`; it has no token environment
flag. `scripts/production_preflight.py` writes its verified multi-instance
TOML format with alias `production`. It creates the directory with mode `0700`
and the config with mode `0600`. It refuses any existing config directory and
removes its own config in `finally`. SSH key and known-host files use mode
`0600` inside a temporary directory with mode `0700`, which is removed on
exit. The runner's `HOME` stays unchanged.

Only the last preflight step receives the three secrets. The script passes
their values through files rather than command arguments, removes `BOTTLE_*`
values from child process environments, captures Bottle and SSH output, and
withholds raw remote responses from logs. It prints fixed error messages and
validated SHA fields. No credential file is uploaded as an artifact. A
force-killed runner may interrupt cleanup; GitHub-hosted runners are temporary.

Rotate or revoke the dedicated credentials when their owner, purpose or
expiry changes. Replace the environment secrets through a protected channel.
Rotate the API token and update `BOTTLE_API_TOKEN` before January 11, 2027.
Update the pinned known-host entries only after independently verifying the
new host key. Missing, expired or denied credentials fail the preflight.

## Local verification

The preflight is intended for an empty GitHub-hosted runner. It fails before
reading credentials unless the event is a push to `main` and `GITHUB_SHA`
matches the checked-out commit. Do not run it against your ordinary Bottle
login configuration.

Its deterministic tests exercise event and checkout rejection, private file
permissions, TOML escaping, read-only commands, strict SSH host verification,
credential cleanup after failures and timeouts, refusal to overwrite existing
config, and suppression of secret-bearing errors:

```sh
uv run --no-sync pytest -q tests/test_production_preflight.py
uv run --no-sync ruff check scripts/production_preflight.py tests/test_production_preflight.py
uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs
uv run --no-sync pytest -q tests
docker build --build-arg APP_REVISION="$(git rev-parse HEAD)" --tag ca-map-ci .
```

These checks make steps 1 through 4 reviewable: the production branch,
required CI policy, a success-dependent job for an exact main commit, and
production API/SSH authentication. The user chose manual releases initially.
Step 5, automatic application deployment and its shutdown, health, reload and
rollback behavior, is not implemented.
