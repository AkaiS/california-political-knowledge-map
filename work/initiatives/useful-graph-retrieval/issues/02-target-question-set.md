# Decide the target question set for California political retrieval

Labels: wayfinder:grilling, ready-for-agent
Parent: [Useful Graph Retrieval](../MAP.md)

## Question

What questions must this retrieval layer answer, expressed concretely enough to
choose retrieval modes against and to build an Evaluation Data Set from later?

The roadmap named four orientations — entity, edge, neighborhood, and community.
This ticket turns them into an authored set of representative questions over the
settled ontology, each one traced to the subgraph and traversal that would answer
it, so that later tickets can be judged against real targets rather than
abstractions. In doing so it cuts the four to three; see the Answer.

It should also distinguish questions the graph is meant to answer from questions
it must decline, since answers are meant to direct readers to original reporting
rather than substitute for it.

## Blocking

- Blocks: Decide which subgraph is retrievable now and which is deferred.
- Blocks: Prototype query construction and validation against the ontology.
- Blocks: Decide the retrieval modes and the index inventory they require.

## Answer

The set itself is [question-set.md](../question-set.md): ten question families
across three orientations, roughly twenty-five natural-language questions, plus
a Declined list and a Deferred list. This section records the decisions the set
embodies, so that later tickets read policy from here and targets from there.

**Three orientations, not four.** The honest taxonomy is **entity lookup**,
**relationship lookup**, and **multi-hop traversal**. "Neighborhood" without
community detection is bounded multi-hop from a seed set and earns no separate
name, and the community orientation is cut outright: it requires a Graph Data
Science install the local stack does not have, per
[the survey](03-survey-graph-retrieval-patterns.md). The roadmap, the MAP, the
inbox, and ticket 06 are corrected to match, and community moves to the MAP's
Out of scope, so a later ticket cannot revive it by citing the roadmap.

Orientation is **derived from the path**, not asserted beside it: it is the
shape of the path's entity segment, which is the path with its terminal
grounding hop removed. One node is an entity lookup, one edge a relationship
lookup, two or more edges a multi-hop traversal. It is recorded so coverage is
checkable at a glance; where orientation and path disagree, the path is right.

**The corpus grounds the answer; the graph reaches it.** The ontology's value is
that it connects portions of the corpus — a query assembles a subgraph, and the
Article Chunks hanging off its nodes and edges are what gets loaded into
context. This is the read-side consequence of
[ADR-0013](../../../docs/adr/0013-a-news-derived-relationship-asserts-existence-and-identity-not-payload.md):
an edge asserts existence and identity only, so unless entities and
relationships were made far richer than that ADR allows, the detail an answer
needs lives in the Chunk. No new ADR is warranted; the trade-off is already
recorded there. `GLOSSARY.md` gains the term **Grounding Evidence**.

**Every question carries a grounding axis.** A question is either
`evidence-grounded` — a Chunk states the answer — or `structure-derived` — the
answer is a count, list, or intersection that no Chunk states. Structure-derived
questions are in scope but second-class: never delivered as a bare result,
always with the Grounding Evidence behind each element counted. A set that
ignored this axis would produce a contract in ticket 08 unable to tell a cited
claim from an uncited aggregate.

**Declined and Deferred are different things.** *Deferred* is a coverage state
that closes with outcome-5 ingestion; ticket 04 owns it and decides the layer's
behaviour when a question reaches an unpopulated region. *Declined* is a
permanent stance belonging in the contract: out of domain, narrative or motive,
normative, predictive, beyond-evidence inference, private individuals, and
absence over an open universe. Ticket 08 needs exactly this line to distinguish
a declined question from a failed one.

The sharpest case is negation against absence. **Negation** over an enumerable
universe with recorded non-events — every Assembly member, every roll call — is
Deferred: the complement is finite and meaningful, and the roll-call layer closes
it. **Absence** over an unbounded complement — every organization that did not
fund a campaign — is Declined permanently: the answer set is enormous and would
report our Publications' coverage rather than a fact about California politics.

**Three hard-case tags, not one.** `ambiguous seed`, `temporal scope`, and
`negation` mark questions where a plausible-looking retrieval returns
confidently wrong grounding, and they demand different fixes — disambiguation in
query construction, as-of-date semantics, and an explicit decline respectively.
Tagged questions are mixed into the set rather than segregated, so tickets 05
and 06 are judged on whether they handle them.

**No expected answers here.** The set records the question, its orientation, and
the path that would answer it. Expected outputs belong to the Evaluation Gold
Set, which [ADR-0006](../../../docs/adr/0006-bind-evaluation-gold-sets-to-one-task-contract.md)
binds to exactly one Evaluation Task Contract — and that contract is ticket 08's
output, not this ticket's. Traversals are recorded in ontology path notation
rather than Cypher for the same reason: no graph exists to run Cypher against,
and executable queries are ticket 05's output.

**Subjects are real where the corpus supports them.** News-layer questions name
real subjects from the gathered Source Articles — SB 9, the $28 construction
wage bill, the Uber insurance law, Proposition 38, the climate deal — so a
family that is unanswerable in practice is discovered early. Outcome-5 questions
use placeholders, since an invented FPPC donation would be a target that can
never be verified.

**The set is additive.** Anyone, including an agent, may add questions.
Removals and rewordings are the maintainer's alone: a retrieval mode that cannot
answer a question must not be fixed by editing the question.

### Handed forward

- To ticket 08: **Grounding Evidence is a proper subset of the Evidence Set**,
  and no Evidence Set is valid without it. `Evidence Set` remains 08's term to
  define; this ticket only fixes the boundary.
- To tickets 04 and 06: `ontology.md` declares **no path from `:Committee` to
  `:Bill` or `:LegislativeEvent`**. A Committee connects only to
  `:LegislativeTenure`. Committee-activity questions are therefore unanswerable
  by ontology shape rather than by missing data, and no outcome-5 ingestion
  closes the gap.
