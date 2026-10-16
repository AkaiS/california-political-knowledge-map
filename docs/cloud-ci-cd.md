# Production CI and authentication preflight

`main` is the production branch. `.github/workflows/ci.yml` runs each kind of
work once:

- On a pull request, `tests` runs the deterministic Python and Node checks on
  the exact PR head, then `review-gate` checks that head's review policy.
  Greptile is required unless the PR title or description contains
  `[skip greptile]`.
- On a push to `main`, `tests` is skipped. `review-gate` verifies that the
  merge commit's tree is identical to the reviewed PR head and that the head's
  `tests` succeeded, so the merged tree has already been tested. In parallel,
  `image-inputs` compares the push's `before` commit with its SHA over the
  paths that `.dockerignore` re-includes, which are the only files that can
  change the image.
- If image sources changed, `container-build` builds the production Dockerfile
  at that push SHA, including its pinned llama.cpp binary, dependency
  installation and build metadata, while `production-preflight` checks
  credentials in parallel. Otherwise the build, preflight and release are
  skipped: changes to CI, scripts, tests, docs, work items and local-only
  tooling leave production as it is.

`scripts/image_inputs.py` reads the paths from `.dockerignore`, so adding a
path to the build context also makes it trigger releases. The file must stay
an allowlist that starts with `*`. A missing `before` commit counts as a
change, and a failed comparison fails the job, which blocks that release.

The image's `APP_REVISION` records the push SHA. The image stays on the
temporary runner; Bottle builds its own image from source during the release.
The CI build exists so a broken build fails before the release stops the
running application. A cold build has a 60-minute limit.

The required branch checks are `tests` and `review-gate`, both from the GitHub
Actions app, ID `15368`. Configure the `main` branch to require a pull request
and both successful checks, require the branch to be up to date, and enforce
the rules for administrators without a bypass. The required up-to-date rule
makes the reviewed head the integration baseline, which is what lets `main`
reuse the PR's test results. The workflow alone cannot enforce repository
settings.

On a push to `main` that changes image sources, `production-preflight` runs
after `review-gate` succeeds and checks out that push's exact `github.sha`. It uses the `production` GitHub
environment. That environment must allow deployments only from `main`. The job
shares the `production` concurrency group and does not cancel an in-progress
run. GitHub's concurrency queue can replace an older pending run with a newer
one; it does not guarantee that every queued push runs.

This phase validates credentials. It runs `bottle app status` and SSH `true`.
It has no application deploy, stop, reload, shutdown or rollback command.
GitHub may describe environment jobs as deployments, but this job does not
release application code. Its summary reports the candidate SHA separately
from the current checkout SHA observed through Bottle. An unavailable current
SHA is reported as unavailable. A successful status read does not establish
application health or release readiness.

## Build review gate

`scripts/review_gate.py` reads GitHub metadata through the runner's `gh` CLI.
By default, it requires the external `Greptile Review` check from app ID
`867647`, slug `greptile-apps`, to complete successfully for the exact pull
request head.
The latest summary must come from bot ID `165735046`, login
`greptile-apps[bot]`, contain exactly one
`<!-- greptile_confidence_score:5 -->` marker, and identify that full head SHA
in its `Last reviewed commit` link. Its update must follow the check's start.
A successful Greptile check with a score of 3/5 rejects the build.

For a change that does not need Greptile, include the exact marker
`[skip greptile]` in the PR title or description when creating it. For example,
use the title `docs: rename domain glossary [skip greptile]`.
The gate then requires no Greptile check, summary, or confidence score.
`.greptile/config.json` also sets this marker as `ignoreKeywords`, which
[Greptile documents as skipping reviews for matching PR titles or descriptions](https://www.greptile.com/docs/code-review/greptile-config-reference#filters).
The CI gate itself only reads review evidence; it never invokes Greptile.
Adding the marker later cannot undo a review that already started.

PR title or description edits rerun CI so adding or removing the marker
rechecks the policy. The gate reads the current PR metadata, verifies the
policy did not change while it collected evidence, and applies the same
opt-out when checking the merged PR on `main`. Keep the marker through merge.

Every review thread must be resolved, including outdated threads. A review
that still requests changes also rejects the build. The gate reads all pages
of reviews, threads, checks and commit statuses, plus summary comments when
Greptile is required. Every other visible
check and status must complete successfully. Neutral, skipped, cancelled and
failed checks do not count as green. The gate excludes only its own
`review-gate`, `image-inputs`, `container-build`, `production-preflight` and
`release` jobs after checking
the Actions app identity, run repository, run head SHA and authoritative
workflow path `.github/workflows/ci.yml`. Same-named jobs from other apps or
workflows must succeed. A successful `tests` job from this CI workflow is
required independently of the workflow's `needs` dependency.

Missing or stale review evidence and pending checks wait up to 30 minutes,
with a 30-second polling interval. A definitive score below 5/5, unresolved
feedback, failed check, malformed evidence or API failure rejects the build.
The gate rechecks the pull request head during each poll and immediately
before success. A new head requires a new workflow run and, unless opted out,
a new Greptile review.

A push to `main` must correspond to exactly one associated merged pull
request whose `merge_commit_sha` equals the push SHA. GitHub commit metadata
must show an identical tree for that merge and the reviewed PR head. The gate
revalidates the merged PR's review and head checks, including its `tests`
job, then requires every other check on the main commit to be green. The
skipped `tests` job on the main commit is neither required nor counted. This
accepts the exact reviewed merge without waiting for a Greptile review on a
merge SHA that Greptile does not review.
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
workflow use the same review policy and explicit opt-out as other pull requests.

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
uv run --no-sync pytest -q tests/test_image_inputs.py tests/test_production_release.py
uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs
uv run --no-sync pytest -q tests
```

The review-gate tests cover the explicit Greptile opt-out, retained tests and
feedback requirements, policy changes during polling, trusted score and commit
markers, stale and missing evidence, unresolved outdated threads, requested changes, other
checks and statuses, API pagination, workflow ownership, fork event context,
head changes during polling, bounded timeout, merged PR provenance and the
success-dependent workflow ordering. No local container build is needed to
verify this policy. GitHub runs the image build on `main` after the gate
succeeds.

These checks cover the production branch, required CI policy, review before
build, a success-dependent job for an exact main commit, and production
API/SSH authentication.

## Approved release

The `release` job runs after `container-build` and `production-preflight`
succeed on each push to `main` that changes image sources, and waits in the
`production-release` GitHub environment until the owner approves it from the
run's **Review deployments** button. Merging alone never releases. An
unapproved run can be left waiting or rejected.

`scripts/production_release.py` reuses the preflight's credential handling and
follows the manual sequence in [cloud deployment](cloud-deployment.md):

1. Refuse if a newer commit on `main` changes image sources relative to the
   candidate. An approval that arrives after such a merge would otherwise roll
   production back. Newer merges that leave image sources alone never release
   on their own, so they do not block the candidate that carries their image.
2. Read the current Bottle checkout. If it already equals the candidate,
   change nothing and succeed only if `/health/ready` returns 200 within 15
   minutes. Bottle reports the checkout during builds too, so a retry after a
   readiness failure cannot pass on the SHA alone.
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
- the same two variables as `production`;
- its own three secrets, created by `scripts/provision_release_credentials.sh`.

GitHub cannot copy secrets between environments, so the release has its own
credentials. The script runs on the owner's machine with the owner's Bottle
and SSH logins. It creates a 90-day owner-scoped Bottle token named
`ca-map-github-release-<date>` and a new Ed25519 key. The key is authorized with
`restrict`, which disables forwarding and terminals but allows the release
commands. The script confirms that the key can run `df` and that the token can
read `/api/apps`, then passes all three values to `gh secret set` on stdin. No
value is printed, and the temporary files are deleted on exit. Run it again to
rotate both before the token expires, then delete the old token with
`bottle tokens delete` and remove the old key line from `authorized_keys`.

The zone's host key comes from `ssh-keyscan` and is trusted on first use. No
authenticated channel for it is available. The script pins that key for the
session that authorizes the new SSH key, so the stored known-hosts entry
belongs to the host that accepted it.
