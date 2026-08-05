# Build the initial Relevance Filter Evaluation Gold Set

Labels: wayfinder:research, ready-for-human
Parent: [Repository-Wide Model Evaluation Strategy](../MAP.md)

## Question

What collection, binary human-labeling, review, provenance, and split procedure will produce the first versioned Evaluation Gold Set for the Relevance Filter while preserving a held-out test split?

## Blocking

- Blocks: Specify the Relevance Filter evaluation and comparison report.

## Decision

Create `relevance-gold-v0.1` from a predeclared, post-extraction candidate
population. It is a versioned collection of binary, human-adjudicated
Evaluation Cases, not a database query, a classifier-training extract, or a
set of automated `INCONCLUSIVE` decisions.

The release has three splits:

| Split | Use | Access rule |
| --- | --- | --- |
| `training` | Logistic-regression fitting only | May contain human labels; never contains held-out groups. |
| `calibration` | Prompt/few-shot, threshold, and model-selection work | May be inspected repeatedly while developing. |
| `held-out` | Comparison and release-check reporting only | Do not use its items, labels, errors, or per-case results to choose a model, prompt, threshold, feature, or few-shot example. |

The first release should aim for 200 adjudicated cases: 120 training, 40
calibration, and 40 held-out. The target is a starting operational size, not a
statistical quality floor. Each split must contain both classes, and the
held-out split should include at least 20 `RELEVANT` cases; expand the release
if the candidate population cannot meet that constraint without reusing a
leakage group. Report prevalence-weighted aggregate metrics alongside
stratified diagnostics so any intentional oversampling remains visible.

### Binary labeling policy

An annotator reviews the displayed headline, description, and clean article
text (or a retained, access-controlled source artifact when clean text is
unavailable). They assign exactly one label:

- `RELEVANT`: the article substantively concerns California government,
  elections, ballot measures, political actors, public policy, regulation, or
  political influence relevant to the California Political Knowledge Map.
- `IRRELEVANT`: California politics or policy is absent, merely incidental, or
  the article is principally about another topic/jurisdiction without a
  substantive California political connection.

`INCONCLUSIVE` is an automated Relevance Status used to route an item for
review. It is never a human label, a Gold Set expected output, or a split.
Annotators must choose one binary label and cite the shortest supporting text.
The named Gold Set steward records any guide ambiguity exposed in the pilot or
adjudication log; a semantic rule change creates a new annotation-guide and
Gold Set revision.

### Collection, sampling, and split procedure

1. Freeze an eligible-candidate export before anyone labels it. Include the
   canonical URL, publication ID, collection timestamp, headline, description,
   clean-text/source-artifact hash, extractor version, and the automated
   status/score that produced the candidate. Exclude pages without enough
   retained material for a reviewer to make the binary decision.
2. Assign a stable `group_id` before sampling. Group canonical/redirect URL
   variants, exact duplicates, syndicated copies, and near-duplicate text.
   Add a shared group for a dependent article series or material time-window
   when it would otherwise leak the same story into multiple splits.
3. Predeclare strata from fields available before labeling: publication,
   publication section/category when present, collection period, and a
   difficulty proxy such as current-model status/score band or model
   disagreement. Stratify the candidate export, then use a deterministic,
   group-disjoint assignment with the algorithm, group-key version, and seed
   recorded in the release manifest. Keep the held-out prevalence representative
   where practical; deliberately oversampled edge strata are diagnostic and
   must be reported separately.
4. Pilot the annotation guide on 20 non-held-out cases. Both reviewers label
   independently and blind to automated status, model output, and each other.
   Revise and version the guide before the production labeling round; do not
   silently relabel pilot cases under the revised guide.
5. Have two independent human reviewers blind-label every held-out case and a
   rotating audit sample of the training and calibration cases. Matching labels
   are accepted. A named third reviewer adjudicates every disagreement and
   records the final label, supporting evidence, guide issue, and decision.
   Retain both original labels rather than overwriting them. Publish raw
   agreement, disagreement rate, a binary reviewer confusion matrix, and a
   chance-corrected agreement coefficient for each release.
6. Author immutable Evaluation Case revisions from adjudicated examples. A
   case's typed task input preserves the exact representation evaluated
   (headline and description for the metadata classifier; clean text as an
   access-controlled artifact when the LLM path needs it), its expected output
   is binary, and its metadata records provenance and review facts. Assemble
   `relevance-gold-v0.1` with exact case-revision memberships and split
   assignment through the existing `EvaluationGoldSet` contract.
7. Freeze and hash the manifest. The held-out artifacts and labels remain
   access-controlled; routine development receives only calibration/training
   material and aggregate held-out reports at predeclared evaluation points.
   If held-out item-level inspection guides development, retire that test split
   and publish a new Gold Set version.

### Required case and release provenance

Each Evaluation Case needs an opaque stable ID and revision, source URL and
publication ID, retrieval timestamp, canonical URL, content and metadata
hashes, text-representation/extractor version, sampling strata, `group_id`,
split, annotation-guide revision, reviewer labels, evidence spans, adjudicated
label/rationale, review timestamps/roles, and sensitivity/redaction status.
Raw source text, reviewer identity, and detailed rationales are controlled
Evaluation Artifacts rather than public evaluation metadata.

The release needs a data statement describing the candidate population,
inclusion/exclusion rules, sampling and split algorithm/seed, strata counts,
annotator preparation, agreement/adjudication outcomes, known coverage gaps,
intended/prohibited uses, manifest hash, steward, and changelog. Any addition,
removal, redaction, correction, or changed label creates a new Gold Set
version; existing Evaluation Case revisions and membership remain immutable.

### Current execution state

The tracked `document_store.db` has 43 cached article records from the
pre-relevance-label schema. It is a useful seed population but cannot yet
produce `v0.1`: it has no relevance label/provenance columns, and no human
labels. First run the existing schema migration on a copy of that database (or
collect a new candidate export), then recruit two reviewers and an adjudicator.
No automated, keyword, model, or LLM label may be promoted to an authoritative
Gold Set label without this review process.

## Research Findings

The detailed, cited evidence for this decision is in
[the gold-set research findings](../research/03-build-initial-relevance-evaluation-gold-set-findings.md).
It supports predeclared stratified sampling, a piloted binary guide, blind
double-labeling and adjudication, grouped deterministic split assignment,
held-out governance, and versioned dataset documentation.

## Acceptance Criteria

- [ ] An eligible candidate export and deterministic, group-disjoint split
  manifest have been frozen before production labels are visible.
- [ ] Annotation guide v0.1 has been piloted and versioned.
- [ ] Every held-out case is independently double-labeled and disagreements
  are adjudicated with evidence retained.
- [ ] `relevance-gold-v0.1` contains only binary expected outputs and exact,
  immutable Evaluation Case revisions with complete provenance.
- [ ] The release data statement, manifest hash, changelog, split counts, and
  reviewer-agreement report are stored with the Gold Set.
- [ ] The held-out split is access-controlled and excluded from all training,
  calibration, few-shot, threshold, prompt, and model-selection work.

## Comments

### 2026-07-10 — Research and protocol completed; human review required

The Gold Set design is complete and ready for the human labeling phase. The
remaining work cannot be automated without violating the requirement that
human-labeled examples are authoritative: two independent reviewers and one
adjudicator must execute the documented binary-review procedure. Once the
manifested cases are authored, this issue can move to completed and unblock the
Relevance Filter evaluation suite.

### 2026-08-04 — Seed population is no longer the blocker; two consumers await the splits

The "Current execution state" section above is stale. It reports 43 cached
records "from the pre-relevance-label schema", with "no relevance
label/provenance columns, and no human labels". The migration it names as
prerequisite work has since run. `document_store.db` now holds:

| Relevance Status | Label source | Rows | With embeddings |
| --- | --- | --- | --- |
| `RELEVANT` | `HUMAN` | 79 | 44 |
| `IRRELEVANT` | `HUMAN` | 13 | 3 |
| `RELEVANT` | `LLM` | 1 | 1 |

That is 92 human-adjudicated labels against a v0.1 target of 200, both classes
present. The remaining blockers are reviewer recruitment and the double-labeling
and adjudication procedure, not schema or seed data. Note these 92 labels were
not produced under the annotation guide this issue specifies, so they are
candidate material for the labeling round rather than promotable labels — the
existing prohibition on promoting an unreviewed label to an authoritative Gold
Set label covers them.

Two code paths are waiting on the split assignments and should be rewired to
read them rather than approximating them from `relevance_label_source`:

- `get_training_rows` in `classifier/src/classifier/trainer.py` currently filters
  to `relevance_label_source = 'LLM'`, which excludes every human label. Against
  the table above that matches one row of one class, so the classifier cannot be
  fitted at all. The `training` split's access rule — "Logistic-regression
  fitting only. May contain human labels" — is what this query should express.
- `get_gold_standard_examples` in `src/knowledge_map/adapters/sqlite_db.py`
  selects three human-labeled rows per class for the Relevance Agent's few-shot
  prompt, with no split awareness. Under the final acceptance criterion here,
  few-shot material must come from `calibration` (or `training`), never from
  `held-out`; as written it can draw a held-out case into the prompt.

Recorded from a review of the Pipeline Stage Ownership branch. See that
project's issue 10 for the reopened acceptance criterion this supersedes.
