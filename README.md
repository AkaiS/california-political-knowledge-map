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

Start the local browser chat shell with:

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

This currently launches the chat shell. Question preparation and retrieval are
not connected yet.

## Model deployments

Operational guidance for choosing local llama.cpp or OpenRouter chat, configuring
providers and BYOK, and reading Evaluation Run provenance is in
[`docs/model-deployments.md`](docs/model-deployments.md).
