# Java job alerts for 107 companies

This repository checks the configured employers' public career sites and sends matching roles to Telegram. The company list is in `companies.yaml`; the full numbered list is in `COMPANIES.md`.

## What the watcher does

- Runs on a 10-minute GitHub Actions schedule.
- Uses public career-site/ATS listings first: Workday, Greenhouse, Lever, SmartRecruiters, Eightfold, Oracle HCM, and readable official career pages.
- Checks all 107 employers each run. It starts with your 45 priority employers, polls validated feeds where available, then rechecks unresolved official careers pages every pass so newly exposed feeds can be picked up immediately.
- Tracks each employer's last source status. It sends a Telegram alert when a source starts failing, has no public feed, is available only through the optional secondary feed, or recovers. Scheduled reports also show coverage counts and the companies needing attention.
- Remembers requisition IDs in `state/db.json` so the same opening is not sent repeatedly.
- Keeps the existing Java, Bengaluru/Hyderabad, recency, and experience filters.
- Contains no LinkedIn scraper, endpoint, or fallback.

Adzuna is an optional secondary source for companies whose official page cannot be read. It is queried on each scheduled run only when both `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` are configured. It is not a guarantee that every employer opening appears there.

TheirStack is a second, batched aggregator source. When `THEIRSTACK_API_KEY` is set, one request searches all configured employer names for India-based Java jobs indexed since the prior successful run. Results are paginated up to 1,000 jobs per run; reaching that cap is recorded as incomplete, and the discovery watermark is not advanced. It filters closed jobs and LinkedIn URLs. Provider matching may still miss company-name aliases, so it complements rather than replaces verified official feeds. TheirStack charges one API credit per job returned, including jobs later rejected by the profile filter. Self-test never calls this API; the first normal scheduled or manual run does.

This is polling, so an alert can only arrive after TheirStack has indexed a posting and the next watcher run completes. No API can guarantee discovery at the exact time the employer publishes it. TheirStack recommends webhooks for real-time delivery; that requires a public webhook receiver and hosting, which this GitHub Actions polling workflow does not provide. See [TheirStack's periodic-fetch guidance](https://theirstack.com/en/docs/guides/fetch-jobs-periodically) and [job search API reference](https://theirstack.com/en/docs/api-reference/jobs/search_jobs_v1).

## Coverage limits

All 107 companies are configured, but a company being listed here does not prove that its live feed is readable. Some career pages block automated requests or do not expose a public listing feed. The watcher reports those companies as failed or no-feed; it does not count them as checked successfully. Run the self-test after deployment and resolve every `❌`/`⚪` row before relying on full coverage. A site can also change its feed without notice.

The saved audit validated 28 direct sources in the original 53-company list. This package now has 107 unique entries; duplicate names such as Dell, SAP, Adobe, and Nutanix were consolidated. The 54 additional entries have **not** been individually feed-validated in this update. Your 45 current priority employers are listed in `priority_companies` and are checked first each pass. This is a 107-company watchlist, not a promise of complete listing coverage. Run the included self-test after deployment; resolve each `❌`/`⚪` result or add a verified ATS adapter before relying on that employer's automated listings. DrawBox and LOVIS use provisional best matches, labeled in `COMPANIES.md`.

## Set up Telegram and GitHub

1. Create a Telegram bot with `@BotFather`, start a chat with it, and obtain the bot token and chat ID.
2. Create a **private** GitHub repository and upload the contents of this folder, preserving `.github/workflows/watch.yml`.
3. Under **Settings → Secrets and variables → Actions**, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. Optional aggregator source: create a TheirStack API key and add it as the GitHub Actions secret `THEIRSTACK_API_KEY`. Their API charges credits per returned job; check your plan and balance before enabling it. This remains secondary to official career feeds.
5. Optional broader fallback: add `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` from an Adzuna developer account. This remains secondary to official career feeds.
6. Open **Actions → job-watch → Run workflow**, select `selftest`, and inspect the report. Then run it again in `normal` mode. The schedule runs from the repository's default branch.

For a TheirStack authentication/access diagnostic, manually run the workflow once with mode `theirstack-auth-check`. It sends one GET to the documented credit-balance endpoint, consumes no job-search credits, does not run company feeds, and does not read or write job state. On an error it logs the HTTP status and a sanitized response body; it never prints the API key or authorization header. A 200 verifies that the key is accepted by the account endpoint; a 403 body is needed to distinguish invalid authentication from account/endpoint access restrictions.

The package is prepared but not live until you upload it to your GitHub repository and add the Telegram secrets. TheirStack is also inactive until its API key is saved as an Actions secret. Do not paste any tokens into this project or chat.

The database in `state/` contains job IDs, URLs, match decisions, and status history, so keep the repository private. GitHub's hosted-runner minutes for private repositories depend on the account plan; public repositories avoid those minute charges but expose the repository contents.

## Ten-minute timing

The workflow cron is set to every 10 minutes, away from the top of the hour. GitHub says scheduled runs can be delayed or dropped during high load, so this is an approximately 10-minute schedule, not a hard real-time guarantee. If you need a second clock to dispatch the workflow, a separate scheduler can POST to:

```text
https://api.github.com/repos/<OWNER>/<REPO>/actions/workflows/watch.yml/dispatches
```

Use a narrowly scoped GitHub token with Actions write permission, the `Accept: application/vnd.github+json` and `Content-Type: application/json` headers, and this body:

```json
{"ref":"main","inputs":{"mode":"normal"}}
```

Configure that scheduler for every 10 minutes. The GitHub workflow still needs to finish before the next dispatch; overlapping runs are serialized.

## Files

- `companies.yaml` — all 107 company entries, the 45 priority names, careers URLs, filters, and explicit source overrides.
- `watcher.py` — discovery, career feed readers, matching, Telegram notifications, and health state.
- `.github/workflows/watch.yml` — scheduled and manual workflow.
- `COMPANIES.md` — numbered employer list and source coverage notes.
- `state/source_coverage.csv` — generated after a live run with official ATS/adapter status and separate TheirStack status, latest success, result count, and failure reason for every company.
- `test_watcher.py` — offline regression checks; run locally with `python test_watcher.py` when you want to validate code changes.

## Tune the filters

- `experience.my_years`: current profile experience used by the fit check.
- `filters.locations`: allowed cities.
- `filters.max_age_days`: posting recency window.
- `filters.exclude_title`: titles that should not alert.
- `skills.must_have`: required skill in the job description.
