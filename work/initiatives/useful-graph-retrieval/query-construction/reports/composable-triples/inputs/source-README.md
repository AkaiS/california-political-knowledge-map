# Questions grounded in the populated graph

Use these questions for the next [query-construction experiment](../issues/05-prototype-query-construction-and-validation.md). All 25 have an executed reference query with nonempty results and resolvable Grounding Evidence, checked on 2026-09-08 against the local graph of 98 NewsArticles and 2,407 Chunks.

The questions preserve all eleven families in the [target question set](../question-set.md), plus its later committee category. They make the subjects, session, and reporting scope concrete. The original target set still records the broader product ambitions and its Declined and Deferred examples. Those examples do not belong in this positive construction batch.

- [cases.yaml](cases.yaml) is the authored input: question, family, scope, reference Cypher, and parameters.
- [verified-results.json](verified-results.json) contains the reference results, their evidence groups, and all 533 distinct supporting Chunks with source article metadata. Its hash identifies the case file that was executed.
- [verify.py](verify.py) rechecks the references against the live graph. It uses read-only queries, checks Neo4j's query classification, and fails on empty results or unresolved evidence. A successful check establishes retrievability, not independent truth of the extraction.

These are construction examples with observed reference outputs. They are not a
formal Evaluation Gold Set.

Follow-up on 2026-09-08: both prototypes have now run against all 25 questions.
See the [new construction comparison](comparison.md) for the frozen runs,
semantic audit, costs, and interpretation limits. The earlier reference
verification remains preserved alongside the fresh recheck.

## Preserved categories and concrete subjects

| Family | Cases | Subjects and expected reference results |
| --- | --- | --- |
| E1: Entity dossier | C-E1-01, C-E1-02 | Steve Hilton, two reporting chunks; Gail Pellerin, one. |
| E2: Measure lookup | C-E2-01, C-E2-02 | SB 9 in session 2025-2026, 19 chunks; Proposition 38, 20. |
| E3: Policy area sweep | C-E3-01 through C-E3-03 | July 2026 housing, nine articles; July labor, six; article counts across all 26 populated Policy Areas. |
| R1: Stated position | C-R1-01, C-R1-02 | California Nurses Association's recorded position on AB 1018; Reform California's endorsement of the Steve Hilton campaign. |
| R2: Lobbying | C-R2-01, C-R2-02 | Four organizations recorded for AB 186; California Chamber of Commerce and Lyft recorded against SB 947. |
| R3: Campaign funding | C-R3-01, C-R3-02 | Michelson Center For Public Policy and the Yes on Proposition 38 campaign; PAC California Leads and the Ed Musgrove campaign. |
| M1: Policy footprint | C-M1-01, C-M1-02 | Catalina Media Development LLC reaches two areas through AB 1740; Stand With Survivors reaches three through SB 577. |
| M2: Same side | C-M2-01, C-M2-02 | Shared support for AB 186, starting from Walt Disney or Creative Artists Agency. Each reaches three other organizations. |
| M3: Reported alongside | C-M3-01, C-M3-02 | Steve Hilton shares a chunk with Reform California. A named Santa Monica article supplies nine organization-and-chunk rows alongside Gavin Newsom. |
| M4: Influence chain | C-M4-01, C-M4-02 | California Leads → Ed Musgrove campaign → Ed Musgrove; Michelson Center → Yes on Proposition 38 campaign → Proposition 38. |
| M5: Reported vote | C-M5-01, C-M5-02 | Catherine Blakespear on SB 1007 and Scott Wiener on SB 1229. Both have a recorded no vote and attached reporting that explicitly states it. |
| C1: Committee lookup | C-C1-01, C-C1-02 | AB 2540's referral to Senate Appropriations; the two stored committee targets of AB 2540 referrals. |

These counts describe the reference query's output, not a required row layout for a generated query. The source text is in the verified-results evidence records. The campaign-support questions make no claim that a PAC's independent spending is a direct contribution to a candidate.

## What changed to make the categories answerable

M2 uses two `LOBBIED_FOR` edges on AB 186. The reporting describes support from studio and union lobbyists. This preserves the shared-side intersection without pretending the graph's missing `DECLARED_STANCE.alignment` values are populated.

M4 uses the populated two-hop chain through a campaign, with both target alternatives of `CAMPAIGN_FOR`. The original extension from a funded candidate to a Bill still has zero matches. These two cases therefore test the existing prefix and target union, not the full original chain or causal influence.

M5 asks for individually reported votes. It does not ask for every senator's vote, a party-wide voting rate, or non-voters in an authoritative roster. News uses the declared direct Politician-to-LegislativeEvent Shortcut Rule. LegislativeTenure and District remain absent, so their structural checks stay outside this live-data batch.

The committee examples ask about referrals because those specific paths and their reporting exist. A referral is not relabeled as a hearing. Measure questions name a known Bill Designation and session; descriptive-name disambiguation remains a separate later challenge.

R1 retrieves a recorded position and its text without filtering a nonexistent alignment value. R3 retrieves funding links and reporting without computing totals from absent amount or date fields. E3 follows article-level `DISCUSSES_TOPIC` and `HAS_CHUNK`. Publication dates are converted from their stored strings, and Policy Areas are matched by their stored names rather than assuming vocabulary slugs are graph ids.

## How to use this set

Send the constructor the construction instruction from `cases.yaml`, the persisted News Ontology, and the natural-language question. Keep family labels, reference queries, parameters, outputs, and evidence out of the construction prompt. If an interface requires case identifiers, assign opaque ids instead of sending the family-coded identifiers.

Every case in this batch has a verified retrieval path. Ask for a query that retrieves that data. A deferral is a failure to attempt construction in this batch; no coverage gate should prevent a query from reaching validation. Test permanent decline and missing coverage separately using the original controls.

Score the requested entities, article sets, counts, and relevant evidence. Nonempty rows alone do not pass: the earlier typed prototype returned California housing evidence for a Texas question. Equivalent Cypher and output grouping are acceptable; query text and row order are not the answer. Multi-hop rows retain evidence groups for each claim so a final Bill mention cannot stand in for evidence of an earlier funding or lobbying link.

For the article-count case, a representative Chunk provides an entry point to each counted Source Article. The topic decision belongs to that article, not independently to the representative Chunk. Other topic cases return the article's full Chunk list.

The graph contains extraction errors and duplicate nodes with the same project id. Reference rows use distinct project identities where appropriate, and the witness text was inspected for the selected relationship and vote examples. An unrelated edge that merely happens to exist was not sufficient to select a question. For example, the proposed Gail Pellerin vote case was excluded because its attached text describes a proponent without explicitly stating her vote; she remains a valid entity-dossier subject.

Recheck from the repository root:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run python work/initiatives/useful-graph-retrieval/query-construction/verify.py
```

This writes a fresh inspection to `.scratch/query-construction/verification.json`. Compare it with the saved reference before another model experiment. Graph changes can alter expected sets even when every question still returns rows. Update a reference deliberately, and retain the case-file hash and inspection time with the experiment.
