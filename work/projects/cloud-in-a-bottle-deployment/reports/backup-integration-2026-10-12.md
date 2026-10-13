# Project backup integration

Research date: 2026-10-12. Read-only inspection of the sole selected instance, `akaisenghor.bottle.cloud`, and its exact installed public source. No backup configuration, credentials, host files, schedules, or other app data changed.

Bottle reports platform revision `6ea27634d1cbfc1b29caec29b53b76d919201b97`. Its running `backup` app comes from `https://github.com/cloud-in-a-bottle/backup` at `ed5e03c7b6458d7bb051f2b937ed66008812c46c`. The manifest calls this version `0.2.0`; its Dockerfile pins restic `0.19.1` and image digest `sha256:136600b6ff6843d61d355f7f71f460a166429f35de6fd11b568fece3c9a4d510`. [Installed manifest](https://github.com/cloud-in-a-bottle/backup/blob/ed5e03c7b6458d7bb051f2b937ed66008812c46c/cloudinabottle.toml), [Dockerfile](https://github.com/cloud-in-a-bottle/backup/blob/ed5e03c7b6458d7bb051f2b937ed66008812c46c/Dockerfile)

## Installed API contract

The owner accesses `https://backup.akaisenghor.bottle.cloud`; use Bottle's injected authentication. Routes also exist under the app's injected base path. All contracts below come from the installed [app.py](https://github.com/cloud-in-a-bottle/backup/blob/ed5e03c7b6458d7bb051f2b937ed66008812c46c/app.py).

| Endpoint | Contract |
| --- | --- |
| `POST /api/config` | Partial update accepts `repo`, `repo_password`, `env` object, `interval_seconds`, `keep_last`, `keep_hourly`, `keep_daily`, `keep_weekly`, `keep_monthly`, `keep_yearly`, and optional `router_api_token`. Returns `{ok:true}`. Positive intervals clamp to at least 60 seconds; zero disables scheduling. Retention values clamp to nonnegative integers. |
| `GET /api/config`, `GET /` | Return/render credential values. Do not read these for routine metadata inspection. |
| `POST /api/repo/test` | Optional `repo`, `repo_password`, `env` overrides. Tests connectivity; does not prove backup or recovery. |
| `POST /api/backup` | Optional string `name` only. Starts a background capture. No directory selectors. |
| `GET /api/status` | Operation flags, last result/time, interval, repository URL/backend. Prefer projecting fields needed for status. |
| `GET /api/snapshots` | Snapshot metadata and `repo_ok`. |
| `POST /api/check` | Starts restic check; poll `GET /api/check/status`. |
| `POST /api/restore` | `snapshot` plus optional `root`, restricted to `app_data`, `app_temp_data`, or legacy `vm_data`. Restores in place; no arbitrary isolated destination. Full configuration recovery confirms caller ownership. Do not invoke for a recovery rehearsal against live apps. |

There are no configurable include/exclude roots, preparation hooks, or per-project retention policies. Captures always read all `/data/app_data` and `/data/app_temp_data`, excluding the backup app's own directories, recovery staging, and archive. They also capture private app definitions and API-key verifiers through a required approved Private definitions export grant. An optional owner token adds runtime grants/states. SQLite, Neo4j and other apps' live files are not coordinated. [Scope and permissions](https://github.com/cloud-in-a-bottle/backup/blob/ed5e03c7b6458d7bb051f2b937ed66008812c46c/README.md)

The user explicitly chose the bundled backup service. The project-only boundary previously recommended in this report was an implementation assumption, not a user requirement. Use the bundled service and treat the prepared corpus and closed SQLite recovery snapshots as this project's authoritative restore artifacts. Broader captured live files do not establish database consistency. Its retention groups all `bottle` and legacy `openhost` snapshots together, so use a repository dedicated to this Bottle instance.

## Configuration evidence

The follow-up trusted SSH inspection parsed configuration privately and printed only flags, names and counts. It found `repo_configured=false`, `password_configured=false`, `backend=unknown`, `remote=false`, `env_key_names=[]`, `interval_seconds=0`, and no configured owner router token. Backup history has zero rows, zero successful entries and zero recorded snapshot IDs. No provider or off-server storage is currently configured. The installed service supplies the backup software; this observation does not establish included storage.

The earlier 1–2 GB destination estimate covered only prepared project artifacts. Bundled capture also includes other apps and temporary build storage, so measure actual repository size before claiming it fits a provider's free allowance. `GET /api/repo/stats` reports deduplicated repository storage after configuration and capture.

## Minimum service integration

Use the installed service's restic executor, encryption, capture, operation lock, history and retention. A thin host systemd user timer can coordinate preparation and its existing API; no new backup service or application scheduler is needed.

1. Run the project's existing `deployment/backup_sqlite.py` inside `openhost-california-knowledge-map` using `uv run --no-sync --python 3.13.5`. Read `/data/app_data/california-knowledge-map/sqlite/document_store.db`; write a new immutable timestamp directory under its `recovery/sqlite/`. The helper closes the consistent SQLite backup and records integrity and checksum without deleting visitor guides or quota state.
2. Only after preparation succeeds, invoke `POST /api/backup` with a descriptive `name`, then poll `/api/status` and `/api/snapshots` until a successful completed capture is recorded. The service includes both `recovery/seed` and `recovery/sqlite/<timestamp>` because they reside in permanent app data. It also captures other apps and live files. Do not treat those live graph/SQLite copies as this project's recovery point. Missing Private app-definitions approval fails capture; approve the installed service's requested grant if needed.
3. Set the service's `keep_daily=7` and `keep_weekly=4`; rules overlap. Keep at least the latest two immutable corpus release directories in app recovery storage. The service has a single policy, so corpus release count is a file-retention decision rather than separate snapshot tags. Preserve local closed SQLite artifacts until verified upload, then use bounded local retention to avoid cumulative copies. [Restic retention](https://restic.readthedocs.io/en/stable/060_forget.html)
4. Use `OnCalendar=daily`, `Persistent=true`, serialization and a bounded timeout for the preparation/trigger/status sequence. Keep the bundled service's `interval_seconds=0` when the ordered timer owns triggering, so no unprepared automatic capture races that sequence. An independently staggered SQLite timer plus service interval is simpler but only guarantees the last completed SQLite snapshot, not a newly prepared snapshot for each capture. [Timer contract](https://github.com/systemd/systemd/blob/main/man/systemd.timer.xml), [linger](https://www.freedesktop.org/software/systemd/man/252/loginctl.html)

The trusted read-only SSH probe confirms host user `host`, `/usr/bin/systemctl`, `/usr/bin/flock`, `/usr/bin/crontab`, a running systemd user manager, and `Linger=yes`. Its only listed user timer is `launchpadlib-cache-clean.timer`; leave that timer untouched. No restic binary resolves on the noninteractive default path. The first SSH attempt failed host-key verification; retry used the already verified task known-hosts file with strict checking. No trust checks were disabled.

Podman is also outside the default path. The existing instance preflight establishes version `5.8.3`, rootless mode and the command prefix `cd /home/host/openhost` followed by `/home/host/.pixi/bin/pixi run -e dev podman`. Use that verified prefix rather than assuming a `.openhost/pixi/...` binary path. Restic is already inside `openhost-backup`; no host restic installation is required.

## Restore and remaining human steps

Once the owner configures `repo`, `repo_password` and backend `env` through the existing backup service, save an external copy of the repository password and confirm provider costs/caps. Use an existing remote destination if available; no additional provider is required merely because B2 was researched. A local repository does not satisfy off-server recovery.

After a successful capture, run the service's existing restic CLI against its saved repository and credentials, loaded privately into subprocess environment. Use `restic restore <snapshot> --target <isolated-temporary-directory>` with include filters restricted to this app's `recovery/seed` and selected `recovery/sqlite/<timestamp>`. Avoid emitting environment or repository password values. Never call `/api/restore` for this rehearsal: it overwrites live data roots. Verify restored artifact checksums, SQLite integrity and guide ownership/quota, then rehearse application readiness against those restored artifacts. Public launch requires this actual off-server restore result.
