# Deploy the portfolio app on Cloud in a Bottle

Labels: ready-for-agent

Planned October 12, 2026 against repository revision `5c00b4d`. The maintainer selected Imbue's $20 plan and OpenRouter with a $5/month cap, then authorized starting implementation using orchestration and the Cloud in a Bottle skill. Container packaging, public-service controls and safe data preparation are assigned in parallel. Provisioning and public launch still require their checks below. [Implementation record](IMPLEMENTATION.md).

## Outcome and scope

Publish a stable HTTPS URL where portfolio visitors can submit a California political question, receive a Source Guide, open its Source Articles and relevant section links, and return to their saved guides. Support low traffic with a fixed server bill and bounded external-service use.

Use Imbue Large, advertised at $20/month for 8 GB RAM, 4 vCPU, and 160 GB disk. Start on its supplied domain; a custom domain can follow after launch. Keep scraping, the Story Pipeline, model evaluations, and bulk graph updates on the existing machine. The public deployment serves a prepared corpus. [Imbue plans](https://cloudinabottle.imbue.com/).

Initial inference uses the existing OpenRouter Model Deployment. ChatGPT subscription inference is a later option and does not block this launch. Preserve ADR 0023's Jev structural retrieval, sparse and dense branches, existing immutable prompts, and the stored embedding space. This plan proposes no new retrieval backend or model re-embedding.

## Proposed runtime

Deploy one Cloud in a Bottle app with one container containing:

| Process | Responsibility | Network |
| --- | --- | --- |
| Python 3.13.5 / FastAPI | Source Guides and one Uvicorn worker | Container HTTP port 8080, listening on `0.0.0.0` |
| Neo4j Community | Prepared graph, full-text and vector indexes | Bolt on `127.0.0.1:7687` inside the container |
| CPU llama.cpp | Existing EmbeddingGemma artifact and settings | HTTP on `127.0.0.1:8081` inside the container |
| Existing process supervisor | Service startup, signals, child reaping, bounded restarts, logs | No public administration interface |

Cloud in a Bottle supplies HTTPS and its HTTP router. Do not declare additional host ports for Neo4j or embeddings. Its cross-app service system speaks HTTP/WebSocket and does not establish a private Bolt network. Bundling the processes avoids that integration, but must pass the restart and rootless-container checks below. [App deployment](https://cloudinabottle.org/docs/creating_an_app/overview.html), [cross-app services](https://cloudinabottle.org/docs/creating_an_app/cross_app_services.html).

Use a pinned supervisor such as supervisord, installed through `uv` into the managed Python environment. Reuse process management rather than writing a service manager. Pin the Neo4j distribution and matching Java runtime, llama.cpp revision, Python, uv, and base image. Match the existing graph's Neo4j version before choosing an upgrade. Confirm the hosted machine architecture before selecting binaries. [Container process management](https://docs.docker.com/engine/containers/multi-service_container/).

### Initial resource budget

These are proposed starting limits, not measured requirements:

| Allocation | Starting budget |
| --- | --- |
| Combined app container | 5 GiB maximum, 3 CPU cores |
| Neo4j within that maximum | 1 GiB heap + 1 GiB page cache, with room for native memory |
| Python, embeddings, supervisor and spare container capacity | Remaining 3 GiB; measure peak usage and bound embedding threads |
| Host, router, DNS, filesystem cache and backup operations | About 2.57 GiB outside the container on the actual host |
| Image build | Separate 2 GiB maximum, run while this app is stopped |

Authenticated preflight measured about 7.57 GiB total host RAM and 1.36 GiB
already used. The initial six-GiB proposal was reduced to five GiB for host
headroom. The real-corpus ARM64 rehearsal peaked at 2.15 GiB during startup,
vector search and reader checks. A complete paid question on the x86_64 host
must still establish the workload limit.

The manifest has separate runtime and build memory limits. Builds compete for the same 8 GB host, so the first release procedure accepts maintenance downtime instead of rebuilding beside a full running container. Require at least 20% free disk before a build or corpus replacement, and retain only the tested release plus its rollback candidate. [Manifest resource limits](https://cloudinabottle.org/docs/creating_an_app/manifest_spec.html).

## Persistent data and credentials

Use the injected `BOTTLE_APP_DATA_DIR` as the persistence root. Proposed children are `neo4j/`, `sqlite/document_store.db`, `models/`, and `recovery/`. Keep secrets out of these database exports. Store log files only with bounded rotation; prefer container stdout/stderr for service logs.

Copy a consistent, sanitized SQLite corpus, preserving Stories and Publication metadata. The current reader uses this database for publication labels and relevant section links, and the same database holds saved Source Guides. Clear local saved guides and search attempts in the export copy only. Do not deploy the maintainer's private questions or alter the original database. Set `SQLITE_DB_PATH` to this persistent file before application imports. [Reader projection](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/chat_presentation.py:70), [Guide store](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/adapters/source_guides.py:27).

Preserve the embedding artifact's checksum and the current pooling, projection, context and 768-dimensional vector settings. Use CPU inference and a Linux model path. Do not download a different conversion or rebuild embeddings as a deployment shortcut. [Embedding launcher](/Users/akaisenghor/Projects/california-political-knowledge-map/main/scripts/llama-embed.sh).

Retrieve credentials at startup through Cloud in a Bottle's secrets service with explicit grants. Inject them into the existing environment-based application without logging the response or putting credentials in Docker layers or command arguments. Validate the installed secret service's actual response format first. [Secrets service](https://cloudinabottle.org/docs/creating_an_app/cross_app_services.html).

| Configuration | Required value or action |
| --- | --- |
| `CHAT_DEPLOYMENT` | `openrouter` |
| `OPENROUTER_API_KEY` | Dedicated public-demo key with $5 monthly spending limit |
| `OPENROUTER_MODEL`, `OPENROUTER_PROVIDERS` | One paid model and exclusive provider policy, selected after real structured-output/tool compatibility checks |
| `TYPESAFE_API_KEY` | Jev credential; confirm account availability, quotas and billing |
| `NEO4J_URI`, username/password/database | Container loopback connection and fresh deployment credentials |
| `LLAMA_CPP_EMBEDDING_BASE_URL`, `EMBEDDING_MODEL` | `http://127.0.0.1:8081` and `embeddinggemma` |
| `SQLITE_DB_PATH` | Persistent corpus/Source Guide database |
| `LOGFIRE_TOKEN`, project and environment | Deployment-specific telemetry credentials and `production` environment |

Reuse the model factory and telemetry initialization. The cloud entry point must initialize telemetry before building agents. Preserve the current schema validation and read-only Cypher authorization. Avoid depending on macOS Keychain. Do not configure the unused legacy Query Rewriter for this deployment. [Model deployments](/Users/akaisenghor/Projects/california-political-knowledge-map/main/docs/model-deployments.md), [Jev credential](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/adapters/jev.py:75).

## Public access and cost controls

Initially keep the app owner-only. Make the visitor routes public after verification. `public_paths` uses prefixes, so publishing `/` exposes the entire app route tree. Keep operator actions in SSH/CLI or a separate owner-only service. Inventory all routes and middleware before publication. [Routing and owner headers](https://cloudinabottle.org/docs/how_it_works/routing.html), [Security](https://cloudinabottle.org/docs/how_it_works/security.html).

The current local service lists saved guides globally and has no visitor ownership check. Before public launch, introduce an anonymous visitor identity with a random secure HttpOnly cookie. Scope guide listing, reading, updates and cancellation to that identity. Enforce ownership server-side; a guessed guide ID must not authorize access. Returning in the same browser restores that visitor's guides. Clearing the cookie loses access. No account signup, guide sharing, or identity recovery is required for the first version. Explicitly curated public examples may be added separately.

Proposed launch defaults:

- One active question execution and at most two queued executions for the entire process. Reject excess admission without creating an unbounded task queue.
- Limit submissions and updates per visitor and source IP using an existing rate-limit library; begin at three per hour per visitor and a global ceiling of 20 per day. Retune after observed traffic. Provider spending controls remain the budget authority.
- Bound request body size and question length, initially 4,000 characters. Reuse existing validation; do not change prompt resources for deployment.
- Keep the existing 180-second retrieval deadline. Add an overall 240-second question deadline and ensure cancellation reaches model requests and worker operations where supported. Start with 60-second model request timeouts, two transport attempts and a 15-second rate-limit wait cap; verify these do not silently degrade representative questions.
- Bound output and aggregate model calls through the framework's supported limits after measuring a representative complete question. Do not implement a second token-accounting system.
- Use an OpenRouter-funded route for the demo. Avoid BYOK charges outside the selected cap. Verify budget exhaustion produces a useful terminal outcome and prevents further paid work. Do not change to another model/provider to bypass a limit.
- Apply origin checks to modifying requests and correct proxy trust for visitor IP limits. Persist guide ownership, bounded retention and any daily admission counters that must survive restarts. Keep the deployment single-worker until shared admission state is implemented.

Measure complete questions across Chat Agent, Jev composition and binding, and TypeSafe selection. A small number of external model calls is not a reliable cost estimate for a whole Source Guide.

## Implementation phases

### 1. Measure and freeze the release inputs

Record Neo4j version, database size, indexes and graph counts; SQLite schema and corpus size; exact GGUF checksum; llama.cpp revision; Python/uv versions; and application commit. Measure idle and peak memory for representative questions. Confirm Jev account billing and the chosen OpenRouter model/provider supports the current tools and outputs. Preserve the local corpus and private guide database unchanged. Record the packaging decision in an ADR before implementation changes architecture.

Deliverable: a deployment inventory and compatible export recipe. If the combined workload cannot stay within the proposed memory budget, reduce ingestion/build concurrency and tune limits before changing the selected plan.

### 2. Build a reproducible container

Add a Dockerfile, `.dockerignore`, `cloudinabottle.toml`, supervisor configuration and a cloud-specific web launch command. Use `uv sync --locked` with the required deployment dependencies, and `uv run --no-sync` at runtime. Package immutable prompts, coverage resources and web assets from the repository. Exclude `.env`, SQLite files, cached models, `.scratch`, and local review outputs from the build context.

Startup fetches secrets, verifies writable data directories, starts Neo4j and embeddings, then starts one web worker after those dependencies are ready. An unhealthy required process must make readiness fail. Add cheap liveness/readiness endpoints without generating paid model requests on each poll. Ensure graceful shutdown cancels work, records interrupted attempts and flushes database state. Retain build commit/version metadata even when the image has no Git checkout.

Deliverable: image that boots under rootless Podman with the proposed memory limit and passes restart, dependency failure, import, resource-loading and persistent-data checks.

### 3. Make the local web app ready for visitors

Implement the ownership and admission controls above. Keep source corpus reads and graph retrieval unchanged. Add meaningful tests for cross-visitor list/read/update/cancel access, quota rejection, request limits, cancellation, restart and public error responses. Run the existing deterministic CI suite with `uv`.

Deliverable: a public service whose saved guides stay scoped to each visitor and whose work remains bounded.

### 4. Export data and rehearse recovery

Create a Neo4j Community offline dump of the selected graph using version-compatible tools. Produce the sanitized SQLite copy through SQLite's backup API rather than copying an actively written database file. Restore both into a disposable instance and verify full-text/vector indexes, corpus alignment, Publication labels and section links. Configure fresh cloud Neo4j authentication separately; a graph dump is not a credential migration. [Neo4j offline backup](https://neo4j.com/docs/operations-manual/current/backup-restore/offline-backup/).

Keep the graph release export immutable off the server. Nightly, create a consistent SQLite backup, then send recovery artifacts to encrypted off-server storage with restic. Target a 24-hour recovery point for saved guides and a one-hour restoration procedure, subject to rehearsal. Retain seven daily copies and four weekly copies, adjusting storage to measured sizes.

Graph data changes only during a corpus release. Back up the graph before replacement and retain its version with the matching SQLite corpus export. Refresh the SQLite corpus tables without deleting cloud visitor guides or ownership. Capture platform state, backup configuration and recovery credentials separately; the bundled backup app excludes platform state and reads live database files without consistency guarantees. [Bottle backup limitations](https://cloudinabottle.org/docs/operation/backups.html).

Deliverable: an operator can recover the same corpus and saved guide ownership from a clean environment, with measured restoration time.

### 5. Provision the selected space and deploy privately

Create the Imbue Large space with the owner's SSH key, billing and supplied domain. Confirm 8 GB/4 vCPU/160 GB, machine architecture, actual region and any transfer charges. Configure the required secrets and off-server backup destination. Account/payment, provider-key creation and secret entry are human steps; automate the reproducible deployment steps after credentials are available.

Deploy the candidate owner-only. Transfer the checked corpus and model artifact into persistent storage through authenticated channels. Import the graph once, before serving traffic. Startup must refuse an empty or incompatible database instead of silently overwriting existing data. Establish startup ordering so readiness is checked after data import; an empty graph can prevent current app startup.

The documented CLI supports `bottle app deploy <git-url> --wait`, and reload with `--update` pulls before rebuilding. Exact release-ref selection and automatic rollback are not documented. Inspect the installed CLI/API, determine a reproducible way to select a tested commit, and record the actual deployed SHA. Do not invent a `--ref` flag or deploy a moving branch without checking the resulting commit. [Bottle CLI](https://cloudinabottle.org/docs/operation/cli.html).

Deliverable: a private deployment with the intended code/corpus versions, functioning secrets, verified backups and a rehearsed return to the previous tested release. Confirm private-repository access if needed.

### 6. Verify and publish

Use the repository's Source Guides verification map and real HTTP service. Exercise question assessment, successful retrieval, Deferred/Declined outcomes, saved guide reopening, update/cancel, original article links and section links, dependency failure and provider-limit exhaustion. Keep live smoke requests within the $5 model budget. HTTP checks establish service behavior; browser verification remains subject to the repository's explicit browser authorization.

Verify two independent visitor cookie jars cannot list, read or modify each other's guides. Reboot the container and the space; confirm the corpus, model artifact, saved guides and ownership survive, and unfinished searches terminate as interrupted. Kill each required process to check readiness and supervisor recovery. Measure memory, disk growth, embedding latency, question completion time, and whole-question external cost.

Test the actual HTTPS hostname and proxy middleware. Check that Neo4j and embedding ports are unreachable publicly. Publish the intended routes, repeat unauthenticated checks through that hostname, then add the URL to the portfolio. Keep corpus coverage dates visible so visitors understand the prepared snapshot.

Deliverable: a public link, a verification record naming the deployed commit/corpus, and an operator runbook.

## Releases, rollback and ongoing operation

For code updates, first pass CI and candidate verification, record the release SHA, back up persistent state, stop question admission, drain or explicitly interrupt active searches, stop the app, rebuild and restart during a short maintenance window. Verify readiness, saved guides and a representative question before reopening admission. Never combine a Neo4j major upgrade with a routine app release.

Rollback returns to the previous tested checkout/image and configuration without deleting persistent data. If a migration prevents old code from reading new data, restore the matching pre-release backup while the app is stopped. Rehearse this before public launch; the platform does not establish zero-downtime or automatic rollback. Avoid app removal, which can delete data without its preservation option.

Initially review uptime, failed searches, backup success, memory/disk and provider spending each day after launch. Reuse existing Logfire instrumentation. Add an inexpensive external HTTPS health check and notify the operator only on actionable outages or failed backups. Set log retention and guide retention deliberately; a proposed first policy is 30 days for anonymous saved guides, preserving curated examples independently.

## Budget and launch gates

| Item | Budget treatment |
| --- | --- |
| Imbue Large | $20/month advertised base |
| OpenRouter | Up to $5/month, maintainer-selected cap |
| Jev / TypeSafe | Separate usage cost and account terms to confirm; required for the existing retrieval path |
| Off-server backups | Provisional $1 to $3/month allowance, verify after measuring retained bytes and selecting storage |
| Domain | $0 additional initially with supplied domain; custom domain optional |
| Logfire, taxes and transfer | Verify account quotas and actual provider terms; do not assume included |

TypeSafe currently advertises $42 per billion input tokens, equivalent to $0.042 per million. That headline does not establish this account's full bill or quotas. Confirm them and measure real selection usage before publication. The total budget is $20 plus used inference, Jev, backup storage and any applicable extras; $25 is not an all-in guarantee. [TypeSafe pricing headline](https://typesafe.ai/).

Launch requires all of the following:

1. Current tools/output schemas work on the selected OpenRouter route, and Jev credentials/billing are available.
2. CPU embeddings reproduce the existing vector space and retrieval works against the exported corpus.
3. The runtime fits within the 5 GiB container limit with host headroom and no out-of-memory failures.
4. Visitor isolation, bounded admission, provider spending controls and proxy/hostname behavior pass their checks.
5. Consistent off-server recovery and release rollback have been rehearsed.
6. The tested public HTTPS URL runs the recorded release and shows accurate corpus coverage.

Unresolved provisioning details are the supplied hostname, actual region/architecture, backup destination and its quote, TypeSafe account terms, exact release-selection mechanism, and measured memory/cost limits. These are explicit prelaunch checks, not reasons to stop preparing the container and public-service changes.

Supporting research: [platform fit](/Users/akaisenghor/Projects/california-political-knowledge-map/main/work/research/cloud-in-a-bottle-2026-10-12.md), [deployment details](/Users/akaisenghor/Projects/california-political-knowledge-map/main/work/research/cloud-in-a-bottle-deployment-details-2026-10-12.md).
