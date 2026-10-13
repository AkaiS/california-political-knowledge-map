# Source Guides verification map

Read this index before driving the app. These four features cover the primary Source Guides web interface and its public service routes.

## Baseline preconditions

- Launch from `../SKILL.md` using a separate port and fresh disposable SQLite copy.
- Require doctor success and an empty saved-guide list before the initial submission.
- Use the populated, configured Neo4j corpus and actual local models. Authentication and dependency prerequisites are in `../references/runtime.md`.
- Browser actions require explicit authorization under `AGENTS.md`. HTTP verification remains available, but it covers only service behavior.

## Driving conventions

The browser recipes name accessible labels and stable IDs found in the packaged UI. Use a host's documented browser API to fill, click, select, and capture state after authorization. No project Playwright or Cypress runner exists.

For HTTP recipes, set `VERIFY_URL=http://127.0.0.1:8132` only after confirming that the process is owned by this run. `VERIFY_GUIDE` is the `guide_id` returned by the last successful submission, and `VERIFY_ATTEMPT` is its `latest_attempt.attempt_id`. Derive them from saved response bodies; they are not fixture IDs. POST requests require `Content-Type: application/json` and JSON bodies with no extra keys.

Capture the action and resulting response or rendered state in the run's proof directory. Read-only database checks supplement user-path proof. A failed or skipped entry point remains unverified even when another entry point passes. Polling for a terminal attempt does not establish successful retrieval; inspect its outcome and disclosures.

## Features

- [Submit and assess a question](question-assessment.md) covers submission, missing references, broad questions, editing, and new questions.
- [Read a guide](reading.md) covers article links, reading directions, views, highlights, coverage, and search details.
- [Reopen saved guides](saved-guides.md) covers the saved list, direct fragments, reload, restart, and independent questions.
- [Control a search attempt](attempts.md) covers update, retry, cancel, interruption, and retained reading.

## Seed-map limits

This map excludes administrative ingestion, Publication registration, Selector Healing, classifier review, CLI evaluations, evaluation-reviewer web interfaces, and Logfire exploration. The generated helper covers one HTTP question-assessment entry point plus persistence checks. Browser controls and the other journeys remain untested until their own proof is recorded.

On 2026-10-12, the default HTTP missing-reference journey and its saved-guide persistence checks passed on the production app with a disposable SQLite copy. Proof is indexed by `../references/generation.md`. All other listed entry points remain unverified.
