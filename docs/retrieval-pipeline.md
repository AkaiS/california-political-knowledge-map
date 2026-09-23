# Retrieval pipeline and Chat Agent handoff

`core.retrieval.RetrievalCoordinator` connects an approved Query Rewrite to the
full-text, dense, and typed structural branches, weighted fusion, and Evidence
Assembly. `core.chat.ChatSession` connects question preparation and approval to
that coordinator and one final Retrieval Answer from the same Chat Agent.

## Construction

The caller supplies the asynchronous Neo4j driver, structural construction
agents, verified Coverage Description, and explicitly
relevant collection IDs. Relevant IDs may name a collection with no matches.
They must have entries in the supplied description. Coverage is authored input;
the coordinator does not infer new capabilities from retrieved records.

```python
from knowledge_map.adapters.dense import Neo4jDenseRetriever
from knowledge_map.adapters.evidence import EvidenceStore
from knowledge_map.adapters.full_text import Neo4jFullTextRetriever
from knowledge_map.adapters.structural import Neo4jStructuralRetriever
from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.core.question_preparation import get_query_rewriter
from knowledge_map.core.retrieval import RetrievalCoordinator
from knowledge_map.schemas.fusion import FusionConfig

config = FusionConfig()
store = EvidenceStore(driver)
retrieval = RetrievalCoordinator(
    full_text=Neo4jFullTextRetriever(driver),
    dense=Neo4jDenseRetriever(driver, candidate_limit=config.dense_candidate_limit),
    structural=Neo4jStructuralRetriever(driver, agents=structural_agents),
    load_grounding=store.load_grounding,
    fusion_config=config,
    deadline_seconds=60,
)
session = ChatSession(
    original_question,
    chat_agent=get_chat_agent(chat_deployment),
    rewriter=get_query_rewriter(rewriter_deployment),
    retrieval=retrieval,
    coverage=coverage,
    relevant_collection_ids=relevant_collection_ids,
)
proposal = await session.prepare()
# Present proposal.approval only when its status is awaiting_approval.
# After the person approves that proposal:
answer = await session.approve()
```

`session.reject(correction)` records the rejected proposal and feedback through
the existing QuestionPreparation boundary. Call `prepare()` again for a fresh
proposal. Declined questions and unavailable rewrites cannot be approved.
Approval is consumed before retrieval starts, so a second call cannot run the
search or answer again. The Chat Agent assesses only the proposed question and
coverage, even though the session retains the original question for conversation.

## Routing, bounds, and evidence

The coordinator starts its monotonic deadline when `run()` receives approval.
It prepares keywords synchronously, then starts both text branches together.
A relational rewrite adds typed structural retrieval to the same concurrent
group. Every branch gets the same `RetrievalRequest` and absolute deadline.
The default duration is 60 seconds and must be finite and positive. An injected
clock must use the event loop's monotonic coordinate system.

Branch failures are independent. Completed ranked candidates remain in the
execution record when another branch raises or times out. Each unfinished
branch becomes a `FailedBranch`. Caller cancellation cancels the running
branches and propagates. Structural construction retains its existing
three-semantic-relationship bound and two corrections per model stage.

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
model context. The original question remains conversation context; the approved
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
in-memory branches and fake Neo4j drivers. Existing
branch tests continue to cover compilation, hop bounds, and stage corrections.
No UI, live service, or retrieval-quality measurement is required for this
integration contract.
