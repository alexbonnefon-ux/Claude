"""SerpAPI-based job scraper.

Replaces the blocked LinkedIn and Welcome to the Jungle scrapers.
Two complementary search strategies:

1. Google Jobs engine – broad search across all job boards indexed by Google.
   Catches WTTJ, LinkedIn, Indeed, company pages, etc.

2. Google Search site: filter – targets specific ATS domains directly.
   e.g. site:jobs.ashbyhq.com "Head of People" Paris
   Finds companies we don't have hardcoded, or catches what the direct
   API misses.

Setup: set SERPAPI_KEY in your .env file.
Free plan: 100 searches / month  →  https://serpapi.com
"""
import logging
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import SERPAPI_KEY
import settings_db
from scorer import Job
from scrapers.base import fetch_json, make_job_id

log = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"

# ATS domains for the Google site: fallback
ATS_SITES = [
    ("jobs.ashbyhq.com",   "Ashby"),
    ("boards.greenhouse.io", "Greenhouse"),
    ("jobs.lever.co",      "Lever"),
]

# Location modifiers appended to each Google Jobs query
LOCATION_SUFFIXES = [
    "France remote",
    "Paris hybride",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _posted_ago_to_date(text: str) -> Optional[str]:
    """'3 hours ago' → today's ISO date.  'yesterday' → yesterday."""
    if not text:
        return None
    t = text.lower().strip()
    now = datetime.now(timezone.utc)
    try:
        if t in ("today", "just now"):
            return now.date().isoformat()
        if "yesterday" in t:
            return (now - timedelta(days=1)).date().isoformat()
        n = int(t.split()[0])
        if "hour" in t or "minute" in t:
            return now.date().isoformat()
        if "day" in t:
            return (now - timedelta(days=n)).date().isoformat()
        if "week" in t:
            return (now - timedelta(weeks=n)).date().isoformat()
    except (ValueError, IndexError):
        pass
    return None


def _serpapi_available() -> bool:
    if not SERPAPI_KEY:
        log.warning("SERPAPI_KEY not configured – skipping SerpAPI scrapers. "
                    "Set it in .env to enable Google Jobs search.")
        return False
    return True


# ---------------------------------------------------------------------------
# Strategy 1 – Google Jobs engine
# ---------------------------------------------------------------------------

def search_google_jobs(keyword: str, location_suffix: str = "France") -> list[Job]:
    """One Google Jobs query → list of Job objects."""
    if not _serpapi_available():
        return []

    query = f"{keyword} {location_suffix}"
    params = {
        "engine":  "google_jobs",
        "q":       query,
        "api_key": SERPAPI_KEY,
        "hl":      "en",
        "gl":      "fr",
        "chips":   "date_posted:3days",   # last 3 days; DB dedup handles overlaps
    }

    data = fetch_json(SERPAPI_URL, params=params)
    if not data:
        return []

    if "error" in data:
        log.error("Google Jobs API error: %s", data["error"])
        return []

    jobs: list[Job] = []
    for item in data.get("jobs_results", []):
        title    = item.get("title", "").strip()
        company  = item.get("company_name", "").strip()
        location = item.get("location", "").strip()
        desc     = item.get("description", "")

        ext          = item.get("detected_extensions", {}) or {}
        salary_text  = ext.get("salary", "")
        posted_raw   = ext.get("posted_at", "")
        date_posted  = _posted_ago_to_date(posted_raw)

        # Best apply link
        apply_options = item.get("apply_options", []) or []
        url = apply_options[0].get("link", "") if apply_options else ""
        if not url:
            url = item.get("sharing_link", "")

        job_id = make_job_id("google_jobs", item.get("job_id") or (title + company + location))

        jobs.append(Job(
            job_id      = job_id,
            title       = title,
            company     = company,
            location    = location,
            url         = url,
            date_posted = date_posted,
            description = desc,
            salary_text = salary_text,
            source      = "Google Jobs",
        ))

    log.info("Google Jobs '%s' → %d results", query, len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Strategy 2 – Google Search with site: filter
# ---------------------------------------------------------------------------

def search_google_site(domain: str, ats_label: str,
                       titles: list[str]) -> list[Job]:
    """Search a specific ATS domain for any matching HR titles."""
    if not _serpapi_available():
        return []

    # Build a compact OR query from the most distinctive title terms
    title_terms = " OR ".join(f'"{t}"' for t in titles[:6])
    query = f"site:{domain} ({title_terms}) (France OR Paris OR remote OR télétravail)"

    params = {
        "engine":  "google",
        "q":       query,
        "api_key": SERPAPI_KEY,
        "num":     10,
        "hl":      "en",
        "gl":      "fr",
    }

    data = fetch_json(SERPAPI_URL, params=params)
    if not data:
        return []

    if "error" in data:
        log.error("Google Search API error (%s): %s", domain, data["error"])
        return []

    jobs: list[Job] = []
    for result in data.get("organic_results", []):
        link    = result.get("link", "")
        snippet = result.get("snippet", "")

        # Extract title – Google often formats it as "Job Title - Company | ATS"
        raw_title = result.get("title", "")
        title     = raw_title.split(" - ")[0].split(" | ")[0].strip()

        # Guess company from URL path
        parts   = [p for p in link.split("/") if p]
        company = parts[3].replace("-", " ").title() if len(parts) >= 4 else ""

        job_id = make_job_id(f"google_site_{domain}", link)

        jobs.append(Job(
            job_id      = job_id,
            title       = title,
            company     = company,
            location    = "",    # unknown from search snippet
            url         = link,
            description = snippet,
            source      = f"Google → {ats_label}",
        ))

    log.info("Google site:%s → %d results", domain, len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape_all() -> list[Job]:
    """Run both strategies and return deduplicated Job list."""
    titles   = settings_db.job_titles()
    all_jobs: list[Job] = []
    seen_ids: set = set()

    def _add(jobs: list[Job]) -> None:
        for j in jobs:
            if j.job_id not in seen_ids:
                seen_ids.add(j.job_id)
                all_jobs.append(j)

    # ── Strategy 1: Google Jobs per title + location ──────────────────────
    for title in titles:
        for suffix in LOCATION_SUFFIXES:
            try:
                _add(search_google_jobs(title, suffix))
                time.sleep(1.2)   # respect SerpAPI rate limit
            except Exception as exc:
                log.error("Google Jobs '%s %s': %s", title, suffix, exc)

    # ── Strategy 2: Google site: search per ATS domain ───────────────────
    for domain, label in ATS_SITES:
        try:
            _add(search_google_site(domain, label, titles))
            time.sleep(1.2)
        except Exception as exc:
            log.error("Google site:%s: %s", domain, exc)

    log.info("SerpAPI scraper total: %d unique jobs", len(all_jobs))
    return all_jobs
