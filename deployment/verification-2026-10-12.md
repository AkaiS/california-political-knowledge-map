# Isolated container verification

This checks infrastructure against a synthetic two-node graph. It does not
establish retrieval quality against the prepared corpus or public launch.

The local Linux ARM64 Docker image `ca-map-bottle-candidate:local` booted with
the production entry point, `uv sync --locked` dependencies and the pinned CPU
llama.cpp binary. The tested image ID was
`sha256:fe19b40c554229d3ba58d7fe1c2a9ac29ec0aa013e0ee469ff3eded0ee4c6a87`.
Its managed Python was 3.13.5 and its extracted source-content hash was
`b6832362332050b0f058b57cbbed614a1a0abce76b17ea480c82acfd5983b680`,
which matched the working source after excluding Python cache files. The image
contains an explicit `uncommitted-candidate` revision marker, not a release SHA.
The seed-manifest helper later gained a local export-manifest argument; that
operator-only edit was not part of this image rehearsal.
Cloud transport defaults were subsequently corrected to 60 seconds, two
attempts and a 15-second rate-limit wait cap, and the manifest ceiling was
reduced to five GiB after the instance preflight. This image therefore records
the earlier runtime and does not establish the current candidate source hash.

The container had `--network none --hostname localhost --memory 6g --cpus 3`.
Every credential was synthetic, and external network requests could not leave
the container. A resolvable loopback hostname is needed for this isolated
Neo4j setup. Earlier network-isolated fixture starts without it failed before
data creation. The fixture used the exact Neo4j Community 2026.07.1 image,
created one CalMatters-shaped Source Article and one Article Chunk, stopped,
then produced a genuine offline dump. It never modified the local corpus graph.

The persistent rehearsal volume used a copy of the sanitized SQLite export
and the actual 333,590,944-byte EmbeddingGemma artifact with its frozen checksum.
That graph and SQLite were deliberately not a matching production corpus.

Observed checks:

- All three supervised processes reached RUNNING.
- Real HTTP `/health/ready` returned 200 and `/api/guides` returned an empty list.
- A CPU `/v1/embeddings` request returned 768 dimensions with HTTP 200 in
  0.018 seconds for the short input `California housing policy`.
- The same input sent to the unchanged existing localhost embedding service
  returned 768 dimensions. CPU/local cosine similarity was 0.9997455, maximum
  absolute component difference was 0.0029392, and both vector norms were
  approximately one. This supports compatibility for that one input while
  recording the CPU/GPU numeric difference. It does not prove retrieval quality
  across the corpus or bit-identical vectors.
- Idle memory was 1.521 GiB initially and 1.47 GiB after restart within the
  six-GiB runtime limit. This is not a whole-question peak measurement.
- The fresh deployment password authenticated to the restored graph. The
  default `neo4j` password was rejected. The fresh password was absent from
  captured boot logs.
- A synthetic owned guide, its attempt and a daily admission count of seven
  survived an actual container restart. The unfinished attempt became
  `interrupted`, and its ownership remained `isolated-owner`.
- Stopping the embedding process changed readiness to 503 while liveness
  remained 200. An explicit supervisor restart recovered the dependency.
- Stopping Neo4j likewise returned readiness 503 and liveness 200. An explicit
  supervisor restart recovered graph connectivity.
- Shutdown reached the web lifespan, completed application shutdown, cleaned
  up embeddings and let Neo4j stop with exit status zero. A 75-second Docker
  grace period was used; Neo4j needed about eleven seconds. Bottle's inspected
  ten-second stop period therefore needs the runbook's maintenance procedure.

Nineteen focused runtime/revision/review tests passed after startup schema and
credential argument-file checks. Ruff passed on the packaging source. The
runtime rejects incompatible corpus and existing private-table schemas before
loading data, preserves state on restart, rejects a changed model checksum,
redacts failed secrets responses and removes the mode-0600 password argument
file after use.

Remaining checks require the actual target and authorized release inputs:
rootless Podman with Bottle's idmapped data mount, measured build memory under
its two-GiB ceiling, a consistent real Neo4j dump and its matching SQLite corpus,
index and reader verification, real provider/telemetry credentials, external
model compatibility and spending controls, whole-question resource/cost
measurements, HTTPS/proxy behavior and off-server recovery. The isolated run
could not send telemetry; expected export failures appeared in its logs.

Disposable evidence is retained under
`/private/tmp/ca-map-bottle-rehearsal/` and build diagnostics under
`/private/tmp/ca-map-bottle-build-final.log`. No images were pushed or apps
published. The owner-only manifest still has `public_paths = []`.
