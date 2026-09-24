Project Overview: CA Political Knowledge Map — synchronous Story Pipeline that processes a SourceArticle through coreference resolution -> chunking -> embedding -> entity extraction -> persistence (`src/knowledge_map/core/pipeline.py:182`).
Dual store: SQLite document store (`document_store.db`, `src/knowledge_map/adapters/sqlite_db.py:15`) plus Neo4j graph.
Two chat Model Deployments: local llama.cpp-served GGUF and OpenRouter upstream model with local embeddings (see `docs/model-deployments.md`).

## Project planning

The local work tracker starts at [`work/README.md`](work/README.md). Product
direction lives in [`work/roadmap.md`](work/roadmap.md), while unshaped ideas,
defects, and questions are captured in [`work/inbox.md`](work/inbox.md).

## Setting up a Git worktree

After creating and entering a new worktree, run:

```bash
./scripts/setup-worktree.sh
```

The script finds the primary worktree automatically, copies local configuration
that should remain independent (`.env`, `.agents`, `.claude/settings.local.json`,
and Logfire credentials), symlinks the shared `document_store.db`, creates fresh
scratch directories, and runs `uv sync --frozen`. It never overwrites files
already present in the new worktree and deliberately excludes `.venv`, caches,
logs, dead-letter queue data, and Claude worktrees.

Use `--dry-run` to preview the setup, `--source PATH` to transfer local state
from a different worktree, or `--skip-sync` when dependencies are already set
up.

## Setting up the databases

After configuring `SQLITE_DB_PATH`, `NEO4J_URI`, `NEO4J_USERNAME`,
`NEO4J_PASSWORD`, and optionally `NEO4J_DATABASE` in `.env`, run:

```bash
./scripts/setup-databases.sh
```

The script initializes or migrates the SQLite document store, then applies the
versioned Cypher files under `schema/neo4j/`. The initial schema installs the
full-text, ID, and Article Chunk vector indexes and waits for them to become
online. Its `IF NOT EXISTS` statements make setup safe to rerun. Neo4j keeps
the installed indexes current as ingestion changes graph data, so runtime
adapters only validate or query them.

## Local chat

Start local retrieval chat with:

```bash
uv run ca-map chat
```

The command prints `http://127.0.0.1:7932`. Open that URL in your browser.
Use `uv run ca-map chat --port 8123` to choose another port. The server always
binds to `127.0.0.1`, stays in the foreground, and stops with Ctrl+C.

Pydantic AI serves its stock frontend from its default CDN build and caches the
HTML under `$XDG_CACHE_HOME/pydantic-ai/web-ui`, or
`~/.cache/pydantic-ai/web-ui` when `XDG_CACHE_HOME` is unset. The first visit may
require network access, and frontend assets can still require CDN access after
the HTML is cached. This is not an offline frontend bundle.

Enter one political question to receive a Query Rewrite Proposal. Deferred
questions include the coverage limit and the recoverable portion; Declined
questions and unavailable rewrites end without approval. Approving the proposal
runs retrieval once. Search details shows the search in progress, then expands
to show retrieval routes, branch ranks, graph claims, coverage, and branch
outcomes. The answer presents numbered Source Article links and verified
passages, with Deferred limits and branch failures kept visible. Candidate
wording and detailed failure diagnostics are excluded from Search details.

Reject a proposal to request a change, then describe that change in the chat
composer. The same Chat Session returns a revised proposal for approval. You
can repeat this correction loop; retrieval starts only after you approve a
proposal. Each browser conversation handles one political question. After an
answer, a Declined question, an unavailable rewrite, or an unrecoverable failure,
start a new chat for another question. Completed Chat Session objects are
released; only their conversation IDs remain in memory to prevent continuation.

Pending approvals and corrections exist only in application memory and remain
available until you continue or stop the server. Restarting the server discards
them. Browser-managed history stays readable, but continuing an old conversation
returns "Start a new chat to ask a question." It cannot restore a Chat Session.

Startup requires the existing SQLite document store at `SQLITE_DB_PATH`, which
defaults to `document_store.db`, and a reachable Neo4j configured with
`NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`. `NEO4J_DATABASE` defaults to
`neo4j`. Chat opens SQLite read-only and does not create a missing store.

Set `QUERY_REWRITER_MODEL` and the other `QUERY_REWRITER_*` settings for the
Query Rewriter. `CHAT_DEPLOYMENT` selects `local`, the default, or `openrouter`
for the Chat Agent and structural construction, using the existing deployment
environment settings. These choices are fixed at startup. The frontend has no
model or tool picker. Each required local model endpoint must answer its
model-listing request unless `SKIP_MODEL_REACHABILITY_CHECK` is set. Any HTTP
response counts as reachable; the check does not inspect response status,
generation quality, or which weights the server loaded. OpenRouter is not
probed, so its first real request reports provider reachability failures.

The authored CalMatters description lives in
`src/knowledge_map/resources/calmatters-coverage.json`. Startup refreshes its
article count and publication-date range from distinct CalMatters Source
Articles with Article Chunks in Neo4j. At least one is required. Unknown
publication dates remain unknown, and completeness has no assumed denominator.
Every version-one question uses this one collection, with no monthly coverage.
Embedding availability, structural generation, and retrieval index checks wait
until retrieval, where existing branch failures remain visible.

The application shares its agents, retrieval dependencies, and coverage across
in-memory Chat Sessions. Shutdown closes the Neo4j driver and the model and
embedding HTTP clients that this application owns.

The first valid question assigns an application audit ID and dispatches a
session-start observation to a separate SQLite database. `CHAT_AUDIT_DB_PATH`
selects its location, defaulting to `chat_audit.db`. The observation saves the
original question, startup code revision and dirty state, resolved Model
Deployments, prompt digests, fusion and context settings, and the startup
coverage counts with their observation time. The audit ID appears as
`chat_audit_id` on the Chat Session's Logfire spans.

Inspect a saved trail without starting chat, model clients, Neo4j, or Logfire:

```bash
uv run ca-map audit list
uv run ca-map audit list --since 2026-09-23T00:00:00Z --until 2026-09-24T00:00:00Z
uv run ca-map audit list --has-answer no --failed-stage dense_search
uv run ca-map audit list --code-revision COMMIT --model-deployment local:MODEL
uv run ca-map audit show AUDIT_ID
uv run ca-map audit show AUDIT_ID --db /path/to/chat_audit.db
uv run ca-map audit export AUDIT_ID > trail.json
```

All three commands print JSON to stdout and accept `--db`, which overrides
`CHAT_AUDIT_DB_PATH`. They open the existing database read-only, without creating
or migrating it. Missing, unreadable, or invalid databases produce an error on
stderr and exit with code 1. `show` and `export` also report an unknown audit ID
as an error.

`list` returns session IDs, `observed_at`, and `has_retrieval_answer`, ordered by
the earliest saved stage's start time. `observed_at` is the saved session-start
time, or `null` when that record is missing; the trail remains findable.
`--since` and `--until` compare known session-start times inclusively and require
an ISO 8601 timestamp with a timezone. Trails without a saved session start do
not match a time filter. `--has-answer yes` or `no` filters on the presence of a saved
Retrieval Answer record, including answers with zero passages. Absence does
not establish why an answer record is missing.

Filters combine with AND. `--code-revision` matches the exact saved commit.
`--model-deployment` takes `local:MODEL` or `openrouter:MODEL` to match kind and
model in any saved role, including the Query Rewriter and Chat Agent. To
distinguish deployments with the same kind and model, pass one complete saved
deployment JSON object from `show` or `export` as the argument. That matches
the full object, including endpoint, provider policy, and request settings.
A missing session-start record cannot match either settings filter. `--failed-stage`
matches an exact saved stage name whose result is `failed`, such as
`dense_search` or `evidence_assembly`.

`show` and `export` print the same saved stage records and any Retrieval Answer
snapshot, ordered by stage start time with stage ID breaking ties for display.
The times retain overlapping intervals; the output adds no sequence number or
session completion status. Redirect export to a separate file to retain the JSON.

The trail records session start, Query Rewrite Proposals, question-policy and
coverage assessments, correction feedback, and approval. Proposal records have
one-based attempt numbers; assessment, correction, and approval records identify
their proposal by stage ID. There is no separate rejection record. A later
proposal shows that the earlier proposal was replaced.
Model stages retain timing, token usage, and safe failure metadata. Retrieval
branches, structural construction, fusion, and Evidence Assembly also save stage
observations. [Evidence Assembly records](docs/evidence-assembly.md#chat-session-audit-trail)
include selected and omitted chunk IDs, omission reasons, context use, and relevant
coverage. The `chat_agent_guidance` stage saves validated guidance, timing, and
the model usage available for that call. Failed guidance saves a safe diagnostic
and failure kind.

Before emitting a Retrieval Answer's browser text, chat dispatches one
`retrieval_answer` record containing the exact rendered text and the selected
passages and Source Article citations. Passage snapshots retain their Article
Chunk IDs and `stored_chunk` provenance. They contain stored wording, which can
include coreference resolution, and do not claim verbatim Publication wording.
An answer with zero passages still gets a record. Evidence Assembly failure,
Declined questions, unavailable rewrites, abandoned approvals, and failed
guidance leave only the stages saved so far.

A missing record has no inferred outcome. Each insert runs in the background;
storage failures are logged and chat continues. The answer record does not
confirm that a browser received or read the answer. Committed records survive
restart, but an insert still in flight may be lost on process exit.
Records remain until the operator manages the database outside this command.

## Model deployments

Operational guidance for choosing local llama.cpp or OpenRouter chat, configuring
providers and BYOK, and reading Evaluation Run provenance is in
[`docs/model-deployments.md`](docs/model-deployments.md).
