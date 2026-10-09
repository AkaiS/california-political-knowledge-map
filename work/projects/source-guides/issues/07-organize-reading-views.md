# 07 Organize reading through contrast and timeline views

Labels: enhancement, ready-for-agent
Parent: [Source Guides spec](../PRD.md)

## What to build

Organize saved Source Articles into question-specific Article Groups for
opposing positions, differing accounts, chronological reading, or other useful
parts of the question. Preserve an ungrouped list when organization is unavailable.

## Acceptance criteria

- [ ] The existing Chat Agent produces typed optional groups over articles that
  passed the final relevance gate. Validate article references and omit any
  membership pointing outside the included sources.
- [ ] One article can appear in several groups with a distinct reading direction
  for each membership. Group labels identify what to investigate and do not
  assign an article a political position.
- [ ] Contrast views can organize supporters' and detractors' arguments or
  differing accounts when supported by retrieved evidence. They direct readers
  to articles without supplying conclusions or adjudicating the accounts.
- [ ] Timeline views organize reading without replacing it with event narration.
  Preserve requested chronology, distinguish publication dates from reported
  event dates, and avoid inventing dates or treating developments as disagreement.
- [ ] Unavailable groups fall back to all passing articles with their relevance
  reasons. Invalid guidance and provider/validation failure remain distinct from
  a successful ungrouped result or relevance rejection.
- [ ] Save and restore groups and membership-specific reading directions.
  Default relevance order and complete coverage of included articles remain
  available. No chunks appear in groups or their details.
- [ ] Changed prompts use new immutable versions, and shared evaluation consumers
  understand the same group contract without rewriting historical outputs.

## Blocked by

- [02 Save, browse, and reopen Source Guides](02-save-and-reopen-guides.md)

## Validation

At the application boundary with temporary real SQLite and deterministic model
outputs, check overlapping membership, omitted-source references, persistence,
chronology, absent dates, and group-free fallback. Use existing controlled
evaluation examples for librarian behavior. Browser-check contrast and timeline
reading, overlapping articles, restored views, and safe rendering. Run required
checks with uv and do not introduce independent Chat Session tests.
