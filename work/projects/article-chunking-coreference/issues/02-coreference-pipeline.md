Labels: completed

> This completed issue is retained under the original project, but its current
> coreference contract is the structured Mention Span flow in [Coreference
> Resolution via Mention Spans](../../coreference-mention-spans/PRD.md).

## What to build

An LLM-based Coreference Resolution pipeline that identifies and resolves ambiguous pronouns or referring expressions in a Source Article's text before chunking.

The pipeline must:
1. Use a Pydantic AI Coreference Resolution annotator agent to return a structured list of Mention Spans anchored to numbered sentences.
2. Use a Coreference Critic LLM agent to return one verdict for each validated Mention Span.
3. Support a self-correcting feedback loop: if the Critic rejects spans, the annotator receives the critic's reasons and performs another pass for those spans only.
4. Derive each surviving span's character range from the original Source Article and replace it with its canonical entity name to produce resolved text for chunking.

## Acceptance criteria

- [x] Coreference Resolution annotator agent returns Mention Spans with sentence labels, verbatim mentions, occurrences, and canonical entities.
- [x] Critic agent reviews each Mention Span and correctly rejects incorrect reference mappings with reasons.
- [x] Python orchestrator retries up to 3 times on critic rejection and asks only for rejected spans again.
- [x] Python substitution derives ranges from the Source Article and produces resolved text without changing other characters.
- [x] Mocked unit tests verify Mention Span validation, critic verdicts, targeted retries, and substitution.

## Blocked by

None - can start immediately
