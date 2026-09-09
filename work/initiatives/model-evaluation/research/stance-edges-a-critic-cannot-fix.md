# The stance edges a critic cannot fix: the case for retraction

Not tied to a numbered issue. Written from two dry runs of the stance alignment backfill
(`knowledge_map.core.stance_backfill`) against the stored graph, both against local
`gemma4:26b`, and from one blind review of the first run's output by a separate reviewer.
Both run plans and the reviewer's verdicts are committed beside this file. Neither run
wrote anything: the graph still holds 174 `DECLARED_STANCE` edges, 0 with `alignment`,
174 stamped `needs_review`.

Recorded because the measured defect is not the one the Stance Alignment Critic was built
to fix, and because the obvious repair — letting the critic abstain — was tried here and
did not work. The proposal at the end is a design the runs argue for and do not yet
license.

## What the runs measured

Every stored stance lacks the one property the ontology says a stance entails. The graph
inventory of 2026-09-08 counted 174 such edges, each carrying only `chunks` and
`needs_review`. All 174 have asserting chunk references and none is dangling, so each one
can be shown the passage it came from.

The backfill reads those edges, groups them by asserting Article Chunk, and runs the
critic once per chunk. 174 edges reduce to 166 chunks, so the pass costs 166 inferences,
not 174.

**Run 1**, the three-value critic as committed at `10a72ba`: 166 chunks read, 166
inferences, 322.9s. 167 edges settled on a single alignment; 7 were left unsettled because
the chunks asserting them disagreed.

## What the blind review found

The 167 settled edges were given to a reviewer that never saw the critic's answers, with
one option the critic does not have: `UNSUPPORTED`, for a passage that does not state the
source's position on the target at all.

| | |
| --- | ---: |
| Reviewer agrees with critic | 145 / 167 (86.8%) |
| Agreement excluding `UNSUPPORTED` cases | 145 / 156 (92.9%) |
| Agreement where reviewer was high-confidence | 128 / 133 |
| Reviewer called `UNSUPPORTED` | 11 |

Three of the eleven were checked by hand against the raw chunk text and the reviewer was
right in each:

- **Gavin Newsom → SB 1229.** The chunk is environmentalists criticising Newsom's actions.
  His position on the bill does not appear. Critic: `POSITIVE`.
- **Mike Gipson → AB 1642.** Gipson authored AB 1795, the companion bill named in the same
  sentence. Critic: `POSITIVE`.
- **CDFW → SB 1305.** A legislative analysis finds the department lacks staff capacity for
  the bill's roadmap. That is a budget finding, not a departmental position. Critic:
  `NEGATIVE`.

Counting the eleven together with four flatly wrong directions and five cases where the
critic went directional on a hedged position, **20 of 167 settled edges — 12.0% — would
have entered the graph wrong or unsupported.**

## The premise this retires

The Stance Alignment Critic was built for a producer that emits the right edge with an
empty `properties`. That defect is real and the critic fixes it: on the 156 cases the
reviewer could judge, it agrees 92.9% of the time, and the alignments it supplies are not
a constant — 89 `POSITIVE`, 74 `NEGATIVE`, 4 `NEUTRAL`, where always answering the
plurality would score 53%.

But a second defect sits underneath it. **The producer also emits stance edges the passage
does not support at all.** For those, there is no alignment to recover, and a pass whose
only job is to supply one will supply a wrong one. The critic's own contract forbids the
fix: it is "never allowed to subtract a claim".

## Abstention was tried and is close to inert

**Run 2** added a fourth verdict, `NO_STANCE_STATED`, deliberately outside the ontology's
vocabulary so the write path cannot store it. An abstention is dropped before matching, so
the claim passes through exactly as the producer wrote it, still carrying its incomplete
Claim Key. The instructions were widened to name the failure shapes and to separate a
stance from the mood of the passage.

166 chunks, 166 inferences, 279.9s. 163 edges settled, 6 abstentions, 5 conflicts.

**One of the eleven unsupported edges was recovered.** The other ten still receive a
confident invented direction.

The instructions name the shape of one of the ten explicitly — *"when the source is
connected to the target only by adjacency, such as authoring a different bill"* — and
`Mike Gipson → AB 1642` still came back `POSITIVE`.

That is the same result [alignment-is-not-a-wording-problem.md](alignment-is-not-a-wording-problem.md)
reached on the producer prompt, reproduced on the critic prompt. Four wordings were
measured inert there; this is the first measured on the second pass, and it agrees.

Overall the change moved 20/167 (12.0%) wrong-or-unsupported to 16/161 (9.9%), and part of
that improvement is disagreements removed rather than corrected. It also cost two correct
verdicts: `UC → AB 713` reads *"UC does not have a position"*, an explicitly stated
non-position that the reviewer called `NEUTRAL` and the widened instructions pushed into
abstention. The boundary between "states no position" and "states a position of none" is
drawn wrong in the current wording.

## The retraction path

The defect is in the edge's existence, not its properties, so the verdict that reaches it
has to be about the edge rather than about `alignment`. The shape:

1. The critic keeps its abstention verdict. Nothing about the inference changes, and the
   pass costs no more than it does today.
2. The write path stops treating an abstention as a pass-through and starts treating it as
   evidence against the claim.
3. An edge is retracted only when **every** chunk asserting it abstains. One chunk's
   silence is not evidence against another chunk's stated direction — the same asymmetry
   the existing conflict handling already respects, where disagreeing chunks leave an edge
   unsettled rather than letting one win.

The graph needs a state for this that it does not have. `needs_review` currently means one
thing: the Claim Key is incomplete. "The passage asserting this claim does not support it"
is a different fact about a different part of the edge, and stamping both into one flag
loses the difference precisely where a person would need it. Quarantining — recording
which chunks declined to support the claim, and leaving the edge in place — is reversible
and keeps the provenance a later pass would need. Deleting is not.

## What this does not license

A retraction path built on today's abstention rate would retract almost nothing: 6
abstentions across 174 edges, one of which was a genuine unsupported claim. **Retraction
is the right shape for the defect and is gated on a lever this work has not found.** The
rate has to move first, and prompt wording is now measured inert against it five times
across the two passes. What has not been tried: a stronger deployment for the critic than
the producer's, and showing the critic the chunks either side of the one it is judging,
since several of the eleven have the source's real position stated elsewhere in the same
article.

## One finding outside the scope of this note

The stored chunk text is damaged by coreference substitution. Pronouns have been replaced
with full names in ways that produce ungrammatical text: *"Al Muratsuchi, Al Muratsuchi
authored Proposition 2"*, *"38% of California Department of Fish and Wildlife existing
duties"*, *"tricky to campaign in favor of Proposition 3 with another tax on the ballot"*.
This is what is stored on the `Chunk` nodes, so it reaches every consumer of chunk text and
not only this critic. It is a plausible contributor to the wrong directions measured above
and deserves its own investigation.
