"""
scrapers.py — one function per source.

Each scraper takes a `cfg` dict (its own section from config.yaml) and returns
a list of job dicts with these fields:

    {
        "title":   "Operations Lead",
        "company": "Acme Crypto",
        "url":     "https://example.com/jobs/123",
        "posted":  "2d",           # free-form, may be empty
        "location": "New York, NY", # free-form, may be empty
        "source":  "web3.career",
    }

To add a new source:
  1. Write a `scrape_xxx(cfg)` function below.
  2. Register it in the SCRAPERS dict at the bottom.
  3. Reference it by that key in config.yaml under `sources:`.
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
    _cf_scraper = cloudscraper.create_scraper()
except ImportError:
    _cf_scraper = None

log = logging.getLogger("job_bot.scrapers")

# A modern-looking User-Agent — some sites 403 short or generic UAs.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}


# ── web3.career ─────────────────────────────────────────────────────────────

def scrape_web3career(cfg):
    """Scrape web3.career operations job listings."""
    jobs = []
    url = cfg.get("url", "https://web3.career/operations-jobs")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for row in soup.select("tr.table_row"):
            title_tag = row.select_one("div.job-title-mobile h2")
            link_tag = row.select_one("div.job-title-mobile a")
            if not title_tag or not link_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = link_tag.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = "https://web3.career" + href

            company_tag = row.select_one("td.job-location-mobile h3")
            company = company_tag.get_text(strip=True) if company_tag else "Unknown"

            time_tag = row.select_one("time")
            posted = time_tag.get_text(strip=True) if time_tag else ""

            # Location: TD with /web3-jobs-XYZ city links, or a Remote badge.
            location = ""
            for td in row.select("td"):
                loc_links = td.select("a[href*='web3-jobs-']")
                if loc_links:
                    location = ", ".join(a.get_text(strip=True) for a in loc_links)
                    break
            if not location:
                for a in row.select("a"):
                    if "remote" in a.get_text(strip=True).lower():
                        location = "Remote"
                        break

            jobs.append({
                "title": title,
                "company": company,
                "url": href,
                "posted": posted,
                "location": location,
                "source": "web3.career",
            })

        log.info("web3.career: scraped %d jobs", len(jobs))
    except Exception as e:
        log.error("web3.career scrape failed: %s", e)

    return jobs


# ── cryptocurrencyjobs.co ───────────────────────────────────────────────────

def scrape_cryptocurrencyjobs(cfg):
    """Scrape cryptocurrencyjobs.co operations listings."""
    jobs = []
    url = cfg.get("url", "https://cryptocurrencyjobs.co/operations/")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Collect job-detail anchors, then walk up to find their <li> container.
        seen = set()
        detail_links = []
        for a in soup.select("a[href]"):
            h = a.get("href", "").rstrip("/")
            if (h.startswith("/operations/") or h.startswith("/sales/")) and h.count("/") >= 2:
                detail_links.append(a)

        for a in detail_links:
            href = a.get("href", "")
            if href in seen:
                continue
            seen.add(href)

            # Walk up to find <li> container
            li = a
            for _ in range(6):
                li = li.parent
                if li is None:
                    break
                if li.name == "li":
                    break
            if li is None or li.name != "li":
                continue

            full_url = ("https://cryptocurrencyjobs.co" + href) if not href.startswith("http") else href
            title = a.get_text(strip=True)

            # Parts of li text, separated by a rare char. Layout is usually:
            # [0: title, 1: company, 2: location, 3+: separators / category / tags]
            li_text = li.get_text("\x1f", strip=True)
            parts = [p.strip() for p in li_text.split("\x1f") if p.strip() and p.strip() != "·"]

            company = parts[1] if len(parts) >= 2 else "Unknown"
            location = parts[2] if len(parts) >= 3 else ""

            jobs.append({
                "title": title,
                "company": company,
                "url": full_url,
                "posted": "",
                "location": location,
                "source": "cryptocurrencyjobs.co",
            })

        log.info("cryptocurrencyjobs.co: scraped %d jobs", len(jobs))
    except Exception as e:
        log.error("cryptocurrencyjobs.co scrape failed: %s", e)

    return jobs


# ── cryptojobslist.com ──────────────────────────────────────────────────────

def scrape_cryptojobslist(cfg):
    """Scrape cryptojobslist.com (Cloudflare-protected; needs cloudscraper)."""
    jobs = []
    if _cf_scraper is None:
        log.warning("cryptojobslist: install `cloudscraper` to enable this source")
        return jobs

    url = cfg.get("url", "https://cryptojobslist.com/operations")
    try:
        resp = _cf_scraper.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for tr in soup.select("tr[role='button']"):
            title_a = tr.select_one("a.job-title-text")
            if not title_a:
                continue
            title = title_a.get_text(strip=True)
            href = title_a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = "https://cryptojobslist.com" + href

            company_a = tr.select_one("a.job-company-name-text")
            company = company_a.get_text(strip=True) if company_a else "Unknown"

            tds = tr.select("td")
            posted = tds[-1].get_text(strip=True)[:10] if tds else ""

            location = ""
            for span in tr.select("span"):
                txt = span.get_text(strip=True)
                if "📍" in txt:
                    location = txt.replace("📍", "").strip()
                    break

            jobs.append({
                "title": title,
                "company": company,
                "url": href,
                "posted": posted,
                "location": location,
                "source": "cryptojobslist.com",
            })

        log.info("cryptojobslist.com: scraped %d jobs", len(jobs))
    except Exception as e:
        log.error("cryptojobslist.com scrape failed: %s", e)

    return jobs


# ── builtin.com ─────────────────────────────────────────────────────────────

def scrape_builtin(cfg):
    """Scrape builtin.com and builtinnyc.com job pages."""
    jobs = []
    pages = cfg.get("pages") or [
        "https://www.builtinnyc.com/jobs/operations/artificial-intelligence",
        "https://www.builtinnyc.com/jobs/operations",
        "https://builtin.com/jobs/remote/operations",
    ]
    seen_urls = set()

    for url in pages:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for card in soup.select("div[data-id='job-card']"):
                title_a = card.select_one("a[data-id='job-card-title']")
                if not title_a:
                    continue
                title = title_a.get_text(strip=True)
                href = title_a.get("href", "")
                if not href:
                    continue
                if href.startswith("/"):
                    href = "https://builtin.com" + href
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                company_a = card.select_one("a[data-id='company-title']")
                company = company_a.get_text(strip=True) if company_a else "Unknown"

                location = ""
                posted = ""
                for span in card.select("span"):
                    t = span.get_text(strip=True)
                    if not t or len(t) > 100:
                        continue
                    if "ago" in t.lower() and not posted:
                        posted = t
                    if not location and any(x in t for x in [
                        ", NY", ", CA", ", TX", ", FL", "Remote", "Hybrid",
                        "New York", "United States",
                    ]):
                        location = t

                jobs.append({
                    "title": title,
                    "company": company,
                    "url": href,
                    "posted": posted,
                    "location": location,
                    "source": "builtin.com",
                })
        except Exception as e:
            log.error("builtin scrape failed for %s: %s", url, e)

    log.info("builtin.com: scraped %d jobs across %d pages", len(jobs), len(pages))
    return jobs


# ── linkedin.com (public job-search pages) ──────────────────────────────────

def scrape_linkedin(cfg):
    """Scrape LinkedIn's public job-search pages (no auth)."""
    jobs = []
    searches = cfg.get("searches") or []
    if not searches:
        log.warning("linkedin: no `searches` configured")
        return jobs

    seen_urls = set()
    for search_url in searches:
        try:
            resp = requests.get(search_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for card in soup.select("div.base-card, li.result-card, div.job-search-card"):
                title_tag = card.select_one("h3, .base-search-card__title")
                title = title_tag.get_text(strip=True) if title_tag else ""

                company_tag = card.select_one(
                    "h4, .base-search-card__subtitle, a.hidden-nested-link"
                )
                company = company_tag.get_text(strip=True) if company_tag else "Unknown"

                link_tag = card.select_one(
                    "a.base-card__full-link, a[href*='linkedin.com/jobs/view']"
                )
                if not link_tag:
                    continue
                href = link_tag.get("href", "").split("?")[0]

                time_tag = card.select_one("time")
                posted = time_tag.get("datetime", "") if time_tag else ""

                loc_tag = card.select_one(
                    ".job-search-card__location, span[class*='location']"
                )
                location = loc_tag.get_text(strip=True) if loc_tag else ""

                # Normalize: strip country subdomain so dedup works across regions.
                m = re.search(r"linkedin\.com/jobs/view/(?:.*?[-/])?(\d{5,})", href)
                norm = (
                    f"https://www.linkedin.com/jobs/view/{m.group(1)}"
                    if m
                    else href.rstrip("/")
                )
                if norm in seen_urls:
                    continue
                seen_urls.add(norm)

                if title:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "url": href,
                        "posted": posted,
                        "location": location,
                        "source": cfg.get("source_label", "LinkedIn"),
                    })
        except Exception as e:
            log.error("linkedin scrape failed for %s: %s", search_url, e)

    log.info("linkedin: scraped %d jobs across %d searches", len(jobs), len(searches))
    return jobs


# ── Registry ────────────────────────────────────────────────────────────────

SCRAPERS = {
    "web3career": scrape_web3career,
    "cryptocurrencyjobs": scrape_cryptocurrencyjobs,
    "cryptojobslist": scrape_cryptojobslist,
    "builtin": scrape_builtin,
    "linkedin": scrape_linkedin,
    "linkedin_startup": scrape_linkedin,
}
