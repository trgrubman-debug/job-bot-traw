"""
notifiers.py — one class per notification channel.

Each notifier exposes a `send_jobs(new_jobs, total_scanned)` method that
formats and sends a digest. Secrets come from environment variables (so
they never end up in a config file or git history).

To add a new notifier (e.g. Slack, email, SMS):
  1. Subclass `Notifier` below.
  2. Register it in the NOTIFIERS dict at the bottom.
  3. Reference it by that key in config.yaml under `notifiers:`.
"""

import logging
import os
import time
from datetime import datetime

import requests

log = logging.getLogger("job_bot.notifiers")


class Notifier:
    """Base class. Subclasses override `send_jobs` and `send_heartbeat`."""

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.heartbeat_when_empty = bool(self.cfg.get("heartbeat_when_empty", False))

    def send_jobs(self, new_jobs, total_scanned):
        raise NotImplementedError

    def send_heartbeat(self, total_scanned):
        raise NotImplementedError


# ── Discord ─────────────────────────────────────────────────────────────────

class DiscordNotifier(Notifier):
    """Posts to a Discord channel via webhook URL.

    Reads DISCORD_WEBHOOK_URL from env.
    """

    DISCORD_MSG_LIMIT = 1900  # leave headroom under Discord's 2000-char limit

    def __init__(self, cfg):
        super().__init__(cfg)
        self.webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        if not self.webhook_url:
            log.warning(
                "Discord notifier enabled but DISCORD_WEBHOOK_URL is unset; "
                "messages will not be sent."
            )

    def _post(self, content):
        if not self.webhook_url:
            return
        try:
            r = requests.post(self.webhook_url, json={"content": content}, timeout=15)
            if r.status_code >= 400:
                log.error("Discord post failed (%d): %s", r.status_code, r.text[:200])
        except Exception as e:
            log.error("Discord post error: %s", e)

    def send_jobs(self, new_jobs, total_scanned):
        if not new_jobs:
            if self.heartbeat_when_empty:
                self.send_heartbeat(total_scanned)
            return

        # Collapse near-duplicates (same title + company) with a "×N" counter.
        collapsed = {}
        for job in new_jobs:
            k = (job["title"].lower().strip(), job["company"].lower().strip())
            if k in collapsed:
                collapsed[k]["count"] += 1
            else:
                collapsed[k] = {**job, "count": 1}
        jobs = list(collapsed.values())

        # Group jobs by source for readable output.
        by_source = {}
        for job in jobs:
            by_source.setdefault(job["source"], []).append(job)

        lines = [
            f"## 🔎 Daily Job Scan — {datetime.now().strftime('%B %d, %Y')}",
            f"**{len(jobs)} new role(s) found**",
            "",
        ]
        for source, batch in by_source.items():
            lines.append(f"### {source} ({len(batch)})")
            for job in batch:
                posted = f" • {job['posted']}" if job.get("posted") else ""
                loc = f" • {job['location']}" if job.get("location") else ""
                count = f" ×{job['count']}" if job.get("count", 1) > 1 else ""
                lines.append(
                    f"**{job['title']}**{count} — {job['company']}{loc}{posted}"
                )
                # < > brackets suppress Discord's URL preview unfurl.
                lines.append(f"<{job['url']}>")
                lines.append("")

        # Split into ≤1900-char chunks on line boundaries.
        buf = ""
        messages = []
        for line in lines:
            if len(buf) + len(line) + 1 > self.DISCORD_MSG_LIMIT:
                messages.append(buf)
                buf = line + "\n"
            else:
                buf += line + "\n"
        if buf.strip():
            messages.append(buf)

        for msg in messages:
            self._post(msg)
            time.sleep(1)  # gentle pacing
        log.info(
            "Discord: posted %d job(s) in %d message(s)", len(jobs), len(messages)
        )

    def send_heartbeat(self, total_scanned):
        self._post(
            f"✅ **Job Bot Ran** — {datetime.now().strftime('%B %d, %Y')}\n"
            f"Scanned {total_scanned} listings, no new roles today."
        )


# ── Telegram ────────────────────────────────────────────────────────────────

class TelegramNotifier(Notifier):
    """Posts to a Telegram chat via Bot API.

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from env.
    """

    TG_MSG_LIMIT = 4000  # Telegram's hard limit is 4096; leave a buffer

    def __init__(self, cfg):
        super().__init__(cfg)
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not self.token or not self.chat_id:
            log.warning(
                "Telegram notifier enabled but TELEGRAM_BOT_TOKEN / "
                "TELEGRAM_CHAT_ID are unset; messages will not be sent."
            )

    def _post(self, text):
        if not self.token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if r.status_code >= 400:
                log.error(
                    "Telegram post failed (%d): %s", r.status_code, r.text[:200]
                )
        except Exception as e:
            log.error("Telegram post error: %s", e)

    def send_jobs(self, new_jobs, total_scanned):
        if not new_jobs:
            if self.heartbeat_when_empty:
                self.send_heartbeat(total_scanned)
            return

        # Same collapse-then-group pipeline as Discord, plain-text formatted.
        collapsed = {}
        for job in new_jobs:
            k = (job["title"].lower().strip(), job["company"].lower().strip())
            if k in collapsed:
                collapsed[k]["count"] += 1
            else:
                collapsed[k] = {**job, "count": 1}
        jobs = list(collapsed.values())

        by_source = {}
        for job in jobs:
            by_source.setdefault(job["source"], []).append(job)

        lines = [
            f"*🔎 Daily Job Scan — {datetime.now().strftime('%B %d, %Y')}*",
            f"{len(jobs)} new role(s) found",
            "",
        ]
        for source, batch in by_source.items():
            lines.append(f"*{source}* ({len(batch)})")
            for job in batch:
                posted = f" • {job['posted']}" if job.get("posted") else ""
                loc = f" • {job['location']}" if job.get("location") else ""
                count = f" x{job['count']}" if job.get("count", 1) > 1 else ""
                title = _md_escape(job["title"])
                company = _md_escape(job["company"])
                lines.append(f"• {title}{count} — {company}{loc}{posted}")
                lines.append(job["url"])
                lines.append("")

        # Split into ≤4000-char chunks on line boundaries.
        buf = ""
        messages = []
        for line in lines:
            if len(buf) + len(line) + 1 > self.TG_MSG_LIMIT:
                messages.append(buf)
                buf = line + "\n"
            else:
                buf += line + "\n"
        if buf.strip():
            messages.append(buf)

        for msg in messages:
            self._post(msg)
            time.sleep(1)
        log.info(
            "Telegram: posted %d job(s) in %d message(s)", len(jobs), len(messages)
        )

    def send_heartbeat(self, total_scanned):
        self._post(
            f"✅ *Job Bot Ran* — {datetime.now().strftime('%B %d, %Y')}\n"
            f"Scanned {total_scanned} listings, no new roles today."
        )


# ── Gmail ───────────────────────────────────────────────────────────────────

class GmailNotifier(Notifier):
    """Sends a daily digest email via Gmail SMTP.

    Requires a Gmail App Password (not your regular password):
      myaccount.google.com → Security → 2-Step Verification → App passwords

    Reads GMAIL_SENDER, GMAIL_APP_PASSWORD, and GMAIL_RECIPIENT from env.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.sender = os.environ.get("GMAIL_SENDER", "").strip()
        self.password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
        self.recipient = os.environ.get("GMAIL_RECIPIENT", "").strip()
        if not all([self.sender, self.password, self.recipient]):
            log.warning(
                "Gmail notifier enabled but GMAIL_SENDER / GMAIL_APP_PASSWORD / "
                "GMAIL_RECIPIENT are unset; messages will not be sent."
            )

    def _send(self, subject, body_html):
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        if not all([self.sender, self.password, self.recipient]):
            return
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.attach(MIMEText(body_html, "html"))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
                smtp.login(self.sender, self.password)
                smtp.sendmail(self.sender, self.recipient, msg.as_string())
        except Exception as e:
            log.error("Gmail send error: %s", e)

    def send_jobs(self, new_jobs, total_scanned):
        if not new_jobs:
            if self.heartbeat_when_empty:
                self.send_heartbeat(total_scanned)
            return

        collapsed = {}
        for job in new_jobs:
            k = (job["title"].lower().strip(), job["company"].lower().strip())
            if k in collapsed:
                collapsed[k]["count"] += 1
            else:
                collapsed[k] = {**job, "count": 1}
        jobs = list(collapsed.values())

        by_source = {}
        for job in jobs:
            by_source.setdefault(job["source"], []).append(job)

        date_str = datetime.now().strftime("%B %d, %Y")
        rows = []
        for source, batch in by_source.items():
            rows.append(f"<h3>{source} ({len(batch)})</h3><ul>")
            for job in batch:
                posted = f" &bull; {job['posted']}" if job.get("posted") else ""
                loc = f" &bull; {job['location']}" if job.get("location") else ""
                count = f" &times;{job['count']}" if job.get("count", 1) > 1 else ""
                rows.append(
                    f'<li><a href="{job["url"]}">{job["title"]}{count}</a>'
                    f" &mdash; {job['company']}{loc}{posted}</li>"
                )
            rows.append("</ul>")

        body = (
            f"<h2>Daily Job Scan &mdash; {date_str}</h2>"
            f"<p><strong>{len(jobs)} new role(s) found</strong></p>"
            + "".join(rows)
        )
        self._send(f"Job Bot: {len(jobs)} new role(s) — {date_str}", body)
        log.info("Gmail: sent digest with %d job(s)", len(jobs))

    def send_heartbeat(self, total_scanned):
        date_str = datetime.now().strftime("%B %d, %Y")
        self._send(
            f"Job Bot: no new roles — {date_str}",
            f"<p>Scanned {total_scanned} listings on {date_str}. No new roles today.</p>",
        )


def _md_escape(text):
    """Escape characters that Telegram's legacy Markdown treats specially."""
    return (
        text.replace("\\", "\\\\")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("`", "\\`")
            .replace("[", "\\[")
    )


# ── Registry ────────────────────────────────────────────────────────────────

NOTIFIERS = {
    "discord": DiscordNotifier,
    "telegram": TelegramNotifier,
    "gmail": GmailNotifier,
}
