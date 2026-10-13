---
name: verify-source-guides
description: Verify California Political Knowledge Map Source Guides through its real local HTTP service. Use for question assessment, saved guides, article reading, or search attempt changes. Browser journeys require the repository's explicit browser authorization.
---

# Verify Source Guides

Read `AGENTS.md` and [the feature index](features/README.md), then choose a mapped journey. The primary interface is the Source Guides web UI. Its public HTTP routes provide service verification when browser use is restricted. Administrative CLI commands and evaluation reviewers are separate interfaces outside this seed map.

## Files and portability

The verification controls are bundled in this project-local skill directory. `scripts/verify.py` contains the executable helper; `features/` contains the user journeys; `references/` contains prerequisites and verification notes. Copying this directory with the repository carries those files to another checkout.

Each run derives the repository root from the helper's location and creates fresh disposable state under that checkout's `.scratch/`. It needs no pre-existing temporary files. `uv sync --frozen` installs dependencies using uv's normal cache for the current host. Historical proof under `docs/verification/source-guides/` is optional reference material; the helper never loads prior manifests or follows their old state paths.

Another computer still needs the application's configured document store, populated Neo4j corpus, model services, and credentials described in [runtime prerequisites](references/runtime.md). Those are runtime prerequisites rather than files supplied by the verification skill.

## Launch

Run from the repository root. Use `uv` for Python and dependency commands.

```bash
uv sync --frozen
VERIFY_RUN=$(date -u +%Y%m%dT%H%M%SZ)-$$
VERIFY_PROOF="docs/verification/source-guides/$VERIFY_RUN"
mkdir -p "$VERIFY_PROOF"
uv build --out-dir .scratch/verification-build > "$VERIFY_PROOF/build.log" 2>&1
```

Build readiness requires both the wheel and source distribution to build successfully. The helper expects a new evidence directory, so use its `journey` child below.

```bash
CHAT_DEPLOYMENT=local .agents/skills/verify-source-guides/scripts/verify.py \
  --port 8132 --evidence-dir "$VERIFY_PROOF/journey"
```

The helper creates a fresh `.scratch/verify-source-guides-*` directory, backs up the configured SQLite document store through a read-only connection, clears saved guides and attempts in the copy, and applies `init_db` migrations to that copy. It retains real Story and Publication data for reading and highlights. The application creates its Source Guide tables during production startup. The fixture and its deletion exist only in the disposable copy.

It launches the real `uv run --frozen --no-sync --project <resolved repository root> ca-map chat --port 8132` command with `SQLITE_DB_PATH` pointing at the copy and the disposable directory as its working directory. This also isolates `.scratch/pipeline.log`. Readiness requires a live owned listener, the Source Guides shell, a nonempty `/api/coverage` response, and `/api/guides` with an empty saved list. Initialization must finish within 60 seconds.

The helper owns its app process group, port, and SQLite copy. Existing Neo4j, model services, and any app on port 7932 remain user-owned. Use another `--port` if 8132 is occupied. Never drive an existing app merely because it answers on a familiar port. Separate runs need distinct ports and evidence directories. Shared models can contend for inference capacity; the corpus can change if another process ingests during verification.

For environment, authentication, corpus, and first-install prerequisites, read [runtime prerequisites](references/runtime.md). A fresh SQLite directory alone cannot replace the required populated Neo4j corpus. This workflow proves an existing configured environment; it does not prove first-time graph or model provisioning.

## Doctor

The helper runs a read-only doctor before submission and again after restart. It checks the captured process group, listener PID and command, working directory, checkout revision and dirty status, SQLite tables, shell identity, coverage, and saved-guide listing. It writes `doctor.json` and `root.html` outside disposable state. The second doctor replaces the first snapshot with the current restarted instance; both process identities remain in `actions.json`.

Source Guides has no application login. Successful startup establishes acceptance of the configured Neo4j and Jev prerequisites. Model listing proves reachability only. Embedding inference, Jev service availability, retrieval indexes, and actual model weights require a retrieval journey.

On surprising behavior, stop the drive, inspect `doctor.json`, `server.log`, and `actions.json`, then repeat in a fresh run. The next drive starts with doctor again. A readiness failure is a blocker, not a passing health check.

## Drive

Required capabilities are subprocess control, local HTTP, filesystem access, and the host's `ps` and `lsof`. The shipped helper targets macOS and Linux. Other hosts need an equivalent listener/process ownership check before driving.

The default helper submits the complete text `Who supported that bill?` through `POST /api/questions`, requires HTTP 202, polls the guide until assessment finishes, and requires `needs_edit` with an explanation and `not_searched`. It then reopens the guide, checks the saved list and read-only SQLite rows, restarts its own app, and requires identical saved content and attempt identity. This proves the HTTP entry point for question assessment and saved-guide persistence.

Use the exact browser selectors and HTTP actions in the chosen feature file for other journeys. HTTP responses do not prove rendered controls, focus, reading order, new-tab navigation, or browser receipt. Browser verification requires explicit authorization under `AGENTS.md` and a documented browser-control capability. Capture screenshots and accessibility state when that path is authorized.

For additional drives, launch the same command with `--pause-after-doctor` in an owned PTY. It holds at the ready prompt. Execute mapped HTTP commands in another terminal and retain their requests and responses in that run's evidence directory. Press Enter in the owned PTY to run the default journey, restart check, and cleanup. Ctrl+C at the prompt triggers cleanup and records a failed run. The default run needs subprocess control only; this interactive mode also needs PTY input control.

The helper can also submit a different complete question with `--question` and an explicit `--expect`. Those modes run real models and may reach Jev or OpenRouter. Read the journey preconditions and existing external-service authorization before running them. Do not turn a failed retrieval into a pass by changing the expected result.

## Evidence

Proof lives under `docs/verification/source-guides/`, outside disposable state. Keep each run in a new directory. `manifest.json` records the exact launch, question, deployment, source store, entry point, and limitations. `actions.json` retains HTTP methods, paths, request bodies, responses, status codes, and process events. `submitted.json`, `terminal.json`, `saved-list.json`, `reopened.json`, and `persisted.json` capture the stages. `sqlite-proof.json` provides a second read-only view of the persisted question and attempt count. `server.log` and copied `pipeline.log` preserve execution output. `cleanup.json` records teardown, and `artifacts.json` inventories retained files.

Use production routes for actions. SQLite inspection is corroborating proof, not the user action. The helper uses no model mocks, test-only endpoints, or internal setters to produce a guide. There is no dry-run mode. SQLite changes stay in the copy; graph retrieval is read-only. Production Logfire telemetry and configured model/Jev requests remain real external effects. Keep their authorization explicit when host approval requires it. Credentials stay out of evidence.

## Cleanup

The helper's `finally` block stops only its captured app process group with SIGINT, waits for shutdown, and uses SIGTERM if shutdown exceeds 20 seconds. It copies its pipeline logs, removes its SQLite copy and disposable directory, and retains proof. Cleanup also runs after startup or assertion failure. Exit code zero and `cleanup.json` with `passed: true` are required for success.

If the helper is forcibly killed before cleanup, use the process group recorded in `actions.json` and the state directory in `manifest.json`. Confirm that the current process command and working directory still match before signaling it. Remove only that run's state after its process exits. Keep the user-owned app, Neo4j, and model services running.

Confirm the files in `artifacts.json` still exist after teardown. Build outputs in `.scratch/verification-build` and a cache created solely for the run may be removed separately after retaining `build.log`.

## Helpers and verification status

`scripts/verify.py` is executable. Use `scripts/verify.py --help` from this skill directory, or the repository-relative invocation above. It runs all five stages in one owned session and exits nonzero on a failed expectation. It intentionally refuses to reuse an evidence directory.

Generation on 2026-10-12 built the wheel and source distribution and passed the default live HTTP journey after the user authorized production Logfire telemetry. The actual local model returned `needs_edit` for `Who supported that bill?`; saved-list, reopening, read-only SQLite, and restart checks passed. Both owned launches exited zero, the verification port closed, and disposable state was removed. Proof remains at `docs/verification/source-guides/2026-10-12-proof/`. See [generation evidence](references/generation.md) for artifacts and limitations.

Browser behavior, broad-topic retrieval, article reading, independent questions, updates, retry, cancellation, and interruption remain unverified. The optional `--pause-after-doctor` and `--interrupt-after-submit` modes are documented controls whose live paths remain untested. The initial sandbox failure is retained separately at `docs/verification/source-guides/2026-10-12-generation/`.

Use `maintain-verification-skill` to audit this skill and its feature map after the routes or UI change.
