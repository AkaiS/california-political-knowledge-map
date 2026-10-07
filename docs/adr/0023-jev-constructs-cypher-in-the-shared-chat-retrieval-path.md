# Jev constructs Cypher in the shared chat retrieval path

Chat and chat evaluations use `chat_dependencies` and the same `ChatSession`.
The staged Jev experiment, including the repaired Article occurrence wiring,
is now the production Cypher branch. It runs alongside sparse full-text and dense
retrieval. Fusion and Evidence Assembly retain their existing contracts.

Jev selects the schema, semantic roles, Organization subtypes, and attached
properties. A request-local Jev reporting gate permits relationship-free stored
reporting retrieval. Negative, missing, invalid, and failed gate decisions forbid
it. The configured Chat Model Deployment supplies composition and positional
binding. The deterministic compiler supplies provenance traversal; CyVer and a
parameter-aware read-only EXPLAIN must authorize execution.

Every approved question reaches this branch, including reporting questions the
rewriter marks non-relational. Historical execution records retain their original
branch-selection semantics through the default `structural_reporting` field.
Production startup always enables reporting and exposes no backend selector.
The old structural adapter is no longer wired into chat or evaluations.

The `.8` schema cutoff and `.52` structural/property/reporting cutoffs preserve
the experiment settings. Subtype refinement requires `.8`. They remain
uncalibrated; promoting this path is not a claim about answer accuracy.
The shared retrieval deadline is 180 seconds. Completed sibling evidence remains
available if Jev fails, without retrying through another Cypher backend.

Production modules and immutable prompt resources ship in the package. They
never restore source from Git history, modify import paths, patch module globals,
or read experiment development references during execution. Peer-description
version 2 records the experiment's wording deletion without changing version 1.

Evaluation reports and application observations retain Jev decisions, prompt
versions, usage, validated Cypher, bound values, semantic result rows, and
Grounding Evidence. The unlabeled chat Data Set supports inspection, not an
answer-quality score. Evaluation Run provenance still follows ADR 0017.
