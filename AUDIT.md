# Audit of the previous implementation (before this change)

Scope inspected: `watcher.py`, `test_watcher.py`, `companies.yaml`, `COMPANIES.md`, all source adapters, persistence (`state/*.json`), scheduler (`watch.yml`), Telegram delivery.
Baseline tests: the previous synthetic suite (sections A-E) passed when last run, before this work. It could not catch the defects below because it only contained inputs written to match the parser.

## Defects found by probing the old parser with real-world wording
| Input | Old result | Problem |
|---|---|---|
| `between 2 and 4 years of experience` | overall = 4 years | silently dropped the lower bound |
| `Exp: 4-6 Years` / value on the line after an `Experience Required :` heading | not recognised / dropped | very common posting header style |
| `3 years' experience ...` (typographic apostrophe), `five-plus years` | not recognised | |
| `Total exp of 4+ years in Java Development.` | skill-specific only, no overall | explicit "Total" wording ignored |
| `Team Leader (7-10 Years Experience).` | ambiguous | parenthetical style |
| label `Basic qualifications:` | treated as education, statement discarded | heading mistaken for content |
| `2+ years` plus `minimum 3 years` | "conflict" | compatible statements should combine (stricter minimum) |
| unlisted skill, e.g. mandatory `AWS 3+` | allowed up to total experience + 1 year | an assumption, not evidence |
| description length >= 150 chars | "complete" | length is not completeness |
| Oracle HCM / SmartRecruiters / Eightfold | one request per search term | later pages silently missed |
| description changed after first look | never re-checked | stale decisions |
| LinkedIn fallback | blocked from GitHub servers | no value; removed |

## What was correct and is kept
Persistent job database and dedupe by requisition id, delivery-confirmed publishing, pending retry, scheduled reports, company config, Adzuna as an optional backup route, `state/seen.json` migration.

## What changed (see README for architecture)
`experience.py` (new): data model, extraction, conflict resolution, eligibility. `watcher.py`: adapters (career-site sitemap / job-list / Workday root resolver, paging), retrieval status, revalidation, health, reports. LinkedIn removed.
