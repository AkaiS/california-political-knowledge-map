Status: completed

## What to build

An LLM-based Coreference Resolution pipeline that identifies and resolves ambiguous pronouns or referring expressions in a Source Article's text before chunking.

The pipeline must:
1. Use a Pydantic AI Coreference Resolution annotator agent to produce an Annotated Article where ambiguous references are wrapped in tags: `<ref entity="Entity Name">pronoun</ref>`.
2. Use a Coreference Critic LLM agent to validate the annotations.
3. Support a self-correcting feedback loop: if the Critic finds issues, the annotator receives the critic's error messages and performs another pass (up to 3 retries, falling back to the original text on failure).
4. Parse the final Annotated Article in Python, replacing all `<ref>` tags with their canonical entity names to produce clean plain text for chunking.

## Acceptance criteria

- [x] Coreference Resolution annotator agent successfully identifies and tags pronouns using the `<ref>` tag markup schema.
- [x] Critic agent reviews annotations and correctly raises issues for incorrect reference mappings.
- [x] Python orchestrator retries up to 3 times on critic failure, and falls back gracefully to the original text.
- [x] Python replacement function successfully translates tags to clean plain text.
- [x] Mocked unit tests verify the annotation, critic feedback loop, retries, and tag-to-plaintext substitution.

## Blocked by

None - can start immediately
