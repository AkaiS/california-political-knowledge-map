# Policy Area Vocabulary

Labels: completed

Authored for [issue 01](issues/01-author-policy-area-vocabulary.md). This is the
closed vocabulary of `PolicyArea.id` values. Ticket 02 consumes it as-is; no
entry is decided again downstream.

## Sources

Both fetched 2026-08-06.

**Senate** — [Senate Office of Research policy areas](https://sor.senate.ca.gov/policyareas),
23 entries. The SOR list is the Senate's own subject-matter taxonomy and tracks
its standing committees. Note it has *already* excluded Appropriations, Rules,
and Budget — it is a subject-matter taxonomy, not a full roster.

> Agriculture · Banking and Financial Institutions · Business, Professions, and
> Economic Development · Education · Elections and Constitutional Amendments ·
> Energy, Utilities, and Communications · Environmental Quality · Governmental
> Organization · Health · Housing · Human Services · Insurance · Judiciary ·
> Labor and Industrial Relations · Local Government · Natural Resources · Public
> Employment and Retirement · Public Safety · Revenue and Taxation · State
> Mandates · Technology · Transportation · Veterans' Affairs

**Assembly** — [Assembly standing committees](https://www.assembly.ca.gov/committees),
32 entries. Select, joint, sub-, and special committees are out of scope: the
ticket specifies standing committees.

> Aging and Long-Term Care · Agriculture · Appropriations · Arts, Entertainment,
> Sports, and Tourism · Banking and Finance · Budget · Business and Professions ·
> Communications and Conveyance · Economic Development, Growth, and Household
> Impact · Education · Elections · Emergency Management · Environmental Safety
> and Toxic Materials · Governmental Organization · Health · Higher Education ·
> Housing and Community Development · Human Services · Insurance · Judiciary ·
> Labor and Employment · Local Government · Military and Veterans Affairs ·
> Natural Resources · Privacy and Consumer Protection · Public Employment and
> Retirement · Public Safety · Revenue and Taxation · Rules · Transportation ·
> Utilities and Energy · Water, Parks, and Wildlife

## Exclusion rule

A committee contributes a policy area only if its jurisdiction is *a subject a
bill can be about*. A committee whose jurisdiction is the *legislative process
itself* — how bills are funded, scheduled, referred, or how the Legislature and
elections are constituted — contributes nothing, so that a bill dying in
Appropriations is not recorded as being about "appropriations".

| Committee | Chamber | Why excluded |
| --- | --- | --- |
| Appropriations | A (S: absent from SOR) | Fiscal gatekeeping. |
| Budget | A (S: absent from SOR) | Fiscal process. |
| Rules | A (S: absent from SOR) | Referral and internal governance. |
| Elections; Elections and Constitutional Amendments | A, S | Named by the ticket. Constitution of the Legislature and the ballot mechanism, not a bill subject. |
| State Mandates | S | A reimbursement mechanism under Article XIII B. Bills are not *about* state mandates; they *incur* one. |

## The vocabulary

27 entries. Every entry is a topic, not a committee name: "Assembly
Transportation Committee" yields `transportation`. No `Committee` node is created
by this ticket.

| `id` | `name` | Assembly source | Senate source |
| --- | --- | --- | --- |
| `aging-and-long-term-care` | Aging & Long-Term Care | Aging and Long-Term Care | — |
| `agriculture` | Agriculture | Agriculture | Agriculture |
| `arts-entertainment-and-tourism` | Arts, Entertainment & Tourism | Arts, Entertainment, Sports, and Tourism | — |
| `banking-and-finance` | Banking & Finance | Banking and Finance | Banking and Financial Institutions |
| `business-and-professions` | Business & Professions | Business and Professions | Business, Professions, and Economic Development (split) |
| `economic-development` | Economic Development | Economic Development, Growth, and Household Impact | Business, Professions, and Economic Development (split) |
| `education` | Education (K–12) | Education | Education (split) |
| `emergency-management` | Emergency Management | Emergency Management | — |
| `energy-and-utilities` | Energy & Utilities | Utilities and Energy | Energy, Utilities, and Communications (split) |
| `environment-and-natural-resources` | Environment & Natural Resources | Environmental Safety and Toxic Materials; Natural Resources; Water, Parks, and Wildlife (parks & wildlife only) | Environmental Quality; Natural Resources |
| `government-operations` | Government Operations | Governmental Organization | Governmental Organization |
| `health` | Health | Health | Health |
| `higher-education` | Higher Education | Higher Education | Education (split) |
| `housing` | Housing & Community Development | Housing and Community Development | Housing |
| `human-services` | Human Services | Human Services | Human Services |
| `insurance` | Insurance | Insurance | Insurance |
| `judiciary` | Judiciary | Judiciary | Judiciary |
| `labor` | Labor & Employment | Labor and Employment | Labor and Industrial Relations |
| `local-government` | Local Government | Local Government | Local Government |
| `privacy-and-consumer-protection` | Privacy & Consumer Protection | Privacy and Consumer Protection | — |
| `public-employment-and-pensions` | Public Employment & Pensions | Public Employment and Retirement | Public Employment and Retirement |
| `public-safety` | Public Safety | Public Safety | Public Safety |
| `taxation` | Revenue & Taxation | Revenue and Taxation | Revenue and Taxation |
| `technology` | Technology & Communications | Communications and Conveyance | Technology; Energy, Utilities, and Communications (split) |
| `transportation` | Transportation | Transportation | Transportation |
| `veterans-and-military-affairs` | Veterans' & Military Affairs | Military and Veterans Affairs | Veterans' Affairs |
| `water` | Water | Water, Parks, and Wildlife (water only) | Natural Resources (split) |

## Judgement calls

**Cross-chamber deduplication.** Fourteen topics appear in both chambers with
matching jurisdiction and are collapsed to one entry each, keeping the shorter or
more legible name: `agriculture`, `banking-and-finance`, `government-operations`,
`health`, `housing`, `human-services`, `insurance`, `judiciary`, `labor`,
`local-government`, `public-employment-and-pensions`, `public-safety`,
`taxation`, `transportation`. Two more — `veterans-and-military-affairs` and
`environment-and-natural-resources` — are cross-chamber but also involved in a
rename or merge, and are described below. `business-and-professions` and
`education` appear in both chambers too, but the Senate side of each is split
rather than deduplicated; see the splits.

**Splits (4).**

- *Energy, Utilities, and Communications* (S) bundles two topics California news
  treats separately — the grid, PG&E, and rate-setting on one side; broadband and
  platform regulation on the other. The Assembly agrees: it runs **Utilities and
  Energy** and **Communications and Conveyance** as separate standing committees.
  Split into `energy-and-utilities`, with the communications half folded into
  `technology`, which is thin on its own.
- *Education* (S) splits into `education` (K–12) and `higher-education`, matching
  the Assembly's two committees. UC/CSU/community-college funding and admissions
  are a distinct beat from K–12.
- *Water* is broken out of the Assembly's **Water, Parks, and Wildlife**. Delta
  conveyance, groundwater, and drought allocation are high-volume and distinctly
  reported. Parks and wildlife remain in `environment-and-natural-resources`.
- *Business, Professions, and Economic Development* (S) splits into
  `business-and-professions` and `economic-development`, matching the Assembly's
  two committees. Occupational licensing and professional regulation are a
  different beat from growth, investment, and household economic impact.

**Merges (1).**

- *Environmental Quality* / *Environmental Safety and Toxic Materials* (pollution,
  CEQA, air and water quality) merges with *Natural Resources* (land, forestry,
  wildlife, parks). News prose rarely respects the line.
**Chamber-specific committees with no counterpart (4).** All four are
Assembly-only and all four are kept, because each is a live California news beat
that the Senate's coarser taxonomy buries inside `government-operations` or
`human-services`: `aging-and-long-term-care`,
`arts-entertainment-and-tourism`, `emergency-management` (wildfire response,
disaster declarations), and `privacy-and-consumer-protection` (CCPA, AI
regulation).

**Scope-widening renames (1).** `veterans-and-military-affairs` follows the
Assembly's broader *Military and Veterans Affairs* rather than the Senate's
*Veterans' Affairs*, so that base closures and National Guard deployments have a
home. Other renames — `banking-and-finance`, `labor`, `taxation`,
`public-employment-and-pensions`, `government-operations` — are shortenings only,
with jurisdiction unchanged.

**`government-operations` was kept, not excluded.** *Governmental Organization*
sounds like a process committee but is not one — its jurisdiction is gambling,
alcoholic beverage control, horse racing, and state procurement. It survives the
exclusion rule because bills genuinely are about those things. With
`emergency-management` now broken out separately, it is the weakest remaining
entry and the first candidate to drop.

**Dropped from the Assembly list without a merge: none.** Every non-process
Assembly standing committee is represented above.

## Review record

Reviewed and accepted on 2026-08-06. Two questions were raised during drafting
and both were decided by the reviewer:

1. **`economic-development` is its own entry**, not folded into
   `business-and-professions`. The draft folded it on the Senate's combined
   pattern; the reviewer chose the Assembly's split. It is carried in the splits
   list above.
2. **`arts-entertainment-and-tourism` is kept.** It is the lowest-volume entry in
   California political news and was flagged as a candidate to drop; the reviewer
   kept it. Dropping "Sports" from the committee name remains a deliberate
   narrowing — stadium and franchise stories are rarely *policy* stories.

The energy/communications split, the education split, the water split, and the
environment merge were confirmed against the Assembly standing committee list,
which runs each of the split pairs as separate committees.

`government-operations` is the weakest surviving entry — with
`emergency-management` broken out, little remains but gambling, alcoholic
beverage control, horse racing, and procurement. It is the first candidate to
drop if the vocabulary is ever revised.
