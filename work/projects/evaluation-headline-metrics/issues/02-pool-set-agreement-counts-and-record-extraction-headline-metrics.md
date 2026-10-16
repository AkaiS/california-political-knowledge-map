# 02: Pool set-agreement counts and record Extraction Headline Metrics

**What to build:** A completed Extraction run records pooled and per-case
agreement on nodes and relationships. Its pooled F1 then rests on raw matched,
expected and found counts rather than on averaged ratios.

First, as a prefactor, the set-agreement scoring helpers gain a count form
beside the existing ratio form. Case evaluators and headline report evaluators
use the same identity functions, so a pooled count and a case score always
agree on what matched. Per-case score names stay the same.

**Blocked by:** 01, Record Headline Metrics end to end for Relevance.

Labels: ready-for-agent

- [ ] The set-agreement helpers expose matched, expected and found counts
  through the same identity functions the case evaluators use. Existing
  per-case scores are unchanged.
- [ ] Extraction declares `extraction-v1`. Its primary row is pooled node F1.
- [ ] Extraction's headline rows are:
  - node precision and recall;
  - pooled relationship precision, recall and F1;
  - node F1 and relationship F1 as per-case means;
  - ontology conformance rate;
  - `execution_failure_rate`.
- [ ] Each pooled row carries its numerator and denominator.
- [ ] Sub-label, node-property, claim-property and stance-alignment accuracy
  are diagnostic rows.
- [ ] A case where both sides are empty keeps its documented per-case pass and
  adds zero to every pooled count.
- [ ] Engine-run tests cover a both-empty case, a failed case, and a population
  where pooled and per-case F1 disagree.
