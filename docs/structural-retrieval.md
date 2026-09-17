# Typed structural retrieval

Ticket 06 reuses the two public seams below under the user's blanket approval.
`Neo4jStructuralRetriever.retrieve(request: RetrievalRequest, *, deadline:
float) -> SuccessfulBranch | FailedBranch` is the behavioral seam for bounded
multi-hop retrieval, per-stage correction bounds, explicit multi-Bill assignment,
and failure logs. `get_structural_agents(*, ontology_model, selection_model,
wiring_model, binding_model) -> StructuralAgents` supplies scripted models whose
typed requests and deterministic correction feedback can be inspected. Tests
execute compiled queries against a disposable Neo4j graph; they do not assert
Cypher text or call private compiler functions.

Ticket 05 test seams, recorded before implementation under the user's blanket
approval:

- `Neo4jStructuralRetriever.retrieve(request: RetrievalRequest, *, deadline:
  float) -> SuccessfulBranch | FailedBranch` receives only the approved Query
  Rewrite. Tests inject scripted Pydantic AI models and an external Neo4j driver,
  then observe ranked candidates, graph claims, Grounding Evidence, identity
  ambiguity, and structured failure logs. Controlled-graph tests execute the
  compiled query in the disposable Neo4j fixture.
- `get_structural_agents(*, ontology_model, selection_model, wiring_model,
  binding_model) -> StructuralAgents` creates the four model stages through the
  shared observable agent factory. Tests inspect typed requests and responses
  through the injected models.

`BranchCandidate.grounding` carries optional hydrated Article Chunk text and a
Source Article citation. Existing branch producers may leave it absent. This
text is transformed ingestion text, not a verified quotation; original Story
verification remains the Evidence Assembler's responsibility.

The implementation follows the atomic semantic constructor preserved at
`511eaeee`. Models filter the News Ontology, select compiler-owned pieces,
wire numeric occurrences, and bind positional values. Code owns graph labels,
identifiers, variables, parameters, projections, and provenance paths.

The constructor supports one entity or a connected question containing at most
three semantic relationships and four role occurrences. Repeated labels and
relationship types retain separate occurrence indices. Every selected role must
belong to the connected question, and each selected relationship and filter is
wired exactly once. `distinct_roles` expresses an explicit request for other or
different entities by excluding equal internal IDs. No new ADR is introduced.

The supplied `RECORDED_VOTE` piece matches any of `VOTED_AYE`, `VOTED_NO`, or
`ABSTAINED`. It is one semantic hop, because a match traverses one of those
relationships. The ontology filter must retain all three alternatives before
the selector can use that piece. This lets a reported-vote question search every
recorded position without guessing the vote first.

## Calling the branch

Pass four configured Pydantic AI `Model` instances to `get_structural_agents`.
They may share the same Model Deployment. The Query Rewriter remains separately
configured. Inject the resulting `StructuralAgents` and a Neo4j `AsyncDriver`
into `Neo4jStructuralRetriever(driver, agents=agents, database="neo4j")`.
The caller owns the driver and supplies an absolute event-loop deadline to
`retrieve`. The deadline covers all model stages, query execution, and hydration;
the remaining time also limits the Neo4j transaction.

Each stage uses a closed Pydantic output and the shared observable agent factory.
There are no model-callable database tools. The ontology filter narrows the News
Ontology, the selector chooses supplied catalog IDs, the wiring stage connects
numeric occurrences, and the binder returns values in wired-filter order.
Binding an internal ID treats it as a literal value supplied by the question,
never as a Cypher identifier.

Pydantic AI output validators return deterministic failures through `ModelRetry`.
Each stage allows its initial response and at most two corrections, including
Pydantic output-shape failures. Correction history carries the exact preceding
failure. Correction attempts share the original deadline and contribute to
total model usage. Transport errors leave the stage immediately; the structural
adapter adds no transport retry loop.

The compiler supports exact name, internal-ID, title, and Bill-session filters.
Publication dates use inclusive lower and exclusive upper calendar-date bounds,
matching the selected prototype. Bill names pass through
`parse_bill_designation` before the database reads them; an unparseable Bill name
is a validation failure. Name lookup does not perform fuzzy Entity Resolution.
Queries preserve every matching physical node through its Neo4j element ID,
including nodes that share the same internal ID. No uniqueness constraint or
entity merge is introduced.

When multiple filters bind Bill names, the binder receives each slot's numeric
index, its role index, and the selected question wiring. It returns `null` for
those entries in `values` and an explicit `bill_names` assignment for every slot:

```json
{
  "values": [null, null],
  "bill_names": [
    {"slot_index": 1, "value": "Senate Bill 1947"},
    {"slot_index": 0, "value": "Assembly Bill 186"}
  ]
}
```

Assignment order does not matter. Missing or repeated slots fail validation.
Each value is parsed separately; repeated normalized Bill identities are
rejected unless explicit session filters distinguish them. A single Bill-name
slot continues to use the positional contract. There is no question-wide first
designation fallback.

## Evidence and outcomes

Chunk-level claims follow their `chunks` provenance and require both claim
endpoints to mention the same Article Chunk. `ABOUT_TOPIC` follows its `articles`
provenance. `DISCUSSES_TOPIC` follows the source `NewsArticle` to its chunks, as
required by ADR 0020. A Policy Area entity lookup also follows article-level
topic connections. A Source Article lookup follows its own chunks.

Multi-hop candidates carry every claim in their matched question, and hydration
collects the evidence behind each claim. Shared evidence produces one row per
matched question and Article Chunk. Fixed `MENTIONED_IN`, Source Article lookup,
and `HAS_CHUNK` paths do not count toward the three semantic relationships and
are never selected by the model as question relationships.

Candidates retain the Claim Key, review flag, claim provenance, endpoint element
IDs, stored chunk wording, and Source Article citation. The stored Source
Article ID supplies the URL when there is no separate URL property. Candidate
ranks follow chunk ID, Source Article ID, and entry element ID; there is no
invented structural similarity score. Ranking configuration and fusion belong
to ticket 07.

No matching semantic entity or relationship returns `SuccessfulBranch` with an
empty candidate tuple. A matched claim whose provenance cannot produce valid
Grounding Evidence fails hydration. The branch does not silently discard that
claim and call the traversal empty.

`retrieval_branch_failed` records identify `schema_filtering`, `typed_selection`,
`wiring`, `binding`, `validation`, `hop_bound`, `cypher_execution`, `hydration`, or `deadline`,
plus failure kind, consumed attempts, and deadline exhaustion. These details stay
in logs; callers receive the shared `FailedBranch`. Each initial attempt counts
as one, while a deadline exhausted before execution counts as zero. Exhausted
corrections record three attempts for the failing stage. A later database or
hydration failure does not inherit another stage's correction count.
`retrieval_model_usage` records requests and input/output tokens across the four
stages, including completed usage before failure.

## Verification

`tests/test_structural_retrieval.py` injects scripted models and external driver
faults through the recorded seams. It covers every initial model stage, compiler
validation, correction exhaustion, the hop ceiling, invalid wiring and Bill
assignments, database and hydration failures, deadlines, question isolation,
usage accounting, and exact retention of stored wording.

`tests/integration/test_structural_neo4j.py` executes compiled queries against the
repository's disposable Neo4j fixture. Enable it with
`RUN_NEO4J_INTEGRATION=1 uv run --no-sync pytest -q tests/integration/test_structural_neo4j.py`.
These tests establish controlled behavior. They do not measure model selection
quality or recall on the political corpus.

The controlled graph includes the verified construction families' two-hop
campaign, same-side lobbying, and reported-vote shapes, plus three-hop campaign
and Policy Area extensions. It exercises correction success on either permitted
correction and exhaustion at every model stage, successful empty three-hop
searches, and both chunk-level and article-level provenance beyond the semantic
hop budget. The preserved 25-case batch currently contains at most two semantic
hops; its original three-hop campaign extension is checked on controlled data.

The 25 verified construction cases remain development checks, not a held-out
Gold Set. Recheck their read-only reference queries with:

```sh
uv run --no-sync python work/initiatives/useful-graph-retrieval/query-construction/verify.py
```

This reference recheck establishes that the authored cases still retrieve their
evidence. It does not score the production models' question construction.
