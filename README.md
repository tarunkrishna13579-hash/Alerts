# Free Java Job Alert Bot -> Telegram   (ONE GitHub repo, ₹0)

Every ~10 minutes GitHub runs this for you. It checks the career sites of your 53 companies and
sends a Telegram message only for jobs that fit: Java / Spring Boot / REST / microservices,
Bangalore or Hyderabad, and a required experience that includes your 2 years (0-3, 1-3, 2-4, 2-5, "2+").
Each job is sent ONCE (the job ID is remembered in state/seen.json). You never add jobs yourself.

## Setup (about 10 minutes)
1. Telegram: search @BotFather -> /newbot -> copy the TOKEN. Send "hi" to your new bot.
   Open https://api.telegram.org/bot<TOKEN>/getUpdates -> copy the number after "chat":{"id": -> CHAT ID.
2. GitHub: new repo, **Public** (free unlimited minutes; your token stays hidden in Secrets). Upload
   everything in this folder, keeping the .github/workflows/watch.yml path.
3. Repo -> Settings -> Secrets and variables -> Actions -> New repository secret:
   TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
4. Actions tab -> "job-watch" -> Run workflow -> mode **selftest**. The report distinguishes validated direct feeds,
   authorized Adzuna fallback, failed source reads, and companies that currently have no validated automatic feed.
   LinkedIn is disabled by default because automated access is frequently rate-limited; it is not a reliable fallback.
5. Run workflow again with mode **normal** (it then repeats automatically every ~10 min).
   The first run sends currently open matching jobs (only jobs posted in the last 2 days),
   then only new ones.

## Tuning (companies.yaml)
- experience.max_min_years: 2 -> set 3 to also accept "3-5 years" roles.
- filters.exclude_title: remove "senior" if you want those too.
- hints: if a company shows ❌, put its Workday/Greenhouse/Lever details there.

## Honest limits
- Experience and skills are read from the job description text. If the full description is missing, the job remains unverified / NEEDS_REVIEW.
- LinkedIn fallback is disabled by default. A company without a validated feed is listed with its official careers URL rather than being silently treated as checked.
- When Adzuna credentials are configured, it is used as a secondary feed for companies without a validated direct feed and for temporary direct-feed failures. Adzuna coverage is not guaranteed to be complete.
- A direct feed is only confirmed after the self-test reads and parses jobs; a configured hint alone is not proof of coverage.
- Workday HTTP 429 responses honor Retry-After where possible, use bounded backoff, and stop candidate discovery rather than probing many guessed tenant/site combinations.
- GitHub's scheduler can delay runs by a few minutes.

## Make it run every 10 minutes for real (GitHub's own timer is unreliable)
GitHub's schedule often skips runs (you saw 2 runs in 6 hours). Fix: a free outside timer wakes the workflow.
1. GitHub -> profile picture -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens
   -> Generate new token. Repository access: **Only select repositories -> Alerts**.
   Permissions -> Repository permissions -> **Actions: Read and write**. Generate and copy the token (keep it private).
2. Sign up free at https://cron-job.org -> Create cronjob:
   - URL: https://api.github.com/repos/<YOUR-GITHUB-USER>/Alerts/actions/workflows/watch.yml/dispatches
   - Schedule: every 10 minutes
   - Advanced -> Request method: **POST**
   - Headers: `Authorization: Bearer <YOUR TOKEN>` , `Accept: application/vnd.github+json` , `Content-Type: application/json`
   - Request body: `{"ref":"main","inputs":{"mode":"normal"}}`
3. Save, press "Test run" (expect HTTP 204). Check the Actions tab: runs appear every ~10 minutes.

## Companies with no validated direct career feed -> optional Adzuna key
For companies without a validated direct source, the bot uses Adzuna only if configured. LinkedIn is not the default fallback.
Adzuna is a supplementary job-board API that can list recent Java jobs in Hyderabad/Bangalore. The bot keeps only listings whose company name matches your configured companies.
1. Sign up free at https://developer.adzuna.com/ and copy your **Application ID** and **Application Key**.
2. Repo -> Settings -> Secrets and variables -> Actions -> add two secrets:
   `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
3. Run **selftest**. Lines with 🟣 show companies now covered through Adzuna.
Limits: Adzuna's text may be a short snippet, so the bot tries the job page and otherwise marks experience NEEDS_REVIEW; jobs can appear
10-60 minutes after the company posts them; Adzuna may not list every company's jobs. Companies without an automatic feed remain visible in self-test with their official careers URL.

## Title filter
companies.yaml -> filters.use_title_filter: false  means job TITLES are ignored: any job in Hyderabad/Bangalore,
posted in the last 2 days, whose description asks for Java (and whose required experience fits 2 years) is sent.

## Persistent job database (no duplicate alerts)
- `state/db.json` is the memory. Every job gets a record: company, title, official requisition id, URL, source, posted label,
  first-seen / last-checked, experience found, eligibility (eligible / unverified / ineligible / duplicate), publication
  (pending / published) and first-published time. It is committed to the repo after each run, so every run (timer, manual, restart) shares it.
- Identity = company + official requisition id. A different id is a different vacancy even if the title is identical.
  Job-board copies (Adzuna) are matched to official-site copies by company + title + city and recorded as duplicates.
- Known jobs are skipped without downloading or analysing the description again.
- A job is marked published only after Telegram confirms delivery; failures stay pending and are retried (never re-analysed).
- Re-listings of a known requisition (Workday page path changes -1 -> -2) are recorded and NOT re-sent (repost_alert: false).
- Reports at 10:00, 16:00 and 23:00 IST show counts: new, known skipped, duplicates, eligible / unverified / ineligible, sent, failed, re-listed, top companies.

## Experience rules (what an alert guarantees)
Every alert shows the employer's VERIFIED overall experience in their own words, plus the exact JD sentence. Skill-specific years
(e.g. "3+ years Java", "2+ years AWS") are kept on a separate line and are never shown as the overall requirement.
Overall is taken only from statements about the whole role in mandatory sections; preferred lines are ignored; if the overall requirement
is missing, conflicting, or the description is incomplete the job is stored as NEEDS_REVIEW and appears only in the 10/16/23 IST report, never as a match.
Fit uses experience.my_years (2.2) in companies.yaml; COMPANIES.md lists all 53 companies and how each is covered.
