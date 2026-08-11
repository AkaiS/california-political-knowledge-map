# Identity-bearing values resolve once per Source Article

Ingestion collapses. A node merges onto its minted key and an edge onto its Claim Key, so every Article Chunk that mentions the same entity writes onto one node. A value that bears on identity is therefore resolved once for the whole Source Article, before any chunk is persisted, and every chunk is handed the same settled answer.

A value bears on identity when it is part of a key, or when a later ingester joins on it to decide whether it has met the node before. Bill Session Resolution is the first kind: the session is in the `Bill` key, and getting it wrong mints a second bill. Legislative Event Date is the second: the date stays out of the key deliberately, but an authoritative legislative record is reconciled against news by joining on date and bill, so a wrong date breaks the join as surely as a wrong key would. Both resolve at article scope. Neither is decided by an adapter, which under [ADR 0002](0002-story-pipeline-architecture.md) receives the resolved domain model and writes what it is given.

Resolution reads every chunk's extraction at once, which is what makes a contradiction visible: where chunks disagree on a value, the resolution is `needs_review` and the value is left unset. Preferring one of the stated values would decide the graph by the order chunks happened to be written, and that is the failure this decision exists to prevent — not a lesser version of it.

## Considered options

Resolving per chunk is what this replaces, and it was wrong in a way that read as correct. Each chunk resolved its own value and the write was `SET n += $properties`, so a chunk that stated nothing stamped its inferred fallback over a date an earlier chunk had stated outright. The last chunk mentioning an entity won, verified provenance flags included, and nothing in the graph recorded that a better answer had been overwritten.

Ordering the write instead of the resolution — having Cypher prefer a verified value over an inferred one, with `coalesce` or a conditional `SET` — fixes the overwrite without fixing the cause. It puts precedence rules in the query layer where the ontology cannot see them, it has to be repeated correctly at every write site, and it still cannot tell two stated values apart from one stated twice, so genuine contradictions resolve silently by arrival order.

Keying on the value when it is verified and not otherwise gives an entity two identity shapes, and a later corrected ingest can only find every node it must fix if there is one shape to look for. Keying on the date unconditionally is worse: a wrong date in a key conflates two distinct events irrecoverably, where a name-derived key at worst fragments one event into two nodes that the reconciliation join can merge back.

## Consequences

Article-scope resolution runs in the pipeline before the chunk loop, alongside the coreference and extraction passes it depends on, and its output is passed unchanged to every `ingest_chunk_extraction` call. A resolver takes the article's full list of extractions, not one — the signature is what stops per-chunk resolution being reintroduced by accident.

Order-independence is directly testable, and is tested: resolving the same extractions in both orders yields the same answer. Contradictions leave the graph rather than resolving into it, surfacing as `needs_review` with no value set, which is a larger review queue than order-dependent silence produced and is the intended trade.

Any new value that bears on identity joins this stage. Resolving one at chunk scope reintroduces the same defect in a new place, and the symptom — provenance flags that degrade as an article is ingested — points at the write path rather than at the resolution, which is why it went unnoticed the first time.
