# Query Rewrite and approval

`QuestionPreparation` owns one question's preparation for the Chat Agent. Its
rewriter is a Pydantic AI agent created by `get_query_rewriter`. The injected
asynchronous `assess_question_policy_and_coverage` callable represents the Chat
Agent's question-policy and coverage decision. It receives only a
`QueryRewriteProposal`, containing `question` and the internal `relational`
boolean. The original wording goes only to the rewriter.

```python
from knowledge_map.core.question_preparation import (
    QuestionPreparation,
    get_query_rewriter,
)

preparation = QuestionPreparation(
    original_question,
    rewriter=get_query_rewriter(),
    assess_question_policy_and_coverage=assess_question_policy_and_coverage,
)
presentation = await preparation.prepare()
```

For `awaiting_approval`, display `presentation.approval.question`. Explain any
`explanation` and `recoverable_portion` before asking for approval. This
presentation has no routing boolean. The assessor returns a
`QuestionAssessment` with `allowed`, `declined`, or `deferred`. Declined requires
an explanation; Deferred also requires a description of the recoverable
portion, including an explicit statement if none is known.

Only after the user approves, call `preparation.approve()`. Its
`QueryRewrite` is the user-approved retrieval input, with the assessed question,
internal route, and coverage decision retained. Do not send the original
question to retrieval. A second approval cannot release the same proposal again.

If the user rejects the question, call
`preparation.reject(correction=user_correction)` and then `prepare()` for a new
proposal. Corrections are optional. The rejection is available through
`preparation.rejections` and recorded as a structured `rewrite_rejected` log
event with the rejected question, route, and correction. Every later rewrite
receives the original request and the retained rejections. No rejected
proposal can be approved without preparing a new one.

For `declined` or `rewrite_unavailable`, display `presentation.message`; neither
result contains an approval request. A Declined question ends preparation.
Exhausted transport or transient provider failures record
`rewrite_unavailable` and explain the temporary network problem. There is no
original-wording fallback. Authentication, invalid-request, and model-output
errors propagate to the caller rather than being described as a network
outage. A new preparation instance starts a later attempt after a failure.

The workflow does not itself retrieve or render a chat interface. The Chat
Agent handoff is implemented by Graph-Prioritized Retrieval issue 09. Relevant
Deferred limits stay in the approved value so the eventual answer can repeat
them.

The instructions use examples from the 25 verified construction cases and
remove separate reporting requests while preserving source-discovery intent.
Scripted-model tests verify the approval contract; they do not measure a real
model's rewriting quality. No prompt-text assertions or live model requests are
part of these tests.

Configure the role through [Model Deployments](model-deployments.md). Design
decisions are recorded in the
[Graph-Prioritized Retrieval PRD](../work/projects/graph-prioritized-retrieval/PRD.md).
