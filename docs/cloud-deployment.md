# Cloud deployment runbook

The public app is live at [https://california-knowledge-map.akaisenghor.bottle.cloud/](https://california-knowledge-map.akaisenghor.bottle.cloud/) on the $20 instance,
frozen at `0444a3cffb7c1cb09f220fb7e36b8c45e5081563`. It uses only
`google/gemma-4-26b-a4b-it` through exclusive `deepinfra/fp8`, paid with the
existing OpenRouter key. No additional Google key is required. The user requires
this model to remain fixed; a different model or provider requires direct user
instruction. No automatic model or provider fallback is configured.

The final anonymous guide passed in 17.174719 seconds without owner
authorization: allowed assessment, relevance order, one linked expected
CalMatters AB 1751 article, completed search, `partial: false` and no disclosures.
The saved guide reopens unchanged for its owner; a foreign visitor receives
404, and all seven earlier attempts remain in history. Live routing is
`public_paths = ["/"]`. Peak runtime memory was 1.745 GiB with zero swap and
OOM events. Public assets, privacy, bounds and persistence checks passed.
[Current implementation and evidence](../work/projects/cloud-in-a-bottle-deployment/IMPLEMENTATION.md).

Backup configuration is deferred at the user's explicit request. It is not a
publication prerequisite in this phase; recovery readiness is not established.

## Runtime and release provenance

The manifest reserves 5 GiB and three CPUs for the app, and 2 GiB for builds.
Compile concurrency is one. The runtime includes Neo4j Community 2026.07.1,
Temurin 25.0.3 Java, llama.cpp `dee2a846b82f15d27f84a48fa387cb53e0d99c25`,
Python 3.13.5, uv 0.12.21 and supervisord 4.3.0. Base images use immutable
digests. The upstream llama.cpp embedded server UI fetch still uses an unpinned
asset URL; its server is loopback-only. Embeddings use the fixed GGUF with one
request at a time and two CPU threads.

The target's rootless Podman mapping was verified: container UID/GID `0:0`
corresponds to host `1000:1000` for the app's writable persistence. Only HTTP
8080 is published to a host loopback port. Neo4j Bolt uses container loopback;
its HTTP interface is disabled. Embeddings listen on loopback 8081.

For a local candidate build:

```sh
docker build --build-arg APP_REVISION="$(git rev-parse HEAD)" -t ca-map-candidate .
```

The build excludes credentials, databases, weights, scratch output and Git
history. Bottle does not supply `APP_REVISION`; record the actual remote
checkout SHA and compare `/app/deployment/build-metadata.json` source hashes
with that frozen source. All 383 tracked source hashes match the live release;
the source digest is
`1f2760347408d395426273711ae1b46663b1523e3d0b913c6d6dfc6f6d734096`.
A dirty local image is a development candidate.

## Corpus installation and ordinary updates

The real seed `2026-10-12-real-corpus-01` is already installed. Ordinary code
updates retain the seed, `recovery/installed-release.json`, graph, saved guides
and admission counters. Do not replace or recreate this seed during a code
reload. The installed marker identifies the initial corpus import, while the
verified checkout identifies the running code revision.

For a new empty app, make a sanitized export and pair it with a same-version
offline Neo4j dump that excludes the system database:

```sh
uv run scripts/export_deployment_corpus.py --source document_store.db --release RELEASE
uv run deployment/make_seed_manifest.py /absolute/path/to/seed \
  --corpus-id RELEASE --application-revision COMMIT_SHA \
  --sqlite-export-manifest /absolute/path/to/export/manifest.json
```

Community's graph dump requires a stopped database and an agreed maintenance
window. The SQLite export uses read-only backup, clears local guides, attempts
and admission state, and vacuums private free pages. Transfer only the graph
dump, sanitized database, export `manifest.json`, embedding GGUF and
`release.json` through authenticated SSH into the empty app's
`$BOTTLE_APP_DATA_DIR/recovery/seed/` before its first start.
The embedding artifact SHA-256 is
`b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63`.

Bootstrap verifies checksums, embedding conversion, corpus/guide schemas,
SQLite integrity and Neo4j version, then restores once and creates fresh
Neo4j authentication. Partial unmarked installations fail closed. Model checksum
and SQLite integrity are checked on later starts. Corpus replacement needs a
separate rehearsed graph replacement and corpus-table refresh preserving cloud
visitor ownership. Keep immutable release exports off the server.

## Secrets and request limits

Secrets service `==0.1.0` grants the owner's existing names:
`OPENROUTER_KEY`, `TYPESAFE_API_KEY`, `LOGFIRE_API_KEY`, `NEO4J_PASSWORD`,
`OPENROUTER_MODEL`, `OPENROUTER_PROVIDERS`, `LOGFIRE_URL` and
`CLOUD_PUBLIC_ORIGIN`. Bootstrap maps the three existing provider/telemetry
names to `OPENROUTER_API_KEY`, `LOGFIRE_TOKEN` and `LOGFIRE_PROJECT_URL` in the
application environment. It creates no duplicate credential entries.
The exact origin has no path or trailing slash. Fresh Neo4j passwords require
at least 16 characters. Missing values or denied grants fail startup without
logging values. The injected Bottle app token stays inside the runtime.

The dedicated key's $5 limit and monthly reset are verified. The user's selected
cloud configuration is paid `google/gemma-4-26b-a4b-it`, exclusive provider
`deepinfra/fp8`, funded through the existing OpenRouter key and credits. No
additional Google or DeepInfra key is required. Published endpoint rates are
$0.07 per million input tokens and $0.34 per million output tokens.
[Paid route evidence](../work/projects/cloud-in-a-bottle-deployment/reports/gemma-paid-route-2026-10-12.md).

Question assessment now uses `NativeOutput(QuestionAssessment, strict=True)`
only for OpenRouter Gemma. The existing library transformer emits native JSON
Schema with every property required, explicit null date unions and the fixed
reading-order enum. Guidance keeps its original output-tool mode; prompts,
domain validators, zero output retries, other deployment modes, Jev thresholds
and CPU embeddings are unchanged. String-length and cross-field rules still
use application validation. One isolated actual same-model/same-provider native
assessment passed before this release, followed by the clean anonymous guide.
[Strict integration review](../work/projects/cloud-in-a-bottle-deployment/reports/strict-gemma-review-2026-10-13.md).

The dedicated key's $5 monthly limit and `include_byok_in_limit: true` are
verified. The final anonymous smoke cost $0.00135362 through the selected paid
route. Funded key usage is $0.00629775;
historical BYOK usage is $0.00601500,
unchanged during the selected paid tests. Observed combined usage is
$0.01231275 and remaining monthly allowance is $4.98768725 with a $5 limit,
monthly reset and BYOK counting enabled.
The allowance excludes Jev, Logfire, credit purchase fees and unrelated provider
usage. Earlier trial snapshots are retained in the linked evidence reports.
[Key limit fields](https://openrouter.ai/docs/api/api-reference/api-keys/update-keys).

Earlier nullable/tool enum failures and the temporary Gemini trial are retained
in the historical reports. Gemini is not selected or an approved fallback.
Structural subtype abstention at 0.73 below 0.80 was existing policy and was not
tuned for deployment. Telemetry initializes before agents.
[Hosted diagnosis](../work/projects/cloud-in-a-bottle-deployment/reports/hosted-http-verification-2026-10-12.md).

Cloud model requests default to 60 seconds, two transport attempts and a
15-second rate-limit wait cap. Retrieval retains its 180-second deadline; the
complete question deadline is 240 seconds. One web worker enforces the shared
admission limits. Uvicorn proxy rewriting is disabled. The router source, actual
Caddy forwarding configuration and observed app socket peer support the exact
setting `CLOUD_TRUSTED_PROXIES=127.0.0.1/32`. It is stored in Secrets and
verified active in the current public web process. No broader network is
trusted.
[Proxy review](../work/projects/cloud-in-a-bottle-deployment/reports/trusted-proxy-review-2026-10-12.md).

## Frozen deployment and updates

Always target `akaisenghor.bottle.cloud`. The installed Bottle parser and Git
implementation support a full commit after `@`; exact detached checkout was
verified on this instance. For the first deployment of an absent app:

```sh
bottle app deploy https://github.com/AkaiS/california-political-knowledge-map@COMMIT_SHA \
  --name california-knowledge-map --grant-permissions-v2 --wait \
  --instance akaisenghor.bottle.cloud
```

Review the manifest's individual service grants before approving them. The
source repository is public and does not need owner GitHub OAuth.

For this existing app, first stop admission and shut down services cleanly.
Bottle's ordinary stop allows ten seconds before forced termination; Neo4j
needed about eleven seconds in rehearsal. Open an authenticated instance shell:

```sh
bottle instance ssh --instance akaisenghor.bottle.cloud
```

Inside that shell, use the installed Podman environment:

```sh
cd ~/openhost
/home/host/.pixi/bin/pixi run -e dev podman update --restart=no \
  openhost-california-knowledge-map
/home/host/.pixi/bin/pixi run -e dev podman exec openhost-california-knowledge-map \
  /app/.venv/bin/supervisorctl -c /app/deployment/supervisord.conf shutdown
/home/host/.pixi/bin/pixi run -e dev podman inspect \
  --format '{{.State.Running}}' openhost-california-knowledge-map
```

The installed Podman supports `update --restart=no`. This temporary adjustment
must precede shutdown because the platform's `unless-stopped` policy otherwise
restarts a clean supervisor exit. Verify the policy change and stable stopped
state before reloading. Bottle creates the replacement container with its
normal policy. If shutdown has not finished within 150 seconds plus observation
margin, inspect this app's status instead of forcing a reload. The supervisor
stops web, embeddings and Neo4j in order. A confirmed stopped container avoids
runtime/build competition on the eight-GB host. The earlier private Gemini reload
verified this sequence with clean service exits, no automatic-restart race and
unchanged saved guide/attempt state.

Resolve this app's unique ID from authenticated `/api/apps`, matching its exact
name. The installed owner endpoint sets the existing app's next frozen remote:

```sh
bottle curl --instance akaisenghor.bottle.cloud -- -fsS \
  -X POST https://akaisenghor.bottle.cloud/set_app_remote/APP_ID \
  -H 'Content-Type: application/json' \
  --data '{"repo_url":"https://github.com/AkaiS/california-political-knowledge-map@COMMIT_SHA"}'
bottle app reload california-knowledge-map --update --wait \
  --instance akaisenghor.bottle.cloud
bottle app status california-knowledge-map --instance akaisenghor.bottle.cloud
```

Replace `APP_ID` and `COMMIT_SHA` with the reviewed app ID and full release SHA.
`--update` fetches the stored ref and checks out FETCH_HEAD; the CLI also approves
new v2 permissions declared by that reviewed manifest. Verify the reported SHA,
source digest and retained installed data after startup. Keep 20% free disk and
one tested rollback image/revision. A rollback is an ordinary frozen code update
only while its schemas remain compatible with current persistent data.

Plain reload also invokes the image builder; omitting `--update` only skips the
Git fetch. This installed Bottle version exposes no per-app owner API for
skipping the build or applying only manifest routing. The paid-Gemma config
restart recompiled llama.cpp despite unchanged app source. The public commit
changes only the manifest and a test, both excluded from the Docker build
context, but cache reuse is not guaranteed. Allow for another build and keep
the graceful maintenance sequence. Do not substitute internal recovery helpers
or global cache/settings changes.
[Installed builder review](../work/projects/cloud-in-a-bottle-deployment/reports/build-cache-review-2026-10-13.md).

## Readiness and publication

`/health/live` checks the web process. `/health/ready` checks authenticated graph
connectivity and embedding health without paid inference:

```sh
bottle curl --instance akaisenghor.bottle.cloud -- -fsS \
  https://california-knowledge-map.akaisenghor.bottle.cloud/health/ready
```

Startup waits up to 180 seconds for dependencies. Supervisor retries startup at
most three times; a later stable-process crash requires an inspected owner
restart. Administration uses a private Unix socket. Service output goes to
stdout/stderr; Neo4j file logs rotate using its distribution configuration.

The frozen public release and anonymous paid-Gemma reading journey pass.
Owner reopening, foreign-visitor 404 responses, preserved attempt history,
public assets, privacy, bounds and persistence checks passed. Runtime peak was
1.745 GiB with zero swap/OOM events; final funded billing was recorded. Exact
proxy trust remains `127.0.0.1/32`.
Hosted owner cancellation, failure/interruption recovery and precise forwarded-IP
attribution remain limitations; existing local evidence does not establish each
behavior on this host. These are follow-up evidence, not new launch gates.

## Deferred recovery setup

When backup work resumes, use the installed Bottle backup service and verify its
broader app capture, destination and schedule. Prepare consistent SQLite
snapshots with the existing helper; the initial sanitized exporter is not a
backup of cloud visitor data. Run inside the app container:

```sh
uv run --no-sync python deployment/backup_sqlite.py \
  --source "$BOTTLE_APP_DATA_DIR/sqlite/document_store.db" \
  --output-root "$BOTTLE_APP_DATA_DIR/recovery/sqlite-backups"
```

The helper includes committed WAL pages and preserves corpus, guide ownership,
attempts and quotas. It creates an owner-only timestamped directory with a
checksum manifest after integrity/foreign-key checks. Pair these snapshots with
the immutable graph/model release. The broader Bottle backup reads live files;
its capture does not itself prove database consistency. Verify an actual restore
before claiming recovery, and handle visitor snapshots through authenticated,
encrypted storage. No new destination or dedicated job is required now.

Contracts match installed Bottle
[`6ea27634d1cbfc1b29caec29b53b76d919201b97`](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/tree/6ea27634d1cbfc1b29caec29b53b76d919201b97).
[Hosted deployment evidence](../work/projects/cloud-in-a-bottle-deployment/reports/hosted-private-deployment-2026-10-12.md),
[installed backup contract](../work/projects/cloud-in-a-bottle-deployment/reports/backup-integration-2026-10-12.md).
