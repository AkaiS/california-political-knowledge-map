# Staged Jev query-construction experiment

This preserves the implementation tested on October 6, 2026. It removes the
wording-example sentence about entities "alongside" one another from both peer
fragment descriptions. It replaces the reporting keyword gate with one Jev Noul
for successful selections that contain no semantic relationship or role-plan edge.
Negative, missing, invalid, and failed gate decisions forbid reporting execution.

Jev narrows the schema and performs staged role selection, Organization subtype
refinement, and property selection. Code prunes the fragments deterministically.
A local model composes and binds the selected structure. The deterministic compiler
hydrates reporting context; CyVer validates the query before read-only Neo4j
execution. Production retrieval and dependencies are unchanged.

## Frozen settings and results

Schema probabilities were captured once and replayed at .7 and .8. Every
downstream call was fresh. Structural, property, and reporting-intent cutoffs
were .52; subtype refinement required a winning-option probability of .8.
The launcher below defaults to schema .8 and makes fresh schema calls. These
saved scores describe the frozen implementation, before the review repairs below.

| Set | Schema cutoff | Semantic exact /25 | Evidence exact /25 | Evidence F1 | Evidence precision | Evidence recall | Required schema retained | Conditional availability |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Dev | .7 | 23 | 24 | 99.92% | 100.00% | 99.85% | 121/121 | 121/121 |
| Dev | .8 | 24 | 24 | 99.92% | 100.00% | 99.85% | 121/121 | 121/121 |
| Held-out | .7 | 12 | 13 | 74.81% | 93.33% | 62.42% | 135/135 | 129/135 |
| Held-out | .8 | 14 | 15 | 80.94% | 94.09% | 71.02% | 134/135 | 129/135 |

Required schema retention measures needed labels, predicates, and properties
after narrowing. Conditional availability measures them after structural
selection and subtype refinement, before property thresholding. It does not
measure correct role attachment. Precision, recall, and F1 pool evidence across
cases; exactness counts cases whose complete sets match.

The October 2 unchanged .8 control had 24 semantic and 24 evidence exact matches
on dev, with 99.92% evidence F1. On held-out it had 13 semantic and 12 evidence
exact matches, 75.80% F1, and 64.33% recall. Earlier unchanged held-out runs
varied by one semantic match and two evidence matches. These are single runs,
and the control is historical. There is no matched .7 control or repeatability
estimate. The combined .8 result supports further evaluation, not a production
promotion or a claim that the two improvements add independently.

| Set | Cutoff | Executed / nonempty | Abstentions | Requests | Tokens | Batch seconds |
|---|---:|---:|---:|---:|---:|---:|
| Dev | .7 | 24 / 24 | 0 | 120 | 209,288 | 174.15 |
| Dev | .8 | 24 / 24 | 0 | 119 | 208,247 | 163.98 |
| Held-out | .7 | 18 / 15 | 1 | 109 | 271,977 | 200.27 |
| Held-out | .8 | 18 / 16 | 1 | 115 | 259,299 | 210.41 |

These costs exclude replayed schema calls and queue wait. Runs were serialized.
Local-model timings vary, so differences are not isolated ablation costs.
[evaluation.json](evaluation.json) preserves the aggregate scores, per-stage
costs, and source-report hashes. Held-out questions, gold, traces, and individual
failures are excluded from this PR and were not reviewed for this experiment.

## Restore and verify

The previous prototype lives at Git commit
`104d626000ba189b1beafe306a186f167ff98e4a`. `bootstrap.py` restores its `src`
and development references, then overlays the exact frozen implementation files
in [source-manifest.json](source-manifest.json). It applies the separate
[runtime-v2.patch](runtime-v2.patch) and verifies every active source and prompt
against [runtime-v2-manifest.json](runtime-v2-manifest.json). The result lives in
`.scratch/jev-staged-runtime-v2`; an existing historical runtime is preserved.
The bootstrap never changes the checkout or production modules. A shallow clone
must fetch that historical commit before restoration.

The review repairs move authored prompt text into immutable, explicitly versioned
resources under `src/knowledge_map/resources/prompts/jev-staged`. Synthetic rendering
comparisons verify that the text sent to models is unchanged. Compiler-owned Article
selections now use the staged selector's validated occurrence indices, allowing two
same-label topic roles to remain distinct and keep their own filter attachments.
Invalid attachments still stop execution. This wiring repair changes behavior and
has not been rerun on dev or held-out evaluations; the tables above remain historical.

Default `uv run pytest` discovery is restricted to the production `tests` directory.
The experimental suite must be selected explicitly, so its restored imports and
optional dependencies cannot affect the production suite.

From the repository root, run:

```sh
experiment=work/initiatives/useful-graph-retrieval/query-construction/experiments/jev-staged
uv run python "$experiment/bootstrap.py"
uv run --with typesafe-sdk==0.7.2 --with cyver==2.0.2 python "$experiment/validate.py"
uv run --with typesafe-sdk==0.7.2 --with cyver==2.0.2 pytest -q "$experiment/tests"
```

The offline checks use synthetic inputs. They cover personhood, schema closure,
subtype abstention, parent-role distinctness, property attachment, deterministic
hydration, unchanged fragment shapes, and the reporting gate's failure behavior.
They also cover repeated Article-topic roles, rejected invalid wiring, binding and
execution with synthetic service stubs, and exact prompt rendering against the
frozen sources. They make no hosted-model, local-model, or graph calls. The frozen
source files remain byte-for-byte unchanged. The separately recorded repairs do not
inspect held-out questions, gold, traces, or individual failures.

## Run against the development graph

Configure the repository's `.env` for its local model and Neo4j. Set
`TYPESAFE_API_KEY` or use the existing Keychain entry, service `jev_api`, account
`test_key`. Then run:

```sh
uv run --with typesafe-sdk==0.7.2 --with cyver==2.0.2 python "$experiment/run.py"
uv run --with typesafe-sdk==0.7.2 --with cyver==2.0.2 python "$experiment/run.py" --schema-threshold .7
```

This sends the development questions and schema/fragment descriptions to Jev,
calls the configured local model, and reads Neo4j. Reports and events stay in
`.scratch/jev-staged-runtime-v2/results`. CLI overrides such as `--case`, `--output`,
and `--raw-events` pass through to the original runner. A fresh graph or model
version can change results. Reference scoring happens after the execution batch.
Protected held-out inputs and saved schema probabilities remain local; this
launcher does not publish them or claim to reproduce the four saved runs exactly.
