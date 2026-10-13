# Hosted deployment and publication

The public portfolio release on `akaisenghor.bottle.cloud` is running at
`0444a3cffb7c1cb09f220fb7e36b8c45e5081563`, with exclusive paid DeepInfra Gemma
configuration active. Authenticated readiness and fresh anonymous homepage
requests both return 200 at
[California Political Knowledge Map](https://california-knowledge-map.akaisenghor.bottle.cloud/).
Deployment, configuration-trial and publication evidence appears below.
Earlier attempts stopped before app creation because
Bottle's GitHub authorization fallback masked a consumed-version constraint
error. The corrected complete manifest passes the actual installed parser.
The existing six apps remain running.

## Initial frozen release

- Git repository `https://github.com/AkaiS/california-political-knowledge-map`.
- Branch `codex/cloud-in-a-bottle-deployment`.
- Frozen application SHA `daeda4fec637fe68819a8993c1acbf80d4feec7c`.
- Corpus release `2026-10-12-real-corpus-01`, Neo4j Community 2026.07.1.
- Private URL `https://california-knowledge-map.akaisenghor.bottle.cloud/`.
- Committed manifest keeps `public_paths = []`, runtime 5,120 MiB and three
  CPUs, build limit 2,048 MiB, and no extra host ports.

## Transfer evidence

`bottle app list` confirmed no existing `california-knowledge-map` app before
staging. The new app-specific persistent directory was absent. Free disk was
122G with 16% used; host available memory was 6,349 MiB at that reading.

Only five whitelisted files were transferred over authenticated Bottle SSH.
The tar source was `.scratch/deployment-corpus/2026-10-12-real-corpus-01`.
The destination was a newly created staging directory beneath the future
app's own persistence root:

```text
/home/host/.openhost/local_compute_space/persistent_data/app_data/california-knowledge-map/recovery/seed-transfer-a17b3c1
```

The command refused an existing `recovery/seed` and refused an existing staging
directory. After transfer, remote `sha256sum` matched local checksums for every
file:

| File | SHA-256 |
| --- | --- |
| `neo4j.dump` | `b9c57e38234afdd659f36eae2caca3f447d903fadcabd669effca696d3e00314` |
| `document_store.db` | `ab0739c4236ad225fd57e9e46eebbd87b84f1cb23339f550a4befecd84fb1a2f` |
| `embeddinggemma-300M-Q8_0.gguf` | `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63` |
| `release.json` | `5a653b0507cbeb08491ae84da50716ea1797f2f8e1388e7928b10bbf339f8b01` |
| `manifest.json` | `2670df0d193674bb4323a015db52e6b1e9f6d679304463763497017ab8672641` |

The initial immutable release manifest names the original application SHA. The sanitized
SQLite export preserves 157 Stories and Publication metadata, clears the six
local guides and seven attempts, and removes private free pages. No local
database or model artifact was changed during transfer.

The staging directory was renamed to `recovery/seed` only after checksum
verification and another absence check. Its host owner/group are `1000:1000`,
mode `775`; the transferred seed occupies 358 MiB. Platform directory
precreation is idempotent and will preserve this seed on first deployment.

Before bootstrap, the corrected release manifest was activated atomically.
The prior `a17b3c1` manifest remains in
`recovery/release-history/a17b3c119e30071e40f021ceba420cdc22914e6c.json`.
All three artifact hashes were verified unchanged against both manifests, and
no installed release marker or app record existed during the correction.
The new `release.json` hash is
`fafdaeaefbf287f681d7d601f6d647b68ef80fe9da7939df59c8cc155e139e69`.
The corpus and model were not retransferred.

## Deployment attempt and authorization gate

The authorized command was:

```sh
bottle app deploy \
  https://github.com/AkaiS/california-political-knowledge-map@codex/cloud-in-a-bottle-deployment \
  --name california-knowledge-map --grant-permissions-v2 --wait \
  --instance akaisenghor.bottle.cloud
```

It exited with status 1 and reported that GitHub authorization is required.
It supplied this owner connection URL:

[Connect GitHub on this instance](https://oauth-provider.akaisenghor.bottle.cloud/device?provider=github&scopes=repo&return_to=%2F&account=default&consumer=).

No app record was created. A subsequent `bottle app list` still showed only
backup, bottle-community-chat, catalog, filestash, oauth-provider and secrets,
all running. No existing app was stopped or modified. No grants were installed
for a new app, no paid questions were sent, and no secrets were read or printed.
CLI evidence is `/private/tmp/ca-map-bottle-private-deploy.log`.

The owner subsequently made the repository public. Anonymous `git ls-remote`
from both the local machine and instance confirmed the frozen branch SHA.
Another deploy still returned the authorization prompt. The installed
`clone_with_github_fallback` invokes OAuth after any clone/manifest failure,
which masked the candidate's invalid consumed service constraint `0.1.0`.
The packaging correction is `==0.1.0`, preserving the intended exact version.
No OAuth connection is needed for this now-public source.

The entire corrected manifest was validated with the actual installed
`compute_space.core.manifest.parse_manifest` in its managed pixi interpreter,
launched through a temporary public `uv` binary. It confirmed 5,120 MiB runtime,
2,048 MiB build, three CPUs, owner-only routing and all nine exact grants.
Twenty-eight focused tests and Ruff passed. A regression checks the consumed
specifier accepts `0.1.0`, rejects later versions, and retains exact grants.

The installed `clone_repo` also checked out a full commit ref in a disposable
temporary directory and returned exactly
`a17b3c119e30071e40f021ceba420cdc22914e6c`. Corrected deployment can therefore
use `https://github.com/AkaiS/california-political-knowledge-map@NEW_FULL_SHA`,
with actual checkout verification, rather than a moving branch.

The corrected deployment command uses the full SHA:

```sh
bottle app deploy \
  https://github.com/AkaiS/california-political-knowledge-map@daeda4fec637fe68819a8993c1acbf80d4feec7c \
  --name california-knowledge-map --grant-permissions-v2 --wait \
  --instance akaisenghor.bottle.cloud
```

During the build, `bottle app status` confirmed detached HEAD
at the exact corrected SHA. The AMD64 image compiled llama.cpp under the
2,048 MiB build limit. During compilation, host available RAM readings were
5,757 to 5,936 MiB, swap usage stayed zero, and one compiler RSS sample was
193,852 KiB. There were no reported OOM failures. These are sampled readings,
not a measured build-memory peak. Build progress is captured in the app's
build log and `/private/tmp/ca-map-bottle-private-deploy-daeda4f.log`.

Build and startup completed. The sections below record the actual AMD64 image,
limits, mapped persistence, readiness, restored graph and CPU embedding checks.
The separate HTTP verifier owns the budget-checked model smoke tests.
Publication remains outside this private deployment stage.
The user explicitly deferred backup configuration this turn. Existing backup
state remains unchanged; recovery readiness is not claimed.

## Actual startup and resource evidence

`bottle app status california-knowledge-map` reports `running`, with detached
HEAD `daeda4fec637fe68819a8993c1acbf80d4feec7c`. The required Secrets grants and
bootstrap succeeded, and telemetry initialized before the web app. Authenticated
`bottle curl -- -fsS` against `/health/ready` returned `{"status":"ready"}` with
HTTP 200. Supervisor reports Neo4j, embeddings and web all `RUNNING`.

| Observed property | Value |
| --- | --- |
| Container | `openhost-california-knowledge-map` |
| Container ID | `2207b0f51e69b8b60cedbbbcedf7cdbd761f2290f86a398617026c7d2b2cc421` |
| Image ID | `1400ae1d062e62565cf994d60fdce88b2c27497487c5f7aa8fd344589d55c014` |
| Image architecture / size | `amd64` / 1,739,834,223 bytes |
| Runtime memory limit | 5,368,709,120 bytes, exactly 5 GiB |
| CPU period / quota | 100,000 / 300,000, exactly three cores |
| Published port | `127.0.0.1:9006` to container `8080/tcp` only |
| Source content SHA-256 | `9f9f67e1eec0a8c5cf3fc3fffa8a52d398af964029a1be8b4c8f65d2e729a48a` |

The app-specific host persistence root is mounted read/write at
`/data/app_data/california-knowledge-map`. The graph directory and SQLite file
appear as UID/GID `0:0` inside the container and `1000:1000` on the host,
confirming the rootless mapping. No Neo4j or embedding port is published.
All six pre-existing apps remained running.

The startup cgroup reading was 2,193,584,128 bytes current memory and
2,287,812,608 bytes peak (about 2.13 GiB), with zero swap. Every reported
`memory.events` counter, including `oom` and `oom_kill`, was zero. This records
startup and early verification, not the complete paid-question peak.

## Source and corpus checks

All 383 tracked `src/` files in the image match their bytes at the frozen Git
commit. The first aggregate comparison mistakenly sorted strings, while
`deployment/build_metadata.py` sorts `Path` objects. Repeating the expected
digest with the build script's ordering produced the exact image content hash
above. Per-file comparison found zero mismatches; this was a verification
ordering mistake, not a deployed source change. Bottle does not pass the
`APP_REVISION` build argument, so the image's build revision remains `unknown`;
the verified checkout and source digest establish provenance.

The installed release marker names the corrected SHA and corpus
`2026-10-12-real-corpus-01`. Neo4j reports Community 2026.07.1, 3,668 nodes,
6,061 relationships, 98 Articles and 2,407 Chunks. All 16 indexes are `ONLINE`,
including the 768-dimension cosine vector index and three full-text indexes.
SQLite passes its integrity check and retains 157 Stories, one Publication and
215 publication projection rows. Every graph Article URL is present in SQLite;
the fresh deployment initially had zero private guides. Loopback home and
readiness requests returned 200, and the guide list was empty.

A real CPU embedding for a generic California housing-policy input returned
HTTP 200, 768 dimensions and norm `0.9999999975855076` in about 0.023 seconds.
No paid model call was used for this infrastructure check.

The pinned llama.cpp build fetched an upstream embedded server UI asset from
an unpinned `latest` URL. That loopback server UI is not the exposed Source
Guides UI, and the GGUF remained checksum-pinned. This is a remaining build
reproducibility limitation. A separate asset checksum was not available in the
final image; the built `llama-server` binary SHA-256 is
`1c0a139d7cf8e1781959a4ebe1ae3db2295253b99f62f34fca18ddca474ff350`.

Local disposable evidence files are
`/private/tmp/ca-map-bottle-hosted-runtime-evidence.json` and
`/private/tmp/ca-map-bottle-hosted-source-evidence.json`; the corresponding probe
scripts are beside them. Probes consumed only the required credential inside
the owned app and emitted no credential values.

## Bounded model verification follow-up

The HTTP verifier reported its first permitted assessment reached `needs_edit`.
Its second execution failed assessment before retrieval. A scoped log check
covering UTC `2026-10-13T01:52:10` through `01:52:13` found two
`QuestionAssessment` validation errors: `publication_date_from` and
`publication_date_through` both failed `date_from_datetime_parsing` because the
input was too short. A subsequent field-only check confirmed both values were
the literal string `"null"`, with input type `str`, rather than JSON null or an
empty string. No downstream provider was recorded in the scoped log.
The terminal exception was `UnexpectedModelBehavior:
Exceeded maximum output retries (0)`. This identifies structured-output
compatibility as the failure; the app remained running. The scoped log summary
excluded input values, tokens, environments and unrelated logs. No additional
paid execution or service operation was performed by the packaging worker.

The app stays private and stable while the HTTP verifier finishes its report.
A controlled restart and any publication need the coordinated next phase.

## Corrected model profile and immutable update

The root verified the profile correction with the full deterministic suite
(1,790 passed, 77 skipped) and committed it at
`a74ca13ffd6a6a6ddfd23568e8e9f26934d57286`. The release changes the OpenRouter
profile and adds its regression test; the container manifest and grants remain
unchanged. The root explicitly authorized this own-app redeploy.

Installed platform source confirms the supported update endpoint:

```sh
bottle curl --instance akaisenghor.bottle.cloud -- -fsS \
  -X POST -H 'Content-Type: application/json' \
  --data '{"repo_url":"https://github.com/AkaiS/california-political-knowledge-map@a74ca13ffd6a6a6ddfd23568e8e9f26934d57286"}' \
  https://akaisenghor.bottle.cloud/set_app_remote/qfU4cawr45T5
bottle app reload california-knowledge-map --update --wait \
  --instance akaisenghor.bottle.cloud
```

The remote-setting POST returned HTTP 200 and `ok: true`. The CLI update fetches
the persisted exact ref and checks out `FETCH_HEAD` detached; it also sends the
owner's settings approval. Actual status after reload confirms the exact new
SHA. No direct platform database edit, seed restore, marker overwrite or other
app operation was used.

Before reload, supervisor received `shutdown` through its private socket and
`podman wait` returned zero. However, the platform's `--restart=unless-stopped`
automatically restarted the container after that clean exit. The subsequent
inspection showed it running again. Consequently this attempt does **not**
establish that platform removal avoided its ten-second stop timeout. It does
establish the first supervised shutdown exited zero, and the corrected app's
graph and SQLite are healthy afterward. The installed Podman help supports
`podman update --restart=no CONTAINER`; the next coordinated maintenance should
apply that reversible adjustment to this owned container before supervisor
shutdown and waiting for exit. The platform recreates `unless-stopped` on the
replacement container. No such extra operation occurred during HTTP retry.

The pre-update and post-update metadata snapshots are exactly equal: two guides,
two attempts, unchanged guide identity/owner/latest-attempt hash, unchanged
attempt-status hash, and daily admission count two for `2026-10-13`.
SQLite integrity remains `ok`. The installed marker SHA remains
`fafdaeaefbf287f681d7d601f6d647b68ef80fe9da7939df59c8cc155e139e69`, so its seeded
application revision remains the initial `daeda4f` revision while the running
code advances to `a74ca13`. No private question text was emitted by these checks.

| Corrected runtime property | Observed value |
| --- | --- |
| Container ID | `f149f8937b37a8f3e84ebaa4313617d326d8e937e50e44cc7c481492e48253c6` |
| Image ID | `584327c5ce4cdb02e8835df9eb580e7416d99c68a183078774673aa178cd35da` |
| Source content SHA-256 | `7cf60672c3715e2612243655d9a2f45939b2caa88addb484de5df5220900efd1` |
| Tracked source comparison | All 383 files match the exact commit; zero mismatches |
| Readiness | Authenticated HTTPS and loopback both 200 |
| Supervised processes | Neo4j, embeddings and web all `RUNNING` |
| Memory / CPU | 5,368,709,120 bytes / 100,000 period and 300,000 quota |
| Early startup peak | 1,534,251,008 bytes, about 1.43 GiB |
| Swap / OOM counters | Zero / all zero |
| Restart policy | `unless-stopped` |

The graph still has 3,668 nodes, 6,061 relationships, 98 Articles and 2,407 Chunks,
with all 16 indexes online and Article URLs aligned with SQLite. SQLite retains
157 Stories, one Publication and both owned guides. The real CPU embedding
check again returned 768 dimensions. The separate HTTP verifier received the
new readiness signal and container ID before its corrected model retry.

Disposable evidence files are `/private/tmp/ca-map-bottle-private-reload-a74ca13.log`,
`/private/tmp/ca-map-bottle-before-redeploy-state.json`,
`/private/tmp/ca-map-bottle-after-a74-state.json`,
`/private/tmp/ca-map-bottle-a74-runtime-evidence.json` and
`/private/tmp/ca-map-bottle-a74-source-evidence.json`. This worker made no paid
call. Public routing remains disabled and backup configuration remains deferred.

The corrected HTTP retry passed assessment and completed a guide with two
articles in about 12 seconds, but retained a `partial_search` disclosure. A
scoped stdout/stderr check for UTC `02:29:15` through `02:29:30` found HTTP
202/200 responses and no exception type, branch diagnostic or provider usage.
It also found Neo4j warning `01N52`: property `url` does not exist. This warning
does not establish the cause of the partial result. `record_branch_failure`
writes diagnostic attributes to Logfire spans; branch helpers also log structured
warning extras, which were absent from the captured container output.
The failed retrieval branch therefore remains unidentified from
container logs; full successful retrieval is not claimed. The app remains
private and running while that follow-up is investigated. No extra paid call
was made to obtain this log check.

The root's subsequent telemetry diagnosis identified an intentional structural
selector abstention: `LaborUnion` scored 0.73, below the 0.8 threshold, because
the request did not specify the role subtype clearly enough. The partial result
was not treated as a deployment defect, and no selector tuning was performed.

## Prepared publication and remaining model reliability check

The root authorized preparation of `public_paths = ["/"]` for the intended
visitor routes, with the existing manifest assertion updated accordingly.
The actual installed full platform parser accepts the prepared manifest with
the same 5,120 MiB runtime, 2,048 MiB build, three CPUs and nine exact grants.
Forty-nine focused cloud-runtime/public tests and Ruff pass. The parser's
disposable evidence is `/private/tmp/ca-map-bottle-public-manifest-evidence.json`.
This is a working-tree preparation only; the hosted app still has owner-only
routing.

The second corrected HTTP check, a bill-focused assessment at UTC
`02:43:39.486880` through `02:43:40.482856`, failed before retrieval. A scoped
log check identified one `QuestionAssessment.reading_order` `literal_error`:
the output was the literal string `"null"` (`str`) rather than one of
`relevance`, `publication_asc`, `publication_desc`, `event_asc` or `event_desc`.
The terminal error was again `UnexpectedModelBehavior: Exceeded maximum
output retries (0)`. No downstream provider field appeared in these logs.
The error-only check emitted no question, prompt, credential or owner data.
Publication remains on hold for the root's model reliability decision; no new
paid execution or service operation followed this failure.

## Private Gemini configuration trial

After an isolated assessment succeeded, the root authorized a nonsecret model
route change to `google/gemini-3.1-flash-lite`, with providers
`google-ai-studio,google-vertex/global`, and a same-code private restart.
The reviewed `CLOUD_TRUSTED_PROXIES=127.0.0.1/32` setting was also ready for
pickup. No prompts, retry policy or code were changed for this trial.

Before maintenance the remote checkout was clean at `a74ca13` and its manifest
still had `public_paths=[]`. The local public draft was not copied or deployed.
This time the worker set only the owned container's restart policy to `no`,
verified that policy, issued supervisor shutdown and waited for container exit.
Independent inspection afterward still showed `running=false`, `status=exited`,
`exit=0`, `oom=false` and `restart=no`. Uvicorn logged `Application shutdown
complete` and `Finished server process`; supervisor then recorded web termination
by SIGTERM. Embeddings exited zero. Neo4j logged `Stopping...`, `Stopped.` and
exited zero. Its shutdown took about eleven seconds, beyond Bottle's normal
ten-second stop allowance. No automatic restart raced this maintenance.

The worker ran a plain reload, without pulling code:

```sh
bottle app reload california-knowledge-map --wait \
  --instance akaisenghor.bottle.cloud
```

The cached image remained
`584327c5ce4cdb02e8835df9eb580e7416d99c68a183078774673aa178cd35da`.
The recreated container is
`897eb6ccd171737fd1b05780a604f35256e47abe7874ecc77596b78485589019`, with normal
`unless-stopped` policy, 5 GiB memory and three CPUs. All 383 source files again
match `a74ca13`, with source hash
`7cf60672c3715e2612243655d9a2f45939b2caa88addb484de5df5220900efd1`.

Only the three permitted nonsecret web-process configuration values were
emitted: the Gemini model, the two-provider list and `127.0.0.1/32`. They match
the authorized settings. Credential values were not emitted. Pre/post state
snapshots are exactly equal: three guides, four attempts, daily admissions four,
unchanged identity/status hashes and unchanged installed marker. SQLite integrity
is `ok`; graph counts, all 16 online indexes and 768-dimension CPU embeddings
remain healthy. Authenticated HTTPS readiness returned 200, and all three
supervised services are running.

The early restarted-container memory peak was 1,468,334,080 bytes (about 1.37 GiB),
with zero swap and zero OOM counters. The HTTP verifier received readiness and
the new container ID for the authorized full bill retry. No extra paid request
was made by this worker. Evidence is retained in the disposable
`/private/tmp/ca-map-bottle-gemini-shutdown.log`,
`/private/tmp/ca-map-bottle-private-reload-gemini.log`,
`/private/tmp/ca-map-bottle-before-gemini-state.json`,
`/private/tmp/ca-map-bottle-after-gemini-state.json`,
`/private/tmp/ca-map-bottle-gemini-source-evidence.json` and
`/private/tmp/ca-map-bottle-gemini-runtime-evidence.json`.

## Paid DeepInfra Gemma configuration trial

The user requested a paid Gemma route through OpenRouter rather than the Google
BYOK route. The root verified two isolated assessments through exclusive
`deepinfra/fp8`: each used one HTTP request, emitted JSON null dates and a valid
reading order, reported `is_byok=false`, and together cost $0.00053218.
The root then configured `google/gemma-4-26b-a4b-it` and `deepinfra/fp8` and
authorized a private configuration-only restart. This worker made no paid call.

The remote checkout was again confirmed clean at `a74ca13`, with
`public_paths=[]`; the local publication commit was not fetched. Before stopping,
the state snapshot recorded three guides, five attempts and daily admissions
five for `2026-10-13`, with SQLite integrity `ok` and unchanged installed marker.
The worker set only this container's policy to `no`, verified it, shut down
supervisor and waited. Two observations confirmed a stable exited container,
exit zero and no OOM. Uvicorn completed application shutdown, embeddings exited
zero, and Neo4j logged `Stopped.` and exited zero.

A plain `bottle app reload ... --wait`, without `--update`, started the private
rebuild. Contrary to the initial cache expectation, its llama.cpp stage rebuilt
the apt, Git and CMake steps. The installed build command specifies the
2,048 MiB memory and combined memory/swap ceilings and has no explicit
`--no-cache` or layer override; installed Podman defaults `--layers=true`.
The build log showed only one cache-hit line. The cause of the misses was not
established, and no global cache or platform setting was changed. Sampled host
available memory remained about 5.7 GiB with zero swap during compilation.

The platform's supported plain reload always invokes the builder. Static review
found no owner API/CLI route for image-only restart or manifest-only publication;
internal archive/startup helpers are not an approved publication shortcut. The
prepared publication commit changes only the manifest and its test, which the
Docker context excludes, but a later cache hit is not guaranteed. This build
was allowed to finish rather than being interrupted for an optimization.

Readiness was 503 during maintenance because the replacement container had not
been created. Build and startup subsequently completed. Authenticated HTTPS
readiness is 200. The new container is
`74b6f2823194cba6493a5f98a79b30b41c4dab10d7e81502554b308c6fd502af`, and image is
`aef0b360fac312621498b9cd5595596377c435a1b17e0995e97b0932f158be30`.
Normal `unless-stopped` policy and exact 5 GiB/three-CPU limits are restored.
Its early peak was 1,413,320,704 bytes (about 1.32 GiB), with zero swap and zero
OOM counters.

The active nonsecret settings match the authorized Gemma model, exclusive
`deepinfra/fp8` route and reviewed `127.0.0.1/32` proxy range. All 383 source
files still match `a74ca13` exactly, including aggregate
`7cf60672c3715e2612243655d9a2f45939b2caa88addb484de5df5220900efd1`.
Post-restart persistent state is exactly equal to the baseline: three guides,
five attempts, daily admissions five, identity/status hashes and installed
marker all retained; SQLite integrity is `ok`. No seed was reimported.

The private app remains unpublished and is held stable for the separately
authorized full-guide check. The rebuilt image ID differs despite matching
application source bytes; the previously documented unpinned embedded UI fetch
remains a reproducibility limitation. No build cache was cleared, and no
retained image was removed. The rebuilt AMD64 image is 1,739,834,222 bytes;
`llama-server` SHA-256 is
`5594e47e015c4e7f966e64cbe8914599681e74836d1bb9ab2ad31f0fb44c3690`.
The exact cause of the changed binary digest was not established. The preceding
tested image `584327c5ce4cdb02e8835df9eb580e7416d99c68a183078774673aa178cd35da`
still exists for rollback. Disposable progress evidence is
`/private/tmp/ca-map-bottle-paid-gemma-build-progress.log`; shutdown and baseline
files are `/private/tmp/ca-map-bottle-paid-gemma-shutdown.log` and
`/private/tmp/ca-map-bottle-before-paid-gemma-state.json`.
Post-start evidence is `/private/tmp/ca-map-bottle-after-paid-gemma-state.json`
and `/private/tmp/ca-map-bottle-paid-gemma-source-evidence.json`.

## Public portfolio rollout

The root authorized publication under the user's original portfolio goal after
the full paid DeepInfra Gemma HTTPS guide completed cleanly in 14.875 seconds:
expected Article, reading directions and two groups; `partial=false`, search
completed, and no disclosures. Cross-owner access remained 404 and history was
preserved. The reported OpenRouter retry delta was $0.00139204; ordinary usage
was $0.00448407 with $4.99551593 remaining under the $5 monthly cap. Historical
BYOK usage did not increase during this paid route check. The separate HTTP
verification report owns those model and privacy results.

The public manifest and existing assertion were frozen at
`c3c3f01ed569f5336d8f8a0188cefec7cbed1c3a`. Its source tree is byte-identical to
`a74ca13`; only the manifest and test changed. The installed full parser and
49 focused tests had already accepted `public_paths=["/"]`. The audited routes
serve the Source Guides UI/assets, owned guide APIs, coverage and health; docs,
OpenAPI and admin endpoints are absent.

The worker took a fresh pre-publication snapshot: three guides, six attempts and
daily admissions six, with ownership/latest-attempt hashes, attempt statuses,
SQLite integrity and installed marker recorded without emitting private text.
The supported owner remote-ref POST accepted the exact `c3c3f01` ref. The owned
container's policy was temporarily set to `no`; supervisor shutdown then produced
a stable exited container with exit zero and no OOM. Uvicorn completed shutdown,
embeddings exited zero, and Neo4j logged `Stopped.` and exited zero. The worker
then ran the standard authorized `reload --update --wait`.

This publication build reused 24 cached steps and retained image
`aef0b360fac312621498b9cd5595596377c435a1b17e0995e97b0932f158be30`.
Actual hosted checkout is clean at the exact full public SHA, with
`public_paths=["/"]`. All 383 tracked source files match, with unchanged digest
`7cf60672c3715e2612243655d9a2f45939b2caa88addb484de5df5220900efd1`.
The recreated container is
`1c6af300e2abd641b973cfa1334cfa05f1227a38fdeaae93e08406b784886a23`.

Post-rollout state and allowed nonsecret configuration are exactly equal to the
baseline: three guides, six attempts, daily admissions six, all recorded hashes
and the installed marker unchanged, integrity `ok`, Gemma 26B with exclusive
`deepinfra/fp8`, and trusted proxy range `127.0.0.1/32`. No seed was imported or
marker overwritten. Runtime remains 5 GiB and three CPUs, with normal
`unless-stopped` policy and only host `127.0.0.1:9006` published to web port 8080.
Neo4j ports have no host bindings; build limit remains 2,048 MiB.

Authenticated `/health/ready` returned 200. A fresh raw `curl -q` request, with
no owner Authorization or saved cookie jar, returned homepage 200 and the Source
Guides shell. Recent Uvicorn access lines show actual socket peer `127.0.0.1`,
within the reviewed trusted range; only that peer address was extracted, with
no headers or visitor addresses emitted. The early public-container memory peak
was 1,356,804,096 bytes (about 1.26 GiB), with zero swap and all OOM counters zero.

The root and HTTP verifier received the public readiness signal and new
container ID. The app is held stable for the separately authorized fresh
anonymous full-guide and final privacy/header checks. This worker made no paid
call and did not change another app, reboot the instance or remove cache/rollback
images. Backup setup remains explicitly user-deferred.

Disposable publication evidence is
`/private/tmp/ca-map-bottle-public-reload-c3c3f01.log`,
`/private/tmp/ca-map-bottle-public-build-progress.log`,
`/private/tmp/ca-map-bottle-public-shutdown.log`,
`/private/tmp/ca-map-bottle-before-public-state.json`,
`/private/tmp/ca-map-bottle-after-public-state.json`,
`/private/tmp/ca-map-bottle-public-source-evidence.json`,
`/private/tmp/ca-map-bottle-public-anonymous-home.html` and
`/private/tmp/ca-map-bottle-public-access-peer.log`.

## Anonymous assessment follow-up

The final fresh anonymous guide check failed assessment at UTC
`2026-10-13T07:28:21.165173` through `07:28:22.847845`, before retrieval. The
five-second scoped log check found one `QuestionAssessment.reading_order`
`literal_error`: the model emitted the literal string `"null"` (`str`) rather
than `relevance`, `publication_asc`, `publication_desc`, `event_asc` or
`event_desc`. The terminal exception was `UnexpectedModelBehavior: Exceeded
maximum output retries (0)`. This is the same validation class observed in the
earlier bill check despite an intervening successful full private guide.

The running public release and chosen Gemma 26B/exclusive DeepInfra configuration
remain unchanged while the root investigates the structured-output integration.
No model/provider swap, rollback, restart, additional paid execution or other-app
operation was performed by this worker. Anonymous landing access and deployment
readiness passed; final anonymous guide functionality is not yet verified.
The scoped log extraction emitted only the validation field, expected enum,
actual enum scalar and exception type. Evidence is
`/private/tmp/ca-map-bottle-public-anonymous-assessment-scoped.log`.

## Locally tested strict assessment integration release

The root fixed the chosen Gemma integration without changing model, provider,
prompts, domain values, retry count, profiles or guidance output. For OpenRouter
Gemma only, assessment now uses `NativeOutput(QuestionAssessment, strict=True)`.
Before deployment, the full local deterministic suite passed 1,799 tests with
77 skips and one existing warning in 72.35 seconds; 129 focused and 19 independent
checks also passed. One isolated request through the same Gemma 26B/exclusive
DeepInfra route verified the actual strict native JSON-schema assessment in
1.18 seconds, with `is_byok=false` and reported cost $0.00022590. No saved hosted
guide was changed by that isolated test. The root then authorized the exact
public release `0444a3cffb7c1cb09f220fb7e36b8c45e5081563`.

The pre-update snapshot recorded four guides, seven attempts and daily admissions
seven, with identity/status hashes and installed marker preserved. The supported
remote-ref POST returned 200. Only the owned container's restart policy was set
to `no`; supervisor completed shutdown, and independent inspection confirmed
stable `running=false`, exit zero and no OOM. Uvicorn completed application
shutdown, embeddings exited zero, and Neo4j stopped and exited zero. Standard
`reload --update --wait` fetched the exact frozen commit and reused 13 cached
build steps.

Actual hosted checkout is clean at the new full SHA, with `public_paths=["/"]`.
All 383 deployed source files match its Git tree exactly, including
`core/chat.py` with the strict native assessment wrapper. The new source digest
is `1f2760347408d395426273711ae1b46663b1523e3d0b913c6d6dfc6f6d734096`.
The image is
`62ba97b22b01be84085555a5c9643c25c85b907dbfdaf3df10124aec36109d3a`, and
container is
`a00c8bcacc09ce9927a6db5d0a0e942f97f7c13ae7e2f667154844847c572bdb`.
The image is AMD64 and 1,739,834,217 bytes. Actual host bindings publish only
`127.0.0.1:9006` to web port 8080; Neo4j ports have no host bindings. The preceding
image `aef0b360fac312621498b9cd5595596377c435a1b17e0995e97b0932f158be30`
is still retained.

The post-update state and permitted nonsecret configuration exactly match the
baseline: four guides, seven attempts, daily admissions seven, all recorded
identity/status hashes and installed marker unchanged, SQLite integrity `ok`,
`google/gemma-4-26b-a4b-it`, exclusive `deepinfra/fp8` and trusted range
`127.0.0.1/32`. No seed or marker was overwritten. Runtime is still 5 GiB and
three CPUs, build limit 2,048 MiB, and normal `unless-stopped` policy is restored.
Authenticated readiness and a fresh anonymous non-inference homepage GET both
returned 200. The early runtime peak was 1,491,484,672 bytes (about 1.39 GiB),
with zero swap and all OOM counters zero.

The root dispatched exactly one final anonymous full-guide smoke after these
checks. This worker holds the service stable and submits no model request.
Testing for this fix occurred locally first; public testing is the final smoke,
not an iterative diagnosis loop. Backup configuration remains user-deferred.
Disposable evidence is `/private/tmp/ca-map-bottle-strict-reload-0444a3c.log`,
`/private/tmp/ca-map-bottle-strict-build-progress.log`,
`/private/tmp/ca-map-bottle-strict-shutdown.log`,
`/private/tmp/ca-map-bottle-before-strict-state.json`,
`/private/tmp/ca-map-bottle-after-strict-state.json`,
`/private/tmp/ca-map-bottle-strict-source-evidence.json` and
`/private/tmp/ca-map-bottle-strict-anonymous-home.html`.
