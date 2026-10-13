# Cloud deployment implementation

Labels: ready-for-agent

Started October 12, 2026. The maintainer authorized beginning the deployment
plan with the orchestration and Cloud in a Bottle skills. This record separates
prepared artifacts and verified behavior from remaining provisioning and launch
checks.

## Assignments

| Assignment | Owned changes | Acceptance |
| --- | --- | --- |
| Packaging | Dockerfile, manifest, runtime, supervisor and deployment guide | Pinned image; private service ports; safe startup; real isolated boot and persistence checks |
| Public service | Visitor controls, web entry, SQLite ownership and tests | Cross-visitor access rejected; bounded work; existing local behavior preserved |
| Data preparation | Inventory, SQLite export and recovery scripts/tests/report | Original data unchanged; private guides scrubbed; corpus preserved; compatible graph dump recipe |
| Integration | Shared dependencies, ADR 0025, configuration and tracker | Focused checks and deterministic suite; clear remaining launch gates |

## Accepted facts

The local graph runs Neo4j Community 2026.07.1 with Temurin Java 25.0.3. All
16 indexes are online, including the 768-dimensional cosine vector index. The
inventory observed 3,668 graph nodes and 157 SQLite Stories. The CPU embedding
runtime to match is llama.cpp build 10150, revision `dee2a846b`. These are local
observations, not measurements on an Imbue space.

The official Bottle CLI is installed from upstream commit
`6ea27634d1cbfc1b29caec29b53b76d919201b97`. The maintainer completed interactive
login. The sole configured instance, `akaisenghor.bottle.cloud`, responded with
HTTP 200. Its six standard apps were running. Read-only instance preflight is
under way; no hosted app has been modified by this work.

## Pending verification and launch checks

- Inspect the authenticated instance's version-matched docs.
- Verify the trusted router peer and hosted build/runtime behavior on x86_64.
- Configure a dedicated $5/month OpenRouter key, compatible paid route, Jev and
  Logfire credentials, plus off-server recovery storage.
- Finish the disposable restore of the authorized real Neo4j/SQLite seed and
  freeze its release manifest against the final tested commit.
- Rehearse the matching real corpus, off-server restore, rollback and private
  hosted workload, including build memory under the manifest's 2 GiB limit.
- Publish only after the deployment plan's public launch checks pass.

## Implemented and verified locally

The pinned container, owner-only manifest and deployment runtime are in place.
Credentials come from explicit Bottle secret grants, database and model seeds
are validated before installation, and private service ports remain loopback.
The [deployment runbook](/Users/akaisenghor/Projects/california-political-knowledge-map/main/docs/cloud-deployment.md)
records startup, release provenance, operator steps and known platform limits.

Public mode now scopes saved guides and their controls to anonymous browser
identities. It bounds request bodies, question length, active and queued work,
per-visitor/IP submissions and persistent daily admission. It requires an
explicit HTTPS origin. The original local mode remains available; existing
unowned private guides are not exposed in public mode.

The actual SQLite export removed six local guides and seven attempts from its
copy, preserved reader corpus data and left the source checksum unchanged. All
98 graph Source Articles have matching SQLite Stories. See the
[data preparation report](reports/data-preparation-2026-10-12.md).

Verification evidence:

- Full deterministic Python suite: 1,773 passed and 77 skipped after allowing
  loopback HTTP fixtures. The first sandboxed run could not bind those sockets.
- JavaScript CI checks: all 31 passed.
- Independent public-service checks found an expired-guide admission defect,
  which was corrected; privacy, cancellation and local lifecycle checks pass.
  [Public-service review](reports/public-service-review-2026-10-12.md).
- Independent packaging checks found incompatible SQLite schema and private
  build-context inclusion defects, which were corrected. Final focused
  packaging and revision checks pass. [Packaging review](reports/packaging-review-2026-10-12.md).
- A real Linux ARM64 Docker candidate booted under 6 GiB/3 CPU limits with
  external networking disabled. It used a synthetic graph, the sanitized SQLite
  corpus and the exact embedding artifact. Readiness was 200; real CPU
  embeddings returned 768 dimensions. Idle memory was about 1.5 GiB.
- Actual container restart retained an owned guide and daily quotas, and marked
  an unfinished attempt interrupted. Dependency failure caused readiness 503;
  explicit supervisor recovery worked. Fresh Neo4j authentication succeeded and
  the default password was rejected. [Image rehearsal](/Users/akaisenghor/Projects/california-political-knowledge-map/main/deployment/verification-2026-10-12.md).

No paid model request or live source graph mutation was performed. This dirty
candidate has source-content metadata; it is not a committed or hosted release.
The Docker checks do not establish rootless Podman behavior, the target's actual
resource use, real question completion, HTTPS/proxy behavior or backup recovery.

Bottle's inspected stop operation allows ten seconds before forced termination.
The isolated Neo4j shutdown needed about eleven seconds with a 75-second Docker
grace period. Planned maintenance must first drain the web service and request
private supervisor shutdown before invoking Bottle stop/reload; verify this on
the installed instance. Ordinary Bottle stop is not recorded as graceful.

## Authenticated preflight and real corpus export

The maintainer completed Bottle login and authorized a brief local Neo4j stop
for the offline export. The original container restarted after a 14-second
maintenance interval. The dump operation took three seconds. Read-only
before/after inventory retained 3,668 nodes, 6,061 relationships and all 16
online indexes. SQLite's source checksum remained unchanged.

The paired seed is in `.scratch/deployment-corpus/2026-10-12-real-corpus-01`.
Its Neo4j dump is 30,364,204 bytes with SHA-256
`b9c57e38234afdd659f36eae2caca3f447d903fadcabd669effca696d3e00314`.
The sanitized SQLite and fixed embedding checksums match the earlier inventory.
The final application revision and release manifest remain pending. The
disposable restore passed index, vector, reader and restart checks, with a
2.15 GiB peak across those probes. The maintainer reports external credentials
configured with the dedicated $5 monthly OpenRouter cap.

Authenticated preflight found Bottle revision
`6ea27634d1cbfc1b29caec29b53b76d919201b97`, matching the inspected contracts.
The instance runs x86_64, four CPUs, 8,127,721,472 bytes of RAM and rootless
Podman 5.8.3. Its filesystem has about 123 GiB free. The local ARM64 rehearsal
does not prove this target build. The bundled backup app has no recorded
successful snapshots; off-server recovery remains unverified.

Key-name-only inspection found an existing TypeSafe entry. It was preserved.
Authenticated owner API calls added only the confirmed-missing Neo4j password,
model, provider and origin entries. No credential values were printed or saved
in the repository. [Credential setup](../../../docs/cloud-credentials.md)
describes the remaining external keys, monthly cap and billing review.

The maintainer clarified existing names `OPENROUTER_KEY`, `LOGFIRE_API_KEY`
and `LOGFIRE_URL`. Key-name-only inspection confirmed their presence. Cloud
bootstrap maps those entries to the application's standard environment names.
It does not copy credentials or create duplicate secret entries.
See the [instance preflight](reports/instance-preflight-2026-10-12.md).

The initial runtime ceiling is now 5 GiB, leaving about 2.57 GiB outside the
app on this host. A complete paid question must still pass that limit. An
independent fresh-process review confirmed cloud model transport settings of
60-second requests, two attempts and a 15-second rate-limit wait cap before
configuration imports. The 240-second question deadline remains in effect;
98 targeted checks passed. Local defaults remain unchanged.
