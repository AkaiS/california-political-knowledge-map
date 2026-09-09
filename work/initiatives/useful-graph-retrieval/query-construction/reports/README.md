# Query-construction experiment archive

This archive preserves the committed reports, assessments, and input snapshots
from three throwaway prototypes. Files beneath the three prototype directories
are unchanged copies of their source Git blobs. [manifest.json](manifest.json)
records each original path, full commit, blob id, SHA-256, and size.

## Read the results

| Experiment | Assessment | Raw evidence |
| --- | --- | --- |
| Generated Cypher, original 42 questions | [Original comparison](../../prototype-comparison.md) | [Baseline report](generated-cypher/results/generated-cypher-report.json) |
| Generated Cypher, verified 25 questions | [Corrected analysis](generated-cypher/results/generated-cypher-verified-analysis.md) | [Frozen report](generated-cypher/results/generated-cypher-verified-report.json) |
| Typed queries, original 42 questions | [Original comparison](../../prototype-comparison.md) | [Original failures](typed-retrieval/observed-report.raw.json), [recovered selections and graph replay](typed-retrieval/observed-report.json), [post-fix smoke](typed-retrieval/smoke-report.json) |
| Typed queries, verified 25 questions | [Assessment](typed-retrieval/verified-question-assessment.md) | [Frozen report](typed-retrieval/verified-question-report.json) |
| Composable triples, three 25-question arms | [Findings](composable-triples/findings.md) | [Frozen report](composable-triples/results/full-report.json), [compiler-only replay](composable-triples/results/duplicate-projection-replay.json), [prechange interface smoke](composable-triples/results/interface-smoke.json) |

The [verified-question comparison](../comparison.md) and
[composable-triples comparison](../composable-triples-comparison.md) distinguish
execution outcomes from complete retrievals. Read their corrections before
using a raw summary field as a score. In particular, the generated report
combines validation stops with empty results, the typed report loses some
budget-triggering response bodies, and the triples results include a separate
compiler-only replay. None is a formal Gold Set.

## Implementation provenance

| Prototype | Preserved commit | Annotated tag |
| --- | --- | --- |
| Generated Cypher | `ecc99466b6c1de0a65795af2b685f00114e8a94f` | `experiments/query-construction/generated-cypher-2026-09-08` |
| Typed retrieval | `8f975fc456bf3824bf018a34033e8dc0c89fb16b` | `experiments/query-construction/typed-retrieval-2026-09-08` |
| Composable triples | `2da6872086fefaadd2cc073915a917dab5625fb7` | `experiments/query-construction/composable-triples-2026-09-08` |

The tags retain the prototype implementations and their ancestor commits.
The original generated baseline used `6633c18`, the typed baseline used
`2509811`, and the generated verified batch was captured in `5cce14a` before
the documentation correction in `ecc9946`. The triples commit contains the
projection correction; its frozen report records the pre-correction run.

To reproduce an implementation, create a worktree at its tag or commit, run
`scripts/setup-worktree.sh`, then follow the prototype's README there. Use a
fresh report output path. The archived README files retain their original run
context; commands requiring prototype code do not run from this archive.
Recorded temporary paths inside snapshots are historical metadata, not required
locations for a new checkout.

The reusable reference cases and read-only verifier are [one directory up](../README.md).
The [next-experiment plan](../next-experiment.md) carries forward unresolved
pattern-selection and entity-binding work. No retrieval architecture was
selected by archiving these results.
