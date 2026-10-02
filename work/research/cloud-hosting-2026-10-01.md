# Cloud hosting research, 2026-10-01

## Addendum: ChatGPT subscription inference

OpenAI's September 29 DevDay announcement adds Sign in with ChatGPT, allowing eligible Plus and Pro users to authorize app inference against their plan. OpenAI explicitly documents an open-source app running on a personal self-hosted VM. This creates another inference option for personal operation, alongside OpenRouter. [DevDay announcement](https://learn.chatgpt.com/docs/whats-new/devday-2026), [VM guide](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms).

The documentation does not establish that the developer's subscription can fund anonymous portfolio visitors. It directs paid or remotely hosted app developers to an interest process. Until that eligibility is confirmed, the public-demo recommendation below remains API-backed. Subscription inference consumes the existing Codex/ChatGPT Work allowance and still requires hosting Neo4j, the application, and embeddings. See the [focused research note](/Users/akaisenghor/Projects/california-political-knowledge-map/main/work/research/chatgpt-plan-inference-2026-10-01.md) for eligibility and integration details. [Hosted-app guidance](https://developers.openai.com/siwc/token-sharing-open-source), [Usage limits](https://learn.chatgpt.com/docs/sign-in-with-chatgpt).

## Recommendation

For a public portfolio demo, serve a prepared CalMatters graph, keep ingestion on the existing machine, and use OpenRouter for the Chat Agent and Query Rewriter. Run the small existing EmbeddingGemma model beside the application. This preserves the retrieval system while avoiding a cloud server large enough for the local chat model.

My first choice on cost is an 8 GB VPS running the web application, Neo4j Community, EmbeddingGemma, and an HTTPS proxy. Advertised low-cost candidates are roughly **$9-13/month**, with important stock or annual-payment conditions detailed below. DigitalOcean is a clearer price fallback at **$28.80/month for 4 GB with weekly backups**, subject to memory measurements, or **$57.60 for 8 GB**. [OVHcloud](https://us.ovhcloud.com/vps/), [Hetzner prices](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [DigitalOcean prices](https://www.digitalocean.com/pricing/droplets), [DigitalOcean backups](https://docs.digitalocean.com/products/backups/details/pricing/).

For easier deployment and less host maintenance, choose Railway. A planning estimate for the whole stack is **$32-45/month** with Neo4j running as a service you operate. Railway plus AuraDB Free can be cheaper, roughly **$11-22/month** for app and embedding compute, but Free Aura's inactivity policy makes it a weaker unattended portfolio choice. Fully managed paid Aura starts around **$65.70/month by itself**. [Railway rates](https://docs.railway.com/pricing/plans), [Aura pricing](https://neo4j.com/pricing/), [Aura instance lifecycle](https://neo4j.com/docs/aura/managing-instances/instance-actions/).

These are planning estimates, not measured resource requirements. Exclusions include taxes, domain registration, separate offsite backups, paid observability, registry/build charges, and traffic beyond included amounts. A small API inference budget of $1-5/month is plausible for the sample traffic below; enforce a spending limit before exposing the app. Repository baseline: `e17ffc5`.

## What actually needs to move

The public chat path currently depends on Neo4j, model inference, and in-memory Chat Sessions. It does not open SQLite at startup or use it for Evidence Assembly. The startup coverage query and EvidenceStore both read Neo4j. SQLite can remain local with the Story Pipeline when the deployed graph is a prepared snapshot. Source code takes precedence over older documentation describing SQLite startup reads. [Chat startup](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/chat_startup.py:117).

There are two separate model decisions:

- Both the Chat Agent and Query Rewriter can use OpenRouter. They have independent deployment settings; configuring only one leaves the other potentially dependent on local chat inference. OpenRouter requires a key, a model, and an explicit allowed provider list. [Deployment guide](/Users/akaisenghor/Projects/california-political-knowledge-map/main/docs/model-deployments.md).
- Dense retrieval still calls the local llama.cpp embedding endpoint. The supplied EmbeddingGemma Q8_0 artifact is approximately 318 MB. Keep the same model, projection, and embedding settings. An API embedding replacement requires adapter and authentication work; a different embedding space requires rebuilding stored vectors, even if dimensions match. [Embedding server](/Users/akaisenghor/Projects/california-political-knowledge-map/main/scripts/llama-embed.sh), [Deployment guide](/Users/akaisenghor/Projects/california-political-knowledge-map/main/docs/model-deployments.md).

The local chat model has approximately 14.44 GB of weights, before runtime memory. That is incompatible with the cheap VPS plans considered here. Moving chat inference to OpenRouter is the main cost reduction. [Chat server script](/Users/akaisenghor/Projects/california-political-knowledge-map/main/scripts/llama-server.sh).

The last recorded graph inventory, dated September 8, contains 98 Source Articles, 2,407 Article Chunks, 3,668 nodes, and 6,061 relationships. This is a historical observation, not a fresh measurement. It supports testing a small portfolio corpus first. [Graph inventory](/Users/akaisenghor/Projects/california-political-knowledge-map/main/work/initiatives/useful-graph-retrieval/research/04-graph-inventory-2026-09-08.md).

## Managed service route

All app-platform estimates below exclude chat inference and paid Aura unless specified. Assume low traffic, no ingestion on the public service, and app plus embedding memory of 1-2 GB. That memory assumption must be measured.

| Platform | Current pricing and estimated cost | Fit for this project |
| --- | --- | --- |
| Railway | Hobby is a $5 minimum including $5 usage. Container memory is $10/GB-month, actual CPU use $20/vCPU-month, egress $0.05/GB, and volume storage $0.15/GB-month. At 1-2 GB average memory, 0.05 vCPU, and 1 GB egress: $11.05-21.05 app plus embedding. [Rates](https://docs.railway.com/pricing/plans). | Best managed shortlist choice. Add a private Neo4j container and persistent volume to avoid Free Aura pauses. At 3-4 GB total average memory, 0.05-0.2 vCPU, 5 GB storage, and 1 GB egress, the calculated bill is $31.80-44.80. The Hobby fee is included, not added again. |
| Render | Paid web compute is $7/month for 512 MB or $25 for 2 GB. Hobby workspace has no subscription fee. Persistent disks cost $0.25/GB-month. A 2 GB app/embedding service plus a 2 GB Neo4j private service and 5 GB disk totals $51.25. [Pricing](https://render.com/pricing/). | Straightforward deployments, but its RAM price steps are less attractive. A disk belongs to one service instance and prevents horizontal replicas and zero-downtime redeploys. Cron jobs cannot access that disk. [Disk rules](https://render.com/docs/disks). |
| Fly.io | Usage pricing varies by region. The published shared-CPU examples put a 2 GB app/embedding Machine around $11/month; budget roughly $12-14 with small storage/traffic and confirm the selected region. Volumes cost $0.15/GB-month and US/EU internet egress $0.02/GB. [Pricing](https://fly.io/docs/about/pricing/). | Competitive for app hosting, but operating Neo4j and its storage still falls to you. Its free trial ends after 2 machine-hours or 7 days; old permanent free allowances are not a basis for a new deployment budget. [Trial](https://fly.io/docs/about/free-trial/). |
| Google Cloud Run | Request billing includes 180,000 vCPU-seconds, 360,000 GiB-seconds, and 2 million requests monthly at Tier 1 pricing. An illustrative 1,000 questions at 60 seconds each on 1 vCPU and 2 GiB uses 60,000 vCPU-seconds and 120,000 GiB-seconds, within those allowances. Other account workloads, startup, builds, storage, networking, and logs can add charges. [Pricing](https://cloud.google.com/run/pricing). | Potentially near-zero app compute after changes to session storage. Current approval state lives in process memory, and instances can disappear between proposal and approval. Session affinity is best effort. Running one maximum instance does not make memory durable. [Session affinity](https://docs.cloud.google.com/run/docs/configuring/session-affinity), [Autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling). |

Render Free sleeps after 15 idle minutes and can take about a minute to resume. Its 512 MB limit must accommodate both the Python app and embedding process if combined. It has no persistent disk and may suspend unusually high outbound API/database traffic. I would use it for an experiment, not the primary portfolio link. Hobby includes 5 GB monthly outbound bandwidth, then $0.15/GB. [Free service rules](https://render.com/docs/free), [Pricing](https://render.com/pricing/).

The Railway estimate assumes a graph fitting its documented 5 GB Hobby volume allocation. Measure database files and transaction logs, configure log retention, and confirm larger-volume terms before growth forces a plan change. Volumes also prevent replicas and cause a short redeploy interruption. [Plan allocations](https://docs.railway.com/pricing/plans), [Volume behavior](https://docs.railway.com/volumes/reference).

### The managed database changes the bill

The latest Aura FAQ gives Free limits of 200,000 nodes and 400,000 relationships, comfortably above the recorded graph. Another official landing page still lists 50,000 and 175,000; both exceed this snapshot, but verify the actual account limits. Free does not include rolling seven-day backups. [Current FAQ](https://neo4j.com/cloud/platform/aura-graph-database/faq/), [Older conflicting page](https://neo4j.com/free-graph-database/).

The operational documentation says Free pauses after 72 hours of inactivity, and deletes an instance paused for more than 30 days. A paused database cannot serve visitors and requires resumption. This undermines a portfolio link that may sit unused for weeks. Do not assume occasional read-only visits satisfy the inactivity definition. [Lifecycle documentation](https://neo4j.com/docs/aura/managing-instances/instance-actions/).

Aura Professional starts at $0.09/GB-hour with a 1 GB minimum. At 730 hours that is $65.70/month, with daily backups and seven-day retention. Railway app plus embedding and paid Aura therefore starts around $77-87/month under the assumptions above; Render's 2 GB app plus Aura is $90.70. A managed app platform with a Neo4j container avoids that price, but you retain database upgrades, backup consistency, and recovery responsibilities. [Aura pricing](https://neo4j.com/pricing/).

## VPS route

Use one Linux host with containers or supervised services for the Python application, Neo4j, EmbeddingGemma, and Caddy. Public traffic reaches HTTPS only; Neo4j and embedding endpoints stay private. Caddy can obtain and renew certificates for a public domain whose DNS points to the server. [Caddy HTTPS guide](https://caddyserver.com/docs/quick-starts/https).

| Candidate | Compute | Monthly infrastructure with provider backups |
| --- | --- | --- |
| Hetzner EU CX23, conditional on stock | 2 vCPU, 4 GB RAM, 40 GB disk; $6.49 | $8.39 including $0.60 IPv4 and 20% backups. |
| Hetzner EU CX33, conditional on stock | 4 vCPU, 8 GB RAM, 80 GB disk; $9.99 | $12.59 including $0.60 IPv4 and 20% backups. Preferred initial size. |
| OVHcloud US VPS-2, advertised annual equivalent | 4 vCores, 8 GB RAM, 75 GB disk | From $8.50/month; linked configuration selects 12 months paid upfront, approximately $102. IPv4 and previous-24-hour daily backup included. Monthly and renewal quotes need confirmation. |
| DigitalOcean Basic 4 GB | 2 vCPU, 80 GB disk; $24 | $28.80 with weekly backups. |
| DigitalOcean Basic 8 GB | 4 vCPU, 160 GB disk; $48 | $57.60 with weekly backups. |

Hetzner figures use its June 15, 2026 price adjustment and EU specifications; USD prices exclude VAT. The public page currently marks the cost-optimized products unavailable. EU plans include 20 TB transfer. The same cheap plan price cannot be assumed in Oregon: the US CPX21 and CPX31 now list $37.49 and $73.49 respectively. [Price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [Specifications and availability](https://www.hetzner.com/cloud/cost-optimized/), [IPv4](https://docs.hetzner.com/cloud/servers/primary-ips/overview/), [Backup charge](https://docs.hetzner.com/cloud/billing/faq/).

DigitalOcean figures use standard Basic Droplets; weekly backups add 20%, daily backups 30%. Region availability must be checked at provisioning. [Droplet pricing](https://www.digitalocean.com/pricing/droplets), [Backup pricing](https://docs.digitalocean.com/products/backups/details/pricing/).

OVHcloud's low headline is not a verified month-to-month offer. Its configuration link selects `upfront12`, and long commitments can leave you liable for the remaining balance. Choose a standard datacenter for the proposed container deployment; its Local Zone FAQ says Docker is not supported there. [VPS offering and configuration links](https://us.ovhcloud.com/vps/), [Billing terms](https://support.us.ovhcloud.com/hc/en-us/articles/360002306224-Overview-of-Billing-with-OVHcloud-US).

Neo4j lists a cloud minimum of 2 GB RAM and 2 CPU cores. The app, embedding process, OS, and vector-index working memory are extra. Four GB may work for this small graph and low concurrency, but there is no measured evidence yet. Start with 8 GB if affordable, then reduce after observing memory and latency. [Neo4j requirements](https://neo4j.com/docs/operations-manual/current/installation/requirements/).

Oracle Always Free is worth considering only if zero spend is essential. Its current documentation lists an Ampere allowance equivalent to 2 OCPUs and 12 GB RAM, plus 200 GB block storage. Capacity can be unavailable, and idle instances can be reclaimed after the documented seven-day utilization window. That is a poor primary home for an unattended portfolio demo. [Oracle limits and reclamation](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

## Inference and spending limits

OpenRouter currently lists `google/gemma-4-26b-a4b-it` from $0.042 per million input tokens and $0.22 output. The page lists DeepInfra at $0.07/$0.34. Required tool and structured-output support varies by provider; test the explicit provider policy already required by this project. [Model and provider rates](https://openrouter.ai/google/gemma-4-26b-a4b-it).

Illustrative usage per completed question is 10,000 aggregate input tokens and 2,000 aggregate output tokens across rewriting, structural construction, and answering. At those assumptions, 100 questions cost $0.086 at the lowest listed rates, and 1,000 cost $0.86; DeepInfra gives $0.138 and $1.38. These are arithmetic examples, not measured project usage. Reasoning, retries, corrections, long evidence, and ingestion increase consumption. Credit purchases have a listed 5.5% platform fee. [OpenRouter pricing](https://openrouter.ai/pricing).

Use a dedicated public-demo API key with a monthly USD limit, cap question length and concurrent work, and throttle anonymous visitors. Provider rate-limit retries are already implemented, but they are not an application spending ceiling. OpenRouter supports key spending limits and daily/weekly/monthly resets. If using BYOK, check `include_byok_in_limit` and the upstream account's separate billing controls. [Key limits](https://openrouter.ai/docs/api/api-reference/api-keys/update-keys), [Existing request behavior](/Users/akaisenghor/Projects/california-political-knowledge-map/main/docs/model-deployments.md).

Keep existing Logfire instrumentation on its Personal plan, which currently includes 10 million telemetry records/month with a $0 cap and 30-day retention. [Logfire pricing](https://pydantic.dev/pricing).

## Work required before sharing the link

1. Measure web, embedding, and Neo4j memory at idle and during simultaneous sample questions. Record completion latency and aggregate token cost. Use these measurements to choose between 4 and 8 GB or size managed services.
2. Package Python 3.13 with `uv` and the existing lockfile. Add deployment configuration and an app factory. Preserve telemetry setup currently called by the CLI and configure `LOGFIRE_TOKEN` or the deliberate untraced opt-out. The CLI hardcodes loopback; a container deployment needs the platform's port and network binding. [CLI startup](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/cli/main.py:435).
3. Pass the chosen hostname to the stock Pydantic AI UI's `allowed_hosts`. The current app calls `to_web()` without public host configuration. Run one application worker initially because Chat Sessions live in a process-local dictionary. Bound and expire abandoned sessions and terminal conversation IDs. Restarts currently lose active approvals; explain that behavior to visitors. [Web app](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/web.py:109).
4. Select OpenRouter independently for chat and rewriting. Deploy the existing CPU embedding runtime and artifact on the private network, adapting its macOS paths, loopback binding, and GPU options for Linux/container use.
5. Transfer a consistent graph dump with its indexes, verify retrieval and citation hydration, and use a read-only database identity for the public app where the chosen edition supports it. Keep ingestion credentials and SQLite on the local ingestion machine.
6. Add provider-key spending limits, public request throttling, short public request/model timeouts, question size limits, and concurrency caps. Configure secrets outside the repository. Keep Neo4j Bolt/browser and model ports closed to the internet.
7. Configure HTTPS, health checks, process restarts, OS/security updates, and monitoring. Use an existing portfolio subdomain if available. Display corpus dates and a few supported example questions.
8. Retain a consistent database export off the host and test restoration. Provider snapshots alone do not demonstrate recoverability. Neo4j Community documents offline dump/load backup; plan the short maintenance window. Hetzner server backups exclude attached volumes. [Neo4j offline backups](https://neo4j.com/docs/operations-manual/current/backup-restore/offline-backup/), [Hetzner backup scope](https://docs.hetzner.com/cloud/servers/backups-snapshots/overview/).

No cloud resources were created and no deployment code changed during this research. The remaining decision is whether the lower recurring VPS cost is worth owning host and database maintenance. For this project's current dependencies, it probably is, provided a suitable low-cost instance is actually available.
