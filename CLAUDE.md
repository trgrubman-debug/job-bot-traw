# Instructions for AI coding assistants

You're helping a user set up this job-scraping bot. They've dropped the
repo into their editor and expect you to walk them through every step
end-to-end — from picking sources to having a daily digest land in their
chat — without them needing to read the README first.

**Be opinionated.** Don't ask open-ended "what do you want?" questions.
Recommend a sensible default, briefly explain the tradeoff, and let them
override. The walkthrough below tells you exactly what to recommend.

## What the bot does

Scrapes job boards, dedupes against a local SQLite DB, and posts new
listings to Discord or Telegram on a schedule. The architecture:

- `job_bot.py` — orchestrator (config loading, dedup, dispatch).
- `scrapers.py` — one function per source. Registered in `SCRAPERS` dict.
- `notifiers.py` — one class per channel. Registered in `NOTIFIERS` dict.
- `config.yaml` — what to scrape, what to filter, where to post, volume cap.
- `.env` — secrets (webhook URL, bot tokens). Gitignored.

# The walkthrough — ask these questions in this order

## Step 1 — install dependencies

Run this immediately, before any questions:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
cp .env.example .env
```

Then start the conversation.

## Step 2 — what are you searching for?

Ask: **"What kind of jobs are you looking for, and where? (one sentence,
e.g. 'product designer roles in NYC' or 'data engineer, remote-US')"**

Use their answer to drive every subsequent choice. Map it like this:

| Their field | Recommend these `title_keywords` |
| --- | --- |
| Software engineer | `software engineer`, `swe`, `backend engineer`, `frontend engineer`, `full stack`, `staff engineer`, `senior engineer`, `principal engineer` |
| Product manager | `product manager`, `senior pm`, `principal pm`, `group pm`, `head of product` |
| Designer | `product designer`, `senior designer`, `design lead`, `ux designer`, `ui designer`, `design manager` |
| Marketing / growth | `marketing manager`, `growth manager`, `growth lead`, `head of marketing`, `performance marketing`, `lifecycle marketing`, `content marketing`, `brand manager` |
| Data / ML | `data scientist`, `machine learning`, `ml engineer`, `applied scientist`, `research engineer`, `ai engineer`, `llm engineer` |
| Operations | `operations`, `ops`, `chief of staff`, `business operations`, `strategy & ops`, `program manager`, `project manager`, `coo` |
| Sales | `account executive`, `ae`, `sdr`, `bdr`, `sales lead`, `sales manager`, `head of sales` |
| Finance | `finance manager`, `controller`, `analyst`, `cfo`, `treasury`, `accounting` |

Show them your proposed list. Ask if they want to add or remove any.

## Step 3 — which sources should we scrape?

This repo ships 5 sources. **Don't just enable all of them** — recommend
based on their field:

| Field | Enable these sources |
| --- | --- |
| Anything crypto / web3 | web3career, cryptocurrencyjobs, cryptojobslist, linkedin |
| Tech (eng, design, PM, data) at startups | builtin, linkedin |
| Tech at big companies / FAANG | linkedin (only — Built In skews startup) |
| AI / ML specifically | builtin (it has a great AI ops section), linkedin |
| Non-tech (marketing, sales, finance) | builtin, linkedin |

Edit `config.yaml`:

- Set `enabled: false` on any source you're not using.
- For `builtin.pages`, replace the default URLs with ones for their field.
  Browse [builtin.com/jobs](https://builtin.com/jobs) and
  [builtinnyc.com/jobs](https://www.builtinnyc.com/jobs), copy the category
  URLs that match, paste them into `pages:`.
- For `linkedin.searches`, build the URLs by running a job search on
  linkedin.com with the keyword + location + date filters you want, then
  copy each URL. Use `f_TPR=r86400` for "posted in last 24h" — the bot is
  much less noisy with that filter.

## Step 4 — location and volume

Ask: **"What city, and are you open to remote?"**

Use the answer to fill `location_filter`:

```yaml
location_filter:
  enabled: true
  cities_allow: ["<their city>", "<nearby neighborhoods>"]
  cities_block: []                            # cities to reject by name
  remote_allow: true                          # set false if NYC-only, etc.
  remote_geo_allow: ["us", "usa", "united states"]   # who they'll work for
  reject_unknown_locations: true              # safer default
```

If they say "anywhere remote," set `remote_geo_allow: []` (any region).
If they say "in-office only," set `remote_allow: false`.

Ask: **"How many jobs per day do you want to see — small digest (5–10),
medium (10–20), or send-me-everything?"**

Recommend **10–20** (`max_jobs_per_run: 15`). It's the sweet spot for a
daily scan.

## Step 5 — pick a notifier

Ask: **"Discord or Telegram?"**

Default recommendation: **Telegram** — easier to set up (no server
needed, just message a bot), works on phone out of the box, and the
formatting is cleaner. Discord is only better if they already run a
server they want the digest in.

### Telegram walkthrough

Walk them through this exactly:

1. Open Telegram. Search for `@BotFather` and start a chat.
2. Send `/newbot`. Pick a name (any), then a username ending in `bot`
   (e.g. `johns_job_bot`).
3. **Copy the token BotFather sends you** — it looks like
   `7234567890:AAEx...`. This goes in `.env` as `TELEGRAM_BOT_TOKEN`.
4. Find your new bot in Telegram by its username and send it any
   message (just "hi" works).
5. In your browser, visit:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   (paste the token in place of `<YOUR_TOKEN>`).
6. In the JSON response, find `"chat":{"id":...}`. That number is your
   `TELEGRAM_CHAT_ID`.

Write both into `.env`. Set `notifiers.telegram.enabled: true` and
`notifiers.discord.enabled: false` in `config.yaml`.

### Discord walkthrough

1. In their Discord server: **Server Settings → Integrations → Webhooks
   → New Webhook**.
2. Pick the channel, click **Copy Webhook URL**.
3. Paste it into `.env` as `DISCORD_WEBHOOK_URL`.
4. Set `notifiers.discord.enabled: true` in `config.yaml`.

## Step 6 — dry-run to confirm

Always run this first:

```bash
python3 job_bot.py --dry-run
```

It prints exactly what would be posted, without notifying. If the list
looks right, move on. If the list is empty, the filter is probably too
strict — loosen `title_keywords` or `location_filter`.

## Step 7 — pick how it runs every day

Ask: **"Where do you want this to run? Three options, ranked from
easiest to most-control:"**

1. **GitHub Actions (free, no server)** — runs in the cloud, you don't
   manage anything. Best for most people. Setup below.
2. **Your laptop (free, simple)** — only runs while your laptop is on.
   OK if you keep it on overnight, bad otherwise.
3. **A small VPS like DigitalOcean ($4/mo)** — most control, runs 24/7.
   Worth it if they already have a VPS or want one for other projects.

### Option 1: GitHub Actions (recommended)

1. Have them **fork this repo** to their own GitHub account.
2. Copy `examples/github-actions.yml.example` to
   `.github/workflows/job-bot.yml` in their fork.
3. In the fork on GitHub: **Settings → Secrets and variables → Actions
   → New repository secret**. Add each of the secrets they wrote into
   `.env` (e.g. `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
4. Commit and push their `config.yaml` to the fork (it's gitignored by
   default; they can add a `!config.yaml` line to `.gitignore` to track
   their version).
5. On GitHub: **Actions tab → enable workflows → run "job-bot" manually
   once** to confirm it works. After that it runs daily on the schedule.

### Option 2: Run on your laptop (macOS / Linux)

Add a `cron` entry. On macOS run `crontab -e` and paste:

```cron
0 9 * * * cd /path/to/job-bot && /path/to/job-bot/venv/bin/python3 /path/to/job-bot/job_bot.py >> /path/to/job-bot/cron.log 2>&1
```

Replace `/path/to/job-bot` with the absolute path (use `pwd` inside the
repo to get it). 9 AM local; edit the hour to taste.

### Option 3: DigitalOcean droplet

If they don't have a VPS yet:

1. Sign up at [digitalocean.com](https://www.digitalocean.com/).
2. **Create → Droplets → Ubuntu 22.04 LTS → Basic → Regular SSD
   ($4/mo)**. Pick the region closest to them.
3. Set the auth method to **SSH key**. If they don't have one:
   ```bash
   ssh-keygen -t ed25519     # accept defaults
   cat ~/.ssh/id_ed25519.pub  # copy this into DigitalOcean's "Add SSH Key" form
   ```
4. Once the droplet is up, grab its IP from the dashboard.

Then deploy:

```bash
# From your laptop, replace <IP> with the droplet's address.
ssh root@<IP> "apt update && apt install -y python3 python3-venv git"
ssh root@<IP> "git clone https://github.com/<their-username>/job-bot /opt/job-bot"
scp config.yaml .env root@<IP>:/opt/job-bot/
ssh root@<IP> "cd /opt/job-bot && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"

# Sanity check on the server:
ssh root@<IP> "cd /opt/job-bot && ./venv/bin/python3 job_bot.py --dry-run"

# Install the cron job:
ssh root@<IP> "(crontab -l 2>/dev/null; echo '0 9 * * * cd /opt/job-bot && /opt/job-bot/venv/bin/python3 /opt/job-bot/job_bot.py >> /opt/job-bot/cron.log 2>&1') | crontab -"
```

The cron runs daily at 9 AM UTC by default; ask them what time they want
and convert their local time to UTC before writing the entry.

## Customization cheat sheet (for follow-up requests)

| User asks | Where to edit |
| --- | --- |
| Different job titles | `title_keywords` in `config.yaml` |
| Different city / country | `location_filter` in `config.yaml` |
| Accept remote-anywhere | Set `remote_geo_allow: []` |
| Accept any location at all | Set `location_filter.enabled: false` |
| Fewer / more jobs per day | `max_jobs_per_run` (5–10 tight, 10–20 default, 30+ everything) |
| New job board | New function in `scrapers.py` + register in `SCRAPERS` dict |
| Slack / email / SMS notifier | New `Notifier` subclass in `notifiers.py` + register in `NOTIFIERS` dict |
| LinkedIn search needs different filters | Edit URLs under `sources.linkedin.searches` |

Always re-run `python3 job_bot.py --dry-run` after config changes so the
user can see the new filter take effect.

## Things to avoid

- **Don't commit `.env`** — ever. Confirm with `git status` before any
  `git add .`. The `.gitignore` already covers it, but be explicit.
- **Don't hardcode secrets** anywhere. They go in `.env` (local) or
  GitHub Actions Secrets (CI). Never in `config.yaml`.
- **Don't reset `seen_jobs.db` casually** — that's how the user gets a
  flood of "new" jobs on the next run. Ask first.
- **Don't install dependencies system-wide** on macOS. Always use the
  project venv (the user might be on a PEP 668 system).
- **Don't enable every source by default.** Recommend based on field
  (see Step 3 table). More sources ≠ better; signal-to-noise drops fast.

## Testing changes

```bash
source venv/bin/activate
python3 job_bot.py --dry-run
```

A successful run prints each scraper's count and a list of jobs that
would have been sent. If a scraper returns 0, the site's HTML probably
changed — inspect the page in a browser and adjust selectors in
`scrapers.py`.
