#!/usr/bin/env python3
"""
job_bot.py — main entry point.

Reads config.yaml + .env, runs every enabled scraper, dedupes against a local
SQLite database, then dispatches new jobs to every enabled notifier.

Usage:
    python3 job_bot.py                    # uses ./config.yaml
    python3 job_bot.py --config foo.yaml  # custom config path
    python3 job_bot.py --dry-run          # scrape and filter, no notifications
"""

import argparse
import hashlib
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

from scrapers import SCRAPERS
from notifiers import NOTIFIERS

log = logging.getLogger("job_bot")


# ── Config + env ────────────────────────────────────────────────────────────

def load_config(path):
    if not os.path.exists(path):
        log.error("Config file not found: %s", path)
        log.error("Copy config.example.yaml to config.yaml and edit it.")
        sys.exit(1)
    with open(path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(level_name):
    level = getattr(logging, str(level_name).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# ── Title filter ────────────────────────────────────────────────────────────

def title_matches(title, keywords):
    """True if the title contains any of the keywords (case-insensitive)."""
    if not keywords:
        return True  # no filter configured → accept everything
    t = title.lower()
    return any(kw.lower() in t for kw in keywords)


# ── Location filter ─────────────────────────────────────────────────────────

REMOTE_TOKENS = ("remote", "anywhere", "worldwide", "global", "work from home", "wfh")


def location_ok(location, title, lf):
    """Apply the location filter from config.yaml.

    Returns True if the location is acceptable. If `lf['enabled']` is false,
    everything passes through.
    """
    if not lf or not lf.get("enabled", True):
        return True

    cities_allow = [c.lower() for c in (lf.get("cities_allow") or [])]
    cities_block = [c.lower() for c in (lf.get("cities_block") or [])]
    remote_allow = bool(lf.get("remote_allow", True))
    remote_geo_allow = [g.lower() for g in (lf.get("remote_geo_allow") or [])]
    reject_unknown = bool(lf.get("reject_unknown_locations", True))

    loc = (location or "").lower().strip()
    title_lc = (title or "").lower()

    # No location available → fall back to title hints, then reject_unknown.
    if not loc:
        if any(c in title_lc for c in cities_allow):
            return True
        if remote_allow and any(r in title_lc for r in REMOTE_TOKENS):
            return True
        return not reject_unknown

    # Hard reject for blocked cities (overrides everything).
    if any(c in loc for c in cities_block):
        return False

    is_in_allowed_city = any(c in loc for c in cities_allow)
    if is_in_allowed_city:
        return True

    is_remote = any(t in loc for t in REMOTE_TOKENS)
    if is_remote and remote_allow:
        # If the remote listing names a different geo, require an allow-token.
        # Example: "Remote - India" → reject unless remote_geo_allow lists india.
        if not remote_geo_allow:
            return True
        return any(g in loc for g in remote_geo_allow)

    return False


# ── Dedup database ──────────────────────────────────────────────────────────

def init_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_jobs (
            url_hash TEXT PRIMARY KEY,
            url      TEXT,
            title    TEXT,
            company  TEXT,
            source   TEXT,
            seen_at  TEXT
        )
        """
    )
    conn.commit()
    return conn


def _normalize_url(url):
    """Strip tracking params and country subdomains so the same job dedups."""
    m = re.search(r"linkedin\.com/jobs/view/(?:.*?[-/])?(\d{5,})", url)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    return url.split("?")[0].rstrip("/")


def dedup_key(url, title, company, source):
    """Compute the dedup hash for a job.

    LinkedIn is special — same role often shows up across multiple country
    subdomains with different job IDs, so we collapse on title+company.
    """
    t = re.sub(r"\s+", " ", (title or "").lower().strip())
    c = re.sub(r"\s+", " ", (company or "").lower().strip())
    if "linkedin" in (source or "").lower() or "linkedin.com" in (url or "").lower():
        return hashlib.sha256(f"linkedin|{t}|{c}".encode()).hexdigest()
    norm = _normalize_url(url or "")
    return hashlib.sha256(f"{norm}|{t}".encode()).hexdigest()


def is_new(conn, job):
    h = dedup_key(job["url"], job["title"], job.get("company", ""), job["source"])
    row = conn.execute("SELECT 1 FROM seen_jobs WHERE url_hash = ?", (h,)).fetchone()
    return row is None


def mark_seen(conn, job):
    h = dedup_key(job["url"], job["title"], job.get("company", ""), job["source"])
    conn.execute(
        "INSERT OR IGNORE INTO seen_jobs "
        "(url_hash, url, title, company, source, seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            h,
            job["url"],
            job["title"],
            job.get("company", ""),
            job["source"],
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


# ── Main loop ───────────────────────────────────────────────────────────────

def run(cfg, dry_run=False):
    db_path = cfg.get("db_path", "seen_jobs.db")
    conn = init_db(db_path)

    title_keywords = cfg.get("title_keywords") or []
    location_filter = cfg.get("location_filter") or {}
    sources_cfg = cfg.get("sources") or {}

    all_jobs = []
    for key, scraper_cfg in sources_cfg.items():
        if not isinstance(scraper_cfg, dict) or not scraper_cfg.get("enabled", False):
            continue
        scraper_fn = SCRAPERS.get(key)
        if not scraper_fn:
            log.warning("Unknown source '%s' in config (skipping)", key)
            continue
        try:
            scraped = scraper_fn(scraper_cfg)
        except Exception as e:
            log.error("Source '%s' crashed: %s", key, e)
            continue
        # Apply title + location filter immediately so we don't store junk.
        for job in scraped:
            if not title_matches(job.get("title", ""), title_keywords):
                continue
            if not location_ok(
                job.get("location", ""), job.get("title", ""), location_filter
            ):
                continue
            all_jobs.append(job)

    # Dedup against the database (and against this run too).
    new_jobs = []
    seen_this_run = set()
    for job in all_jobs:
        k = dedup_key(
            job["url"], job["title"], job.get("company", ""), job["source"]
        )
        if k in seen_this_run:
            continue
        seen_this_run.add(k)
        if is_new(conn, job):
            new_jobs.append(job)
            if not dry_run:
                mark_seen(conn, job)

    log.info(
        "Scanned %d filtered jobs; %d new since last run", len(all_jobs), len(new_jobs)
    )

    # Optional cap: if `max_jobs_per_run` is set, send only the freshest N.
    # Sources earlier in the config get priority (typical config puts the
    # higher-signal boards first).
    max_per_run = cfg.get("max_jobs_per_run")
    if max_per_run and len(new_jobs) > max_per_run:
        log.info(
            "Capping at %d (set max_jobs_per_run in config to change)", max_per_run
        )
        new_jobs = new_jobs[:max_per_run]

    if dry_run:
        log.info("Dry run — skipping notifications. New jobs that would be sent:")
        for j in new_jobs:
            log.info("  [%s] %s — %s", j["source"], j["title"], j["company"])
        return

    # Dispatch to every enabled notifier.
    for key, n_cfg in (cfg.get("notifiers") or {}).items():
        if not isinstance(n_cfg, dict) or not n_cfg.get("enabled", False):
            continue
        cls = NOTIFIERS.get(key)
        if not cls:
            log.warning("Unknown notifier '%s' in config (skipping)", key)
            continue
        try:
            cls(n_cfg).send_jobs(new_jobs, total_scanned=len(all_jobs))
        except Exception as e:
            log.error("Notifier '%s' crashed: %s", key, e)

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Run the job-scraping bot.")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config YAML (default: config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and filter, but don't notify or write to the DB",
    )
    args = parser.parse_args()

    # Load .env so notifier classes can read secrets from os.environ.
    load_dotenv()

    cfg = load_config(args.config)
    setup_logging(cfg.get("log_level", "INFO"))

    run(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
