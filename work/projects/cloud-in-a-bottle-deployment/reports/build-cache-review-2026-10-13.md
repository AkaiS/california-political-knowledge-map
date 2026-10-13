# Bottle reload and image reuse

Checked the installed platform source at `6ea27634d1cbfc1b29caec29b53b76d919201b97`, available locally in `/private/tmp/ca-map-bottle-source`. This was a read-only source review; no host calls, settings changes, credentials, paid inference, or application mutations occurred.

## Supported operation

Both plain `bottle app reload` and `reload --update` rebuild and restart. The difference is whether the server first fetches the configured Git ref. The CLI and official operation docs describe this explicitly. `ReloadAppRequest` has only `update` and `approve_new_permissions`; the route always starts `reload_app_background`, which synchronizes manifest-derived routing/settings and calls `start_app_process`, then `build_image`.

Sources: [CLI](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space_cli/src/compute_space_cli/main.py#L173), [operation docs](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/docs/src/operation/cli.md#L50), [request and reload route](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/web/routes/api/apps.py#L178), [reload implementation](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/core/apps.py#L967).

No supported owner endpoint or CLI option was found to restart one app without building, or apply only its manifest routing changes. `restart_app_process` does reuse `openhost-APP:latest`, but is an internal helper for startup/archive recovery. It reads the persisted `manifest_raw`, so it would not by itself activate the new public manifest. Triggering router/global/archive recovery or calling internal helpers would introduce broader effects or bypass the supported deployment flow; neither is recommended.

Sources: [image-reuse helper](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/core/apps.py#L753), [startup recovery](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/core/startup.py#L156).

## Build and cache behavior

The exact builder command is `podman build -t openhost-APP:latest -f DOCKERFILE --memory=2048m --memory-swap=2048m REPO` for this app. Bottle supplies neither `--no-cache`, `--layers`, cache export/import flags, nor a skip-build option. The packaging worker independently checked the installed Podman help, where `--layers` defaults to true. Engine defaults and surviving local cache determine whether individual steps run again.

Source: [builder](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/core/containers.py#L206).

The platform also has periodic dangling-image pruning, and an explicit owner cache-drop endpoint that uses `podman image prune --all --force`. Those mechanisms exist in source; this review does **not** establish that either caused the current cache miss. Do not invoke pruning or change global settings to speed up this rollout.

Sources: [periodic pruning](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/core/image_pruner.py#L117), [cache-drop implementation](https://github.com/cloud-in-a-bottle/cloud-in-a-bottle/blob/6ea27634d1cbfc1b29caec29b53b76d919201b97/compute_space/src/compute_space/core/containers.py#L560).

`git diff --name-status a74ca13ffd6a6a6ddfd23568e8e9f26934d57286 c3c3f01ed569f5336d8f8a0188cefec7cbed1c3a` lists only `cloudinabottle.toml` and `tests/test_cloud_runtime.py`. Both are excluded from the app's source-allowlisted `.dockerignore`; the Dockerfile and all copied build inputs are unchanged. In particular, the llama.cpp compilation stage precedes every application `COPY`. Cache reuse is therefore plausible for publication if the engine retains matching layers, but cannot be promised given the observed recompilation during the current plain reload.

Application sources: [Dockerfile](https://github.com/AkaiS/california-political-knowledge-map/blob/c3c3f01ed569f5336d8f8a0188cefec7cbed1c3a/Dockerfile), [.dockerignore](https://github.com/AkaiS/california-political-knowledge-map/blob/c3c3f01ed569f5336d8f8a0188cefec7cbed1c3a/.dockerignore).

## Recommendation

Let the active controlled reload finish. Verify its paid Gemma configuration, readiness, and persisted data. For the public commit, use the existing supported sequence: set the app's remote to the full `@c3c3f01ed569f5336d8f8a0188cefec7cbed1c3a` Git URL, perform the already verified graceful maintenance sequence, then `bottle app reload california-knowledge-map --update --wait --instance akaisenghor.bottle.cloud`. This correctly synchronizes `public_paths` through the platform and preserves app identity/data. Expect a build invocation and budget time for recompilation until actual cache-hit evidence says otherwise. No narrower supported optimization was identified in this installed version.
