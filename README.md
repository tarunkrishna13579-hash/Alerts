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
4. Actions tab -> "job-watch" -> Run workflow -> mode **selftest**. In ~3-5 minutes Telegram shows which
   companies work on fast direct feeds, which use the slower LinkedIn fallback, and which failed.
   If that report is bad, you've lost 10 minutes, not days.
5. Run workflow again with mode **normal** (it then repeats automatically every ~10 min).
   The first run sends currently open matching jobs (max 20 per run, posted in the last 14 days),
   then only new ones.

## Tuning (companies.yaml)
- experience.max_min_years: 2 -> set 3 to also accept "3-5 years" roles.
- filters.exclude_title: remove "senior" if you want those too.
- hints: if a company shows ❌, put its Workday/Greenhouse/Lever details there.

## Honest limits
- Experience and skills are read from the job description text. If it's missing, you get the alert marked "not stated" / "JD not readable".
- Companies with no open job feed (many bank/big-tech sites) use LinkedIn's public search: slower (30+ min) and can be blocked.
- GitHub's scheduler can delay runs by a few minutes.
