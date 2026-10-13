# Real corpus export and restoration

The maintainer authorized the brief local Neo4j interruption on October 12,
2026. The real seed now exists, and a disposable Linux container restored it.
No paid model request or remote deployment happened during these checks.

## Export evidence

The source was container `c423cdec431da947192e9a1bc6f7d720f0a534efc6d6052ee364c1fa839107bb`,
named `agitated_jepsen`. Its original data volume is
`26ae4f7b0e68ed7be02af64cef3accc7fa3162be2d9bd6d21a497b956d8c20a7`.
The image is Linux ARM64 Neo4j Community 2026.07.1, pinned at
`neo4j@sha256:dca31d0d938dd8bb199c8846abedd897c3a07ddb629eca46a8009ac9e87aece2`.

The process check found two local `ca-map chat` processes and no active
`ca-map` ingestion command. A fresh SQLite export came first. Its checksum
matched the earlier sanitized export. An EXIT restart trap was installed before
stopping Neo4j, with signal handlers that exit through that trap. The stop used
a 120-second graceful ceiling. The same pinned image ran `neo4j-admin database
dump neo4j --to-stdout` while the original was stopped, using `--volumes-from`
and `--network none`. Dump output went to a new `.partial` file, renamed only
after success. The original container restarted immediately afterward.

The whole stop request, dump and restart interval was 14 seconds. The offline
dump command took 3 seconds; its internal report processed 232 files in 0.854
seconds. The isolated dump helper logged a hostname-resolution warning but
completed successfully. Future isolated helpers should use `--hostname
localhost`, as the restore did. The source graph's records, container settings,
volume ownership and credentials were not changed. Neo4j's normal clean
shutdown and restart can change transaction and lock metadata.

Authenticated read-only inventory before and after was identical. It recorded
3,668 nodes, 6,061 relationships, 98 Source Articles, 2,407 Article Chunks and
16 ONLINE indexes at 100%. The 768-dimensional COSINE vector index and all
index options matched. All 98 Source Articles aligned with the 157 SQLite
Stories. Original SQLite main-file SHA256 remained
`a04824a3e605a2c3487b062487839df616bbae98d8bfbfed31a2d9defa108013`.

## Retained seed

The immutable source artifacts are in
`.scratch/deployment-corpus/2026-10-12-real-corpus-01/`. This ignored directory
contains the sanitized export manifest, before/after inventories, export timing,
paired artifact metadata and restoration evidence. It contains no local saved
guides, local search attempts or admission state.

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `neo4j.dump` | 30,364,204 | `b9c57e38234afdd659f36eae2caca3f447d903fadcabd669effca696d3e00314` |
| `document_store.db` | 11,350,016 | `ab0739c4236ad225fd57e9e46eebbd87b84f1cb23339f550a4befecd84fb1a2f` |
| `embeddinggemma-300M-Q8_0.gguf` | 333,590,944 | `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63` |

`paired-artifacts.json` honestly records `uncommitted-candidate`. A final
`release.json` remains pending the reviewed, committed application revision.
For the disposable restore, a separate seed copy used the current manifest
helper and `--application-revision uncommitted-candidate`.

## Real restoration checks

The existing candidate image
`sha256:fe19b40c554229d3ba58d7fe1c2a9ac29ec0aa013e0ee469ff3eded0ee4c6a87`
booted with its production entry point against a fresh disposable data directory.
It had external networking disabled, a loopback hostname, a 6 GiB memory limit,
three CPU cores and exclusively dummy credentials. The original data volume was
never mounted in the rehearsal.

- The offline load reported 232 files and 285.8 MiB processed in 1.645 seconds.
- Readiness returned HTTP 200. Restored node, relationship and article counts
  matched the source. All 16 indexes were ONLINE, with names, labels, properties
  and index configurations identical to the before-export inventory. The
  restored driver's response also included provider metadata such as
  `vector-2026.07`, absent from the initial inventory response.
- All 98 Source Articles aligned with the 157 Stories. The installed SQLite
  initially had zero guides, attempts and daily admission rows.
- CPU embeddings returned 768 dimensions. Querying the restored vector index
  with that vector returned five Article Chunks.
- HTTP coverage returned CalMatters with publication dates from June 15, 2023
  through September 5, 2026.
- A disposable saved guide carrying an actual corpus citation, its CalMatters
  label and two stored navigation URLs returned HTTP 200. Its reading direction
  was authored only for this infrastructure check. No question assessment,
  retrieval answer or model-generated reading direction was claimed.
- An actual container restart retained that completed guide and its owner.
  Readiness recovered to HTTP 200 and the graph still had 3,668 nodes.
- Docker reported 1.631 GiB after these checks. The cgroup peak was
  2,304,090,112 bytes, about 2.15 GiB, across startup and the CPU/vector/reader
  probes. This is not a complete question's peak memory.
- Graceful shutdown completed with exit code zero and no OOM kill. Neo4j took
  roughly eleven seconds. A 75-second Docker grace period was used.

The owned container and anonymous volumes were removed. Its copied data and
dummy environment file were deleted. Logs, probe scripts and results remain in
`/private/tmp/ca-map-real-corpus-rehearsal-2026-10-12/`; the real deployment seed
remains in the separate immutable export directory. The original Neo4j is
running again.

The first probe needed two corrections to its assumptions: Neo4j reports the
similarity function as uppercase `COSINE`, and this repository's Story column
is `title`. Neither correction changed the application or corpus.

## Remaining operator work

Select the final committed application revision before freezing `release.json`.
Transfer the seed through the selected instance's authenticated channel. Confirm
the installed Bottle version, rootless data mapping and actual host resource
limits. Configure the dedicated monthly-capped OpenRouter key and required
provider, TypeSafe and telemetry settings before a private full-question check.
Real provider compatibility, question cost and peak memory, HTTPS/proxy behavior,
encrypted off-server recovery, rollback and public release remain unverified.

For later exports, coordinate local ingestion and scheduled writers before the
window. Install the restart trap before the stop, retain a partial dump on
failure, and restart immediately before model copying or checksumming. The
original SQLite-only export remains unchanged. A consistent cloud backup must
preserve visitor-owned guides and admission state; the sanitizing importer is
not suitable for nightly recovery backups.
