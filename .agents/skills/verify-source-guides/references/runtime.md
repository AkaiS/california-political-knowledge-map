# Runtime prerequisites

Read `README.md`, `.env.example`, `docs/model-deployments.md`, and `docs/agents/secrets.md` for current configuration. The helper loads the root `.env` without printing its contents. Existing shell variables take precedence.

- `SQLITE_DB_PATH` defaults to `document_store.db`. An existing store is required for a production-data copy. Its original connection is read-only. The copy receives current SQLite migrations and starts without saved guides.
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE` identify the shared graph. Defaults are `bolt://localhost:7687`, `neo4j`, an empty password, and `neo4j`. Authentication and a CalMatters Source Article with Article Chunks are mandatory at startup.
- `CHAT_DEPLOYMENT=local` uses `LLAMA_CPP_BASE_URL`, default `http://localhost:8080`, and `LLAMA_CPP_MODEL`. Embeddings use `LLAMA_CPP_EMBEDDING_BASE_URL`, default `http://localhost:8081`, and `EMBEDDING_MODEL`. Startup probes the chat model listing. Embedding inference waits until retrieval.
- `CHAT_DEPLOYMENT=openrouter` uses `OPENROUTER_API_KEY` and the deployment settings in `docs/model-deployments.md`. It keeps local embeddings and skips the OpenRouter startup probe. Real requests can consume the configured provider allowance.
- Jev requires `TYPESAFE_API_KEY` or Keychain service `jev_api`, account `test_key`. A credential accepted by construction does not prove service availability. Retrieval reaches the external Jev service.
- Logfire resolves its token from the environment, Keychain, or root `.logfire/logfire_credentials.json`. The helper resolves this existing credential before changing working directory and passes it in the child environment. It retains the credential's project URL and never writes the token to evidence. Normal runs send production telemetry, including the authored question, public collection coverage, build/model settings, and applicable model observations.

For a first installation, the documented command `./scripts/setup-databases.sh` migrates SQLite and applies the versioned Neo4j schema, including index readiness. Run it only against databases you own and are authorized to modify. Verification of the shared populated graph does not run migrations or ingest seed articles. Stop with the missing prerequisite if coverage or indexes are absent.

Existing local model startup scripts are `scripts/llama-server.sh` and `scripts/llama-embed.sh`. Their weights and runtime prerequisites are documented in `docs/model-deployments.md`. Keep already-running services. The chat script currently invokes a global `python3` preflight, so use the repository's `uv` requirement when provisioning that prerequisite rather than copying the global invocation into verification instructions.

The primary startup command is `uv run ca-map chat`, which binds only `127.0.0.1:7932`; `--port 8132` isolates the verification app. There is no host override, application login, or separate HTTP health route. `/api/coverage` and `/api/guides` become usable after production startup finishes.

The repository documents `KNOWLEDGE_MAP_ALLOW_UNTRACED=1` for offline runs, but it does not disable telemetry when a credential is available. It is not a workaround for a host review rejecting external telemetry. Honor an approval rejection and report the blocked live steps.
