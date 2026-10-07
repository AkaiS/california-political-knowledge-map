# Jev structural retrieval

Production chat and chat evaluations both use `chat_dependencies`, which builds
`JevStructuralRetriever` alongside `Neo4jFullTextRetriever` and
`Neo4jDenseRetriever`. It is the sole production Cypher backend. The preserved
experiment remains an immutable record, and production never bootstraps it.

## Selection and query construction

The branch receives the approved question and the shared absolute retrieval
deadline. Jev narrows the semantic schema at `.8`, retains every endpoint
alternative required by selected relationships, and selects parent roles at
`.52`. Organization subtype refinement requires a winning probability of `.8`;
uncertain required subtypes abstain. Property selection runs at `.52` over the
chosen role occurrences.

Single and peer variants compete within one predicate selection. Independently
required predicates remain separate. When a union overlaps selected individual
predicates, a Jev Choice distinguishes alternatives from conjunctions at `.8`.
For parallel relationships, another Choice at `.8` determines which endpoints
share an identity. Separate Bills retain separate name and session filters;
uncertain operator or endpoint decisions stop construction.

Numeric occurrence attachments preserve repeated roles and their filters.
Compiler-owned Article roles use the repaired staged attachments, including
multiple PolicyArea roles connected to the same Article. Peer descriptions use
immutable version 2, without the experiment's removed wording example.

An Article selected only for publication or title constraints represents the
supporting reporting, rather than another semantic endpoint. The compiler applies
those constraints to each claim's supporting Article after provenance traversal.
Other selected entity roles must still form one connected semantic pattern.

A successful relationship-free selection goes through one Jev reporting-intent
decision at `.52`. Negative decisions forbid shared reporting execution.
Missing, malformed, or failed decisions fail selection. Gate decisions belong
to the request; simultaneous identical questions cannot share mutable state.

The configured Chat Model Deployment composes the selected structure and returns
positional binding values. Composition must preserve Jev's occurrence
attachments. The compiler owns aggregate wiring, provenance traversal, and result
projection. Composition and binding each allow two corrections. The experiment's
unique-occurrence deterministic wiring fallback remains within this compiler;
it does not select another backend.

Binding receives each slot's node variable and incident predicates, so repeated
Bill-name slots preserve their association with the question's relationships.
Binder instructions and the request template explicitly adopt version 2.

Binding validates dates, domain membership, canonical entity matches, ambiguous
identities, and Bill Designations. The deterministic compiler parameterizes
question values. CyVer syntax, schema, and property checks must authorize the
abstract structure. Bound queries also require parameter-aware Neo4j EXPLAIN
and read-only classification before execution.

Finite domains are normalized before canonical entity lookup, so session spelling
variants narrow Bill lookup using the stored session. Claims retain only ontology
Claim Key properties and expose `needs_review` separately.

## Evidence and results

The query returns semantic values and independent evidence groups. The adapter
loads Article Chunks through their actual Source Article links, validates that
each chunk has one owner, and builds `typed_traversal` candidates. Chunk-level
claims name their asserting chunks. Article-level topic claims name their
asserting Source Articles, as required by ADR 0020. Counts retain evidence for
each counted Article.

Candidates have deterministic ordinal ranks and no invented similarity score.
Fusion keeps its existing structural weight and selection limits. Evidence
Assembly supplies verified wording and citations. The Chat Agent sees a semantic
result row only when every chunk supporting that row remains in its selected
evidence. The full pre-selection result remains inspectable in the report.

## Services, deadlines, and observations

The pinned `typesafe-sdk==0.7.2` and `cyver==2.0.2` are normal package dependencies.
Startup resolves `TYPESAFE_API_KEY` or Keychain service `jev_api`, account
`test_key`. Shutdown closes the Jev client and both Neo4j drivers.

The Jev SDK and sync Neo4j/CyVer operations run in worker threads so sparse and
dense branches can progress concurrently. CyVer's driver wrapper forces the
configured database, read routing, and bounded query timeouts. Production uses
one 180-second deadline across retrieval, fusion, and Evidence Assembly.

Reports retain Jev request state, questions, probabilities, selected pieces,
usage, generated Cypher, wiring, binding attempts, validation, and semantic
results. Failed construction records its stage and a safe diagnostic. Provider
exception payloads do not enter the report. Existing `chat_session.structural_stage`
spans join these stages to the Chat Session Audit Trail.

A Jev failure produces `FailedBranch`; completed sparse and dense candidates
remain available, and the final answer discloses the structural failure. There
is no alternate LLM selector after failure.

## Verification

`tests/test_jev_execution.py` drives both chat HTTP approval and the evaluation
runner through real startup and packaged construction with synthetic services.
Selector, Article attachment, and reporting-gate tests cover subtype abstention,
repeated roles, schema closure, invalid decisions, and request isolation. Live
checks use development questions and the configured services. The unlabeled
chat Data Set supplies execution evidence without an answer-quality score.

[ADR 0023](adr/0023-jev-constructs-cypher-in-the-shared-chat-retrieval-path.md)
records the production integration decision.
