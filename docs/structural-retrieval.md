# Typed structural retrieval

Ticket 05 test seams, recorded before implementation under the user's blanket
approval:

- `Neo4jStructuralRetriever.retrieve(request: RetrievalRequest, *, deadline:
  float) -> SuccessfulBranch | FailedBranch` receives only the approved Query
  Rewrite. Tests inject scripted Pydantic AI models and an external Neo4j driver,
  then observe ranked candidates, graph claims, Grounding Evidence, identity
  ambiguity, and structured failure logs. Controlled-graph tests execute the
  compiled query in the disposable Neo4j fixture.
- `get_structural_agents(*, schema_model, selection_model, wiring_model,
  binding_model) -> StructuralAgents` creates the four model stages through the
  shared observable agent factory. Tests inspect typed requests and responses
  through the injected models.

`BranchCandidate.grounding` carries optional hydrated Article Chunk text and a
Source Article citation. Existing branch producers may leave it absent. This
text is transformed ingestion text, not a verified quotation; original Story
verification remains the Evidence Assembler's responsibility.

The implementation follows the atomic semantic constructor preserved at
`511eaeee`. Models filter the semantic schema, select compiler-owned pieces,
wire numeric occurrences, and bind positional values. Code owns graph labels,
identifiers, variables, parameters, projections, and provenance paths.

Ticket 05 supports one entity or one semantic relationship, with one attempt per
construction stage. Ticket 06 extends those same stages to bounded multi-hop
questions and corrections. No new ADR is introduced.

## Calling the branch

Pass four configured Pydantic AI `Model` instances to `get_structural_agents`.
They may share the same Model Deployment. The Query Rewriter remains separately
configured. Inject the resulting `StructuralAgents` and a Neo4j `AsyncDriver`
into `Neo4jStructuralRetriever(driver, agents=agents, database="neo4j")`.
The caller owns the driver and supplies an absolute event-loop deadline to
`retrieve`. The deadline covers all model stages, query execution, and hydration;
the remaining time also limits the Neo4j transaction.

Each stage uses a closed Pydantic output and the shared observable agent factory.
There are no model-callable database tools. The schema filter narrows the News
Ontology, the selector chooses supplied catalog IDs, the wiring stage connects
numeric occurrences, and the binder returns values in wired-filter order.
Binding an internal ID treats it as a literal value supplied by the question,
never as a Cypher identifier.

The compiler supports exact name, internal-ID, title, and Bill-session filters.
Publication dates use inclusive lower and exclusive upper calendar-date bounds,
matching the selected prototype. Bill names pass through
`parse_bill_designation` before the database reads them; an unparseable Bill name
is a validation failure. Name lookup does not perform fuzzy Entity Resolution.
Queries preserve every matching physical node through its Neo4j element ID,
including nodes that share the same internal ID. No uniqueness constraint or
entity merge is introduced.

## Evidence and outcomes

Chunk-level claims follow their `chunks` provenance and require both claim
endpoints to mention the same Article Chunk. `ABOUT_TOPIC` follows its `articles`
provenance. `DISCUSSES_TOPIC` follows the source `NewsArticle` to its chunks, as
required by ADR 0020. A Policy Area entity lookup also follows article-level
topic connections. A Source Article lookup follows its own chunks.

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
`wiring`, `binding`, `validation`, `cypher_execution`, `hydration`, or `deadline`,
plus failure kind, consumed attempts, and deadline exhaustion. These details stay
in logs; callers receive the shared `FailedBranch`. Each initial attempt counts
as one, while a deadline exhausted before execution counts as zero.
`retrieval_model_usage` records requests and input/output tokens across the four
stages, including completed usage before failure.

## Verification

`tests/test_structural_retrieval.py` injects scripted models and external driver
faults through the recorded seams. It covers every initial model stage, compiler
validation, database and hydration failures, deadlines, question isolation,
usage accounting, and exact retention of stored wording.

`tests/integration/test_structural_neo4j.py` executes compiled queries against the
repository's disposable Neo4j fixture. Enable it with
`RUN_NEO4J_INTEGRATION=1 uv run --no-sync pytest -q tests/integration/test_structural_neo4j.py`.
These tests establish controlled behavior. They do not measure model selection
quality or recall on the political corpus.
