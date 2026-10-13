# Cloud in a Bottle hosts a prepared portfolio corpus

The portfolio deployment uses Imbue's 8 GB Cloud in a Bottle space. We bundle
the Source Guides web app, Neo4j Community and CPU EmbeddingGemma in one
supervised container because Bottle's cross-app HTTP services do not supply the
private Bolt connection our retrieval path requires. This accepts a shared
failure boundary and brief maintenance downtime in exchange for a bounded host
cost and fewer platform-specific adapters.

The instance serves an exported graph and SQLite corpus. Scraping, the Story
Pipeline and evaluations stay on the existing machine; embeddings preserve the
stored vector space and OpenRouter funds chat inference through a separate
$5 monthly key limit. Jev remains the structural retrieval backend under ADR
0023 and needs its own external-service credential and billing checks.

Local Source Guides remain a personal store. Public mode scopes saved guides
and search controls to an anonymous browser identity, and never exposes existing
unowned local guides. Bottle owner authentication remains enabled until the
public service, persistence and recovery have been verified. Off-server backups
use consistent database artifacts; live file copying alone does not establish
database recovery.
