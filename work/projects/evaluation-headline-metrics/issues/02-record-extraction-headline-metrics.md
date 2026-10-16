# 02: Record Extraction Headline Metrics

**What to build:** A completed Extraction run records pooled and per-case
agreement on nodes and relationships, with pooled F1 resting on raw counts.
This ticket adds the headline module's `CaseMean` measure. `CaseMean` reads
recorded case scores and assertions; it never recomputes them.

**Blocked by:** 01, Record Headline Metrics end to end for Relevance.

Labels: ready-for-agent

- [ ] Extraction declares `extraction-v1`. Its primary row is pooled node F1.
- [ ] The headline rows are:
  - node precision and recall;
  - pooled relationship precision, recall and F1;
  - node F1 and relationship F1 as per-case means of the recorded scores;
  - ontology conformance, read from the recorded `StayedInsideTheNewsOntology`
    assertion;
  - the automatic `execution_failure_rate`.
- [ ] The diagnostic rows are sub-label, node-property, claim-property and
  stance-alignment accuracy, as `CaseMean` rows.
- [ ] Node and relationship counts use the identity functions the case
  evaluators use, through `detection_counts`.
- [ ] A case where both sides are empty adds zero to every pooled count. Its
  recorded per-case pass still feeds the per-case mean.
- [ ] Engine-run tests cover a both-empty case, a failed case, and a
  population where pooled and per-case F1 disagree.
- [ ] Depth rule, tasks declare: every task touched supplies only a
  `HeadlineDefinition` built from the closed measure set and functions over a
  single case. No task defines a `ReportEvaluator`, builds table rows, or
  computes a population or failure rate.
- [ ] Depth rule, readers call: only the run report module classifies reports,
  accounts for the population, compares or renders. The summary script and
  the RAG reviewer gain none of that logic, and nothing outside the headline
  and run report modules parses table rows.
- [ ] Depth rule, two seams: tests cross only the engine-run seam and the
  summary script's entry point. No test imports a measure's internals or adds
  a module-level test seam.
