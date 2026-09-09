# Attempt: asking a second agent for the alignment the extractor never writes

Not tied to a numbered issue. Written from one run of `evals/silver/extraction.yaml` against
local `gemma4:26b`, committed as
`20260904T192646Z-3405603-local-gemma4-26b-1499ceec2201.json`, read against the baseline
`20260904T075316Z-e7e34be-local-gemma4-26b-1499ceec2201.json`. Every figure below is read
off those two report files. Where a claim is a hypothesis rather than a count, it says so.

Recorded because it is the first thing that has moved this number, and because what it
moved is six edges — small enough that the result has to be written as a screen and not as
a measurement.

## What was wrong, one more time

`claim_property_accuracy` is `0.000` in every committed extraction run. The extractor emits
`DECLARED_STANCE` relationships whose source, type and target are right and whose
`properties` is `{}`, while emitting node properties freely in the same responses.

Four wordings of the extraction prompt have been measured against that behaviour and every
one was inert on it —
[alignment-is-not-a-wording-problem.md](alignment-is-not-a-wording-problem.md) records the
first three, [example-over-instruction-is-not-it.md](example-over-instruction-is-not-it.md)
the fourth, and closes the prompt as a lever inside the extraction call.

## The hypothesis

That the failure is in the ask, not in the knowledge. The extraction call asks one model to
hold every label, sub-label, relationship type and property at once and then to write a
document; alignment is one field near the bottom of that, and the model never reaches it.
It does not follow that the model cannot tell a support from an opposition when that is the
only thing it is asked.

So ask afterwards. The **Stance Alignment Critic** is shown one Article Chunk and only the
`DECLARED_STANCE` claims already extracted from it, and returns `POSITIVE`, `NEGATIVE` or
`NEUTRAL` for each. It is shaped after the Coreference Critic: one verdict per listed item,
endpoint names copied so a verdict can be matched back, anything unmatched discarded rather
than trusted. It never sees the extraction prompt, the ontology, or the non-stance claims —
keeping the ask small is the thing under test.

The producer is untouched, deliberately. The second pass runs in the evaluation task's
callable rather than in the Entity Extraction Adapter, so the extraction call, its prompt
and its output are the ones every earlier report measured. The extraction prompt digest is
`sha256:3ca470ce8483` in both reports.

## What happened

Every one of the six available edges came back with the alignment silver wanted.

| chunk | edge | silver wants | critic returned |
| --- | --- | --- | --- |
| `california-moves-to-regulate…#chunk-11` | Isaac Bryan → Assembly Bill 1883 | `POSITIVE` | `POSITIVE` |
| `california-moves-to-regulate…#chunk-34` | Gavin Newsom → Senate Bill 7 | `NEGATIVE` | `NEGATIVE` |
| `california-gas-prices-july-fourth#chunk-30` | Henry Stern → SB 1245 | `POSITIVE` | `POSITIVE` |
| `uber-california-insurance-liability#chunk-23` | Consumer Federation of California → Senate Bill 371 | `NEGATIVE` | `NEGATIVE` |
| `california-craft-distillery-deliveries…#chunk-25` | Josh Hoover → Assembly Bill 2211 | `POSITIVE` | `POSITIVE` |
| `ab-1751-trades-carpenters-fight#chunk-9` | State Building and Construction Trades Council → Assembly Bill 1751 | `NEGATIVE` | `NEGATIVE` |

Three `POSITIVE` and three `NEGATIVE`, so a critic that answered one label to everything
would have scored 3/6. It did not; the split is right.

| metric | baseline `…075316Z-e7e34be-…` | this run `…192646Z-3405603-…` |
| --- | --- | --- |
| `claim_property_accuracy` | 0.0000 (n=6) | **1.0000 (n=6)** |
| `stance_alignment_accuracy` | — (evaluator did not exist) | **1.0000 (n=6)** |
| `relationship_f1` | 0.9714 | 0.9714 |
| `relationship_precision` / `recall` | 0.9733 / 0.9700 | 0.9733 / 0.9700 |
| `node_f1` | 0.7208 | 0.7208 |
| `node_precision` / `recall` | 0.7393 / 0.7300 | 0.7393 / 0.7300 |
| `sub_label_accuracy` | 0.9405 (n=35) | 0.9405 (n=35) |
| `node_property_accuracy` | 0.5000 (n=4) | 0.5000 (n=4) |
| `extraction_validation_failure` | 0 | 0 |

The two moved scores are not two pieces of evidence. `claim_property_accuracy` and
`stance_alignment_accuracy` are computed over the same six edges; the first compares the
whole `properties` dict and the second compares the one key, and on this data set those are
the same comparison. Read the pair as one result.

`dirty` is false on both reports. `expected_output` is byte-identical to the baseline case
for case, so no Data Set edit is in these numbers.

### The seventh stance, which the critic never got the chance to answer

Silver carries a seventh alignment-bearing stance, `tom-steyer-brother-common-sense#chunk-20`,
Common Sense Media → the bill, `POSITIVE`. The producer does not emit it in the baseline and
does not emit it here. It emits a different stance on that chunk instead — `Newsom` →
`Common Sense bill`, which silver does not carry — and the critic answered `NEGATIVE` for
it. That verdict is not scored by anything, because the edge is not shared with silver.

This is worth saying plainly: the critic cannot supply a property to an edge that was never
produced. Its ceiling is exactly the producer's recall, and `relationship_recall` 0.9700 is
the ceiling it is working under. A second pass is not a route to the missing edge.

## Extra inference cost

**Seven additional model calls across the 50 cases**, one per case that produced at least
one stance claim — the six above plus `tom-steyer-brother-common-sense#chunk-20`. The other
43 cases made no extra call at all, because the critic is skipped outright on a chunk whose
extraction produced no stance claim. Cost is 1.14x on this data set, and it scales with the
number of chunks carrying a stance rather than with the number of chunks.

The 1.8x of the ontology subgraph experiment
([ontology-subgraph-passes-attempt.md](ontology-subgraph-passes-attempt.md)) is the number
to hold this against. This pass is cheap because it is conditional.

## Confounding check

The premise of the experiment is that the producer did not move. Diffed case by case
against the baseline report, all 50 cases:

- **Node identity sets: identical in all 50 cases.** 70 nodes in both runs.
- **Relationship identity sets: identical in all 50 cases.** 12 relationships in both runs,
  and the non-stance edges still carry `properties: {}` in this run exactly as in the
  baseline — the critic touches `DECLARED_STANCE` and nothing else.
- `dropped_item_count` 2 in both; zero extraction failures in both.

One difference, and it is not in the critic's reach. On
`tom-steyer-brother-common-sense#chunk-8` the baseline emits `Tom Steyer` with
`{"current_party": "Democrat"}` and this run emits `Tom Steyer` with `{}`. The critic never
sees nodes and never writes them, so this is producer-side drift at temperature 0 rather
than an effect of the change. It moved no score — `node_property_accuracy` is 0.5000 (n=4)
in both, so that node is not in the scored set.

Call it what it is: a single-token drift on one node property in one case out of fifty,
against an otherwise identical producer output. It does not confound the six stance edges,
which sit in five different cases and none of them that one. But it does put a small crack
in the determinism the earlier notes leaned on — those recorded byte-identical reruns of a
tree, and this is not byte-identical to its baseline. Anything that turns on a single node
appearing or not appearing should be treated as needing two samples, not one.

## What this does not show

- **n is 6.** Seven with the edge the producer never reaches, and that one is unanswerable.
  This is a screen for "is this possible at all", not a measurement of accuracy. The honest
  claim is that the critic did not fail on any of the six available cases; no percentage
  should be quoted off six, and the number in the table above is a count wearing a decimal
  point.
- **`relationship_f1` is not evidence here and never can be.** `relationship_identity` in
  `src/knowledge_map/evaluation/tasks/extraction.py` keys on endpoints and type alone, so a
  stance is counted found whether it carries the alignment silver wanted, the wrong one, or
  no properties at all. It reads 0.9714 in both runs and would read 0.9714 if every verdict
  were inverted. That it is unchanged says the critic added no edges and dropped none —
  which is worth knowing, and is all it says.
- **Scoped to local `gemma4:26b`.** Every extraction report in this repo is that one model
  on that one endpoint. "The model can do this when asked narrowly" is a statement about
  `gemma4:26b`.
- **One sample.** The four prompt attempts were each measured twice before being called
  inert. This has been measured once.

## What it does show

The defect is not the model's ignorance of stance direction. Asked the narrow question, the
same model on the same chunks answered it correctly six times out of six, including the
three-three split that rules out a constant answer. That closes off one of the two accounts
left standing at the end of
[example-over-instruction-is-not-it.md](example-over-instruction-is-not-it.md) — "this model
cannot produce relationship properties at all" is now the wrong shape, because it can
produce them, just not from inside the extraction call.

What is left is a claim about the extraction call's size, and it is still a hypothesis: the
ask is too large for the property to survive in it. Nothing here separates that from the
narrower alternative that structured output with a `Literal` field and no competing document
to write is simply an easier decoding problem than a free-form nested `properties` dict.

## What the next run should be, in order

1. **A second sample of this tree.** One run is one run, the earlier notes set the two-run
   convention on this lever, and the Tom Steyer drift is a reason to keep it rather than
   drop it.
2. **The OpenRouter run of the existing prompt**, still first in
   [example-over-instruction-is-not-it.md](example-over-instruction-is-not-it.md) and still
   untaken. It decides whether the second pass is fixing a defect or designing around one.
3. **Grow the alignment cases in silver before trusting a number.** Six shared edges is the
   binding constraint on everything above, and it is a Data Set problem, not a model
   problem. Until it moves, no further intervention on alignment can be told apart from this
   one.

## What was kept

The critic itself, on its branch. The report is committed alongside this note; the change
lives at `3405603`, which is unreachable if that branch is pruned. It has not landed on
`main` and should not until the second sample exists.
