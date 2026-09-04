# Attempt: reading one chunk once per ontology subgraph

Not tied to a numbered issue. Written from two runs of `evals/silver/extraction.yaml`
against local `gemma4:26b`, both committed: the baseline (`0997321`) and one run of the
changed tree (`8567ee5`). Every figure below is read off those report files. Where a
claim is a hypothesis rather than a count, it says so.

Recorded because the result is inconclusive rather than negative, and an inconclusive
result at 1.8x inference cost is worth writing down before anyone spends the runs again.

## The hypothesis

The model emits under half the silver nodes — 38 against 80 in the baseline. One
explanation is size: a single prompt asks `gemma4:26b` to hold every label, sub-label,
relationship type and property at once. If that is the cause, reading the same chunk
several times under smaller, focused ontology blocks and unioning the answers should
raise recall without costing precision.

## What was tried

The extractable ontology was split into the two components its own edges fall into, and
each chunk read once per component.

**`legislative-record`** — the machinery of lawmaking. Labels `Politician`, `Committee`,
`Bill`, `LegislativeEvent`; types `SERVES_ON`, `CHAIRS`, `VICE_CHAIRS`, `VOTED_AYE`,
`VOTED_NO`, `ABSTAINED`, `ACTION_ON`, `HELD_BY`, `REFERRED_TO`.

**`political-contest`** — who is for or against what, and who is paying. Labels
`Politician`, `Organization`, `Campaign`, `Prop`, `Bill`; types `CAMPAIGN_FOR`, `FUNDED`,
`LOBBIED_FOR`, `LOBBIED_AGAINST`, `ENDORSED`, `DENOUNCED`, `DECLARED_STANCE`.

The split is a property of the ontology, not a convenience. Every extractable
relationship type has both its source and target label sets wholly inside exactly one
component, so **no claim straddles a pass and no pass is asked for an endpoint it was not
shown**. `assert_subgraphs_partition_the_ontology()` enforces three invariants at import:
every extractable label is asked for somewhere, every extractable type is owned by
exactly one subgraph, and a type's endpoint labels are all present in its owner.
`Politician` and `Bill` appear in both passes because they are what the record acts on
and what the contest fights over; the union merges them.

A people-vs-organizations split was considered and rejected: `DECLARED_STANCE` and
`ENDORSED` straddle it.

Mechanically:

- `load_instructions(subgraph)` renders one slice into the prompt. Only the closed
  ontology block varies — the naming and judging rules above it are how to read a passage
  rather than what to look for, so every pass sees the same ones and the block is the
  single variable. With no argument it returns every pass's prompt joined, so the report's
  prompt digest changes when the passes change.
- `extract_entities` loops the subgraphs, using `agent.override(instructions=...)` so a
  caller's agent — its model, retries and hooks — stays the one thing configured.
- `union_extraction_results` merges nodes on `(case-and-space-folded name, label)` and
  relationships on `(folded source, type, folded target)`. First pass wins; a later pass
  fills only what the earlier left empty. Folding stops at case and spacing on purpose:
  anything cleverer is Entity Resolution, which runs later against an authoritative
  record, and a pass that writes `Newsom` where another wrote `Gavin Newsom` has named two
  entities.
- The union is taken **before** conformance. Nothing should need it, since no type
  straddles a pass, but a stray cross-pass edge then survives instead of being dropped as
  dangling.

The evaluator was not touched, so the run stays comparable to the baseline. Two tests in
`tests/test_extraction.py` were adjusted for the changed call count; no behavioural
assertion was weakened. Suite green at 906 passed.

## What happened

| metric | baseline `0997321` | `8567ee5` | delta |
| --- | --- | --- | --- |
| `node_f1` | 0.4975 | 0.5271 | +0.0296 |
| `node_precision` | 0.5333 | 0.5776 | +0.0443 |
| `node_recall` | 0.4803 | 0.5100 | +0.0297 |
| `relationship_f1` | 0.9533 | 0.9360 | −0.0173 |
| `sub_label_accuracy` | 0.9621 (n=22) | 0.9267 (n=25) | −0.0354 |
| `claim_property_accuracy` | 0.000 (n=5) | 0.000 (n=5) | 0.000 |
| `extraction_validation_failure` | 0 | 0 | 0 |
| nodes emitted | 38 | 50 | +12 |
| relationships emitted | 9 | 15 | +6 |

`dirty` is false on both. `expected_output` and `inputs` are byte-identical to the
baseline case for case, so no Data Set edit is in these numbers.

The cross-subgraph worry never materialised: **zero validation failures**, same as
baseline.

Cost:

| | baseline | `8567ee5` | ratio |
| --- | --- | --- | --- |
| requests | 50 | 100 | 2.00x |
| input tokens | 106,338 | 180,626 | 1.70x |
| output tokens | 3,494 | 6,437 | 1.84x |
| summed per-case `task_duration` | 86.7 s | 156.2 s | 1.80x |

## The twelve extra nodes, read one by one

Net +12 is thirteen nodes gained and one lost. Against silver, seven of the thirteen are
exact hits: `Senate Bill 371`, `Antonio Villaraigosa` and its campaign, `Teamsters`,
`UPS`, `Carl DeMaio`, `Cal State Board of Trustees`. Six are not in silver, and they are
not one thing:

- **`Steyer` (`Politician`) and `Steyer campaign` (`Campaign`)**, in
  `california-governor-race-katie-porter#chunk-25`. The passage says "jointly endorsed
  Porter, Steyer and former Los Angeles Mayor Antonio Villaraigosa". Genuine extras: the
  prompt already says a bare surname is never enough to name a person, and silver is
  consistent in taking the two people the passage names in full. Model error.
- **`Carl DeMaio campaign` (`Campaign`)**, in
  `california-legislature-maverick-lawmakers#chunk-19`. The chunk contains no
  endorsement. The `Campaign` node exists only because the prompt's
  `ENDORSED`-cannot-point-at-a-`Politician` rule minted one, and that rule lives in the
  invariant prose, so it fires in both passes. Genuine extra, and traceable to prose
  rather than to the ontology block.
- **`Gavin Newsom` (`Politician`)**, in `tom-steyer-brother-common-sense#chunk-20`:
  "Last fall, Newsom vetoed a Common Sense bill". **This looks like a silver miss, not a
  model error.** The prompt says outright that a governor vetoing a bill is
  `DECLARED_STANCE` `NEGATIVE`, which requires the governor as a node; silver records the
  `Vote` on that bill and not the person who vetoed it. Against it: the passage says
  "Newsom", and the model wrote "Gavin Newsom", which is the same surname expansion
  charged against `Steyer` above. Both readings want the annotation guidance to say which
  wins.
- **`Common Sense bill` and `Common Sense Media bill` (`Bill`)**, same chunk. Silver
  carries one node, `Common Sense Media bill banning AI chatbots for minors`. The passage
  names a measure twice, once as "a Common Sense bill" and once as "the Common Sense
  Media bill banning AI chatbots for minors". Under the prompt's own instruction — a
  Bill's name is the passage's own surface string, verbatim — the first is defensible and
  the second is a truncation of silver's. These are surface-form disagreements about where
  a name ends, not invented entities, and scoring them as extras overstates the precision
  cost.

So of six apparent extras: three are real (two of them one bare-surname rule already in
the prompt), one is a probable silver correction, and two are a naming-boundary question.

The one loss is `California Department of Industrial Relations` in
`ab-1751-trades-carpenters-fight#chunk-22` — a claimless agency in a chunk with no claim,
most likely narrowed out by the `political-contest` focus sentence. That node is emitted
in both baseline runs and lost by three separate changes that each narrow the prompt
toward claims, so the loss is the change rather than the draw. The
`sub_label_accuracy` dip is partly the same story from the other side:
`Cal State Board of Trustees` arrived carrying `GovernmentAgency` where silver, since
[ADR 0021](../../../../docs/adr/0021-a-campus-is-an-educational-institution-not-a-government-agency.md), says
`EducationalInstitution`.

## Why this is inconclusive rather than positive

Three reasons, in order of weight:

1. **The effect is small, and only one run of this tree was taken.** +0.030 node_f1. The
   noise objection is half answered: the baseline tree was run a second time at `e11a8b8`
   under the same prompt digest and reproduced `0997321` byte for byte, so the
   temperature-0 flakiness recorded on the `bbaa22b` tree does not reproduce here and
   +0.030 is unlikely to be draw. What is still missing is a second run of *this* tree,
   which every other experiment this session took and this one did not.
2. **The hypothesis was not really tested.** The full ontology block is 3,074 characters;
   the slices are 1,476 and 2,828. `political-contest` alone is 92% of the block, because
   the twelve `Organization` sub-labels and the stance and funding property lines all land
   in one pass. So this measured "fewer labels and edge types at once", not "a shorter
   block".
3. **There is no two-pass control.** Reading the chunk twice under the *same* prompt and
   unioning would separate the split from the mere second look. It was not run.

Five of the forty systematic misses were recovered. The three groups the handoff calls
ontology or silver decisions — press in attribution, federal bodies, universities — did
not move by a single node, which is consistent with those being decisions rather than
capacity problems.

## What the next attempt should do

Re-measure after the claimless-entity change lands. That change recovers 21 silver nodes
on its own at 1x cost, and its recovered set overlaps this one's, so the marginal value of
subgraph passes is currently unmeasured. Whatever remains after it is the honest question
this experiment should be asked again.

Two things are worth keeping regardless of that:

- **The partition is a real ontology fact.** That the extractable relationship set falls
  into two components with no straddling type is true of the ontology whether or not
  anything reads it in two passes, and it wants a line in the domain docs.
- **The extras trace to prose, not to the ontology block.** Trimming the
  `ENDORSED`/`Campaign` rule is a 1x-cost experiment that this run motivates.

## Retired: rerun against the claimless-entity baseline

Added after the fact. The measurement above compares `8567ee5` to baseline `0997321`,
a tree that no longer exists: PR #19 (`d3f43fc`) put the claimless-entity rule in the
extraction prompt, and `main`'s baseline moved to node_f1 **0.7208**
(`20260904T075316Z-e7e34be-…json`). The branch was rebased onto that baseline's tree and
rerun on the same local `gemma4:26b` deployment, one run, report
`20260904T181210Z-573a681-local-gemma4-26b-1499ceec2201.json`. Both trees are cited by
report filename because the rerun's branch is local-only.

| metric | baseline `…075316Z-e7e34be…` | subgraph `…181210Z-573a681…` |
| --- | --- | --- |
| node_f1 | 0.7208 | **0.6475** |
| node_recall | 0.7300 | 0.6450 |
| node_precision | 0.7393 | 0.6808 |
| relationship_f1 | 0.9714 | 0.9545 |
| sub_label_accuracy | 0.9405 (n=35) | 0.9427 (n=32) |
| claim_property_accuracy | 0.0000 (n=6) | 0.0000 (n=6) |

**The direction reversed.** Against the old baseline the split measured +0.030 node_f1
at 1.8x inference; against the current one it measures **−0.073 at 2x inference**. It is
not an inconclusive result any more. It is a regression, and the +0.030 was the split
recovering nodes the prompt rule now recovers for free — while the split's own cost,
previously hidden under that gain, is what remains.

Seven cases move and every one of them moves down or sideways. Six silver nodes are lost,
all `Organization`, and all of the claimless kind — named in the chunk, connected to
nothing:

- `Uber`, `Consumer Watchdog`, `CalMatters` on `uber-california-insurance#chunk-10`
- `UC Berkeley` on `california-gas-prices-july#chunk-9`
- `San Jose State` on `california-campus-police#chunk-32`
- `Digital Democracy` on `california-legislature-mapping#chunk-8`
- `Cognixion` on `california-moves-to-regulate#chunk-24`

The precision loss is the same mechanism seen from the other side: the pass shown the
`political-contest` component invents a campaign to put in it, adding `Porter campaign`
and `Carl DeMaio campaign` as extras on two chunks where silver has none.

**This is the fourth experiment supporting the open hypothesis, and the first with a
mechanism.** `f4addf2`, `8567ee5` and `b69ea54` each lost claimless nodes after a prompt
narrowed toward claims; here the narrowing is structural rather than verbal — each pass
is literally shown a claim-shaped fragment of the ontology and nothing else — and the
loss is larger and concentrated in exactly that class. A pass that cannot see why an
entity would matter does not name it, and a pass handed a relationship vocabulary with
no matching claim in the chunk fills it anyway. The hypothesis now has a reading:
**narrowing the ontology block trades claimless recall for claim-shaped invention, in
both directions at once.**

Retire the subgraph split. Its measured value against the current tree is negative on
every detection metric at twice the inference, and its original gain has been absorbed
by a one-line prompt rule.
