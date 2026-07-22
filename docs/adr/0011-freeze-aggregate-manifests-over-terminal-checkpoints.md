# Freeze aggregate manifests over terminal checkpoints

This decision supersedes the aggregate-report-blob portion of ADR 0005. Immutable authored definitions and terminal Evaluation Checkpoints remain authoritative evidence. After every manifested case has matching terminal evidence, the Evaluation Ledger canonically serializes a Frozen Aggregate Manifest containing the exact Evaluation Run, Suite, Resolved Evaluation Plan, Evaluation Task Contract hash, evidence-contract version, report-level provenance, and ordered manifest-entry, case-result, and checkpoint identities and content hashes. The manifest contains no copied task inputs, expected outputs, actual outputs, metadata, evaluator results, or complete ReportCase values.

The manifest artifact is content-addressed. Registering it, linking it to the run, and moving the run to `finalization_pending` are one ledger transition; replay of the same composition is idempotent and replacement with a different composition is rejected. Finalization verifies both artifact and checkpoint integrity, then deterministically materializes the Evaluation Report from the exact immutable definitions and checkpoints named by the manifest. That report is a derived projection, never an independently authoritative persisted blob.

The evidence-contract version is the sole persisted authority for checkpoint meaning and evaluator-visible report projection semantics. Materializer code and the installed Pydantic Evals version are implementation details and do not receive independent persisted compatibility versions.

Evidence contract version 1 defines the persisted successful and failed ReportCase projections. Increment the version only when an incompatible persisted shape or semantic change must be supported alongside existing evidence.
