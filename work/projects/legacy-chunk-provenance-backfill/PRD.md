# One-Time Legacy Chunk Provenance Backfill

Labels: ready-for-agent

## Problem Statement

Existing Neo4j Article Chunks contain coreference-resolved wording, an index,
and an embedding, but no range in the original SQLite Story. The Original Story
Passage Provenance change will calculate those ranges during new Story Pipeline
runs. It cannot calculate them retroactively from the information already
stored. When the Evidence Assembler begins requiring ranges, older chunks will
fail verification and the Chat Agent will lose access to reporting already in
the graph.

Reingesting every saved Story would call Coreference Resolution again, spending
model tokens and potentially changing Article Chunk boundaries, embeddings,
Entity Extraction, and graph claims. The graph's current merge-only chunk write
also leaves stale chunks and claims after a shorter rerun. The maintainer needs
to learn how much provenance can be restored without that cost or disruption,
and needs any data change to be reviewable and reversible.

## Solution

Build a one-time, model-free backfill command outside the Story Pipeline and
live retrieval path. Its default mode is read-only. It compares each existing
Article Chunk with its cited original Story, uses exact unchanged wording and
chunk order to propose a contiguous original Story range, and reports the
proposals it cannot establish uniquely. It does not claim that a fuzzy match
or a plausible source passage is verified provenance.

Review a dry-run report and representative proposed passages before any write.
An explicit apply mode may add only the original start, original end, and
Story-content fingerprint already specified for new chunks. It rechecks its
inputs against the approved plan before each write and skips anything that
changed or became ambiguous. A recorded manifest supports inspection,
interrupted-run resumption, and a guarded rollback of only this backfill's
properties. Existing Chunk text, embeddings, identities, and graph
relationships stay untouched.

Develop and review the command on a separate Git branch or worktree. Test it
against copies of the SQLite Story store and a disposable Neo4j graph, not the
shared live data. Commit the command so the migration is reproducible. It may
be removed after the migration is verified; Git history still records the
script and review, while a separate run record documents what happened to the
data. No permanent runtime alignment mechanism is introduced.

## User Stories

1. As a person asking about California politics, I want older reporting to
   remain available as verified Grounding Evidence, so that the provenance
   change does not make the existing corpus disappear from Retrieval Answers.
2. As a person reading a Retrieval Answer, I want any original passage from an
   older Article Chunk to be tied to the correct Story, so that the citation
   and quoted wording agree.
3. As a person reading a Retrieval Answer, I want an uncertain older Chunk to
   fail verification, so that an attractive but wrong passage is not quoted.
4. As a person reading a passage whose Chunk starts inside a coreference
   replacement, I want the whole original mention or no passage, so that no
   guessed fraction of the source is displayed.
5. As a maintainer, I want a count of legacy chunks with and without usable
   provenance, so that I can judge the actual migration need.
6. As a maintainer, I want a read-only dry run first, so that I can inspect
   proposed changes without touching SQLite or Neo4j.
7. As a maintainer, I want the dry run to explain skipped and ambiguous chunks,
   so that a low coverage rate is visible rather than hidden as success.
8. As a maintainer, I want proposals grouped by Source Article and ordered by
   Article Chunk index, so that repeated wording can be judged against nearby
   chunks instead of matched to the first occurrence.
9. As a maintainer, I want exact unchanged text to anchor proposals, so that
   a similarity score alone cannot authorize a quote.
10. As a maintainer, I want a sample of proposed original excerpts and their
    stored Chunk wording available for review, so that I can spot systematic
    alignment errors before applying anything.
11. As a maintainer, I want apply mode to require an explicit plan and
    confirmation, so that inspecting the command cannot accidentally mutate
    the graph.
12. As a maintainer, I want apply mode to reject a Story or Chunk that changed
    since the plan was made, so that offsets are not attached to stale text.
13. As a maintainer, I want a partially completed run to resume without
    duplicating or overwriting work, so that an interruption is recoverable.
14. As a maintainer, I want a precise record of every Chunk property changed,
    so that I can inspect the applied data and reverse only this run.
15. As a maintainer, I want rollback to check current values before removing
    properties, so that it does not erase a later legitimate ingestion result.
16. As a maintainer, I want the code change isolated in a branch or worktree,
    so that an unpromising alignment experiment can be abandoned cleanly.
17. As a maintainer, I want database copies for rehearsal, so that a worktree's
    shared SQLite link or Neo4j connection cannot mutate live data during
    testing.
18. As a maintainer, I want the one-time command committed, so that its exact
    behavior can be reviewed and reproduced after the run.
19. As a maintainer, I want the command removable from the current tree after
    migration, so that a one-time operation does not become a permanent
    runtime dependency.
20. As a maintainer, I want unresolved chunks listed separately, so that I can
    decide later whether selective reingestion is worth its model cost.
21. As a maintainer, I want the backfill to preserve Chunk text, embeddings,
    Entity Extraction, and relationship claims, so that restoring quote
    provenance does not rewrite the political knowledge graph.
22. As a maintainer, I want a post-apply audit of range and fingerprint
    coverage, so that completion means verified data rather than a successful
    command exit.

## Implementation Decisions

- This is an offline data operation, not a new Coreference Adapter, Story
  Pipeline stage, Evidence Assembler fallback, or Chat Agent tool. It does not
  call a model, recrawl a Publication, or rerun Entity Extraction.
- The backfill reads original Story content from SQLite and ordered stored
  Article Chunks through their Source Article links in Neo4j. Existing chunks
  have no successful Coreference Resolution Run or accepted Mention Span map;
  the command must not claim to reconstruct either one.
- Candidate mapping uses exact unchanged source anchors and monotone Chunk
  order within a Source Article. Repeated text, insufficient anchors,
  contradictory order, changed source content, and boundaries whose original
  mention cannot be identified uniquely cause a reported skip. No first-match
  substring lookup, unconstrained fuzzy alignment, or guessed partial
  replacement boundary can authorize a write.
- When a proposed interval crosses an inferred replacement, it may include
  the whole original mention only if the source range is unique and the
  surrounding alignment establishes both edges. Otherwise the Chunk remains
  unmapped. Do not add neighboring sentences as quote context.
- A read-only inventory and plan are the first deliverables. Report totals by
  Story and Chunk, accepted proposals, legacy chunks still missing provenance,
  and skip reasons. Include a reviewable sample of transformed Chunk wording
  beside proposed original Story excerpts. A dry run may legitimately find
  that safe coverage is too low to justify applying the plan.
- The plan records each proposed Chunk ID and owning Source Article, the
  digest of the stored Chunk text, the digest of the original Story content,
  the proposed half-open original range, and any preexisting provenance
  values. Keep raw run artifacts out of the issue tracker and Git; record a
  concise outcome summary in the project after a real run.
- Apply is an explicit mode requiring a reviewed plan, a database backup, and
  operator confirmation. It rechecks Chunk ownership and text digest, Story
  digest, proposed range, and preexisting properties before a conditional
  write. It writes only the original range and SHA-256 fingerprint used by the
  main provenance contract. A conflict skips the Chunk and appears in the
  report. Group writes by Source Article so a partial run is understandable.
- The command is idempotent against an unchanged plan. A rerun recognizes its
  own already-applied values and does not add a second change. It never
  overwrites provenance written by normal ingestion or another backfill.
- Rollback uses the applied manifest and removes or restores only the
  properties this run changed, after checking their current values still
  match the run. It does not delete Chunks or relationships. Code rollback is
  separate: reverting the branch does not undo a database write, while
  leaving additive properties in Neo4j is harmless to older code.
- Rehearsal uses a copied SQLite Story store and disposable Neo4j data.
  Worktree isolation alone is insufficient because the repository's worktree
  setup can link the same SQLite database and a Neo4j connection can still
  target the live graph. The command must show its target database identity
  before apply and refuse an implicit live target.
- Keep the command in version control for review and reproducibility. After
  the operation is verified, a separate commit may remove it from the current
  tree. Git history retains the implementation; it does not by itself record
  which database rows were changed, so the manifest and run summary matter.
- Unmapped legacy chunks continue to fail Evidence Assembly under the main
  provenance contract. The report may identify candidates for selective
  reingestion, but this spec does not authorize or implement that reingestion.
- Do not perform a live write as part of building or testing the command.
  Running apply against user data requires separate explicit approval after
  the dry-run report and backup plan have been reviewed.

## Testing Decisions

- The main test seam is the one-time command. Drive its dry-run, apply, resume,
  and rollback modes against a temporary SQLite Story store and controlled
  Chunk records. Assert observable reports and resulting Neo4j properties,
  not private alignment steps or a particular query string.
- A good test proves that the displayed original passage matches the Story
  slice at the planned offsets and that dry run leaves both stores unchanged.
  It also proves that only the three intended Chunk properties change on
  apply and that rollback restores the previous state.
- Cover a uniquely anchored coreferenced Chunk, unchanged text, length-changing
  replacements, overlapping Chunk text, repeated source wording, and a Chunk
  boundary inside a replacement. Cases with missing or conflicting anchors
  must appear as skips and must not write provenance.
- Cover stale Story content, changed Chunk text, mismatched ownership,
  preexisting provenance, interrupted apply, repeat apply, and rollback after
  a later change. The command must refuse or skip each unsafe mutation.
- Prior art is the existing reset-Stories command and its command-level tests
  for dry run and confirmation, the Evidence Store's SQLite and graph
  hydration tests, and the Story Pipeline's fake-adapter tests. Add a focused
  disposable-Neo4j adapter test only if command-level fakes would miss a real
  conditional-write or rollback behavior.
- A rehearsal on copied data should produce an inventory, proposal sample,
  skip summary, and post-apply audit before any live migration is considered.
  No live model, live user database, or browser is needed for automated tests.

## Out of Scope

- Changing the normal ingestion, Coreference Resolution, retrieval, Evidence
  Assembly, or Chat Agent architecture.
- Reconstructing a full successful Coreference Resolution Run or claiming
  model-level equivalence from old chunks.
- Writing provenance for ambiguous chunks or treating a plausible fuzzy
  match as verified original wording.
- Reembedding Article Chunks, rerunning Entity Extraction, changing graph
  claims, or fixing the separate stale-chunk reprocessing defect.
- Automatically resetting Story statuses or reingesting the whole corpus.
- An unattended live migration or automatic deployment cutover.
- Keeping the migration command in the runtime path after the one-time work.

## Further Notes

This plan complements Original Story Passage Provenance. New Story Pipeline
runs should calculate provenance from accepted, located Mention Spans. This
backfill concerns only older Neo4j Chunks written before that contract existed.
It is an attempt to recover safe ranges without paying for another full
Coreference Resolution pass, not a promise that every old Chunk is recoverable.

The backfill can establish a source range only under its stated alignment
rules. It cannot prove that the old resolved wording was a faithful
Coreference Resolution of the Story. A low safe-alignment rate is a valid
result and a reason to stop before apply, then consider selective reingestion
as a separate decision.
