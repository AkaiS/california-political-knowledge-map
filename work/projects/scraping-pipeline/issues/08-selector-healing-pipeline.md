# 08. Selector Healing Pipeline (Generator/Critic, `selector_proposals`)

Labels: completed

## Parent

[Scraping Pipeline PRD](../PRD.md)

## What to build

Implement the Selector Healing Pipeline, filling the breaker-trip seam from issue 07. Create the `selector_proposals` SQLite table (statuses `PENDING_REVIEW`, `APPROVED`, `REJECTED`, `HEALING_FAILED`; schema in the PRD's "Selector Proposal Store SQLite Schema" section).

On breaker trip, run an asynchronous Generator/Critic Pydantic AI loop (capped at 3 iterations, following the existing coreference Generator/Critic pattern) against exactly one representative article — the one that tripped the breaker. Preprocess its raw HTML first per the PRD (strip head/scripts/styles/svg/nav/footer/iframe/img, large inline attributes, and base64 payloads while preserving classes and IDs). The Generator proposes Article Selectors from the cleaned HTML and JSON-LD targets; the Critic validates presence, cleanliness, and length ratio. An approved candidate is saved as a `PENDING_REVIEW` Selector Proposal; loop exhaustion saves a `HEALING_FAILED` row (retaining the last rejected selectors), logs a critical warning, and dispatches a console alert.

Concurrency guards: set `healing_in_progress` during the loop and clear it on completion; skip any trigger when an unresolved proposal (`PENDING_REVIEW` or `HEALING_FAILED`) exists or a run is in progress; reset all `healing_in_progress` flags on pipeline startup so a crash cannot leave a stale lock.

## Acceptance criteria

- [x] `selector_proposals` table is created on database initialization with the PRD schema
- [x] A breaker trip launches one healing run against the tripping article only, with HTML preprocessing applied before any LLM call
- [x] The Generator/Critic loop caps at 3 iterations, producing a `PENDING_REVIEW` proposal on Critic approval or a `HEALING_FAILED` row plus critical warning and console alert on exhaustion
- [x] Triggers are skipped while an unresolved proposal exists or `healing_in_progress` is set; the flag is always cleared at loop end
- [x] Startup resets all `healing_in_progress` flags to 0
- [x] Tests cover the loop with mocked LLM calls, preprocessing output, single-proposal enforcement, exhaustion handling, and the startup reset

## Blocked by

- [07-circuit-breaker.md](./07-circuit-breaker.md)
