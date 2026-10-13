# Deployment packaging review

Reviewed the dirty deployment candidate against
`work/projects/cloud-in-a-bottle-deployment/PRD.md`, with repository baseline
`5c00b4d`. This review does not identify a committed or hosted release.

## Findings corrected during review

- Startup accepted SQLite tables with expected names but incompatible columns.
  The packaging worker added the reader's required Story, Publication,
  scraped-article and story-link columns to validation before graph restoration.
- Empty, malformed saved-guide and admission tables passed sanitization checks.
  The worker added schema validation for existing guide, attempt and daily
  admission tables. This prevents a successful corpus installation followed by
  web startup failure on those tables.
- The build context allowed `document_store.db.backup`, a filename produced by
  repository SQLite migrations, and local review/configuration directories.
  The worker replaced broad inclusion with a source allowlist and excluded
  database suffixes and backups explicitly.

## Independent verification

```sh
UV_CACHE_DIR=/private/tmp/ca-map-cloud-research-uv-cache uv run --no-sync pytest -q \
  tests/test_cloud_runtime.py tests/test_cloud_runtime_review.py \
  tests/test_chat_telemetry_revision.py
```

Result: 18 tests passed. Ruff passes for the reviewer-owned test file. The
independent review tests exercise real disposable
SQLite files, including application guide tables, and cover:

- Two installed restarts retain SQLite bytes, visitor ownership and the daily
  admission counter, without invoking graph restore.
- Installed model corruption refuses startup without modifying SQLite.
- Authenticated graph readiness rejects an authentication failure. Its only
  HTTP request is local embedding health, with no model inference.
- Denied secret requests expose neither the response body nor app token in the
  startup error.
- Same-name incompatible corpus tables and empty incompatible private tables
  refuse startup.

The existing tests also cover checksum validation before restore, partial
restore overwrite refusal, required secrets and Gitless revision handling.

## Artifact and contract inspection

The manifest retains owner-only routing and publishes only application HTTP.
Neo4j Bolt and CPU embeddings bind to loopback. Startup selects persistent
paths before importing application dependencies and initializes telemetry before
agent construction. It authenticates Neo4j for readiness and uses embedding
health rather than paid requests.

The Bottle secrets contract was inspected from the local upstream checkout at
`/private/tmp/ca-map-bottle-source`, corresponding to upstream revision
`6ea27634d1cbfc1b29caec29b53b76d919201b97`. The inspected OpenAPI definition agrees
with the request path, individual key grants, request body and expected response.
The platform source also describes rootless Podman's idmapped persistence
mounts and the injected `BOTTLE_` environment aliases.

The pinned Neo4j image supplies Java, and llama.cpp is compiled from the frozen
revision for generic CPU instructions. The embedding checksum and launcher
settings preserve the existing conversion, mean pooling and projection.
Supervisor uses a private Unix socket, sends signals to process groups and
bounds startup retries. Stable-process crashes need an owner restart, as
documented. Host architecture and rootless mounts require hosted verification.

## Evidence limits

The independent tests use transport/driver doubles for readiness and secrets.
They do not establish an installed Bottle service, remote grants, real provider
compatibility, the OpenRouter spending cap, public HTTPS/proxy behavior or
whole-question memory/cost. No paid model call, local live database mutation,
browser, push, authentication or provisioning was performed by this reviewer.

Actual image build and isolated process rehearsal are owned by the packaging
worker. The orchestrator reports that the Linux Docker rehearsal reached
readiness HTTP 200, produced a 768-dimensional CPU embedding and used 1.521 GiB
under the six-GiB limit. The container had network disabled and used a synthetic
graph with the sanitized SQLite corpus. Those observations do not establish
real graph alignment or a complete question's peak memory.

The packaging worker subsequently completed the corrected image, restart and
dependency failure checks. The [final rehearsal record](../../../../deployment/verification-2026-10-12.md)
identifies the tested image and source content, fresh graph authentication,
process failure/shutdown and persistence. This evidence comes from that worker;
the independent review did not repeat the container rehearsal. A local ARM64
Docker rehearsal does not prove rootless Podman or the target Imbue architecture.

The orchestrator also reports an approximately 11-second graceful Docker stop
with a 75-second timeout. Bottle's inspected stop procedure gives containers
10 seconds before forcing termination, so that observation does not establish
graceful shutdown through Bottle's default stop command. Planned maintenance
must first drain work and stop services through the private supervisor socket,
then stop the container. Verify interruption recovery for unplanned forced
termination during hosted rehearsal.
