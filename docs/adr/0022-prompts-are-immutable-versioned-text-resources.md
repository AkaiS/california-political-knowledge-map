# Prompts are immutable versioned text resources

Authored LLM instructions and message templates live in UTF-8 text files under
`src/knowledge_map/resources/prompts/<family>/<purpose>/vN.txt`. Modules load an
explicit version through `knowledge_map.prompts.load_prompt`. Instructions,
question policy, correction messages, and model-facing instructional descriptions
follow this rule. Python modules contain resource references and rendering code,
not prompt prose.

A prompt version recorded in Git is immutable. Any change to its text, including
whitespace or template placeholders, creates the next numbered version in the
same directory. Existing versions remain available. A consumer adopts the new
version by changing its explicit reference; there is no implicit latest version.
Tests and evaluation expectations move with that adoption rather than rewriting
the old version to make an existing test pass.

This separates a change in model instructions from a change in orchestration.
The initial extraction preserves the existing rendered prompts so it does not
quietly become another prompt-tuning experiment.

## Rendering and scope

Text files may contain placeholders for runtime data. Rendering inserts article
text, questions, examples, ontology facts, or validation results into the selected
template. Changing those values is a change in input data, not a new template
version. Changing the surrounding instructions or placeholder structure is a new
version.

Keep JSON serialization, schema structure, domain identifiers, ordinary schema
metadata, and diagnostic values in their owning modules. A schema description
that instructs the model how to respond belongs in a prompt resource even though
the schema references it. Captured historical messages and Evaluation Data Set
inputs remain evidence and data; they are not rewritten during prompt migration.

Rendered text retains its original whitespace. Resource loading must work from
an installed package and independently of the current working directory. A
missing requested version fails rather than selecting another version.
The extraction adapter retains its existing missing-resource fallback for
compatibility; that fallback also selects an explicit immutable prompt version.

## Changing a prompt

1. Read the consumer and the version it currently selects.
2. Add a new `vN.txt` beside the existing version. Preserve the old file.
3. Update only the consumers intended to adopt it.
4. Check rendering, resource packaging, and the relevant component behavior.
   Record evaluation changes against the new version without rewriting historical
   reports.

The repository remains the versioning system described in
[ADR 0017](0017-git-is-the-evaluation-versioning-system.md). Evaluation Reports
continue to digest the instructions actually rendered for a run. An immutable
template does not imply an immutable article, ontology, or few-shot example set.
