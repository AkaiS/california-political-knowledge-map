# Read-only Bottle instance preflight

The sole logged-in default instance is `akaisenghor.bottle.cloud`. Its existing
apps were left running. This preflight made no deployment, stop, grant, secret
write, source push or publication. It did not read credential values.

## Installed version and contracts

```sh
bottle version --instance akaisenghor.bottle.cloud
bottle curl --instance akaisenghor.bottle.cloud -- -fsS \
  https://akaisenghor.bottle.cloud/docs/ -o /private/tmp/ca-map-bottle-instance-docs.html
bottle curl --instance akaisenghor.bottle.cloud -- -fsS \
  https://akaisenghor.bottle.cloud/docs/all.md -o /private/tmp/ca-map-bottle-instance-manual.md
bottle curl --instance akaisenghor.bottle.cloud -- -fsS \
  https://akaisenghor.bottle.cloud/api/services/v2 -o /private/tmp/ca-map-bottle-instance-services.json
```

The version command returned `main @ 6ea27634`, full SHA
`6ea27634d1cbfc1b29caec29b53b76d919201b97`. The live manual and service
provider metadata agree with the source used for packaging. In particular,
the default running Secrets provider offers
`github.com/imbue-openhost/openhost/services/secrets`, version `0.1.0`,
endpoint `/_service_v2/`. The candidate's manifest service identity and
explicit grants match it. The live manifest reference supports separate
`memory_mb`, `build_memory_mb`, `cpu_cores`, `public_paths`, app persistence
and v2 consumes declarations.

`bottle curl` needs `--` before forwarded curl options. Passing `-o` as a
Bottle option is rejected. No raw token or local Bottle configuration was read.

## Host and runtime

Read-only SSH was issued through `bottle instance ssh`. Initial BatchMode SSH
failed host-key verification. A subsequent call used
`StrictHostKeyChecking=accept-new` and a task-specific temporary known-hosts
file at `/private/tmp/ca-map-bottle-instance-known-hosts`; the user's normal
SSH configuration was unchanged. The remote command prefix was:

```sh
bottle instance ssh --instance akaisenghor.bottle.cloud -- \
  -o BatchMode=yes -o ConnectTimeout=15 \
  -o UserKnownHostsFile=/private/tmp/ca-map-bottle-instance-known-hosts 'REMOTE_COMMAND'
```

Commands and results:

| Remote command | Result |
| --- | --- |
| `uname -m` | `x86_64` |
| `getconf _NPROCESSORS_ONLN` | `4` |
| `id` | `uid=1000(host) gid=1000(host)`, member of `sudo` |
| `cat /etc/os-release` | Ubuntu 24.04.5 LTS |
| `free -b` | RAM total 8,127,721,472 bytes, used 1,456,705,536, available 6,671,015,936 |
| `df -h /` | `/dev/sda1`, 150G total, 22G used, 123G available, 15% used |
| `command -v podman` and `command -v docker` | Neither is on the noninteractive SSH default path |

Bottle uses a pixi-managed runtime. Running its documented app-shell prefix
resolved the apparent missing-runtime issue:

```sh
cd /home/host/openhost
/home/host/.pixi/bin/pixi run -e dev podman info --format \
  'version={{.Version.Version}} rootless={{.Host.Security.Rootless}} arch={{.Host.Arch}} memory_bytes={{.Host.MemTotal}} mappings={{json .Host.IDMappings}}'
/home/host/.pixi/bin/pixi run -e dev podman ps --format '{{.Names}} {{.Status}}'
/home/host/.pixi/bin/pixi run -e dev podman inspect openhost-secrets \
  --format 'uid={{.Config.User}} mounts={{json .Mounts}}'
/home/host/.pixi/bin/pixi run -e dev podman inspect openhost-secrets \
  --format 'userns={{.HostConfig.UsernsMode}} binds={{json .HostConfig.Binds}}'
```

Podman reported version `5.8.3`, `rootless=true`, architecture `amd64` and
the same RAM total. UID/GID maps have container 0 mapped to host 1000 for
one ID, followed by container 1 mapped to host 100000 for 65,536 IDs.
The default user namespace and container user were empty strings, indicating
default settings. The inspected Secrets mount is read-write:

```text
/home/host/.openhost/local_compute_space/persistent_data/app_data/secrets
  -> /data/app_data/secrets
```

Its host directory is UID/GID `1000:1000`, mode `775`, on ext4-family storage.
Inspect reports `rprivate,rbind`; it does not independently expose an idmap
flag. The exact installed source's `containers.py` renders persistent mounts
with `:idmap`, and the live manual documents this mapping. Container UID 0
therefore fits the confirmed rootless host-account boundary. Writing the
candidate's own mount remains a private deployment test, not a conclusion
established by inspecting another app.

All six standard containers were running. A read-only
`podman stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.MemPerc}} {{.CPUPerc}}'`
returned these idle readings:

| Container | Memory usage | Limit |
| --- | --- | --- |
| oauth-provider | 51.71 MB | 268.4 MB |
| secrets | 73.24 MB | 268.4 MB |
| backup | 67.51 MB | 2.147 GB |
| filestash | 52.68 MB | 268.4 MB |
| bottle-community-chat | 147.2 MB | 2.147 GB |
| catalog | 5.353 MB | 1.074 GB |

These total about 398 MB of container usage, not their reserved memory.
Host available RAM was about 6.21 GiB. A six-GiB candidate at its ceiling
would leave only about 218 MiB beyond the current baseline. The earlier
1.47 to 1.52 GiB candidate idle reading is encouraging, but the proposed
six-GiB proposal was reduced to an initial five-GiB runtime ceiling after this
preflight. That leaves about 2.57 GiB outside the app, or about 1.21 GiB beyond
the observed baseline. Measure actual questions and backup
overlap before launch. The host has 16 GiB swap, currently unused; that does
not establish adequate latency or memory headroom. Free disk exceeds the
20% release/build gate.

The target is AMD64, while the current real image rehearsal was ARM64.
The source-built CPU runtime and pinned multiarchitecture dependencies need
an AMD64 build and actual target rehearsal before deployment acceptance.

## Secret setup metadata

```sh
bottle app status secrets --instance akaisenghor.bottle.cloud
```

This returned the public source
`https://github.com/cloud-in-a-bottle/secrets`, commit
`e49eac5a0ceb569e2eb19ccc499fb65343d371ce`, running. Public source checked
at that exact commit confirms the owner UI at
`https://secrets.akaisenghor.bottle.cloud/` and `Add Secret` with key, value
and optional description inputs. Existing rows use `Edit` then `Save`.
The live UI was not fetched because its template receives secret values.

The owner write endpoint is `POST /api/secrets` with JSON fields `key`,
`value`, and optional `description`. It upserts by key and returns HTTP
**201**, body `{ "ok": true }`. Missing key or missing `value` field returns
400. The HTTP status is confirmed by the installed commit's smoke test.
Writing an existing key replaces its value and description, so absence must
be established before an automated write. No POST was made by this preflight.

Automatic approval review rejected an attempted owner metadata GET because
it could expose values. The request did not execute. The authorized safer
alternative used `podman exec -i openhost-secrets uv run --no-sync --no-cache python -`
with SQLite opened read-only, selecting only key names:

```sql
SELECT key FROM secrets WHERE key IN (?, ?, ?, ?, ?, ?, ?, ?, ?) ORDER BY key
```

The bound names were only the nine requested deployment configuration keys.
The first check found `TYPESAFE_API_KEY` only. A later check, after the parent
chat's separately authorized write, found `NEO4J_PASSWORD` and
`TYPESAFE_API_KEY`. It did not read either value. Existing TypeSafe credentials
must be treated as existing account state; do not replace them silently.

After the parent added deployment configuration and the user reported provider
setup, a final name-only check found `CLOUD_PUBLIC_ORIGIN`, `NEO4J_PASSWORD`,
`OPENROUTER_MODEL`, `OPENROUTER_PROVIDERS` and `TYPESAFE_API_KEY` present.
`OPENROUTER_API_KEY`, `LOGFIRE_TOKEN` and `LOGFIRE_PROJECT_URL` were still
absent under those canonical names. This check preceded the user's clarification
of the actual stored names. A subsequent name-only query confirmed
`OPENROUTER_KEY`, `LOGFIRE_API_KEY` and `LOGFIRE_URL` already exist.
The cloud manifest now grants those exact names, and bootstrap maps them to
the canonical application environment without copying store values or creating
duplicate entries. Missing aliases still fail closed.
The optional `CLOUD_TRUSTED_PROXIES` entry was also absent, retaining the
conservative peer-IP default.

## Backup evidence

```sh
bottle app status backup --instance akaisenghor.bottle.cloud
```

The app is running public repository `https://github.com/cloud-in-a-bottle/backup`
at `ed5e03c7b6458d7bb051f2b937ed66008812c46c`. Its source shows `/api/config`
returns configuration, including credentials, while `/api/status` returns an
unmasked repository field and error text. Those endpoints were not fetched.

A read-only SQLite metadata query through the existing app's managed `uv`
environment found `backups.db` and `config.json` present, zero backup-history
rows and no successful snapshot timestamp. The query selected only counts,
timestamps and statuses, excluding error messages and values. An off-server
destination remains unverified. Running the bundled Backup app is not proof
of recoverable or consistent application backups.

## Bootstrap ordering and remaining gates

After the preflight, cloud transport startup was corrected to set the existing
environment-based 60-second timeout, two attempts and 15-second rate-limit cap
before the first cached settings import. The focused packaging tests passed
21 cases. Independent follow-up passed 98 cloud/public/model cases, verifying
the cached embedding client and chat settings, a 240-second question deadline,
and unchanged local defaults of 3,600 seconds, three attempts and 120 seconds.
The prior image/source hash in the isolated rehearsal report predates this
correction and is not the current candidate. A fresh AMD64 Bottle build and
target rehearsal remain required.
The subsequent three-key alias change passed 27 focused runtime/review/revision
tests and Ruff; its independent review uses fake credentials only.

The exact installed `make_data_dirs_and_env_vars` idempotently creates an
app-specific persistent directory before the background build and automatic
container start. It preserves pre-existing contents. There is no assumed
deploy-without-start flag. Prepare the immutable seed under the future app's
own `persistent_data/app_data/california-knowledge-map/recovery/seed` before
its first start, or expect the fail-closed bootstrap to exit until data and
required grants are available. No directory was created on the instance here.

The inspected runtime stop contract is still `podman stop -t 10`, followed by
forced removal. The recorded longer graceful-shutdown procedure remains a
release requirement. Owner-only routing and individual v2 grants match the
candidate; there are no reasons to publish paths before full verification.

Outstanding prerequisites are the finalized committed seed and code release,
AMD64/target image verification, the required human provider credentials and
spending limits, confirmed TypeSafe account permissions and billing, valid
deployment telemetry, tested proxy/HTTPS behavior, whole-question peak memory,
consistent off-server backups and a restoration/rollback rehearsal. No private
or public deployment was made by this preflight.
