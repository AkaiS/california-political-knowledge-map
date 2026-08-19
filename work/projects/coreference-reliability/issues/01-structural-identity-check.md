Labels: completed

> Historical record: the tag-stripping and Structural Identity Check described
> here belonged to the retired whole-article markup flow, whose subject matter
> was the `<ref entity="...">...</ref>` tag format. That format no longer
> exists anywhere in the codebase; every mention of it below is a record of
> what this ticket built, not a description of current behaviour. Current
> coreference resolution uses the Mention Span contract in [Coreference
> Resolution via Mention Spans](../../coreference-mention-spans/PRD.md).

## Parent

[.scratch/coreference-reliability/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/work/projects/coreference-reliability/PRD.md)

## What to build

Implement a programmatic Structural Identity Check in the coreference resolution process to ensure that the annotated text matches the structure of the original text, preventing downstream alignment errors.

- Developed tag stripping logic that removed the retired `<ref entity="...">...</ref>` tag format and retrieved the inner text.
- Develop whitespace normalization logic to trim outer whitespace and collapse multiple consecutive whitespace/newline characters into single spaces.
- Programmatically execute this check immediately after the annotator agent runs.
- Integrate the check with the existing coreference retry loop: when a structural identity check fails, feed the error back to the annotator agent and decrement the retry budget. Bypass the Critic agent during structural retries to conserve tokens.
- Maintain existing coreference resolution behavior for valid inputs.

## Acceptance criteria

- [x] A helper function stripped the retired `<ref entity="...">...</ref>` tag format from the annotator output and returned the raw text.
- [x] A helper function is implemented to normalize text by trimming leading/trailing whitespace and collapsing multiple spaces or newlines into a single space.
- [x] Structural identity check validates that the normalized stripped annotated text is identical to the normalized original text.
- [x] The retry loop in `resolve_coreferences` handles structural mismatch validation failures by passing feedback back to the annotator agent.
- [x] The Critic agent is bypassed when a structural mismatch is detected (no token usage for Critic validation on structural failures).
- [x] If structural validation fails after all retry attempts (default 3), the resolver falls back to the original text.
- [x] Comprehensive unit tests verify the helper functions, structural mismatch retries, Critic bypass logic, and fallback behavior.

## Blocked by

None - can start immediately
