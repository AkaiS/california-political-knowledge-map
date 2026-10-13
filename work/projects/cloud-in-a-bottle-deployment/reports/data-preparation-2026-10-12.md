# Deployment data preparation

Measured locally on October 12, 2026, against application revision `5c00b4de33223be5d1eda385803f38de51e1ed84`. This records preparation and an export recipe. The local Neo4j server remained running; no offline graph dump or recovery rehearsal has happened.

## Release inputs

Full measurements and index options are in [inventory-2026-10-12.json](inventory-2026-10-12.json).

| Input | Measured value |
| --- | --- |
| Neo4j | Community `2026.07.1` |
| Neo4j JRE | Temurin OpenJDK `25.0.3+9-LTS` |
| Existing Neo4j image | `neo4j@sha256:dca31d0d938dd8bb199c8846abedd897c3a07ddb629eca46a8009ac9e87aece2` |
| Graph | 3,668 nodes, 6,061 relationships, 98 Source Articles, 2,407 Chunks |
| Indexes | 16 ONLINE at 100%; three full-text indexes; COSINE vector index with 768 dimensions |
| Graph disk allocation | 30,192 KiB database directory, 263,172 KiB transaction directory, from `du -sk` |
| Local Neo4j idle memory | Docker reports 1.777 GiB in its 7.75 GiB VM |
| SQLite source | 36,122,624 bytes; 157 Stories, 1 Publication, 1,721 Story section links |
| Corpus alignment | All 98 graph Source Articles have corresponding SQLite Stories; 98 completed and 59 unprocessed Stories |
| Local private content | 6 Source Guides and 7 search attempts |
| Embedding artifact | `embeddinggemma-300M-Q8_0.gguf`, 333,590,944 bytes |
| GGUF SHA256 | `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63` |
| llama.cpp | Build `10150`, revision `dee2a846b`; local AppleClang 21 Darwin arm64 binary |
| Local llama binary SHA256 | `e5c153a1237e1c8e14ce0721d9afba4fd07936c7dc17dc7bd156d4dbe454952a` |
| Python / uv | Python `3.13.5`; uv `0.12.21` |
| Local architecture | Darwin arm64; Docker Desktop Linux arm64 |
| Hosted architecture | Not yet measured |

Keep the GGUF's pooling and projection unchanged. The existing launcher selects context, batch and microbatch sizes of 2,048 and one parallel slot. The deployment uses CPU layers, while the local launcher enables GPU layers. A matching checksum identifies the artifact; whole-vector CPU compatibility still needs a real measurement. No embedding call or paid external model call was made for this inventory.

The process RSS inventory records local processes without command arguments. It includes local chat inference, which is outside the hosted OpenRouter deployment. Neither local Darwin RSS nor the Docker Desktop VM's idle reading establishes peak usage for a complete hosted question. The 6 GiB runtime budget remains a proposal until Linux CPU embeddings and complete Source Guide executions are measured.

## Sanitized SQLite artifact

The release directory is `.scratch/deployment-corpus/2026-10-12-5c00b4d/`. It contains `document_store.db` and `manifest.json`; these runtime artifacts are ignored by Git. The tracked metadata copy is [sqlite-export-2026-10-12.json](sqlite-export-2026-10-12.json).

The export is 11,350,016 bytes with SHA256 `ab0739c4236ad225fd57e9e46eebbd87b84f1cb23339f550a4befecd84fb1a2f`. SQLite's backup API copied the database from a read-only connection. The copy retained every Story, Publication, section link, selector, discovery, proposal and scraped-cache row, verified through per-table content fingerprints. It removed all 6 Source Guides and 7 attempts, then vacuumed the copy so deleted private questions and outcomes do not remain in free pages. If present, `public_daily_admissions` is also cleared; its new schema was not in the local source at export time. The ownership column lives in `source_guides`, so deleting guides also deletes ownership values. Unknown tables stop the export until their privacy classification is reviewed.

The original source main-file SHA256 was `a04824a3e605a2c3487b062487839df616bbae98d8bfbfed31a2d9defa108013` both before and after export. There was no source WAL file during this run. The output passed SQLite integrity and foreign-key checks. This is an incomplete release until it is paired with a same-corpus graph dump and passes recovery checks.

Reproduce inventory with read-only access to local Docker and Neo4j:

```bash
UV_CACHE_DIR=/tmp/ca-map-uv-cache uv run --no-sync python scripts/deployment_inventory.py \
  --neo4j-container c423cdec431d \
  --output .scratch/deployment-corpus/new-inventory.json
```

Create another immutable sanitized release:

```bash
UV_CACHE_DIR=/tmp/ca-map-uv-cache uv run --no-sync python scripts/export_deployment_corpus.py \
  --release chosen-release-name
```

The scripts never replace an existing inventory file or release directory. They never print credentials, source questions or search outcomes.

## Version-compatible offline graph export recipe

Command syntax was verified using `neo4j-admin database dump --help` and `neo4j-admin database load --help` inside the existing `2026.07.1` container. Community's dump command refuses a database mounted in a running Neo4j server. The next step requires explicit approval for local database downtime. Do not run this block before that approval and a coordinated pause in ingestion and other corpus writes.

The existing container is `c423cdec431d`, named `agitated_jepsen`, and `/data` is Docker volume `26ae4f7b0e68ed7be02af64cef3accc7fa3162be2d9bd6d21a497b956d8c20a7`. Recheck that metadata before use. Do not dump or migrate the `system` database; fresh deployment authentication is configured separately.

After explicitly approved downtime:

```bash
set -euo pipefail
corpus_container=c423cdec431d
corpus_image=neo4j@sha256:dca31d0d938dd8bb199c8846abedd897c3a07ddb629eca46a8009ac9e87aece2
corpus_release=chosen-new-release-name

# Pause ingestion before this step and leave it paused until both exports finish.
UV_CACHE_DIR=/tmp/ca-map-uv-cache uv run --no-sync python scripts/export_deployment_corpus.py \
  --release "$corpus_release"
corpus_dir="$PWD/.scratch/deployment-corpus/$corpus_release"

docker stop "$corpus_container"
trap 'docker start "$corpus_container" >/dev/null' EXIT
docker run --rm --volumes-from "$corpus_container" \
  --entrypoint neo4j-admin "$corpus_image" \
  database dump neo4j --to-stdout > "$corpus_dir/neo4j.dump.partial"
mv "$corpus_dir/neo4j.dump.partial" "$corpus_dir/neo4j.dump"
docker start "$corpus_container"
trap - EXIT
```

The command writes the dump through host stdout so a bind-mounted directory does not require permissive host ownership changes. A failed dump leaves a `.partial` artifact, which must never be treated as a release. Re-measure graph counts and corpus alignment while writes remain paused. Record the dump checksum and actual version in a new paired release manifest. Keep the first SQLite-only artifact unchanged. Do not mark a paired release deployable until the following rehearsal passes.

## Disposable recovery rehearsal

Restore into a new disposable data volume. Do not use the local corpus volume or any existing deployment data directory. The offline load command for this version is:

```bash
neo4j-admin database load neo4j --from-path=/release
```

`/release` must contain `neo4j.dump`. Run the command with the pinned Neo4j image, against the disposable empty `/data` volume, before starting that disposable server. The default refuses an existing database; do not add an overwrite flag. Supply a fresh disposable password through a private environment or secrets file, never a command argument or tracked file. Bind any temporary ports only to loopback and set an alternate port so the existing server keeps its own port.

Once the disposable server is running, verify:

- Neo4j Community `2026.07.1`, 3,668 nodes and 6,061 relationships, or the recorded counts of the final frozen release.
- All 16 indexes ONLINE, including three full-text indexes and the 768-dimensional COSINE index with the recorded options.
- Every graph Source Article has a matching SQLite Story, and the Publication and section-link rows agree with the release manifest.
- The prepared SQLite copy has zero Source Guides, attempts and daily admission records while preserving reader metadata.
- CPU embeddings use the exact GGUF checksum and reproduce the current vector space.
- The real HTTP reader opens a Source Article with its Publication label and section links.
- Restart preserves a deliberately created disposable visitor guide and its ownership; source originals remain untouched.

Record elapsed restoration time and Linux peak memory. Clean up only disposable resources created for this rehearsal. This work has not started because the required offline graph dump has not been authorized or produced.

Nightly recovery for an active deployment must back up cloud SQLite with the same consistent backup API, preserving cloud visitor guides and ownership. Sanitizing is only for importing the local corpus into an empty deployment. Nightly backups need encrypted off-server storage and a measured restore; backup credentials, destination, charges and platform recovery metadata remain unconfigured.

## Verification

`UV_CACHE_DIR=/tmp/ca-map-uv-cache uv run --no-sync pytest -q tests/test_deployment_data.py` passed 11 tests. Tests use temporary SQLite databases, including committed WAL content, private deleted bytes, ownership values, original-file hashes, immutable release refusal, unknown-table rejection and invalid foreign keys. Ruff passed for the two scripts and this test module.

Outstanding work includes the offline graph export, disposable recovery rehearsal, target architecture, Linux peak measurements, dedicated $5-capped model key, Jev account billing and quotas, and encrypted off-server backup setup.
