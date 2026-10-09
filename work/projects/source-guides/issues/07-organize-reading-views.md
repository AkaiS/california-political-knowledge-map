# 07 Organize reading through contrast and timeline views

Labels: enhancement, completed
Parent: [Source Guides spec](../PRD.md)

## What to build

Organize saved Source Articles into question-specific Article Groups for
opposing positions, differing accounts, chronological reading, or other useful
parts of the question. Preserve an ungrouped list when organization is unavailable.

## Acceptance criteria

- [x] The existing Chat Agent produces typed optional groups over articles that
  passed the final relevance gate. Validate article references and omit any
  membership pointing outside the included sources.
- [x] One article can belong to several groups or have distinct directions
  within one group. Render its ordinary article link once, with group-labeled
  reading directions listed nearby; accept otherwise-valid repeated
  memberships and consolidate identical entries. Group labels identify what
  to investigate and do not assign an article a political position. Verified
  highlight links remain ticket 08.
- [x] Contrast views can organize supporters' and detractors' arguments or
  differing accounts when supported by retrieved evidence. They direct readers
  to articles without supplying conclusions or adjudicating the accounts.
- [x] Timeline views organize reading without replacing it with event narration.
  Preserve requested chronology, distinguish publication dates from reported
  event dates, and avoid inventing dates or treating developments as disagreement.
- [x] Unavailable groups fall back to all passing articles with their relevance
  reasons. Invalid guidance and provider/validation failure remain distinct from
  a successful ungrouped result or relevance rejection.
- [x] Save and restore groups and membership-specific reading directions.
  Default relevance order and complete coverage of included articles remain
  available. No chunks appear in groups or their details.
- [x] Changed prompts use new immutable versions, and shared evaluation consumers
  understand the same group contract without rewriting historical outputs.

## Blocked by

- [02 Save, browse, and reopen Source Guides](02-save-and-reopen-guides.md)

## Validation

At the application boundary with temporary real SQLite and deterministic model
outputs, check overlapping membership, omitted-source references, persistence,
chronology, absent dates, and group-free fallback. Use existing controlled
evaluation examples for librarian behavior. Browser-check contrast and timeline
reading, overlapping memberships consolidated near one article link under every
view, restored views, and safe rendering. Run required
checks with uv and do not introduce independent Chat Session tests.

## Comments

2026-10-09: The maintainer clarified that each article should appear once as a
non-highlighted link, with relevant highlights in a nearby list when available.
Ticket 07 consolidates its reading directions near that link. Ticket 08 adds
verified highlight links. See the [PRD clarification](../PRD.md#maintainer-clarification-2026-10-09).

2026-10-09: Independent Standards and Spec review accepted the seven criteria
after consolidating the shared reading-order type and fixing complete-list
publication sorting for partial timeline groups. See [review evidence](../validation/ticket-07-review.md)
and [implementation evidence](../validation/ticket-07.md). Ticket 08 owns verified
highlight links; tickets 08 and 09 remain takeable.
