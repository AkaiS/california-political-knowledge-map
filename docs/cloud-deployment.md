# Cloud deployment candidate

The repository prepares one owner-only Bottle app. The runtime contains
Neo4j Community 2026.07.1 with its bundled Temurin 25.0.3 Java runtime,
llama.cpp `dee2a846b82f15d27f84a48fa387cb53e0d99c25`, Python 3.13.5,
uv 0.12.21 and supervisord 4.3.0. Base images use immutable digests.
The manifest grants 5 GiB and three cores to runtime, with a separate 2 GiB
build ceiling. Compile concurrency is one; embedding concurrency is one
with two CPU threads. Host architecture remains a provisioning check.

Bottle runs rootless Podman. The image uses container UID 0 so the platform's
idmapped, host-account-owned persistence directory is writable. This is not
host root. Verify the installed platform's mount mapping before private
deployment. Local Docker checks do not establish rootless Podman behavior.

Build a candidate from the recorded checkout with:

```sh
docker build --build-arg APP_REVISION="$(git rev-parse HEAD)" -t ca-map-candidate .
```

The build excludes local credentials, databases, model weights, scratch output
and Git history. `BUILD_REVISION` and the OCI revision label retain a revision
supplied through the build argument. Bottle's inspected builder does not supply
that argument, so its default revision is unknown. Record its actual remote
checkout SHA externally before release. Gitless telemetry correctly reports an
unavailable SHA. `/app/deployment/build-metadata.json` records source-content
hashes and runtime versions independently of Git. Record dirty source
separately; a dirty image is a development
candidate and must not be described as the committed release.

## Prepare the persistent corpus

Read [the deployment inventory](../work/projects/cloud-in-a-bottle-deployment/IMPLEMENTATION.md)
and use the sanitized export command:

```sh
uv run scripts/export_deployment_corpus.py --source document_store.db --release RELEASE
```

It opens the source read-only and uses SQLite's backup API. It removes saved
guides, attempts and admission state from the copy and vacuums private free pages.
Keep that export paired with a version-compatible offline Neo4j dump. The live
graph must be stopped for Community's offline dump; arrange a maintenance window
before touching the maintainer's running graph. Do not copy its live store files.

Transfer these artifacts through an authenticated channel into
`$BOTTLE_APP_DATA_DIR/recovery/seed/`:

- `neo4j.dump`, the selected database dump, excluding the system database.
- `document_store.db`, the sanitized SQLite export with its export manifest.
- `embeddinggemma-300M-Q8_0.gguf`, checksum
  `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63`.
- `release.json`, created locally after pairing those files.

```sh
uv run deployment/make_seed_manifest.py /absolute/path/to/seed \
  --corpus-id RELEASE --application-revision COMMIT_SHA \
  --sqlite-export-manifest /absolute/path/to/export/manifest.json
```

Startup checks every artifact's checksum, the fixed embedding conversion,
SQLite integrity, required corpus tables, private guide rows and Neo4j version.
It restores the graph once, sets fresh authentication separately, installs the
SQLite and model files, then writes `recovery/installed-release.json`. A partial
restore fails closed. Recover it deliberately while stopped; startup never
overwrites an unmarked database. Later starts retain visitor guides and daily
admission counters. Model checksum and SQLite integrity are checked again.

Do not use this bootstrap for corpus replacement. A later release needs a
separately rehearsed graph replacement and SQLite corpus-table refresh that
preserves cloud guide ownership. Keep immutable release exports off the server.

## Supply grants and configuration

The manifest requests individual keys from secrets service version 0.1.0:
`OPENROUTER_KEY`, `TYPESAFE_API_KEY`, `LOGFIRE_API_KEY`, `NEO4J_PASSWORD`,
`OPENROUTER_MODEL`, `OPENROUTER_PROVIDERS`, `LOGFIRE_URL` and
`CLOUD_PUBLIC_ORIGIN`. The last four are configuration stored in the same
service because the app manifest has no arbitrary environment configuration.
The additional `CLOUD_TRUSTED_PROXIES` grant permits an optional comma-separated
CIDR setting. A missing value keeps conservative peer-IP handling.
The Neo4j password must be freshly generated and at least 16 characters.
`CLOUD_PUBLIC_ORIGIN` is the exact HTTPS origin with no path or trailing slash.
Choose the model/provider after the current tools and structured outputs pass
compatibility checks. The OpenRouter key needs its independent $5 monthly cap.

The three existing Bottle entries map to the application environment at
startup, without creating duplicate store entries:

| Bottle key requested and granted | Canonical application environment |
| --- | --- |
| `OPENROUTER_KEY` | `OPENROUTER_API_KEY` |
| `LOGFIRE_API_KEY` | `LOGFIRE_TOKEN` |
| `LOGFIRE_URL` | `LOGFIRE_PROJECT_URL` |

All other names are unchanged. The mapping is explicit and cloud-only. Missing
aliases fail startup even if a canonical environment value happens to exist.
Direct `CLOUD_SECRET_SOURCE=environment` uses canonical names exclusively.

Bootstrap calls the injected router with its injected app token. It requires
the documented `{secrets: {key: value}, missing: [...]}` response and refuses
missing keys, denied grants and service failures. It never logs values. The
temporary mode-0600 Neo4j argument file avoids placing its password in process
arguments. Environment mode exists only for explicit isolated rehearsals via
`CLOUD_SECRET_SOURCE=environment`; all keys remain mandatory.

Telemetry initializes before agents. Application imports follow persistent
SQLite path selection. Neo4j uses loopback Bolt with HTTP disabled; embeddings
use loopback HTTP on 8081. Only application HTTP 8080 is exposed. The web server
has one worker and Uvicorn proxy rewriting disabled. Cloud
model transport defaults are a 60-second request timeout, two total
transport attempts and a 15-second rate-limit wait cap. Bootstrap and the web
subprocess set these through the existing environment settings before either
cached embedding settings or chat clients load. Explicit transport environment
settings can override them; local command defaults stay unchanged. The overall
question deadline remains 240 seconds. Paid-route compatibility with these
limits still requires real credential-backed checks. Keep
`CLOUD_TRUSTED_PROXIES` unset until the actual Bottle peer and forwarding chain
are verified. An unset value treats the router peer as the source IP, producing
conservative shared rate limits until deployment configuration is confirmed.

## Deploy privately after verification

The current manifest has `public_paths = []`. Keep it that way through the
private rehearsal. Log in interactively and select the intended instance.
With the tested release committed and pushed, deploy its branch using the
documented branch URL syntax:

```sh
bottle app deploy https://github.com/OWNER/REPO@RELEASE_BRANCH \
  --name california-knowledge-map --grant-permissions-v2 --wait --instance INSTANCE
bottle app status california-knowledge-map --instance INSTANCE
bottle app logs california-knowledge-map --instance INSTANCE
```

Record the remote checkout SHA and compare it to the tested release. A branch
can move; the syntax alone does not prove commit selection. The CLI has no
assumed `--ref` flag. For rebuilds, stop admission and the app before rebuilding
so runtime and build allocations do not compete on the eight-GB host. Maintain
at least 20% free disk and retain the tested release plus one rollback candidate.

The installed CLI's `--grant-permissions-v2` approves the individually declared
service keys during deploy. Review that list and populate the required keys
first. Without grants, secrets retrieval returns 403 and bootstrap fails before
readiness. This recipe does not grant access now; provisioning and grant approval
remain operator steps.

`/health/live` checks the web process. `/health/ready` also checks authenticated
Neo4j connectivity and embedding health without paid inference. Web startup
waits up to 180 seconds for both dependencies, then initializes the existing
chat dependency path and its corpus coverage checks. Admission fails when a
required dependency is unavailable.

Supervisor retries startup at most three times and stops process groups on
shutdown. Stable-process exits are not retried indefinitely. A process crash
requires an owner restart after inspection, using the private Unix supervisor
socket or a container restart. Readiness remains false while dependencies are
down. Supervisord has no network administration endpoint. Shutdown allows the
web app to cancel work and records interrupted attempts on the next startup.
Neo4j file logs use the distribution's rolling configuration; service output
goes to stdout/stderr. Verify the platform's stdout retention separately.

The inspected Bottle source stops containers with a fixed ten-second grace
period, then forces termination. Our Docker rehearsal with a 75-second grace
period allowed Neo4j to finish its shutdown after about eleven seconds. The
ordinary Bottle stop command therefore does not establish graceful shutdown.
For planned maintenance, use an authenticated instance shell to request
`supervisorctl -c /app/deployment/supervisord.conf shutdown` inside the app
container, wait for all services to exit, and then invoke Bottle stop/reload.
Confirm this procedure on the installed rootless instance before release.
Unexpected termination still requires crash-recovery and interruption checks.

Before publication, rehearse persistence, interrupted searches, dependency
failure, process restart, off-server SQLite backup and restoration, graph
replacement, and rollback. Verify indexes and article alignment against the
real exported corpus. Measure whole-question peak memory, latency and external
cost. The prepared code does not establish the $5 cap, paid-route compatibility,
TypeSafe billing, HTTPS/proxy behavior, backups or public readiness.

## Consistent SQLite recovery snapshots

Use `deployment/backup_sqlite.py` for cloud recovery. It opens the source
read-only and uses SQLite's backup API, including committed WAL pages. It keeps
all corpus tables, visitor-owned guides, attempts and daily admission counters.
The local sanitizing exporter is only for the initial corpus import.

Run inside the app container, using its persistent data path:

```sh
uv run --no-sync python deployment/backup_sqlite.py \
  --source "$BOTTLE_APP_DATA_DIR/sqlite/document_store.db" \
  --output-root "$BOTTLE_APP_DATA_DIR/recovery/sqlite-backups"
```

Each invocation creates a new timestamped directory with owner-only access. It
contains `document_store.db` and a checksum manifest written after integrity and
foreign-key checks. An existing directory is refused. A failed backup removes
only its newly created snapshot directory. Backups preserve private visitor
content, so transfer them only through authenticated, encrypted recovery storage.

To rehearse SQLite recovery, verify the manifest checksum, restore its database
to a fresh directory and check saved guide ownership, attempts, quotas and
reader corpus. Replacing the live database requires stopping admission and the
web process first. This helper does not configure an off-server destination,
encryption, retention, a nightly schedule or restore the graph. Pair SQLite
snapshots with the immutable corpus/model release and measure actual off-server
restoration before publication.

The service contract was checked against Bottle source
[`6ea27634d1cbfc1b29caec29b53b76d919201b97`](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/tree/6ea27634d1cbfc1b29caec29b53b76d919201b97/services/secrets)
and its [manifest reference](https://cloudinabottle.org/docs/creating_an_app/manifest_spec.html).
Confirm the installed zone matches those contracts before deployment.
