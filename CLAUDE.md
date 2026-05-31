# Instructions for AI coding assistants

If you've been pointed at this repo by a user who wants to use the bot,
here's exactly what to do.

## Project context

This is a job-scraping bot. It reads `config.yaml`, scrapes the enabled
sources, dedupes against a SQLite DB, and posts new jobs to the enabled
notifiers (Discord and/or Telegram). It runs once per invocation — schedule
it with cron or systemd to get daily digests.

Single-file-per-concern layout:

- `job_bot.py` — orchestrator (config loading, dedup, dispatch).
- `scrapers.py` — one function per source. Registered in `SCRAPERS` dict at
  the bottom of the file.
- `notifiers.py` — one class per channel. Registered in `NOTIFIERS` dict at
  the bottom.
- `config.yaml` — what to scrape, what to filter, where to post.
- `.env` — secrets (webhook URL, bot tokens). Gitignored.

## First-run setup

Run these commands in order. The user does **not** need to do anything
manually except provide the secret values when prompted.

```bash
# 1. Create a virtualenv and install dependencies.
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Initialize config and secrets from templates.
cp config.example.yaml config.yaml
cp .env.example .env

# 3. Ask the user which notifier(s) they want to use.
#    Then ask for the corresponding secrets and write them into .env:
#      - Discord:  DISCORD_WEBHOOK_URL
#      - Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
#    (Edit config.yaml `notifiers:` to disable any they don't want.)

# 4. Ask the user what they're searching for, then edit config.yaml:
#    - `title_keywords` — substrings the job title must contain.
#    - `location_filter.cities_allow` — cities to accept.
#    - `location_filter.remote_geo_allow` — which remote regions are ok.
#    - `sources:` — disable any boards they don't care about.

# 5. Dry-run to confirm everything works without posting:
python3 job_bot.py --dry-run

# 6. Live run (will actually post to the configured notifier):
python3 job_bot.py
```

## Scheduling (optional)

If the user wants daily delivery, install a cron entry. See
`examples/crontab.example` for the line. The line below runs daily at 9 AM
UTC; adjust the path to wherever the repo lives:

```cron
0 9 * * * cd /path/to/job-bot && /path/to/job-bot/venv/bin/python3 /path/to/job-bot/job_bot.py >> /path/to/job-bot/cron.log 2>&1
```

For systemd (Linux servers), see `examples/systemd.service.example`.

## Helping the user customize

Common requests and where to make the change:

| Request | What to edit |
| --- | --- |
| Track a different industry / role | `title_keywords` in `config.yaml` |
| Different city / country | `location_filter` in `config.yaml` |
| Accept remote-anywhere | Set `remote_geo_allow: []` in `config.yaml` |
| Accept any location at all | Set `location_filter.enabled: false` |
| Add a new job board | New function in `scrapers.py` + register in `SCRAPERS` dict |
| Add Slack / email / SMS | New `Notifier` subclass in `notifiers.py` + register in `NOTIFIERS` dict |
| LinkedIn search needs different filters | Edit URLs under `sources.linkedin.searches` |

Always re-run `python3 job_bot.py --dry-run` after config changes so the
user can verify the filter before the next live post.

## Things to avoid

- **Don't commit `.env` or `config.yaml`** — both are gitignored for a
  reason. Confirm with `git status` before any `git add .`.
- **Don't hardcode secrets** anywhere. They go in `.env`, period.
- **Don't bypass dedup** by deleting `seen_jobs.db` casually. If you do
  need to reset, ask first — the user may have weeks of state in there.
- **Don't install dependencies system-wide** on macOS. Always use the
  project venv (the user might be on a PEP 668 system).

## Testing changes

There are no formal tests. To verify after a code change:

```bash
source venv/bin/activate
python3 job_bot.py --dry-run
```

A successful run will print each scraper's count and a list of jobs that
would have been sent. If a scraper returns 0, the source's HTML likely
changed — inspect the page and adjust the selectors in `scrapers.py`.
