# Full-text retrieval

`knowledge_map.adapters.full_text.Neo4jFullTextRetriever` accepts the approved
`RetrievalRequest` and returns `SuccessfulBranch` or `FailedBranch`. It does not
call a model. The caller supplies and closes an `AsyncDriver`, selects the
database if needed, and passes an absolute deadline from
`asyncio.get_running_loop().time()` to `retrieve`.

```python
retriever = Neo4jFullTextRetriever(driver, database="neo4j")
outcome = await retriever.retrieve(request, deadline=deadline)
```

Database setup is explicit:

```sh
./scripts/setup-databases.sh
```

The setup script applies `schema/neo4j/001_retrieval_indexes.cypher`. Retrieval
uses a read session and checks required full-text index names, labels,
properties, type, and online state. It does not create indexes during a search.
The schema installs this accepted inventory and waits for indexes to become
online:

| Index | Labels | Property |
| --- | --- | --- |
| `entity_name_fulltext_index` | Bill, Campaign, Committee, LegislativeEvent, Organization, PolicyArea, Politician, Prop | `name` |
| `article_title_fulltext_index` | NewsArticle | `title` |
| `chunk_text_fulltext_index` | Chunk | `text` |
| `<lowercase-label>_id_index` | Each of those eight entity labels, NewsArticle, Chunk | `id` |

The ten ID indexes are non-unique. Setup also creates the Article Chunk vector
index, preserves token indexes, and never merges duplicate entity IDs. Neo4j
2026.07.1 is the integration test version; the entity query uses
[scoped subqueries available since Neo4j 5.23](https://neo4j.com/docs/cypher-manual/5/subqueries/call-subquery/).

## Terms and routes

`extract_full_text_keywords` case-folds the approved question, extracts Unicode
words and numbers, removes a fixed list of function words, and deduplicates in
first-occurrence order. It retains measure numbers and session years. The query
quotes each resulting token and joins tokens with `OR`. User punctuation cannot
become Lucene query operators. No searchable terms is a preparation failure.

Entity-name matches reach chunks through `MENTIONED_IN`. Policy Area names
reach chunks through `NewsArticle-DISCUSSES_TOPIC` and `HAS_CHUNK`, following
ADR 0020. Article-title matches reach every chunk attached by `HAS_CHUNK`;
chunk-text matches resolve their owning Source Article through the same edge.
A matching name or title without a grounded chunk produces no candidate.

Each match-to-chunk contribution retains its route, matched field, entry node's
internal ID and Neo4j element ID, Source Article ID, Article Chunk ID, one-based
branch rank, and native full-text score. These discovery routes carry no
supporting graph claims. Evidence Assembly packages the hydrated stored chunk.

## Ordering and outcomes

Each index orders its contributions by descending native score, then chunk ID,
entry ID, and element ID to break ties. The branch interleaves those lists in
name, title, text order. It does not compare scores between indexes or promise
a particular full-text ranking algorithm. Neo4j owns its native scores and
matching behavior, as described in its
[full-text documentation](https://neo4j.com/docs/cypher-manual/25/indexes/semantic-indexes/full-text-indexes/).

Several contributions may name the same chunk. Keeping them preserves distinct
entry nodes, routes, scores, and pre-fusion ranks. Fusion must deduplicate by
chunk identity while retaining all contributions and count each retrieval
branch once, using that branch's best rank for the chunk.
[Fusion configuration](retrieval-fusion.md) supplies candidate nomination and
output limits; this adapter retains all completed matches before fusion and
context truncation.

A completed search without candidates returns `SuccessfulBranch(candidates=())`.
An unavailable or incompatible index fails the search, even if the question
would have matched nothing. A database failure in any of the three searches
fails the full-text branch. Other retrieval branches can still succeed.

The absolute deadline covers index checks, query execution, result consumption,
and candidate construction. Each database query also receives the remaining
time as its server transaction timeout. Ordinary caller cancellation propagates
to the caller. There is no adapter retry loop.

Structured `retrieval_branch_failed` records use `RetrievalFailureLog` fields and
include `deadline_exhausted`. Preparation failures consume zero attempts;
database work consumes one attempt. Stages distinguish preparation, index
availability, execution, and deadline exhaustion. Diagnostics are authored
messages, never raw driver errors, credentials, or question text. Answer-facing
`FailedBranch` values contain only branch identity and failed status.

## Verification

The offline tests exercise keyword preparation and failure outcomes at the
public retrieval boundary, with driver faults supplied at the database boundary:

```sh
uv run --no-sync pytest -q tests/test_full_text_retrieval.py
```

Integration tests start a fresh Docker container with the pinned Neo4j image,
bind only its Bolt port to localhost, and stop the container afterwards. They
never connect to configured production Neo4j credentials or mount host data.
Docker must be running. The image must be cached or downloadable.

```sh
RUN_NEO4J_INTEGRATION=1 uv run --no-sync pytest -q tests/integration/test_full_text_neo4j.py
```

Normal deterministic-suite runs skip those opt-in tests. They verify the index
inventory, all eight entity labels, title and text discovery, Policy Area
grounding, duplicate identity preservation, route and score retention, safe
query punctuation, successful emptiness, and actual missing-index failure.
