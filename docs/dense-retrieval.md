# Dense retrieval

`knowledge_map.adapters.dense.Neo4jDenseRetriever` embeds the approved
`RetrievalRequest.rewrite.question` and searches Article Chunk embeddings. Its
public request contains no original-question field. It returns the same
`SuccessfulBranch` or `FailedBranch` contracts as full-text retrieval.

```python
retriever = Neo4jDenseRetriever(driver, candidate_limit=50, database="neo4j")
outcome = await retriever.retrieve(request, deadline=deadline)
```

The caller supplies and closes an asynchronous Neo4j driver. `candidate_limit`
is a required positive integer. The example uses the initial
[`FusionConfig.dense_candidate_limit`](retrieval-fusion.md) of 50. `deadline` is
absolute time from
`asyncio.get_running_loop().time()`, shared with the other retrieval branches.
An injected Pydantic AI `Embedder` can replace the default client returned by
`get_embedding_embedder`. Retrieval awaits `embed_query` directly, so embedding
requests and transport retry waits remain cancellable within the deadline.

## Index and candidates

Retrieval uses the existing `chunk_vector_index` installed by
`scripts/setup-databases.sh` from the checked-in Neo4j schema. It checks that
the index is online, indexes the expected label and property, uses cosine
similarity, and has the configured `settings.embedding.dimension`. Searches
use a read session and do not create or alter indexes. The query embedding must
have that dimension, finite values, and a nonzero norm.

The configured limit is supplied to `db.index.vector.queryNodes`. Results reach
their Source Article through `NewsArticle-HAS_CHUNK-Chunk`. No extracted entity,
semantic relationship, or matching structural route is required. An ungrounded
chunk cannot form a candidate. Approximate search and provenance filtering can
return fewer candidates than requested; retrieval does not refill the list.

Candidates sort by descending native vector score, then chunk ID, Source
Article ID, and database element ID. Each retains a one-based branch rank,
native score, chunk and Source Article IDs, and a `chunk_embedding` route with
matched field `embedding`. The route identifies the Chunk's internal and
database element IDs and carries no graph claims. Scores remain local to the
dense branch. Fusion and evidence packaging belong to later project tickets.

## Outcomes and failure logs

A completed search with no grounded matches returns
`SuccessfulBranch(branch="dense", candidates=())`. A missing or incompatible
index returns a failure even when there are no chunks to retrieve.

Structured `retrieval_branch_failed` records carry the shared
`RetrievalFailureLog` fields plus `deadline_exhausted`:

| Stage | Failure kind | Meaning |
| --- | --- | --- |
| `preparation` | `transport` | The embedding provider could not finish the request |
| `preparation` | `validation` | The provider returned an unusable query embedding |
| `index` | `index_unavailable` | The vector index is missing, offline, or incompatible |
| `index` | `database` | Neo4j could not check the index |
| `execution` | `database` or `validation` | Vector search failed or returned invalid candidate data |
| `deadline` | `deadline_exhausted` | The shared deadline expired or Neo4j reported a transaction timeout |

Diagnostics are fixed messages and contain no raw driver errors, provider
responses, credentials, or question text. Answer-facing failures contain only
branch identity and status. `attempts_consumed` counts branch attempts: zero
when the deadline already expired, one after work starts. Transport retries
belong to the existing embedding client; the retriever adds no retry loop.

The deadline covers embedding, index checks, vector search, result consumption,
and candidate construction. Each Neo4j query also receives the remaining time
as its transaction timeout. Ordinary caller cancellation propagates.

## Verification

Offline tests inject provider and database faults at their external boundaries:

```sh
uv run --no-sync pytest -q tests/test_dense_retrieval.py
```

The integration tests use the existing disposable Neo4j container fixture and
apply the same checked-in schema as database setup. They use deterministic
embeddings, require no model service, and never connect to the configured
application graph:

```sh
RUN_NEO4J_INTEGRATION=1 uv run --no-sync pytest -q tests/integration/test_dense_neo4j.py
```

Neo4j 2026.07.1 is the pinned test version. The controlled vectors verify ranked
identities and native scores with a tolerance for index quantization. The empty
index test distinguishes successful emptiness from a missing index.
