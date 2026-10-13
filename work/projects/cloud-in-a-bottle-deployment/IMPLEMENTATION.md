# Cloud deployment implementation

Labels: ready-for-agent

The app is public at [https://california-knowledge-map.akaisenghor.bottle.cloud/](https://california-knowledge-map.akaisenghor.bottle.cloud/) on the selected $20 Cloud in a Bottle
instance, frozen at `0444a3cffb7c1cb09f220fb7e36b8c45e5081563`. It uses fixed paid
`google/gemma-4-26b-a4b-it` exclusively through `deepinfra/fp8`; the user requires
no model or provider changes without direct instruction. There is no automatic
model/provider fallback and no additional Google key is required.

The final anonymous reading journey passed in 17.174719 seconds without owner
authorization: allowed assessment, relevance order, one linked expected
CalMatters AB 1751 article, completed search, `partial: false` and no disclosures.
Owner reopening, foreign-visitor 404 responses, saved attempt history, public
assets, privacy, bounds and persistence checks passed. Runtime peak was 1.745 GiB
with zero swap and OOM events. The $5 monthly key cap and
`include_byok_in_limit: true` are verified; observed usage totals $0.01231275
with $4.98768725 remaining.

The user explicitly said, "Leave backup configuration for later." Backup setup
and off-server recovery are deferred beyond this phase. This record supersedes
older provisioning and backup requirements in the research notes.

## Current deployment

| Item | Verified state |
| --- | --- |
| Instance | `akaisenghor.bottle.cloud`, x86_64, four CPUs, about 8 GB RAM, rootless Podman 5.8.3 |
| App | `california-knowledge-map` |
| Public URL | `https://california-knowledge-map.akaisenghor.bottle.cloud/` |
| Deployed SHA | `0444a3cffb7c1cb09f220fb7e36b8c45e5081563` |
| Source | Public GitHub repository, branch `codex/cloud-in-a-bottle-deployment`; deployment uses a full commit ref |
| Limits | 5 GiB runtime, three CPUs, 2 GiB build, one web worker |
| Live routing | `public_paths = ["/"]`; anonymous shell/assets and final reading guide pass |
| Release provenance | All 383 tracked source files match the frozen release; digest `1f2760347408d395426273711ae1b46663b1523e3d0b913c6d6dfc6f6d734096` |
| Corpus | `2026-10-12-real-corpus-01`, Neo4j Community 2026.07.1, sanitized SQLite and checksum-pinned embeddings |
| Selected inference | Paid `google/gemma-4-26b-a4b-it`, exclusive `deepinfra/fp8`; active in the public release; strict native question assessment only |
| Budget | Key limit $5/month verified; BYOK counting enabled; selected paid DeepInfra tests non-BYOK; total observed usage $0.01231275, remaining $4.98768725 |

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
does not make that provider's enum output reliable. A separate `google/gemini-3.1-flash-lite` trial used only
`google-ai-studio,google-vertex/global`. Its real production assessment trial
passed in 4.113 seconds with one framework request, one HTTP 200 response from
Google AI Studio, typed null dates and `reading_order: relevance`. The unchanged
factory's `reasoning.effort: none` was accepted. The response reported zero
OpenRouter billed cost for existing Google BYOK routing; it was not free inference.

The standard published rates are $0.25 per million input tokens and $1.50 per
million output tokens. Prompts, validators, output retries, Jev thresholds and
CPU embeddings remain unchanged. That private restart activated the Gemini
trial configuration without a code change; this is historical trial evidence.
[Gemini route and trial evidence](reports/gemini-trial-evidence-2026-10-12.md).

The complete Gemini HTTPS guide passed in 19.831821 seconds, retaining one
expected CalMatters AB 1751 article, a nonempty reading direction and an Article
Group. It reported `partial: false`, completed search and no disclosures. Foreign
visitor access returned 404; saved ownership and attempt history persisted.
The runtime peak was about 1.675 GiB with zero swap and OOM events.

The user subsequently chose paid Gemma with no additional Google key. Two
actual assessments through exclusive `deepinfra/fp8` passed, each returning
`allowed`, genuine null dates, typed `None` and `reading_order: relevance` with
one HTTP request. Both observed DeepInfra and `is_byok: false`. Their exact
funded key-usage delta was $0.00053218, bringing OpenRouter-funded usage to
$0.00309203 and remaining credit to $4.99690797 under the verified $5 monthly
limit. Historical BYOK usage stayed $0.00601500. Earlier BYOK snapshots changed
without verifier inference, so their exact per-guide attribution remains
unresolved; the paid Gemma trials' funded delta is separately verified.

The selected provider policy excludes Google endpoints and their BYOK route.
No new DeepInfra or Google key is necessary. The user enabled BYOK counting, and key metadata
now verifies `include_byok_in_limit: true` under the same $5 monthly limit.
This setting does not authorize a model change. The full private HTTPS guide
confirmed non-BYOK routing and funded cost; final public counters are recorded
below.
The allowance excludes TypeSafe, Logfire, purchase fees
and unrelated provider usage. No prompt, validator, output-retry or threshold
relaxation was made. The earlier assessment output tool omitted a strict flag; its later enum
failure motivated the native integration below. Endpoint metadata alone is not
proof of enforcement.
[Paid Gemma route evidence](reports/gemma-paid-route-2026-10-12.md).

The paid-Gemma private HTTPS guide completed in 14.875 seconds, returning
`allowed`, `reading_order: relevance`, genuine null dates, the expected
CalMatters AB 1751 article, reading directions and two Article Groups. It
reported no partial search or disclosures. Ownership and persistent-history
checks passed. Runtime peak was about 1.647 GiB, with zero swap and OOM events.
The exact funded delta was $0.00139204, bringing funded usage to $0.00448407
and the remaining monthly allowance to $4.99551593. Historical BYOK usage
remained $0.00601500. This passed without a new source change.

## Final native assessment release and acceptance

The first public tool-output assessment again returned the invalid reading-order
string `"null"`. The fix preserves the selected model/provider and wraps only
OpenRouter Gemma QuestionAssessment in library `NativeOutput(..., strict=True)`.
Guidance's runtime override retains tool mode; other deployment modes, profiles,
prompts, domain validators, zero retries and retrieval policy are unchanged.
Strict-required properties, null date unions and enum values are emitted in
native JSON Schema. Unsupported wire string-length constraints and cross-field
policy remain enforced by the original application validators.
[Independent strict review](reports/strict-gemma-review-2026-10-13.md),
[hosted diagnosis](reports/hosted-http-verification-2026-10-12.md).

The full deterministic suite passed 1,799 tests with 77 skipped and one existing
sampling-temperature warning in 72.35 seconds. The source worker's 129 focused
checks and independent 19-case review passed. JavaScript checks passed 31 tests.
One isolated real native assessment passed on the same Gemma/DeepInfra route
before commit/push/deployment. The live frozen release then passed one final
anonymous guide retry in 17.174719 seconds, with allowed/relevance assessment,
one linked expected AB 1751 article, completed search, no partial result and
no disclosures, without owner Authorization. The response includes a nonempty
reading direction and two Article Groups. The owner reopens the same guide
unchanged; foreign visitor B gets 404, and all seven prior attempts remain in
history. SQLite holds four guides across three owners and eight attempts
(five completed, three failed), with daily admission count eight. Peak runtime
memory was 1.745 GiB with zero swap and OOM events.

The final anonymous smoke charged $0.00135362. Funded key usage is $0.00629775;
historical BYOK usage is $0.00601500,
unchanged during the selected paid tests. Observed combined usage is
$0.01231275 and remaining monthly allowance is $4.98768725 with a $5 limit,
monthly reset and BYOK counting enabled.
No model change or additional provider key was required. Public deployment and
its reading journey are complete; no new model trials, paid verification or
human budget question remain. Backup configuration remains deferred.

The exact proxy setting `127.0.0.1/32` is active in the current public web
process. Router source, actual Caddy configuration and
socket peer evidence passed [proxy review](reports/trusted-proxy-review-2026-10-12.md).

Hosted owner cancellation and interruption recovery remain follow-up evidence;
local failure checks already pass. They are not new launch prerequisites.

Planned maintenance uses the supported `podman update --restart=no` before
private supervisor shutdown and Bottle stop/reload. The normal `unless-stopped`
policy otherwise restarts a clean exit, making a momentary stopped-state reading
insufficient. The replacement container restores the normal policy. Bottle
gives only ten seconds before forced termination, while Neo4j shutdown took
about eleven seconds. The earlier Gemini maintenance verified the temporary
policy, stable stopped state and clean service exits, then recreated the same
code with the normal policy. Saved guide and attempt state matched before
and after. [Hosted maintenance proof](reports/hosted-private-deployment-2026-10-12.md).

The subsequent same-code paid-Gemma configuration reload invoked a cold
llama.cpp compile. Plain reload always builds in this Bottle version; there is
no supported per-app skip-build or manifest-only API. Public SHA `c3c3f01` did
not change Docker build inputs, but cache reuse was unproven. The later strict
assessment source release was deployed through the official frozen-update flow.
Future reloads still invoke the builder; allow for another build. No cache or
global setting change or internal recovery shortcut is proposed.
[Builder review](reports/build-cache-review-2026-10-13.md).

Backup destination, schedule and off-server restoration remain deferred at the
user's request. Resume that work with the installed Bottle backup service and
its verified contract; a running backup app is not evidence of recoverable
snapshots.
