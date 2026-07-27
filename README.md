Project Overview: CA Political Influence GraphRAG Engine
An enterprise-grade, event-driven data pipeline and AI agentic architecture that ingests unstructured local news, campaign finance data, and legislative records to map networks of political influence in California into a Neo4j graph database.

Core Technical Pillars
Event-Driven Asynchronous Ingestion Loop: A resilient, queue-based data pipeline that isolates raw data scraping from LLM processing to handle non-deterministic failure modes.

Multi-Agent Entity Resolution: Specialized orchestration loops using Pydantic v2 schemas to parse unstructured text, reconcile fuzzy political names/PACs against database constraints, and automatically self-heal generated Cypher query errors.

Production LLMOps: A robust engineering layer implementing exponential backoff (Tenacity), fallback multi-provider routing (Claude/OpenAI), token-optimized semantic context pruning, and automated regression evaluations via a CI/CD evals/ pipeline.

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
that should remain independent (`.env`, `.agents`, and Logfire credentials),
symlinks the shared `document_store.db`, creates fresh scratch directories, and
runs `uv sync --frozen`. It never overwrites files already present in the new
worktree and deliberately excludes `.venv`, caches, logs, and dead-letter queue
data.

Use `--dry-run` to preview the setup, `--source PATH` to transfer local state
from a different worktree, or `--skip-sync` when dependencies are already set
up.
