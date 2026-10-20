# Deterministic Evidence Assembly

`knowledge_map.core.evidence.EvidenceAssembler` turns fused candidates into an
`EvidencePackage` or `EvidenceAssemblyFailure`. It implements
[Graph-Prioritized Retrieval issue 08](../work/projects/graph-prioritized-retrieval/issues/08-deterministic-evidence-assembly.md)
using the existing [retrieval contracts](retrieval-contracts.md).

## Storage boundary

Construct the assembler with one asynchronous storage function:

- `load_grounding(FusedCandidate) -> GroundingEvidence` loads the selected
  Article Chunk's wording and Source Article citation. The returned chunk ID
  and Source Article ID must match the candidate.

Storage adapters must convert database or transport failures to
`EvidenceHydrationError`. Missing rows may raise `LookupError`; operating-system
and value-validation errors also become assembly failures. Cancellation and
unexpected programming errors propagate. The storage call does not retry here.
The [retrieval coordinator](retrieval-pipeline.md) supplies concrete database
wiring and the retrieval deadline.

The assembler uses the hydrated Article Chunk wording directly. It does not load
the SQLite Story or require the coreference-resolved chunk to occur verbatim in
the original body. Each passage carries the `stored_chunk` marker so consumers
do not treat transformed wording as a direct quotation from the Publication.

## Assembly and coverage

Call `await assembler.assemble(execution, candidates, coverage=description,
relevant_collection_ids=collection_ids, limits=limits)` with the complete
execution record and fused candidates. The original branch outcomes remain
unchanged. Selected passages retain their entire fused candidate, including
all routes, graph claims, branch scores, and pre-fusion ranks.

Candidates are visited by fused rank, then chunk ID. Each Source Article appears
once, in the order of its first selected passage. Its passages retain rank order;
separate passages from different parts of the Story remain available. Duplicate
fused chunk IDs, missing contributions, mismatched provenance, and conflicting
citations fail assembly.

The caller supplies relevant collection IDs from its coverage assessment. They
can include a collection with no returned passage, so a Deferred limitation
survives an empty search. Every requested collection must have exactly one
entry. The assembler keeps those entries, sorted by collection ID, and omits
unrelated entries. It does not infer collection relevance from question wording.
Optional `monthly_coverage` is filtered to the same IDs and sorted by collection
and month. No monthly detail is loaded automatically.

## Context budget

`EvidenceContextLimits` defaults to 24,000 characters, 12 passages total, and
`max_passages_per_article=3`. All limits must be positive integers. These are
initial configurable limits, not measured retrieval-quality recommendations.

The article limit prevents repeated chunks from one Source Article from using
the whole context before other articles can be assessed. It retains that
article's highest-ranked passages that fit the character budget. Once the
article reaches its limit, further chunks from it are skipped before loading
their stored wording, and selection continues to other articles. Oversized
passages do not count toward the article limit. This bounds representation per
article without changing fusion scores or adding a relevance judgement.

`render_evidence_context(package)` is the exact evidence input to supply to the
Chat Agent. Its compact JSON contains:

- The approved question and its assessment, including any Deferred explanation
  and recoverable portion.
- Branch outcomes, counts for successful branches, and every failure disclosure.
- Source Article citations, stored chunk passages, and their candidate routes and
  graph claims.
- Relevant coverage, requested monthly detail, and the omitted passage count.

The renderer excludes the execution audit and each contribution's unverified
stored `grounding` wording. Do not substitute `package.model_dump_json()` as the
model context: that serializes the full retained audit as well.

The budget counts Unicode characters with `len(render_evidence_context(package))`,
including JSON syntax, citations, provenance, coverage, and failure disclosures.
It does not approximate tokens. Context accounting metadata is returned in the
typed package and is not part of the rendered model input.

Each whole stored passage is admitted only if the resulting rendered context
fits. An oversized passage is omitted, and later candidates remain eligible.
Reaching the passage limit stops selection. Passage text is never cut mid-sentence
to fill the budget. `omitted_passages` counts unselected fused candidates;
pre-fusion candidates remain in the execution audit. If mandatory context alone
cannot fit, assembly returns a failure instead of dropping coverage or branch
disclosures.

The assembly observation records the configured limits and identifies chunks
skipped for the article cap with `article_passage_limit`. They remain included
in the omitted passage count and the retained execution record.

Assembly failure preserves the entire execution record and adds no failed
retrieval branch. Assembly neither summarizes evidence nor makes another model
decision, sufficiency judgement, disagreement verdict, or retrieval request.

Behavior is covered by `tests/test_evidence.py` using in-memory storage functions.
No database service, model service, or browser is required.
