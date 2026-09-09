# Next experiment: constrained patterns and entity binding

Continue [issue 05](../issues/05-prototype-query-construction-and-validation.md)
from the [composable-triples findings](composable-triples-comparison.md).
This is proposed work, not an accepted production architecture or a record of
an implemented feature.

## Reduce pattern bookkeeping

The supplied-pattern arm retrieved 22 of 25 complete answers. Model-selected
patterns frequently failed on undeclared variables, repeated claim names, and
invalid projections. Test whether moving these identifiers into the compiler
reduces malformed plans:

- Derive a supported triple catalog from the News Ontology and give choices
  stable identifiers. Let code determine the permitted direction.
- Have code assign node handles, edge/evidence ids, binding-slot ids, and
  projection aliases. The model selects declared handles and relationships
  rather than inventing cross-references.
- Keep joins, output targets, and constraints explicit. Two Organizations
  sharing one Bill must use the same Bill handle, with distinct anchor and
  peer handles. Compiler-assigned ids do not decide which intersection the
  question asks for.
- Derive binding descriptions from label, property, and operator. The last
  pattern model embedded question values in those descriptions and sometimes
  passed a naming mistake to the binder.

The unresolved interface choice is a complete structured pattern versus
incremental constrained choices. Build the smallest version that tests the
bookkeeping hypothesis. Do not expand this into a general query language.

## Resolve bindings against stored candidates

All three supplied-pattern binding misses shortened a Campaign's stored name.
Required fields can enforce that a value exists without making it the right
entity. Test read-only candidate lookup restricted by the selected base label
and the question's scope. Return stored ids, names, and useful disambiguating
metadata; select a candidate or record ambiguity instead of taking the first
match or applying case-specific suffix patches.

Bind internal project ids when appropriate and retain Bill session constraints.
Keep Campaigns distinct from their candidates and measures. Duplicate stored
project ids remain ambiguous: candidate lookup must not silently merge nodes
or assert uniqueness. This experiment concerns retrieval-time binding; it does
not authorize a graph rewrite or settle ingestion Entity Resolution.

Use the [retrieval modes and index inventory](../issues/06-retrieval-modes-and-index-inventory.md)
as the capability specification. Entity-name full-text search and non-unique
internal-id lookup are already specified, but their presence must be checked
before relying on them. Keep a temporary read-only prototype fallback explicit
if the required indexes are not installed. External-identifier implementation
remains deferred.

## Measure the stages separately

Retain the same verified questions for continuity, while identifying them as
development examples. Keep an authored-pattern control to isolate binding and
resolution from planning. Compare the constrained pattern interface against
the previous model plans, keeping the model deployment and inference settings
explicit. Add new examples separately before claiming generalization.

Record malformed patterns, unresolved or ambiguous bindings, validation stops,
executed empty results, and complete retrievals separately. Preserve original
outputs alongside deterministic normalization decisions. Check sessions,
sub-labels, date bounds, target unions, and each claim's Grounding Evidence;
nonempty rows or accidental matches are insufficient.

Use the latest transport-level capture so token-limit responses remain visible.
Freeze prompts within a batch and save replays separately from inference.
The [archive](reports/README.md) supplies the original commits, reports, and
known measurement limitations. An architectural decision should follow the
evidence rather than being recorded in an ADR now.
