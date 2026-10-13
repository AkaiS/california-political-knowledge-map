# Cloud in a Bottle for the portfolio deployment

Researched October 12, 2026. This is a documentation and source review, not a deployment or performance test.

Cloud in a Bottle is a credible option for our public portfolio app. I would shortlist Imbue's $20/month 8 GB instance for a first deployment, provided chat inference runs through an external provider. Its advantage is the server plus deployment dashboard, routing, and HTTPS setup at a modest price. Our Neo4j and embedding services need deliberate packaging, and backups remain our responsibility.

## Hosted prices

| Imbue plan | RAM | vCPU | Disk | Advertised monthly price |
| --- | --- | --- | --- | --- |
| Small | 2 GB | 2 | 40 GB | $5 |
| Medium | 4 GB | 3 | 80 GB | $10 |
| Large | 8 GB | 4 | 160 GB | $20 |

Imbue advertises a $10 starter credit and charges only while the space runs. It provisions a dedicated server, configures DNS, and installs the platform. SSH access uses the owner's key. These are hosting prices, not an estimate including model requests or backup storage. The public page does not specify bandwidth quotas, server regions, resizing terms, or an uptime SLA. Those points remain unconfirmed. [Hosted plans](https://cloudinabottle.imbue.com/).

The same open-source platform can run on a separately rented VPS, so Imbue hosting is optional. The project is in active development. [Project site](https://cloudinabottle.org/).

## Public access and deployment

The platform builds a repository's Dockerfile using rootless Podman, with a `cloudinabottle.toml` manifest. Existing applications can use their own container and do not need the example Python template. The application must listen on `0.0.0.0` at the manifest's port. [App creation guide](https://cloudinabottle.org/docs/creating_an_app/overview.html).

Apps require the instance owner's authentication by default. The manifest's `routing.public_paths` publishes selected route prefixes to unauthenticated visitors. This supports a portfolio demo. We would explicitly publish the demo's pages, APIs, and assets while deciding how to protect administrative actions. [Manifest specification](https://cloudinabottle.org/docs/creating_an_app/manifest_spec.html).

HTTPS and app subdomains belong to the platform's routing layer; HTTP and WebSocket requests reach the application through its router. [Platform overview](https://cloudinabottle.org/docs/how_it_works/overview.html).

## Fit with this repository

The current app creates a persistent `SQLiteGuideStore` for Source Guides and connects to Neo4j plus an HTTP embedding service. [Web app](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/web.py), [startup](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/chat_startup.py). Its SQLite path defaults to `SQLITE_DB_PATH` or the configured ingestion database path; deployment should place it under the persistent app directory. [Source Guide store](/Users/akaisenghor/Projects/california-political-knowledge-map/main/src/knowledge_map/adapters/source_guides.py). We also need persistent graph and model files, a Linux embedding-server launch procedure, and funded chat inference. This project has not yet been tested inside a Bottle container.

The manifest provides persistent app directories through `BOTTLE_APP_DATA_DIR` and can provision SQLite files. Container memory defaults to 128 MB and CPU allocation to 0.1 cores, so our manifest must explicitly allocate more. [Manifest specification](https://cloudinabottle.org/docs/creating_an_app/manifest_spec.html).

The documented model is one container per app, with cross-app services through an HTTP/WebSocket router. That is not a drop-in private network for Neo4j's Bolt connection. [Platform overview](https://cloudinabottle.org/docs/how_it_works/overview.html), [cross-app services](https://cloudinabottle.org/docs/creating_an_app/cross_app_services.html). A combined container running the Python app, Neo4j, and embedding server is one possible approach, but its startup, recovery, and updates need testing. Separately managed host services are another possibility because we retain SSH access. These are implementation assessments, not verified recipes. The manifest's additional port mappings bind publicly on `0.0.0.0`; we should not use them to expose Neo4j merely to connect services. [Manifest specification](https://cloudinabottle.org/docs/creating_an_app/manifest_spec.html).

## Backups and recommendation

The bundled restic app requires configuration and separate storage. It reads live files without creating database-consistent dumps. It also excludes the router's state and archive tier. We need consistent Neo4j and SQLite backups plus recovery instructions; installing the backup app alone does not establish recoverability. [Backup guide](https://cloudinabottle.org/docs/operation/backups.html).

I would start by measuring our app, graph, and embedding memory together. The 4 GB plan is a cost-saving candidate if that measurement leaves room for concurrent requests and image builds. The 8 GB plan is the more conservative first trial. Neither size is a measured requirement. Keep bulk ingestion offline and use externally hosted chat inference. The advertised plans do not establish GPU availability, and the roadmap still lists GPU inference support as future work. [Roadmap](https://cloudinabottle.org/docs/roadmap.html).

Cloud in a Bottle reduces deployment work, but this remains a server we must operate. For our portfolio goal, that tradeoff looks reasonable at $20/month plus inference and off-server backups.
