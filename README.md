# Java job-alert bot (career sites only, Telegram, free)

Runs on GitHub Actions (free), reads company career sites, and sends a Telegram alert for a NEW job only when its **verified overall experience requirement fits your 2.3 years**,
the full description mentions Java, the role title matches the Java/backend title allowlist, the location is in India (including Remote - India), and the posting is no older than 48 hours. Spring Boot is preferred, not mandatory. No LinkedIn. No Indeed.

## Files
| File | Purpose |
|---|---|
| `experience.py` | extraction + eligibility engine (data model, statements, conflict resolution, fit rules) |
| `watcher.py` | adapters for career sites, discovery, database, Telegram, reports |
| `merge_state.py` | conflict-aware merge of concurrent JSON state commits |
| `test_stability.py` | tests for rate-limit handling, Workday detail parsing, and state merging |
| `companies.yaml` | your 112 companies, filters, your profile (`experience:`), hints |
| `test_experience.py`, `test_pipeline.py`, `evaluate_real.py`, `evaluation/real_labels.json` | tests and measurement |
| `AUDIT.md`, `COMPANIES.md` | what was wrong before; per-company source and honest status |
| `.github/workflows/watch.yml` | schedule / manual run; runs the tests first |

## How a job is decided
1. **Discovery** - per company the first route that works is used (and remembered): configured hint -> ATS link on the careers page -> Workday site name from the tenant root ->
   the site's sitemap (`robots.txt`) -> job links on the careers page. Sitemap / page-list routes are accepted only if job pages carry schema.org `JobPosting` data.
   Workday, Oracle, Greenhouse, Lever, SmartRecruiters, Eightfold use their public job feeds, with paging.
2. **Known jobs are skipped** (identity = company + official requisition id; cross-site copies matched by company+title+city). Nothing is re-downloaded unless the description changed
   or a needs-review job is retried (every 6 h, max 5 times).
3. **Full description** is fetched; status is recorded: `FULL_EMPLOYER`, `FULL_JOBBOARD`, `PARTIAL_SNIPPET`, `INACCESSIBLE`, `EMPTY`. Only FULL_* can verify anything. Length is only a warning.
4. **Stage 1 - extraction** (`extract_experience_requirements`): every duration becomes a record (raw text, scope, mandatory/preferred, min/max, section, character offsets).
   Scopes: OVERALL, SKILL_SPECIFIC, ROLE_DOMAIN, EDUCATION, COMPANY_HISTORY, OTHER, UNKNOWN. Education years, company history, time frames and preferred / optional lines never count.
   Overall statements are combined by interval intersection (`2+` and `min 3` -> 3+, both kept and the derivation written down); disjoint ones (`2-4` vs `min 5`) = conflict.
5. **Stage 2 - fit** (`evaluate_candidate_fit`): never changes what stage 1 found. Verified overall minimum > 2.3 -> INELIGIBLE; a range such as 2-4 contains 2.3 -> pass;
   range topping out far below 2.3 -> INELIGIBLE. Skill years (`3+ years Java`) are kept apart and shown **for information only** (`skill_checks: info`); set `strict` to let them decide
   (then only your recorded skills count, no allowance, unknown skill -> NEEDS_REVIEW).
6. **Result**: `ELIGIBLE` -> alert once. `INELIGIBLE` -> stored. `NEEDS_REVIEW` (no / conflicting / ambiguous overall statement, partial or missing description) -> stored, listed in the 10:00 / 16:00 / 23:00 IST report, **never** sent as a match.

Alert example: overall range exactly as written, the evidence sentence and section, skill years on a separate line, eligibility reason, and which source supplied the full description.

## Deploy
1. Upload every file of this folder (including `.github/workflows/watch.yml`) to your repo. 2. Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optional backup route: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`).
3. Actions -> job-watch -> Run workflow -> **selftest**: reports, for each configured company, the route, jobs read, pagination status, last success, and what failed and why.
4. Run **normal**. The included workflow schedule is every 30 minutes. Do not also enable cron-job.org at the same time. 5. Tests locally: `python test_experience.py && python test_pipeline.py && python test_stability.py`.

### Final job-alert rules
- Candidate total experience: **2.3 years**. The employer's verified overall experience requirement must fit this profile. Skill-specific years remain informational only.
- Mandatory skill: **Java must appear in the full job description**. A Java title or search keyword alone is insufficient.
- Preferred skill: **Spring Boot**. Its absence does not reject an otherwise eligible Java role. Other resume skills are relevance signals, not mandatory gates.
- Posting age: **48 hours maximum**. If the source does not provide a verifiable posting age, the job is `NEEDS_REVIEW` and is not alerted.
- Location: **India-wide**, including explicitly `Remote - India` roles. A bare `Remote` without India context is `NEEDS_REVIEW`; known non-India locations are rejected. When available, city/state is included in Telegram.
- Titles: allowlisted Java/backend software titles (SDE 1/2, Software Engineer/Developer, Java Developer, Java Backend Engineer/Developer, Backend Engineer/Developer, Associate Software Engineer, MTS, Product/Platform Engineer, API/Microservices Developer, and Java full-stack variants), with QA, frontend, DevOps, senior/lead/manager/architect and unrelated roles excluded.
- Duplicates: one notification per official requisition; re-listed jobs are not re-alerted by default.
- Only a full verified description and a verified eligible overall-experience decision can trigger an alert. `NEEDS_REVIEW` and `INELIGIBLE` are never match alerts.

The included workflow has a 30-minute GitHub schedule. Do not also enable cron-job.org at the same time.

## Measuring on your own data
Run the bot locally with `CAPTURE_DIR=captured python watcher.py`; every full description it analyses is saved. Label some and add them to `evaluation/real_labels.json`, then
`python evaluate_real.py all --captured captured`. A false-eligible item makes the command exit non-zero.

## Known limits (nothing here has been run against the live sites by me)
- Sites that publish no `JobPosting` data and no usable listing (fully script-rendered, bot-protected) cannot be read; the self-test names them.
- Postings that state experience only in a table, image, or unusual phrasing become NEEDS_REVIEW instead of being guessed.
- Workday gives the posting DAY, not the hour; a re-listed requisition is recorded as "re-listed", not as a verified repost.
- Sites without posting dates use new-URL detection: the first run is a baseline, so jobs already open then are not alerted.
- Telegram does not provide an idempotency key for `sendMessage`; a crash after Telegram accepts a message but before the bot saves the confirmation can still rarely repeat an alert. The state merge prevents lost job records and prevents a confirmed `published` record from being downgraded to `pending`, but mathematically exact-once delivery across Telegram and Git cannot be guaranteed without an external transactional outbox.
