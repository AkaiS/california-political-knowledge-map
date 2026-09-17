# Retrieval and answer contracts

`knowledge_map.schemas.retrieval` defines the values passed between retrieval
branches, fusion, Evidence Assembly, and the Chat Agent. These contracts implement
[Graph-Prioritized Retrieval issue 02](../work/projects/graph-prioritized-retrieval/issues/02-retrieval-execution-and-evidence-contracts.md).
The remaining project tickets implement the operations that produce them.

## Approved input and execution facts

`RetrievalRequest` accepts the existing approved `QueryRewrite`, including its
question-policy and coverage assessment. It rejects Declined questions. Extra
fields are forbidden throughout these contracts, including an original-question
field. The approval workflow remains the authority for obtaining user approval;
constructing a Pydantic value does not itself establish user consent.

The expected branches follow the internal `relational` boolean. Full-text and
dense retrieval are always expected. Structural retrieval is expected only for
a Relational Question. `RetrievalExecutionResult.expected_branches` records that
set and rejects a caller-supplied set that disagrees with the rewrite.

Every execution has exactly one outcome per branch, including a skipped
structural outcome for a non-relational question. The `status` discriminator
selects one of these types:

| Type | Meaning | Retained data |
| --- | --- | --- |
| `SuccessfulBranch` | Search completed, possibly without matches | Ordered candidates, including an empty tuple |
| `FailedBranch` | Search could not be completed | Branch identity and the fixed `failed` discriminator |
| `SkippedBranch` | Structural search was not requested | Structural branch identity and `non_relational` reason |

`evidence_by_branch` exposes successful branches, including successful empty
ones. `failed_branches` exposes failures. These views derive from the recorded
outcomes, so they cannot disagree with them. JSON retains the expected branches
and all discriminated outcomes. There is no execution-wide success label.

## Candidates and provenance

`BranchCandidate` identifies an Article Chunk and its Source Article, and retains
`BranchRanking` plus every `RetrievalRoute` that found it. Ranking holds the
originating branch, one-based rank, and finite raw `BranchScore`. A branch with
no native numeric score uses `None`. `BranchScore` preserves the JSON number but
has no ordering operation and cannot occupy the separate numeric
`FusedCandidate.fusion_score` field. Fusion consumes branch ranks rather than
comparing raw scores.

Route kind determines the branch and matched field. Full-text routes match
entity `name`, article `title`, or chunk `text`; dense routes match `embedding`;
typed traversal has no matched text field. Each route retains its entry node
and any supporting `GraphClaim` values.

A graph claim retains endpoint references, relationship type, Claim Key,
`needs_review`, and exactly one provenance grain. Chunk-level claims name their
asserting Article Chunks. Article-level `ABOUT_TOPIC` and `DISCUSSES_TOPIC`
claims name their asserting Source Articles and cannot name an Article Chunk,
as required by ADR 0020. Node references can include the database element
identity alongside the internal ID, preserving distinct graph nodes that share
an internal ID. Candidate deduplication does not resolve these identities.

`FusedCandidate` holds a shared rank and fusion score plus the complete original
branch candidates as contributions. Every contribution must identify the same
Article Chunk and Source Article. Evidence packaging checks selected
contributions against the execution record, rejecting invented contributions,
lost routes, or a passage cited to a different Source Article. The fusion
algorithm and its weights belong to issue 07.

## Evidence and answers

`EvidencePackage` carries the execution record, selected `SourceArticleEvidence`,
relevant `CoverageDescription`, optional monthly coverage, and
`AppliedContextLimits`. The execution record preserves the pre-fusion candidates
even when selection omits passages. Each Source Article appears once, with a
title, HTTP link, publication date when available, and one or more passages.

`VerifiedPassage` records exact original wording, half-open character offsets in
the original Story body, its Source Article identity, and its fused candidate.
The type requires the `original_story` verification marker and checks that the
offset length matches the wording. It cannot prove a quotation against a Story
that it does not hold. The Evidence Assembler in issue 08 must load that Story
and verify the text before constructing the value. Transformed chunk text is
not an alternative verification mode.

`AppliedContextLimits` records the assembler's measurement unit, maximum and
used amount, passage-count limit, and number of omitted passages. Units may be
characters or tokens. Validation rejects a reported overrun and too many selected
passages. The assembler owns measurement of the context actually supplied to the
Chat Agent, including citation and coverage overhead. Contract validation does
not tokenize or count a serialized execution audit as if it were model context.
Budget selection and truncation remain issue 08's work.

`RetrievalAnswer` adds an optional introduction, typed source relevance notes,
and disagreements referring to selected sources. It retains the evidence package
so Deferred limits and branch failures survive answer construction. A separate
`EvidenceAssemblyFailure` retains the execution facts when a package cannot be
assembled; it is not a failed retrieval branch.

`EvidencePackage.failure_disclosures` produces fixed safe messages for every
failed branch, listing structural failure first. An empty successful structural
outcome produces no failure disclosure and remains distinguishable from failure
and skip through the execution record. A renderer must preserve these
distinctions and disclose every failed branch.

## Coverage and diagnostics

Each `CoverageEntry` represents one Publication or distinct public-record
collection, with its authored description, relevant limits, verified available
count, and known expected count when one exists. Completeness stays unknown
without a denominator. The derived percentage is undefined for a zero expected
count; zero available out of a known empty set remains expressible. Publication
entries use Story publication dates rather than event dates. Refresh progress
and retry status are not coverage fields.

`MonthlyCoverage` is a separate response value for on-demand detail. It has its
own expected count, and the evidence package may attach it only for a collection
in the relevant Coverage Description. The primary description does not include
monthly detail by default. Loading and refreshing measured coverage are outside
this contract ticket.

`RetrievalFailureLog` is separate from answer-facing values. It carries branch,
stage, failure kind, attempts consumed, and a safe diagnostic message. Stage
values distinguish preparation, index and execution failures, the structural
construction stages, hydration, and deadline exhaustion. The producer must
supply an authored or sanitized diagnostic, never raw exception or model text.
The branch implementations own log emission. Answer-facing `FailedBranch`
rejects these fields, raw exceptions, and model output.

The behavioral contract tests are in `tests/test_retrieval_contracts.py`. They
exercise construction, rejection of contradictory values, and JSON round trips
without a database or model service.
