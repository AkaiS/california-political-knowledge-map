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

The packaged Source Guides page accepts a complete question and starts assessment
and retrieval directly. Assessment preserves the submitted wording. Broad
meaningful questions proceed; an unresolved reference asks you to edit the
complete question. No Query Rewriter or approval step runs.

The result shows your complete question and linked Source Articles with brief
reading directions and available publication dates. Article links open in another
tab. The guide omits stored passages and candidates without a relevant reading
direction. Deferred coverage limits and partial retrieval failures remain visible.
Use Edit question to revise the complete wording, or New question to clear it.

This first slice runs within the submission request. It has no saved guide,
history, recovery after reload, or detached background execution.

Startup requires the existing SQLite document store at `SQLITE_DB_PATH`, which
defaults to `document_store.db`, and a reachable Neo4j configured with
`NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`. `NEO4J_DATABASE` defaults to
`neo4j`. Chat opens SQLite read-only and does not create a missing store.

`CHAT_DEPLOYMENT` selects `local`, the default, or `openrouter`
for the Chat Agent and Jev composer and binder, using the existing deployment
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
Embedding availability, Jev calls, and retrieval index checks wait
until retrieval, where existing branch failures remain visible.

The application shares its agents, retrieval dependencies, and coverage across
in-memory Chat Sessions. Shutdown closes both Neo4j drivers, the Jev client, and
the model and embedding HTTP clients that this application owns.

Every accepted question uses one retrieval pipeline. Sparse full-text and dense
retrieval run alongside the Jev Cypher branch, then graph-prioritized fusion and
Evidence Assembly select the stored passages. Jev narrows the schema and selects
roles, subtypes, and properties. The configured chat model composes and binds that
selection; the deterministic compiler and CyVer authorize read-only execution.
Reporting questions also reach Jev.
There is no alternate Cypher backend or fallback to the former LLM selector.

Jev startup requires `TYPESAFE_API_KEY`, or the existing Keychain entry with
service `jev_api` and account `test_key`. The pinned SDK and CyVer are normal
project dependencies; no experiment bootstrap or `--with` flags are needed.
The schema cutoff is `.8`, structural/property/reporting cutoffs are `.52`,
and subtype refinement requires `.8`. These experiment settings remain
uncalibrated. All branches share a 180-second retrieval deadline. A Jev failure
preserves completed sparse and dense evidence and discloses the failed branch.

Chat evaluations use this same dependency builder and Chat Session. For example:

```bash
uv run ca-map eval run chat --deployment local --case C-R1-01
```

The report records the Jev decisions, compiler-generated query, validated values,
semantic result rows, verified evidence, and model exchanges. The chat Data Set is
unlabeled, so this run measures execution and supports human review, without an
answer-quality score. Reports go under `evals/reports/chat/`.

Maintainers can inspect application decisions and related model traces through
the [Chat Session trail guide](docs/chat-session-trails.md). It includes Logfire
SQL for one question or a comparison across sessions, saved-search instructions,
and the limits of retention and observed answer presence.

## Model deployments

Operational guidance for choosing local llama.cpp or OpenRouter chat, configuring
providers and BYOK, and reading Evaluation Run provenance is in
[`docs/model-deployments.md`](docs/model-deployments.md).
