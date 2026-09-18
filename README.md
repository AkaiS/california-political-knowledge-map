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

## Model deployments

Operational guidance for choosing local llama.cpp or OpenRouter chat, configuring
providers and BYOK, and reading Evaluation Run provenance is in
[`docs/model-deployments.md`](docs/model-deployments.md).
