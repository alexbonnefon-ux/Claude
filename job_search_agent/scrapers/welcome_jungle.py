"""Welcome to the Jungle (WTTJ) scraper.

WTTJ uses Algolia as their search backend. We query their public Algolia
index directly, which is faster and more reliable than scraping HTML.

The Algolia app ID and API key are public (embedded in their JS bundle).
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from urllib.parse import quote

import settings_db
from config import LOOKBACK_HOURS
from scorer import Job
from scrapers.base import fetch_json, fetch_soup, make_job_id

log = logging.getLogger(__name__)

# These are public/read-only Algolia credentials embedded in WTTJ's frontend
ALGOLIA_APP_ID  = "RQEO4YUND9"
ALGOLIA_API_KEY = "9ba405e5319545c6c7c1cbf2dc4be74c"
ALGOLIA_INDEX   = "jobs"
ALGOLIA_URL     = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"

WTTJ_JOB_BASE = "https://www.welcometothejungle.com"

# Fallback: HTML scraping of the search results page
HTML_SEARCH_URL = "https://www.welcometothejungle.com/en/jobs"


def _algolia_query(keyword: str, page: int = 0) -> Optional[dict]:
    """Query the Algolia search index used by WTTJ."""
    headers = {
        "X-Algolia-Application-Id": ALGOLIA_APP_ID,
        "X-Algolia-API-Key":        ALGOLIA_API_KEY,
        "Content-Type":             "application/json",
    }

    cutoff_ts = int(
        (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp()
    )

    # Build filter for France + posted within window
    filters = (
        f"(office.country_code:FR OR contract.remote_level:fulltime) "
        f"AND published_at >= {cutoff_ts}"
    )

    payload = {
        "query":             keyword,
        "filters":           filters,
        "hitsPerPage":       50,
        "page":              page,
        "attributesToRetrieve": [
            "name", "company", "office", "contract",
            "published_at", "slug", "salary",
        ],
    }

    import json
    import requests
    from scrapers.base import SESSION, REQUEST_DELAY, REQUEST_TIMEOUT
    import time

    time.sleep(REQUEST_DELAY)
    try:
        resp = SESSION.post(
            ALGOLIA_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("WTTJ Algolia query failed (%s): %s", keyword, exc)
        return None


def _html_fallback(keyword: str) -> List[Job]:
    """Scrape the WTTJ search page HTML as a fallback."""
    params = {
        "query": keyword,
        "refinementList[office.country_code][]": "FR",
    }
    soup = fetch_soup(HTML_SEARCH_URL, params=params)
    if not soup:
        return []

    jobs: List[Job] = []
    for card in soup.select("li[data-testid='search-results-list-item']"):
        try:
            link = card.select_one("a")
            title_el   = card.select_one("h4, h3, [data-testid='job-title']")
            company_el = card.select_one("[data-testid='company-name'], h3 + span")
            location_el= card.select_one("[data-testid='job-location'], address")

            if not title_el or not link:
                continue

            title   = title_el.get_text(strip=True)
            company = company_el.get_text(strip=True) if company_el else ""
            location= location_el.get_text(strip=True) if location_el else "France"
            href    = WTTJ_JOB_BASE + link["href"] if link["href"].startswith("/") else link["href"]

            job_id = make_job_id("wttj", href)
            jobs.append(Job(
                job_id   = job_id,
                title    = title,
                company  = company,
                location = location,
                url      = href,
                source   = "Welcome to the Jungle",
            ))
        except Exception as exc:
            log.debug("WTTJ HTML parse error: %s", exc)

    return jobs


def _algolia_to_jobs(data: dict, keyword: str) -> List[Job]:
    jobs: List[Job] = []
    hits = data.get("hits", [])

    for hit in hits:
        title = hit.get("name", "")
        if not any(jt.lower() in title.lower() for jt in settings_db.job_titles()):
            continue

        company_info = hit.get("company", {}) or {}
        company_name = company_info.get("name", "") if isinstance(company_info, dict) else str(company_info)

        office  = hit.get("office", {}) or {}
        city    = office.get("city", "") if isinstance(office, dict) else ""
        country = office.get("country", {})
        if isinstance(country, dict):
            country = country.get("name", "")
        location = ", ".join(filter(None, [city, str(country)]))

        contract = hit.get("contract", {}) or {}
        remote_type = contract.get("remote_level", "") if isinstance(contract, dict) else ""
        if remote_type == "fulltime":
            location = location + " (Full remote)" if location else "Full remote"

        pub_ts = hit.get("published_at")
        date_posted = (
            datetime.fromtimestamp(pub_ts, tz=timezone.utc).date().isoformat()
            if pub_ts else None
        )

        # Salary
        salary_info = hit.get("salary", {}) or {}
        sal_text = ""
        if isinstance(salary_info, dict) and salary_info:
            min_v = salary_info.get("min")
            max_v = salary_info.get("max")
            currency = salary_info.get("currency", "EUR")
            if min_v or max_v:
                sal_text = f"{currency} {min_v or '?'}–{max_v or '?'}"

        slug = hit.get("slug", "")
        job_url = f"{WTTJ_JOB_BASE}/en/jobs/{slug}" if slug else WTTJ_JOB_BASE

        job_id = make_job_id("wttj", slug or title + company_name)
        jobs.append(Job(
            job_id      = job_id,
            title       = title,
            company     = company_name,
            location    = location,
            url         = job_url,
            date_posted = date_posted,
            salary_text = sal_text,
            source      = "Welcome to the Jungle",
            raw         = hit,
        ))

    return jobs


def scrape_all() -> List[Job]:
    all_jobs: List[Job] = []
    seen_ids: set       = set()

    for keyword in settings_db.job_titles():
        log.info("WTTJ – searching: %s", keyword)
        try:
            data = _algolia_query(keyword)
            if data:
                jobs = _algolia_to_jobs(data, keyword)
            else:
                log.info("WTTJ – Algolia failed, trying HTML fallback for: %s", keyword)
                jobs = _html_fallback(keyword)

            for j in jobs:
                if j.job_id not in seen_ids:
                    seen_ids.add(j.job_id)
                    all_jobs.append(j)

        except Exception as exc:
            log.error("WTTJ – error for keyword '%s': %s", keyword, exc)

    log.info("WTTJ – total: %d unique jobs", len(all_jobs))
    return all_jobs
