# 03 — Coreference agents take dependencies, corrections continue the conversation

**What to build:** The numbered Source Article is rendered in one place for both
coreference agents, and a correction round becomes a continuation of the
annotator's own conversation, so it sees the Mention Spans it is being asked to
correct.

Today the numbered article is pasted into three separate prompt builders, and a
correction is a fresh call that re-states the article to an annotator with no
memory of its own answer.

This does not reduce tokens. Instructions are re-sent on every request either
way, and carrying history adds the prior response to the correction round. It is
accepted for correction quality, not as a saving.

Moving the instructions breaks the Dead Letter Queue's metadata, which scrapes
the agent's private instructions attribute and cannot render a
dependency-taking function, so that fix travels with this ticket.

**Blocked by:** None — can start immediately. Note that 04 rewrites the same
resolver loop; working the two in parallel will conflict.

Labels: ready-for-agent

- [x] Both coreference agents declare a dependency type carrying the Source Article and its numbered sentences.
- [x] The numbered Source Article is rendered by one instructions function shared by both agents, and by no other code path.
- [x] The annotation, Coreference Critic, and correction prompts carry only their task-specific content.
- [x] The Coreference Critic still receives exactly one copy of the article.
- [x] A correction round runs with the annotator's prior messages as history.
- [x] A correction round still names only the rejected Mention Spans and their Critic reasons, and leaves accepted Mention Spans untouched.
- [x] The Dead Letter Queue's agent metadata no longer introspects the agent's private instructions attribute.
- [x] That metadata reports the static instruction text, the prompt version, and the resolved model name, and no longer reports a temperature no agent configures.
- [x] The prompt assertions that read the final user message part are rewritten to read the whole rendered request; the properties they assert are unchanged.
- [ ] Every behavioral test in the coreference suite passes without modification.
