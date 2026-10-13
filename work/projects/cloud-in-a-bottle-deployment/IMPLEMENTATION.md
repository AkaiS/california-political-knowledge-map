# Cloud deployment implementation

Labels: ready-for-agent

The owner-only app runs on the selected $20 Cloud in a Bottle instance at
`a74ca13ffd6a6a6ddfd23568e8e9f26934d57286`. Infrastructure and visitor-isolation
checks pass. Gemini 3.1 Flash Lite is active after the private restart. Its HTTPS
guide completed in 19.832 seconds with the expected CalMatters article, reading
direction and Article Group, a completed search and no partial-search disclosure.
Publication is waiting for the owner to enable BYOK usage counting on the
dedicated $5/month OpenRouter key, then public access verification.

The user explicitly said, "Leave backup configuration for later." Backup setup
and off-server recovery are deferred beyond this phase. This record supersedes
older provisioning and backup requirements in the research notes.

## Current deployment

| Item | Verified state |
| --- | --- |
| Instance | `akaisenghor.bottle.cloud`, x86_64, four CPUs, about 8 GB RAM, rootless Podman 5.8.3 |
| App | `california-knowledge-map` |
| Private URL | `https://california-knowledge-map.akaisenghor.bottle.cloud/` |
| Deployed SHA | `a74ca13ffd6a6a6ddfd23568e8e9f26934d57286` |
| Source | Public GitHub repository, branch `codex/cloud-in-a-bottle-deployment`; deployment uses a full commit ref |
| Limits | 5 GiB runtime, three CPUs, 2 GiB build, one web worker |
| Live routing | `public_paths = []`; authenticated readiness 200, unauthenticated shell 404 |
| Prepared public SHA | `c3c3f01ed569f5336d8f8a0188cefec7cbed1c3a`, committed and pushed; not deployed |
| Corpus | `2026-10-12-real-corpus-01`, Neo4j Community 2026.07.1, sanitized SQLite and checksum-pinned embeddings |
| Active inference | OpenRouter `google/gemini-3.1-flash-lite`, exclusive order `google-ai-studio,google-vertex/global`; existing Google BYOK served the Gemini calls |
| Budget | Key limit $5/month verified; `include_byok_in_limit=false`, so the requested inference-wide cap is not yet established |

Bottle revision `6ea27634d1cbfc1b29caec29b53b76d919201b97` matches the
inspected contracts. The complete manifest passes its installed parser;
consumed Secrets service version is `==0.1.0`. GitHub OAuth is not a remaining
prerequisite for the public repository. The six existing apps remain running.
[Instance preflight](reports/instance-preflight-2026-10-12.md),
[private deployment evidence](reports/hosted-private-deployment-2026-10-12.md).

## Accepted infrastructure and data evidence

The AMD64 image built and started on the actual instance under the declared
limits, without reported OOM or swap use. Rootless persistence mapping was
verified. Only application HTTP is published on host loopback; Neo4j Bolt and
embeddings remain inside the container. All 383 tracked source files match the
frozen SHA. Bottle does not inject the image revision argument, so the checkout
and source-content digest establish release provenance.

The hosted graph has 3,668 nodes, 6,061 relationships, 98 Source Articles and
2,407 Article Chunks. All 16 indexes are ONLINE, including the 768-dimensional
COSINE vector index. SQLite passes integrity checks and retains 157 Stories;
every graph Article URL aligns with a Story. Real CPU embeddings returned 768
dimensions. The original container reached about 2.15 GiB during startup and
short assessments. The corrected container's peak after the completed reading
retry was about 1.517 GiB, under its 5 GiB limit, with zero swap and OOM events.
[Hosted runtime and corpus evidence](reports/hosted-private-deployment-2026-10-12.md).

The authorized local offline graph export interrupted Neo4j for 14 seconds and
restarted it immediately. Before/after inventory matched. The SQLite export
removed six local guides and seven attempts, preserved corpus data and left the
source checksum unchanged. A disposable real-corpus restore passed graph,
index, vector, reader and restart checks. The immutable seed was transferred
through authenticated SSH, with all artifact checksums verified remotely.
[Data preparation](reports/data-preparation-2026-10-12.md),
[real seed rehearsal](reports/seed-preflight-2026-10-12.md).

Secrets bootstrap uses individual grants and maps the owner's existing
`OPENROUTER_KEY`, `LOGFIRE_API_KEY` and `LOGFIRE_URL` names to application
configuration. It preserves the existing TypeSafe entry. Credentials and fresh
Neo4j authentication worked at hosted startup; no credential values were
printed or committed. Cloud request settings are 60 seconds, two attempts and
a 15-second rate-limit wait cap. The overall question deadline is 240 seconds.
[Transport review](reports/cloud-transport-review-2026-10-12.md),
[deployment runbook](../../../docs/cloud-deployment.md).

## Source Guides and deployed model compatibility

Public mode scopes saved guides, reads, updates and cancellation to anonymous
browser identities. It bounds body and question size, active and queued work,
hourly visitor/IP submissions and persistent daily admission. Existing unowned
local guides remain private. Hosted HTTPS checks confirmed separate visitor
cookies, foreign-Origin rejection, request bounds, cross-visitor 404 responses
and stable reopening of terminal guides.

The missing-reference question passed and returned `needs_edit`. The initial
reading question failed during assessment before retrieval. The installed OpenRouter
Google transformer inferred from the `google/` model prefix rewrote genuine
nullable date unions into `nullable: true`, which the constrained Gemma route
did not honor. An isolated same-model, same-provider diagnostic changed only
the library schema transformer and returned typed `None` dates successfully.

The factory now selects `OpenAIJsonSchemaTransformer` only for OpenRouter
`google/gemma-` names, including the supported `~` alias. Other inferred
capabilities, Gemini and local profiles, prompts, domain validation and zero
output retries remain unchanged. The ten-case regression and adjacent targeted
suites passed 120 tests. Independent review passed 54 focused tests and verified
standard null/date wire semantics and continued rejection of invalid strings.
[Hosted HTTP checks and diagnosis](reports/hosted-http-verification-2026-10-12.md),
[independent profile review](reports/openrouter-profile-review-2026-10-12.md).

The corrected release preserved the existing guide, failed attempt and visitor
ownership. Its real HTTPS retry completed assessment, retrieval and reading
guidance in 11.996 seconds with two CalMatters articles and nonempty directions.
The saved response explicitly reported a partial search; reopening and foreign
visitor rejection passed again. It is a completed guide, not a clean pass for
every retrieval branch.

Independent direct full-text and dense checks succeeded. A structural-only
probe stopped before composition, binding or graph execution. The bounded
selection probe then confirmed `SelectionAbstention` at `role_subtypes`:
`LaborUnion` scored 0.73 below the unchanged 0.80 threshold, while the other
subtype scored 0.85. All three TypeSafe requests returned HTTP 200; these probes
made zero OpenRouter requests. This is the documented conservative subtype
policy, so no threshold, prompt or selector adjustment was made. Historical
attribution to the original HTTP branch remains limited because its Logfire
span was not queried. [Selection policy](../../../docs/structural-retrieval.md).

The earlier Gemma reading retry cost $0.00131952 by current-key delta. Its
settled funded usage was $0.00232569 before the later Gemini execution. Current
funded and BYOK totals are recorded below.

The bill-focused Gemma execution failed assessment by returning the string
`"null"` for the nonnullable `reading_order` enum. The nullable-schema correction
does not make that provider's enum output reliable. The selected cloud Model
Deployment is now `google/gemini-3.1-flash-lite`, using only
`google-ai-studio,google-vertex/global`. Its real production assessment trial
passed in 4.113 seconds with one framework request, one HTTP 200 response from
Google AI Studio, typed null dates and `reading_order: relevance`. The unchanged
factory's `reasoning.effort: none` was accepted. The response reported zero
OpenRouter billed cost for existing Google BYOK routing; it was not free inference.

The standard published rates are $0.25 per million input tokens and $1.50 per
million output tokens. Prompts, validators, output retries, Jev thresholds and
CPU embeddings remain unchanged. The private restart activated the selected
model/provider configuration without a code change.
[Gemini route and trial evidence](reports/gemini-trial-evidence-2026-10-12.md).

The complete Gemini HTTPS guide passed in 19.831821 seconds, retaining one
expected CalMatters AB 1751 article, a nonempty reading direction and an Article
Group. It reported `partial: false`, completed search and no disclosures. Foreign
visitor access returned 404; saved ownership and attempt history persisted.
The runtime peak was about 1.675 GiB with zero swap and OOM events.

Latest current-key metadata shows OpenRouter-funded usage of $0.00255985 and
tracked BYOK usage of $0.00601500, combined $0.00857485, still below one cent.
BYOK usage increased between metadata snapshots despite no further inference
by the verifier. Delayed settlement or other key activity is unresolved, so
these counters are not a final total or exact per-guide cost attribution.
The zero response cost described OpenRouter billing, not free
Google inference. `include_byok_in_limit` is false, so BYOK currently bypasses
the key's verified $5/month allowance. The owner has been asked to enable
Include BYOK usage in limit on this existing key, keeping the $5 limit and
monthly reset. That required response is pending before publication. The cap
does not cover TypeSafe, Logfire, purchase fees or unrelated provider usage.

## Validation and next acceptance checks

The full deterministic suite with the correction passed 1,790 tests with 77
skipped and one existing sampling-temperature warning, in 67.67 seconds.
JavaScript CI checks passed all 31 tests. Independent privacy, lifecycle,
packaging, transport and schema reviews are recorded in the linked reports.

Remaining work in this phase:

- Obtain owner confirmation and verify `include_byok_in_limit=true` on the
  existing dedicated key, retaining `limit=5` and `limit_reset=monthly`.
- Deploy the prepared public SHA with `public_paths = ["/"]` only after the
  budget setting is verified. Then verify unauthenticated access and visitor
  isolation before publishing the portfolio link. It has not been deployed yet.

The exact proxy setting `127.0.0.1/32` is active in the current web process after
the private Gemini restart. Router source, actual Caddy configuration and socket
peer evidence passed [proxy review](reports/trusted-proxy-review-2026-10-12.md).

Hosted owner cancellation and interruption recovery remain follow-up evidence;
local failure checks already pass. They are not new launch prerequisites.

Planned maintenance uses the supported `podman update --restart=no` before
private supervisor shutdown and Bottle stop/reload. The normal `unless-stopped`
policy otherwise restarts a clean exit, making a momentary stopped-state reading
insufficient. The replacement container restores the normal policy. Bottle
gives only ten seconds before forced termination, while Neo4j shutdown took
about eleven seconds. The latest Gemini maintenance verified the temporary
policy, stable stopped state and clean service exits, then recreated the same
code/image with the normal policy. Saved guide and attempt state matched before
and after. [Hosted maintenance proof](reports/hosted-private-deployment-2026-10-12.md).

Backup destination, schedule and off-server restoration remain deferred at the
user's request. Resume that work with the installed Bottle backup service and
its verified contract; a running backup app is not evidence of recoverable
snapshots.
