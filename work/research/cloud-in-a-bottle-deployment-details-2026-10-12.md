# Cloud in a Bottle deployment details

Checked 2026-10-12 against the official manual. This note supports the deployment plan; it does not record a tested deployment.

## Target and packaging

The selected Large space is $20/month with 8 GB RAM, 4 vCPU, and 160 GB disk. Imbue provisions the server, DNS, and Cloud in a Bottle dashboard, with SSH access on the owner's key. Inference and external backup storage require separate budgets. [Managed plans](https://cloudinabottle.imbue.com/).

Cloud in a Bottle builds a repository Dockerfile with rootless Podman and routes HTTP to its declared port. The app must listen on `0.0.0.0` internally. It forwards WebSockets as well as HTTP. [App guide](https://cloudinabottle.org/docs/creating_an_app/overview.html), [routing](https://cloudinabottle.org/docs/how_it_works/routing.html).

Combining the Python service, Neo4j, and llama.cpp embedding server in one container is a proposed adaptation, not an official tested template. It avoids exposing Bolt through a public extra host port. Cross-app services mediate HTTP requests through the router; they do not provide a private Bolt network. [Cross-app services](https://cloudinabottle.org/docs/creating_an_app/cross_app_services.html).

Use an existing supervisor to manage those processes, forward logs, and allow graceful shutdown, rather than inventing process supervision. Docker documents the supervisord pattern for multiple services but favors separate containers generally. Verify this tradeoff with a container smoke test, including database restart and signal handling. [Docker process-manager guide](https://docs.docker.com/engine/containers/multi-service_container/).

## Manifest and public access

The repository needs `cloudinabottle.toml` with Dockerfile, HTTP port, resource limits, persistent storage, and readiness path. `memory_mb` is a container maximum; `build_memory_mb` separately caps builds and defaults to the runtime limit. Allocate less than all 8 GB so the host, router, backups, and build have room. The exact limit remains a measurement decision. Put graph files, saved Source Guides, and reusable model files under `BOTTLE_APP_DATA_DIR`; use its injected path rather than hardcoding the app name. [Manifest](https://cloudinabottle.org/docs/creating_an_app/manifest_spec.html).

`public_paths` lists unauthenticated route prefixes. Making `/` public exposes every path under it; keep administration out of the visitor service or enforce owner access inside the app. Owner headers are trustworthy only behind the router: it strips client `X-OpenHost-*` values and sets the owner header itself. Normal HTTP ports are exposed on host loopback; extra port mappings bypass router access control. Do not add extra host ports for Neo4j or embeddings. [Security](https://cloudinabottle.org/docs/how_it_works/security.html), [routing](https://cloudinabottle.org/docs/how_it_works/routing.html).

## Credentials

Declare the built-in secrets service with explicit grants for each required secret key. A server-side bootstrap can call `POST $BOTTLE_ROUTER_URL/api/services/v2/call/secrets/get`, authenticate using injected `BOTTLE_APP_TOKEN`, and send a JSON `keys` array. Retrieve credentials at runtime, then initialize the existing environment-based application. Keep secret values out of Git, Docker layers, logs, browser responses, and command arguments. The response contract and bootstrap must be checked against the installed service before implementation. [Secret-service example and permission model](https://cloudinabottle.org/docs/creating_an_app/cross_app_services.html).

The deployment inventory must include OpenRouter, Neo4j, optional Logfire, and the Jev TypeSafe credential. TypeSafe is another external dependency with unverified service cost, so the plan must not present $20 hosting plus an inference allowance as the full confirmed bill. This project-specific requirement comes from the root agent's source inspection of `src/knowledge_map/adapters/jev.py`.

## Releases and recovery

Install the CLI through `uv tool install` using the official Git URL. `bottle instance login` obtains an owner-created token. Documented operations include `bottle app deploy <git-url> --wait`, `bottle app reload <app> --update --wait`, status, logs, stop, SSH, and instance rsync. Reload with `--update` pulls new code before rebuilding. Removal deletes data unless `--keep-data` is supplied. Private GitHub repositories require authorization once. [CLI guide](https://cloudinabottle.org/docs/operation/cli.html).

The manual does not establish a git-ref option, atomic release switch, or automatic rollback. Before launch, inspect the installed CLI/API and record the actual checkout commit. Implement and rehearse returning to the previous tested checkout without deleting data. Do not invent a deploy `--ref` flag or promise zero downtime. Preserve a consistent database snapshot before schema changes.

The bundled restic app needs explicit configuration and external storage. It copies live permanent and temporary files but does not stop databases or create consistent dumps. Archive storage and platform state are excluded. Create database-consistent recovery artifacts separately, then back them up. Keep backup credentials/configuration and reconstructible instance settings separately; restore files only after stopping affected services, and run a restore rehearsal. [Backup and restore](https://cloudinabottle.org/docs/operation/backups.html).
