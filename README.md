# Java job-alert bot (career sites only, Telegram, free)

Runs on GitHub Actions (free), reads company career sites, and sends a Telegram alert for a NEW job only when its **verified overall experience requirement fits your 2.2 years**,
the description asks for Java, and the city is Hyderabad / Bangalore. No LinkedIn. No Indeed (it blocks automated access and its terms forbid it).

## Files
| File | Purpose |
|---|---|
| `experience.py` | extraction + eligibility engine (data model, statements, conflict resolution, fit rules) |
| `watcher.py` | adapters for career sites, discovery, database, Telegram, reports |
| `companies.yaml` | your 105 companies, filters, your profile (`experience:`), hints |
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
5. **Stage 2 - fit** (`evaluate_candidate_fit`): never changes what stage 1 found. Verified overall minimum > 2.2 -> INELIGIBLE; a range such as 2-4 contains 2.2 -> pass;
   range topping out far below 2.2 -> INELIGIBLE. Skill years (`3+ years Java`) are kept apart and shown **for information only** (`skill_checks: info`); set `strict` to let them decide
   (then only your recorded skills count, no allowance, unknown skill -> NEEDS_REVIEW).
6. **Result**: `ELIGIBLE` -> alert once. `INELIGIBLE` -> stored. `NEEDS_REVIEW` (no / conflicting / ambiguous overall statement, partial or missing description) -> stored, listed in the 10:00 / 16:00 / 23:00 IST report, **never** sent as a match.

Alert example: overall range exactly as written, the evidence sentence and section, skill years on a separate line, eligibility reason, and which source supplied the full description.

## Deploy
1. Upload every file of this folder (including `.github/workflows/watch.yml`) to your repo. 2. Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optional backup route: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`).
3. Actions -> job-watch -> Run workflow -> **selftest**: reports, for each of the 105 companies, the route, jobs read, pagination status, last success, and what failed and why.
4. Run **normal**. For a reliable 10-minute rhythm use the cron-job.org trigger (below). 5. Tests locally: `python test_experience.py && python test_pipeline.py && python evaluate_real.py all`.

### 10-minute trigger (GitHub's own timer is unreliable)
Fine-grained GitHub token (only this repo, Actions: read/write) -> cron-job.org POST `https://api.github.com/repos/<user>/Alerts/actions/workflows/watch.yml/dispatches`,
headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`, body `{"ref":"main","inputs":{"mode":"normal"}}`, every 10 minutes (expect HTTP 204).

## Measuring on your own data
Run the bot locally with `CAPTURE_DIR=captured python watcher.py`; every full description it analyses is saved. Label some and add them to `evaluation/real_labels.json`, then
`python evaluate_real.py all --captured captured`. A false-eligible item makes the command exit non-zero.

## Known limits (nothing here has been run against the live sites by me)
- Sites that publish no `JobPosting` data and no usable listing (fully script-rendered, bot-protected) cannot be read; the self-test names them.
- Postings that state experience only in a table, image, or unusual phrasing become NEEDS_REVIEW instead of being guessed.
- Workday gives the posting DAY, not the hour; a re-listed requisition is recorded as "re-listed", not as a verified repost.
- Sites without posting dates use new-URL detection: the first run is a baseline, so jobs already open then are not alerted.
- A crash between a Telegram send and the next save can in rare cases repeat one alert.
