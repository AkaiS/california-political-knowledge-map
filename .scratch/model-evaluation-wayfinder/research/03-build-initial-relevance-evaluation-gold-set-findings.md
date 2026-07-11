# Findings: Initial Relevance Evaluation Gold Set

Research supporting issue [03](../issues/03-build-initial-relevance-evaluation-gold-set.md). Sources are primary research papers or first-party technical guidance.

## Recommended v0.1 protocol

1. **Define the evaluation population and sample before labeling.** Draw from the actual post-extraction candidate-article population, stratifying by publication, publication section/category where available, collection period, and a pre-labeling difficulty proxy (for example, current model/LLM disagreement or score band). Preserve the intended positive/negative rate in the held-out test set where feasible; oversample rare or high-risk strata only for diagnostic coverage, then report per-stratum counts and a prevalence-weighted aggregate. Stratification preserves class proportions, while `StratifiedGroupKFold` combines that objective with non-overlapping groups. [scikit-learn cross-validation guide](https://scikit-learn.org/stable/modules/cross_validation.html), [StratifiedGroupKFold API](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html)

2. **Write and pilot a binary annotation guide.** Define `RELEVANT` and `IRRELEVANT` using the product's California-politics purpose, include positive and negative boundary examples, and require the annotator to capture the shortest supporting text/rationale. Pilot the guide, revise it before the release round, and record its revision. Data statements and datasheets specifically call for documenting collection, composition, recommended uses, and the labeling process. [Bender & Friedman (2018)](https://aclanthology.org/Q18-1041/), [Gebru et al., *Datasheets for Datasets*](https://arxiv.org/abs/1803.09010)

3. **Double-label and adjudicate all held-out cases.** Two annotators independently and blindly label each selected test case. Accept matching labels; send disagreement to a named adjudicator, who records the decision and guide issue. Retain both initial labels, the final label, evidence/rationale, disagreement status, and adjudication record. Publish raw agreement, disagreement rate, a binary confusion matrix, and a chance-corrected agreement coefficient; agreement is a measure of annotation reliability, and a documented decision-point adjudication process identifies and corrects discrepancies. [Artstein & Poesio (2008)](https://aclanthology.org/J08-4004/), [LDC adjudication model](https://aclanthology.org/L06-1332/)

4. **Prevent leakage before creating the split.** Derive a stable `group_id` for each item from the canonical story/article; put exact duplicates, canonical/redirect URL variants, syndicated copies, and near-duplicate text in the same group. If publication series or time windows make items materially dependent, group by that relation too. Make one deterministic, group-disjoint dev/test assignment from the frozen candidate list, recording the algorithm, seed, group-key version, and resulting item IDs. scikit-learn documents that grouping prevents the same group from appearing in multiple folds, and that its stratified-group splitter attempts both class preservation and group disjointness. [scikit-learn splitter comparison](https://scikit-learn.org/stable/auto_examples/model_selection/plot_cv_indices.html), [StratifiedGroupKFold API](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html)

5. **Make the held-out test split evaluation-only.** Do not use its text, labels, error cases, or item-level results to choose prompts, few-shot examples, thresholds, features, or model versions. Iterate on the dev split; run held-out tests only at defined comparison/release checkpoints and retain aggregate reports. Repeated adaptive access can invalidate ordinary holdout inference; when the test set becomes routinely inspected to guide changes, retire it and establish a new released test version. [Dwork et al. (2015)](https://arxiv.org/abs/1506.02629), [NIST AI RMF: Measure](https://airc.nist.gov/airmf-resources/playbook/measure/)

## Gold-set release contract

Release `relevance-gold-v0.1` as an immutable manifest plus controlled item artifacts. Each item should include: opaque item ID; source URL and publication ID; retrieval timestamp; content/metadata hashes and text-representation version; sampling strata; group ID; split; annotation-guide revision; each initial label and evidence; adjudicated label/rationale; and access/redaction status. The release-level data statement should also identify the candidate population, inclusion/exclusion and sampling procedure, annotator roles/training, known gaps, intended use, and prohibited use. This provenance makes the evaluation repeatable and allows a future release to be compared without mutating v0.1. [Bender & Friedman (2018)](https://aclanthology.org/Q18-1041/), [Gebru et al.](https://arxiv.org/abs/1803.09010), [NIST AI RMF: Manage](https://airc.nist.gov/airmf-resources/playbook/manage/)

Govern change through a named gold-set steward: no in-place corrections; every approved addition, removal, redaction, or adjudication correction produces a new semantic version, manifest hash, and changelog that identifies the old and new item state. Keep test item artifacts and labels access-controlled; expose only the aggregate release report and reviewed failure taxonomy. NIST calls for documenting test sets, metrics, methods, processes, and materials so measurement is repeatable and consistent. [NIST AI RMF: Measure](https://airc.nist.gov/airmf-resources/playbook/measure/)

## Decision-ready acceptance criteria

`v0.1` is ready to support a relevance-filter comparison when it has:

- a manifest-locked, human-only, double-labeled and adjudicated evaluation split;
- class, provenance, and sampling-stratum counts plus annotation-agreement results;
- no overlap with development or few-shot/training examples by exact duplicate, near-duplicate, or defined origin group;
- an immutable data statement, annotation guide, split specification/seed, content hashes, and changelog; and
- a documented owner and release-only test-access rule.

