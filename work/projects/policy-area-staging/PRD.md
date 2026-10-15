# Policy Area Staging

Labels: completed

## Problem Statement

A Policy Area is a property of an article's discussion, not of a sentence. It is
the one thing in the News Ontology that an Article Chunk usually cannot see, and
Entity Extraction is asked for it per Article Chunk anyway.

It is also the only label whose emission writes an edge by itself: a Policy Area
returned by any chunk causes a topic edge from that Article Chunk. So the hub
node meant to make two articles on one subject meet is populated by the least
reliable judgement in the pipeline, once per chunk, where two chunks of one
Source Article can disagree without either being wrong.

Three pieces of evidence say this is not a prompt-wording problem.

**The annotation guideline could not state the rule.** The extraction Silver Set
was annotated one Article Chunk at a time. The first draft of the guideline asked
for the Policy Area the chunk is about and could not be applied consistently — a
bill regulating brain-data collection by employers is privacy or labour depending
on which sentence you are reading. The rule was narrowed to "only as the topic of
a Bill or Prop named in this same chunk, and only where the chunk says what the
measure concerns", and the excluded case was recorded as an open question. That
narrowing is an admission rather than a boundary: it says chunk-local topic
judgement is unreliable, so the Silver Set stopped asking for it.

**Topic is scarce at chunk scale by construction.** Ten of the ninety silver
nodes across fifty Article Chunks are Policy Areas. The other eighty are entities
a sentence names outright.

**The first Evaluation Run confirms the split.** `gemma4:26b` and the Silver Set
agree on zero Policy Areas out of ten. Part of that is a naming defect worth
fixing on its own — the model answers with the vocabulary id where the Silver Set
holds the canonical name, because the rendered ontology asks for "one of these
IDs and its corresponding canonical name" and that reads as a choice — but every
topic edge fails with it, and topic edges are ten of the twenty-four silver
claims.

Meanwhile the article-level half of the relationship is declared and unbuilt. The
News Ontology permits a topic edge from a Source Article as well as from an
Article Chunk. Nothing has ever produced the Source Article edge.

## Solution

Policy Area leaves the chunk stage entirely and gets two stages of its own, one
before Entity Extraction and one after.

**Policy Area Classification** runs once per Source Article over the resolved
text and returns the Policy Areas the article discusses, chosen from the closed
vocabulary. It writes the Source Article topic edge the ontology already declares
and nothing builds. Choosing from a fixed vocabulary is a bounded task rather
than an open judgement, and a far easier thing to annotate consistently.

**Entity Extraction** stops being asked. `PolicyArea` leaves the labels the
extraction model is responsible for, and the topic relationship leaves its
relationship list. The chunk prompt loses the twenty-seven-line vocabulary with
them.

**Topic Assignment** runs once per Source Article after extraction, given the
article, its Policy Areas, and every Bill and Prop extraction found. It emits the
topic edges from measures to areas. It is the only place that sees every measure
in the article and every area in the article at once, which is what the judgement
needs, and it cannot run earlier because extraction is what discovers the
measures. It has direct prior art: Bill Session Resolution and Legislative Event
dating are already article-level passes that run after chunk extraction and hand
their results to the write path.

Each stage is separately evaluable against its own Silver Set, as Coreference
Resolution, the Relevance Filter, and Entity Extraction already are.

## User Stories

1. As an AI engineer, I want Policy Areas decided once per Source Article, so that two Article Chunks of one article cannot disagree about what the article is about.
2. As an AI engineer, I want Policy Area Classification to choose from the closed vocabulary rather than extract freely, so that the task is a bounded choice instead of an open judgement.
3. As an AI engineer, I want the classification stage to own the vocabulary, so that an id and its canonical name stop being two answers a model can pick between.
4. As an AI engineer, I want classification to read the coreference-resolved text, so that it sees the same canonical names every later stage sees.
5. As a developer, I want the Source Article topic edge written, so that the declared article-level shape stops being one nothing produces.
6. As an AI engineer, I want `PolicyArea` removed from the labels extraction is responsible for, so that the chunk model is not asked for the one label a chunk usually cannot support.
7. As an AI engineer, I want the topic relationship removed from the chunk extractor's relationship list, so that a topic claim is never made from a chunk that does not state one.
8. As an AI engineer, I want a Policy Area emitted by the chunk extractor to be dropped by conformance and counted in the Adherence Report, so that a model still reaching for it is visible rather than silently obeyed.
9. As an AI engineer, I want the chunk extraction prompt to shrink by the Policy Area vocabulary, so that a chunk supporting one entity is not preceded by twenty-seven lines it cannot use.
10. As an AI engineer, I want Topic Assignment to receive every Bill and Prop the article produced alongside every Policy Area it discusses, so that the assignment is made with the context the judgement actually needs.
11. As an AI engineer, I want Topic Assignment to assert only what the article supports, so that an area the article never connects to a measure is a scored mistake rather than a recorded category.
12. As an AI engineer, I want Topic Assignment to name measures by the surface strings extraction produced, so that an assignment cannot invent a Bill the article never mentioned.
13. As a developer, I want an assignment naming a measure that extraction did not produce to be dropped, so that a hallucinated endpoint cannot mint a node behind the write path's back.
14. As a developer, I want an assignment naming an area outside the article's classified set to be dropped, so that the two stages cannot contradict each other in the graph.
15. As a system operator, I want a Source Article with no Policy Areas to complete normally, so that an article the vocabulary does not cover still reaches the graph with its entities.
16. As a system operator, I want a failure in either new stage to route the article the way a coreference or extraction failure does, so that the Dead Letter Queue and Article Status keep one vocabulary of failure.
17. As an AI engineer, I want both stages behind one adapter Protocol on the Story Pipeline, so that the pipeline gains one seam rather than two and one fake covers both in tests.
18. As an AI engineer, I want a Policy Area Silver Set of twenty article-level cases, so that classification is measured rather than assumed.
19. As an AI engineer, I want a Topic Assignment Silver Set of twenty article-level cases, so that assignment is measured rather than assumed.
20. As an AI engineer, I want both Silver Sets drawn from the twenty Stories already in the coreference Silver Set, so that all four stages are measured over one population.
21. As an AI engineer, I want classification scored as multi-label agreement over the vocabulary, so that a report distinguishes an article labelled with too much from one labelled with too little.
22. As an AI engineer, I want assignment scored on the measure-to-area pairs, so that an article whose areas are right but whose bills are mismatched cannot score as a pass.
23. As an AI engineer, I want the extraction Silver Set's Policy Area nodes and topic edges re-annotated under the new contract, so that the extraction report stops scoring a stage that no longer owns the question.
24. As a maintainer, I want the Policy Area open questions retired from the extraction annotation guideline, so that the guideline stops recording a question answered elsewhere.
25. As a maintainer, I want the number of Policy Areas per article recorded from the Silver Set rather than capped by a guess, so that any future limit is set from the distribution we measured.
26. As a maintainer, I want `GLOSSARY.md` to name both stages, so that the domain vocabulary describes the pipeline that exists.

## Implementation Decisions

### One adapter, two stages

Both stages sit behind a single new adapter Protocol on the Story Pipeline,
beside the Coreference and Entity Extraction Protocols it already declares. It
exposes classification over an article's resolved text, assignment over an
article plus its areas plus its extractions, and the health check the other
adapters carry. Two stages, one seam: the pipeline gains one collaborator and one
fake covers both stages in tests.

The concrete adapter is a Pydantic AI implementation shaped like the extraction
adapter — an agent per stage built from an explicit Model Deployment, structured
output, and errors raised as one stage-specific exception the pipeline maps to
its own failure vocabulary.

### Ordering inside the pipeline

Classification runs after Coreference Resolution and before chunking, because it
reads resolved text and its result is needed by nothing earlier. Assignment runs
after the extraction loop, in the same position Bill Session Resolution and
Legislative Event dating already occupy, and its result travels to persistence
the way theirs do.

### Ontology change

`PolicyArea` leaves the label set the extraction model is responsible for. It
stays in the News Ontology's labels, because the graph still holds the node — it
is simply written by a different stage. The topic relationship from a measure to
an area leaves the rendered extraction prompt's relationship list along with it.

Both removals are enforced by conformance, not only by the prompt: a Policy Area
node or topic relationship arriving from the chunk extractor is dropped and
recorded in the Adherence Report, so a model that keeps producing them is
measurable.

### The Article Chunk topic edge is retired

Today a chunk-level topic edge is written for every Policy Area a chunk emits.
With Policy Area gone from the chunk stage there is nothing to derive it from,
and deriving one for every chunk of the article would assert that every chunk is
equally about the topic, which is the imprecision this project exists to remove.
Retrieval still reaches Article Chunks from a Policy Area: the subgraph runs
through the Source Article and its chunk edges, and Grounding Evidence is defined
as the chunks a subgraph reaches rather than the chunks an edge names directly.

### Stated, not inherited

The standard for an assignment is that the **article** connects the measure to
the area — not the chunk. That is exactly what the assignment stage can see, and
it is the case this project was raised to serve: a chunk that never states a
bill's subject no longer prevents the claim. An area the article never connects
to a measure is a hallucination to be scored down, not a second kind of edge.

Marking inferred assignments with a property was considered and rejected: a
declared relationship property joins that relationship's Claim Key, so two edges
that differed only in how they were arrived at would become two claims about one
pair.

### No cap on areas per article

The classification schema sets no maximum. The Silver Set records the distribution
first, and any limit is set from it. This follows the precedent already set for
the coreference discard threshold: no untested threshold blocks ingestion before
there is data to set it from.

### Write path

The database adapter Protocol gains one method for article-level topics, taking
the Source Article, its Policy Areas, and its assignments. This extends a seam
that already exists rather than adding one, and keeps article-level edges
visibly article-level. Policy Area nodes are keyed the way every non-Bill node is
keyed, from label and name, so the hub a classification writes is the same node a
later article reaches.

### Evaluation

Two tasks join the registry, each with its own Silver Set file named for it, both
drawn from the twenty Stories in the coreference Silver Set so that every stage
is measured over one population. Classification is scored as multi-label
agreement over the vocabulary — precision, recall, and F1 across an article's
areas. Assignment is scored on measure-to-area pairs, with the measure named by
extraction's surface string.

Both Silver Sets are silver: labelled by `claude-opus-5` against a written
annotation guideline, as the coreference and extraction sets are, and each case
naming that guideline in its metadata.

## Testing Decisions

A good test here asserts what the pipeline persisted and what an adapter
returned, never how a stage arrived there. Tests drive the Story Pipeline with
fakes and read the result and the database calls; they do not assert prompt
contents, call counts, or the internals of an agent.

**Story Pipeline, through its existing seam.** Prior art is the existing pipeline
tests, which already drive the pipeline with fake coreference, extraction,
embedding, and database adapters. Extended with a fake Policy Area adapter to
cover: an article's classified areas reaching the assignment stage; assignments
reaching the database as article-level topics; an article with no areas
completing; an assignment naming an unextracted measure or an unclassified area
being dropped before persistence; and a failure in either stage routing to the
Dead Letter Queue and Article Status the way a coreference failure does.

**Ontology conformance, through the existing pure function.** Prior art is the
existing extraction conformance tests. Extended to prove a Policy Area node and a
topic relationship arriving from the chunk extractor are dropped and counted in
the Adherence Report, and that the entities beside them survive.

**Silver Set loading.** Prior art is the coreference and extraction Silver Set
tests, which load each file through its registered task's own types so the file
cannot drift from what the runner validates it against. One equivalent per new
Silver Set, asserting twenty cases, held-out splits, ids that address a Source
Article, and — for assignment — that every measure it names is one the extraction
Silver Set or the article actually contains.

**Evaluators.** Prior art is the extraction and coreference evaluator tests,
which build an evaluator context by hand and assert each score in isolation:
a perfect answer scoring one, a miss costing recall and leaving precision whole,
an unscoreable case scoring nothing rather than failing. The repository-wide
evaluator output contract test already covers the `None` return that would
silently drop a score, and picks up new tasks automatically.

**Extraction Silver Set.** Its Policy Area nodes and topic edges are removed and
its case count assertions stay as they are; the existing conformance assertion
over every silver label is what proves the set matches the narrowed ontology.

## Out of Scope

- Changing the Policy Area vocabulary. It was authored and accepted under News
  Ontology and Graph Population issue 01.
- The id-versus-canonical-name defect in the rendered extraction prompt. It is a
  one-line fix worth making immediately and independently. This project deletes
  the surface it appears on, which is not the same as fixing it.
- Entity Extraction's other measured weakness: in the same Evaluation Run the
  model returned nothing at all for thirty-one of fifty chunks, which dominates
  its node scores and has nothing to do with Policy Areas.
- Retrieval changes. Retiring the chunk-level topic edge changes which Article
  Chunks a topic-first query reaches; measuring that belongs to the Useful Graph
  Retrieval work, not here.

## Further Notes

The classification stage adds one model call per Source Article against N chunk
calls, and removes twenty-seven lines of vocabulary from every one of those N
prompts. On the fifty-chunk extraction population the chunk prompt was roughly
2,500 input tokens per call, so the net token cost is expected to be negative.

The assignment stage is the first stage in the pipeline that asserts a claim with
no Article Chunk behind it. That is deliberate and is what the Problem Statement
asks for, but it means the Grounding Evidence for a topic edge is the Source
Article rather than a chunk. It is worth watching in the first Evaluation Run
whether assignment reaches for areas the article merely mentions in passing.
