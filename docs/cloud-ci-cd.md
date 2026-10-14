# Production CI and authentication preflight

`main` is the production branch. Pull requests and pushes to `main` run the
same deterministic Python and Node checks in `.github/workflows/ci.yml`.
The test, review-gate and build jobs check out the exact reviewed PR head on
pull requests, and the exact push SHA on `main`. PR jobs test and build that
reviewed head. The required up-to-date branch rule supplies the integration
baseline before merging. The image's `APP_REVISION` records the same SHA.
Only after `tests` and `review-gate` succeed does `container-build` build the
production Dockerfile, including its pinned llama.cpp binary, dependency
installation and build metadata. The image stays on the temporary runner.
A cold build has a 60-minute limit.

The required branch checks are `tests`, `review-gate` and `container-build`,
all from the GitHub Actions app, ID `15368`. Configure the
`main` branch to require a pull request and all three successful checks, require
the branch to be up to date, and enforce the rules for administrators without
a bypass. The workflow alone cannot enforce repository settings.

After all three jobs succeed on a push to `main`, `production-preflight` checks out
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

## Build review gate

`scripts/review_gate.py` reads GitHub metadata through the runner's `gh` CLI.
It requires the external `Greptile Review` check from app ID `867647`, slug
`greptile-apps`, to complete successfully for the exact pull request head.
The latest summary must come from bot ID `165735046`, login
`greptile-apps[bot]`, contain exactly one
`<!-- greptile_confidence_score:5 -->` marker, and identify that full head SHA
in its `Last reviewed commit` link. Its update must follow the check's start.
A successful Greptile check with a score of 3/5 rejects the build.

Every review thread must be resolved, including outdated threads. A review
that still requests changes also rejects the build. The gate reads all pages
of comments, reviews, threads, checks and commit statuses. Every other visible
check and status must complete successfully. Neutral, skipped, cancelled and
failed checks do not count as green. The gate excludes only its own
`review-gate`, `container-build` and `production-preflight` jobs after checking
the Actions app identity, run repository, run head SHA and authoritative
workflow path `.github/workflows/ci.yml`. Same-named jobs from other apps or
workflows must succeed. A successful `tests` job from this CI workflow is
required independently of the workflow's `needs` dependency.

Missing or stale review evidence and pending checks wait up to 30 minutes,
with a 30-second polling interval. A definitive score below 5/5, unresolved
feedback, failed check, malformed evidence or API failure rejects the build.
The gate rechecks the pull request head during each poll and immediately
before success. A new head requires a new workflow run and review.

A push to `main` must correspond to exactly one associated merged pull
request whose `merge_commit_sha` equals the push SHA. GitHub commit metadata
must show an identical tree for that merge and the reviewed PR head. The gate
revalidates the merged PR's review and head checks, then requires green checks
for the main commit too. This accepts the exact reviewed merge without
waiting for a Greptile review on a merge SHA that Greptile does not review.
Direct pushes, arbitrary reviewed ancestors, ambiguous merged PRs and merges
that introduce a different tree fail closed. Requiring the PR to be up to date
before merging keeps the reviewed tree equal to the merged tree.

The review job receives only a read-only `GITHUB_TOKEN`, scoped to contents,
checks, commit statuses, Actions run metadata, pull requests and issues. It has
no production environment or deployment secrets, including on fork pull
requests. API
errors withhold raw output. The gate does not post, resolve, approve or change
reviews. GitHub metadata can change after the last read; branch protection and
a fresh run remain necessary when a PR head changes. Changes to the gate or
workflow require the same external review as other pull request changes.

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
uv run --no-sync pytest -q tests/test_review_gate.py
uv run --no-sync ruff check scripts/review_gate.py tests/test_review_gate.py
uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs
uv run --no-sync pytest -q tests
```

The review-gate tests cover trusted score and commit markers, stale and
missing evidence, unresolved outdated threads, requested changes, other
checks and statuses, API pagination, workflow ownership, fork event context,
head changes during polling, bounded timeout, merged PR provenance and the
success-dependent workflow ordering. No local container build is needed to
verify this policy. GitHub runs the image build after the gate succeeds.

These checks cover the production branch, required CI policy, review before
build, a success-dependent job for an exact main commit, and production
API/SSH authentication.

## Approved release

The `release` job runs after `production-preflight` on each push to `main` and
waits in the `production-release` GitHub environment until the owner approves
it from the run's **Review deployments** button. Merging alone never releases.
An unapproved run can be left waiting or rejected.

`scripts/production_release.py` reuses the preflight's credential handling and
follows the manual sequence in [cloud deployment](cloud-deployment.md):

1. Refuse unless the candidate SHA is still the tip of `main`. An approval that
   arrives after a newer merge would otherwise roll production back.
2. Read the current Bottle checkout. If it already equals the candidate, stop
   without changing anything.
3. Refuse if the root filesystem is more than 80% used.
4. Over SSH, set the container's restart policy to `no` and shut supervisor
   down, then poll until the container has stopped, for up to 180 seconds.
5. Pin the app's remote to the candidate SHA through `set_app_remote`.
6. Run `bottle app reload --update --wait`, with a 75-minute limit for a
   llama.cpp rebuild.
7. Require Bottle to report the candidate SHA and `/health/ready` to return 200
   within 15 minutes.

There is no automatic rollback. A failure after step 4 leaves the app stopped
or on a partial update; the job summary names the stage reached and the
previous SHA. Recover with the manual update in
[cloud deployment](cloud-deployment.md). Output from Bottle and SSH stays
withheld, as in the preflight.

Configure the `production-release` environment with:

- the owner as a required reviewer, with self-review allowed;
- deployment branches limited to `main`;
- the same two variables and three secrets as `production`. GitHub cannot
  copy secrets between environments, so they are entered again.

The CI SSH key must be allowed to run the shutdown, state and disk commands,
not only `true`. A forced-command restriction on its authorized-key entry
makes the disk check in step 3 fail before anything is stopped.
