# job-bot

A small, pluggable bot that scrapes job boards on a schedule and posts new
listings to Discord, Telegram, or any channel you wire up. Everything is
driven by a single YAML config — sources, keywords, location filter, and
notifiers all live in one file.

Originally built to track crypto + AI operations roles in NYC and remote, but
the filters are config-driven so it works for any niche.

## Features

- **5 sources out of the box:** web3.career, cryptocurrencyjobs.co,
  cryptojobslist.com, builtin.com / builtinnyc.com, LinkedIn public search.
- **Pluggable notifiers:** Discord (webhook), Telegram (bot API). Easy to
  add Slack, email, SMS, etc.
- **Smart dedup:** SQLite-backed; collapses near-duplicates and LinkedIn's
  per-country-subdomain repeats.
- **Title + location filters:** purely config-driven (no code changes for
  new keywords or cities).
- **Heartbeat option:** Optional "no new jobs today" ping so you know the
  cron is alive.
- **One-file-per-concern layout:** `scrapers.py`, `notifiers.py`,
  `job_bot.py`. Easy to read, easy to extend.

## Quickstart

```bash
git clone https://github.com/cprkrn/job-bot.git
cd job-bot

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
cp .env.example .env

# Edit config.yaml to choose sources, keywords, location filters.
# Edit .env to add your Discord webhook URL and/or Telegram bot credentials.

python3 job_bot.py --dry-run   # see what would be posted
python3 job_bot.py             # post for real
```

### Using an AI coding assistant (Claude Code, Cursor, etc.)

Just clone the repo, open it in your editor, and tell the assistant:

> _"Set this up for me — I want to track [your keywords] in [your city]
> and get a daily digest in [Discord / Telegram]."_

The assistant will read [`CLAUDE.md`](CLAUDE.md) at the repo root for
exact setup steps, then ask you for whichever secrets it needs.

## Setting up a notifier

### Discord

1. In your Discord server: **Server Settings → Integrations → Webhooks → New
   Webhook**.
2. Pick the channel, click **Copy Webhook URL**.
3. Paste it into `.env`:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
   ```
4. In `config.yaml`, set `notifiers.discord.enabled: true`.

### Telegram

1. Message [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot`,
   and grab the bot token.
2. Start a chat with your new bot (or add it to a group / channel).
3. Find your chat ID by sending the bot a message, then visiting:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Look for `"chat":{"id": ...}`.
4. Paste both into `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=987654321
   ```
5. In `config.yaml`, set `notifiers.telegram.enabled: true`.

## Configuring sources

Every source is enabled/disabled in `config.yaml`. Most accept URL parameters
you can tweak — e.g. point `web3career.url` at any of the category pages on
web3.career, or build your own LinkedIn search URL and paste it into
`linkedin.searches`.

### Building a LinkedIn search URL

LinkedIn's public job search supports filters as query params:

| Param        | Meaning                                              |
| ------------ | ---------------------------------------------------- |
| `keywords=`  | The search query                                     |
| `f_TPR=r86400` | Posted in the last 24 hours (86,400 seconds)       |
| `f_TPR=r604800` | Posted in the last 7 days                         |
| `f_WT=2`     | Workplace type = remote                              |
| `geoId=105080838` | New York City metro (look up other geoIDs online) |

Build a search in the normal LinkedIn UI, copy the URL, and paste it under
`sources.linkedin.searches` in `config.yaml`.

## Configuring filters

### Title filter

`title_keywords` is a list of substrings — a job's title needs to match at
least one (case-insensitive). Empty list = accept every title.

### Location filter

The default config is tuned for **NYC + remote-US**. To accept anywhere:

```yaml
location_filter:
  enabled: false
```

To accept only a specific city + EU remote:

```yaml
location_filter:
  enabled: true
  cities_allow: ["berlin"]
  cities_block: []
  remote_allow: true
  remote_geo_allow: ["eu", "europe", "germany"]
  reject_unknown_locations: true
```

`reject_unknown_locations: true` is the safer default — if a scraper can't
parse a location, the job is skipped. Set to `false` to be permissive.

## Adding your own source

Open `scrapers.py` and add a function:

```python
def scrape_mysite(cfg):
    jobs = []
    url = cfg.get("url", "https://example.com/jobs")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    for card in soup.select("div.job"):
        jobs.append({
            "title":    card.select_one("h2").get_text(strip=True),
            "company":  card.select_one(".company").get_text(strip=True),
            "url":      card.select_one("a")["href"],
            "posted":   "",
            "location": card.select_one(".loc").get_text(strip=True),
            "source":   "mysite",
        })
    return jobs
```

Then register it in the `SCRAPERS` dict at the bottom of the file:

```python
SCRAPERS = {
    ...
    "mysite": scrape_mysite,
}
```

And reference it in `config.yaml`:

```yaml
sources:
  mysite:
    enabled: true
    url: https://example.com/jobs
```

## Adding your own notifier

Open `notifiers.py` and subclass `Notifier`:

```python
class SlackNotifier(Notifier):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.webhook = os.environ.get("SLACK_WEBHOOK_URL", "")

    def send_jobs(self, new_jobs, total_scanned):
        ...

    def send_heartbeat(self, total_scanned):
        ...
```

Register it:

```python
NOTIFIERS = {
    ...
    "slack": SlackNotifier,
}
```

And enable it in `config.yaml`:

```yaml
notifiers:
  slack:
    enabled: true
    heartbeat_when_empty: false
```

## Deploying on a schedule

### Cron (Linux / macOS)

See `examples/crontab.example`. The line below runs daily at 9 AM UTC:

```
0 9 * * * cd /opt/job-bot && /opt/job-bot/venv/bin/python3 /opt/job-bot/job_bot.py >> /opt/job-bot/cron.log 2>&1
```

### systemd (Linux)

See `examples/systemd.service.example` for a unit + timer pair.

### macOS launchd

You can also use `launchd` plists — but cron via `crontab -e` is the simplest
on macOS too.

## How dedup works

After every scrape, each job's `(title, company, normalized_url)` tuple is
hashed and looked up in a local SQLite file (`seen_jobs.db` by default). New
hashes get inserted; matches are skipped.

For LinkedIn specifically, the dedup key is just `(title, company)` because
LinkedIn syndicates the same role across country subdomains (`mx.linkedin.com`,
`hk.linkedin.com`, etc.) with different numeric IDs.

Within a single run, near-duplicates are also collapsed into one entry with
a `×N` suffix in the message.

## Troubleshooting

- **403 from a source:** The site is likely behind Cloudflare. Make sure
  `cloudscraper` is installed (`pip install cloudscraper`). It's optional but
  required for `cryptojobslist`.
- **0 jobs scraped:** The site's HTML probably changed. Run with
  `log_level: DEBUG` and inspect the page in a browser.
- **Discord posts nothing:** Check that `DISCORD_WEBHOOK_URL` is set in
  `.env` and the notifier is enabled in `config.yaml`. Try `--dry-run` to
  confirm scraping works.
- **Telegram says "chat not found":** Make sure you've sent at least one
  message to the bot first. Then re-fetch the chat ID via `getUpdates`.

## License

[MIT](LICENSE) — do whatever, no warranty.

## Contributing

PRs welcome, especially new scrapers and new notifiers. Keep the surface
area small and config-driven.
