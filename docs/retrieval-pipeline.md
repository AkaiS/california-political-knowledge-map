# Retrieval pipeline and Chat Agent handoff

`core.retrieval.RetrievalCoordinator` connects an approved Query Rewrite to the
full-text, dense, and Jev Cypher branches, weighted fusion, and Evidence
Assembly. `core.chat.ChatSession` connects question preparation and approval to
that coordinator and one final Retrieval Answer from the same Chat Agent.

## Construction

Chat and chat evaluations obtain their dependencies through the same builder.
It owns the async Neo4j driver, the sync driver CyVer requires, the Jev client,
models, embedding client, and verified CalMatters Coverage Description.

```python
from knowledge_map.chat_startup import chat_dependencies, new_chat_session

async with chat_dependencies(chat_deployment=chat_deployment) as dependencies:
    session = new_chat_session(original_question, dependencies)
    proposal = await session.prepare()
    # Present proposal.approval when its status is awaiting_approval.
    # After the person approves:
    answer = await session.approve()
```

The builder creates `JevStructuralRetriever` as the sole Cypher backend. It
preserves sparse full-text and dense retrieval, existing fusion weights, and
Evidence Assembly. [Jev structural retrieval](structural-retrieval.md) describes
the selection, binding, validation, and provenance rules.

`session.reject(correction)` records the rejected proposal and feedback through
the existing QuestionPreparation boundary. Call `prepare()` again for a fresh
proposal. Declined questions and unavailable rewrites cannot be approved.
Approval is consumed before retrieval starts, so a second call cannot run the
search or answer again. The Chat Agent assesses only the proposed question and
coverage, even though the session retains the original question for conversation.

## Routing, bounds, and evidence

The coordinator starts its monotonic deadline when `run()` receives approval.
It prepares keywords synchronously, then starts both text branches together.
Production startup also starts Jev for every approved question, including a
non-relational reporting question. Every branch gets the same `RetrievalRequest`
and absolute deadline. Production uses 180 seconds; the coordinator constructor
default remains 60 seconds. Durations must be finite and positive. An injected
clock must use the event loop's monotonic coordinate system.

Branch failures are independent. Completed ranked candidates remain in the
execution record when another branch raises or times out. Each unfinished
branch becomes a `FailedBranch`. Caller cancellation cancels the running
branches and propagates. Jev makes bounded staged selection requests. Composition
and binding each allow two corrections after the initial attempt. There is no
fallback to another Cypher backend.

The [fusion configuration](retrieval-fusion.md) supplies the initial weights and
selection limits. Its defaults give structural retrieval weight 2 and each text
branch weight 1, nominate 50 candidates per branch, and retain at most 100 fused
candidates. Pass the same dense candidate limit to the dense retriever as shown
above. Full-text and structural results retain their completed matches before
fusion; their selection limits do not impose a new database-query limit.

Fusion and [Evidence Assembly](evidence-assembly.md) use the same deadline.
Assembly hydrates selected chunks, groups passages by Source Article, and
applies the configured context limits. If the deadline leaves no time to load
recovered candidates, the run
returns `EvidenceAssemblyFailure` with those candidates in its execution audit.
Assembly failure does not relabel a successful retrieval branch as failed.

`EvidenceStore` reads chunks through their actual Source Article links. It uses
the Source Article ID as the citation URL when the graph has no separate `url`
property. Neo4j failures become `EvidenceHydrationError`; absent or ambiguous
grounding raises `LookupError`. The loader does not retry.

## One answer and visible limits

The Chat Agent receives `render_evidence_context(package)` as its evidence
input. It never receives the package's full pre-selection execution audit as
model context. Semantic result rows enter context only when all their supporting
Article Chunks survived Evidence Assembly. The original question remains conversation context; the approved
rewrite controls retrieval and the answer. The agent has no retrieval tools.

The Chat Agent supplies brief guidance, relevance notes, and disagreements.
Code attaches the unchanged evidence package and validates referenced source
IDs. Code also prefixes all failure disclosures, placing structural failure
first. A successful empty structural branch adds "No matching graph connections
were found in the available graph." Deferred explanations repeat in the final
introduction. Text-branch failures remain visible after structural failure.
These messages do not depend on the model remembering to include them.

Assembly failure returns before the final model call. Its `failure_disclosures`
contain every failed branch and the assembly failure message. Consumers must
present these disclosures and must not quote unverified audit candidates.
There is no second retrieval, sufficiency loop, or separate answer agent.
The factory disables output correction retries for the Chat Agent. Invalid
guidance or a final model failure propagates without another search.

## Usage and testing

`retrieval_total_usage` logs model requests, input tokens, and output tokens
across structural construction and dense embedding. `chat_total_usage` includes
Query Rewriter attempts, rejected proposals, policy assessment, retrieval, and
the final response. Usage supplied before a failure or cancellation survives.
No run-wide token cutoff is introduced. Per-stage model corrections and
deployment settings retain their existing bounds.

`tests/test_retrieval.py`, `tests/test_chat.py`, and
`tests/test_evidence_store.py` cover the public seams with scripted models,
in-memory branches and fake Neo4j drivers. `tests/test_jev_execution.py` exercises
the shared startup builder through both chat HTTP approval and evaluation. The
Jev selector, Article attachment, and reporting-gate tests cover pruning, subtype
abstention, indexed wiring, fail-closed decisions, and concurrent request isolation.
