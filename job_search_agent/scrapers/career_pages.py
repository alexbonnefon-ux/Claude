"""Direct career page scrapers for companies that don't use a standard ATS.

Each company gets its own scrape function. We use requests + BeautifulSoup
where pages are server-rendered, and Selenium for JS-heavy pages.

Covered here: Apple, Samsung, Google, Meta, Microsoft, Adobe
"""
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import settings_db
from config import LOOKBACK_HOURS
from scorer import Job
from scrapers.base import fetch_soup, make_job_id, get_driver

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _matches_title(title: str) -> bool:
    t = title.lower()
    return any(kw.lower() in t for kw in settings_db.job_titles())


# ---------------------------------------------------------------------------
# Apple – uses their own Job Search API (JSON)
# ---------------------------------------------------------------------------

def scrape_apple() -> List[Job]:
    from scrapers.base import fetch_json
    log.info("Scraping Apple career page…")
    jobs: List[Job] = []

    # Apple exposes a JSON search API
    api_url = "https://jobs.apple.com/api/role/search"
    params = {
        "filters[postingScope][0]": "HR,HUMRES",
        "filters[locations][0]": "FRA",
        "page": 1,
        "locale": "en-US",
    }
    data = fetch_json(api_url, params=params)
    if not data:
        # Fallback: try scraping the HTML page
        return _scrape_apple_html()

    for item in data.get("searchResults", []):
        title = item.get("postingTitle", "")
        if not _matches_title(title):
            continue

        location = item.get("locations", [{}])[0].get("name", "") if item.get("locations") else ""
        job_id_raw = str(item.get("positionId", item.get("id", title)))
        posting_url = f"https://jobs.apple.com/en-us/details/{job_id_raw}"

        posted = item.get("postDateTime", item.get("modificationDateTime", ""))

        jobs.append(Job(
            job_id      = make_job_id("apple", job_id_raw),
            title       = title,
            company     = "Apple",
            location    = location,
            url         = posting_url,
            date_posted = posted[:10] if posted else None,
            source      = "Apple Careers",
        ))

    log.info("Apple – %d matching jobs", len(jobs))
    return jobs


def _scrape_apple_html() -> List[Job]:
    soup = fetch_soup(
        "https://jobs.apple.com/en-us/search",
        params={"team": "human-resources-HUMRES", "location": "FRA"},
    )
    if not soup:
        return []
    jobs = []
    for card in soup.select("li.table-col-1, li[data-job-id]"):
        try:
            title_el = card.select_one("a.table--advanced-search__title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not _matches_title(title):
                continue
            href  = "https://jobs.apple.com" + title_el["href"]
            loc   = card.select_one(".table--advanced-search__location")
            location = loc.get_text(strip=True) if loc else ""
            job_id = make_job_id("apple", href)
            jobs.append(Job(
                job_id=job_id, title=title, company="Apple",
                location=location, url=href, source="Apple Careers",
            ))
        except Exception as exc:
            log.debug("Apple HTML parse: %s", exc)
    return jobs


# ---------------------------------------------------------------------------
# Google – uses their public jobs search API
# ---------------------------------------------------------------------------

def scrape_google() -> List[Job]:
    from scrapers.base import fetch_json
    log.info("Scraping Google career page…")
    jobs: List[Job] = []

    api_url = "https://careers.google.com/api/v3/search/"
    params = {
        "q":         "People HR",
        "location":  "France",
        "page_size": 20,
        "page":      1,
    }
    data = fetch_json(api_url, params=params)
    if not data:
        return []

    for item in data.get("jobs", []):
        title = item.get("title", "")
        if not _matches_title(title):
            continue

        locations = item.get("locations", [])
        location  = ", ".join(locations) if locations else "France"
        apply_url = f"https://careers.google.com/jobs/results/{item.get('id', '')}"

        jobs.append(Job(
            job_id      = make_job_id("google", str(item.get("id", title))),
            title       = title,
            company     = "Google",
            location    = location,
            url         = apply_url,
            date_posted = item.get("publish_date", "")[:10] or None,
            description = item.get("summary", ""),
            source      = "Google Careers",
        ))

    log.info("Google – %d matching jobs", len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Meta – uses their public jobs API
# ---------------------------------------------------------------------------

def scrape_meta() -> List[Job]:
    from scrapers.base import fetch_json
    log.info("Scraping Meta career page…")
    jobs: List[Job] = []

    api_url  = "https://www.metacareers.com/graphql"
    # Meta's careers page uses GraphQL; we query with their public endpoint
    payload  = {
        "operationName": "CareersJobSearchResultsQuery",
        "variables": {
            "search_input": {
                "q":               "HR People",
                "divisions":       ["People"],
                "offices":         ["Paris, France"],
                "page":            1,
                "results_per_page": 20,
            }
        },
        "doc_id": "5537621266302251",
    }
    from scrapers.base import SESSION, REQUEST_DELAY, REQUEST_TIMEOUT
    time.sleep(REQUEST_DELAY)
    try:
        resp = SESSION.post(api_url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Meta API failed: %s – trying HTML fallback", exc)
        return _scrape_meta_html()

    results = (
        data.get("data", {})
        .get("job_search", {})
        .get("results", [])
    )
    for item in results:
        title = item.get("title", "")
        if not _matches_title(title):
            continue

        locations = [loc.get("city", "") for loc in item.get("locations", [])]
        location  = ", ".join(filter(None, locations))

        jobs.append(Job(
            job_id      = make_job_id("meta", str(item.get("id", title))),
            title       = title,
            company     = "Meta",
            location    = location,
            url         = f"https://www.metacareers.com/jobs/{item.get('id', '')}",
            date_posted = None,
            description = item.get("description", ""),
            source      = "Meta Careers",
        ))

    log.info("Meta – %d matching jobs", len(jobs))
    return jobs


def _scrape_meta_html() -> List[Job]:
    soup = fetch_soup(
        "https://www.metacareers.com/jobs",
        params={"q": "HR+People", "offices": "Paris%2C+France", "division": "People"},
    )
    if not soup:
        return []
    jobs = []
    for card in soup.select('[data-id], [data-job-id], .job-listing'):
        try:
            a     = card.select_one("a")
            title = card.select_one("h4, h3, .job-title")
            loc   = card.select_one(".job-location")
            if not a or not title:
                continue
            t = title.get_text(strip=True)
            if not _matches_title(t):
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.metacareers.com" + href
            jobs.append(Job(
                job_id   = make_job_id("meta", href),
                title    = t,
                company  = "Meta",
                location = loc.get_text(strip=True) if loc else "France",
                url      = href,
                source   = "Meta Careers",
            ))
        except Exception:
            pass
    return jobs


# ---------------------------------------------------------------------------
# Microsoft – uses their JSON API
# ---------------------------------------------------------------------------

def scrape_microsoft() -> List[Job]:
    from scrapers.base import fetch_json
    log.info("Scraping Microsoft career page…")
    jobs: List[Job] = []

    api_url = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
    params  = {
        "q":         "HR People",
        "lc":        "France",
        "l":         "en_us",
        "pgSz":      20,
        "startrow":  0,
    }
    data = fetch_json(api_url, params=params)
    if not data:
        return []

    for item in (data.get("operationResult", {}).get("result", {}).get("jobs", []) or []):
        title = item.get("title", "")
        if not _matches_title(title):
            continue

        locations = item.get("primaryLocation", "") or ""
        job_id_raw = str(item.get("jobId", item.get("id", title)))

        jobs.append(Job(
            job_id      = make_job_id("microsoft", job_id_raw),
            title       = title,
            company     = "Microsoft",
            location    = locations,
            url         = f"https://jobs.microsoft.com/en-us/job/{job_id_raw}",
            date_posted = (item.get("postingDate", "") or "")[:10] or None,
            description = item.get("description", ""),
            source      = "Microsoft Careers",
        ))

    log.info("Microsoft – %d matching jobs", len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Samsung – generic HTML scrape with Selenium (JS-heavy)
# ---------------------------------------------------------------------------

def scrape_samsung() -> List[Job]:
    log.info("Scraping Samsung career page (Selenium)…")
    jobs: List[Job] = []
    driver = None
    try:
        driver = get_driver(headless=True)
        driver.get(
            "https://www.samsung.com/global/business/careers/"
            "search-results/?searchitem=HR&location=France"
        )
        time.sleep(4)

        from selenium.webdriver.common.by import By
        cards = driver.find_elements(By.CSS_SELECTOR, ".job-item, .careers-listing-item, li.job")

        for card in cards[:30]:
            try:
                title_el = card.find_element(By.CSS_SELECTOR, "h3, h4, .job-title, a")
                title    = title_el.text.strip()
                if not _matches_title(title):
                    continue
                link_el = card.find_element(By.CSS_SELECTOR, "a")
                href    = link_el.get_attribute("href") or ""
                loc_el  = card.find_elements(By.CSS_SELECTOR, ".location, .job-location")
                location = loc_el[0].text.strip() if loc_el else "France"

                jobs.append(Job(
                    job_id  = make_job_id("samsung", href or title),
                    title   = title,
                    company = "Samsung",
                    location= location,
                    url     = href,
                    source  = "Samsung Careers",
                ))
            except Exception:
                pass

    except Exception as exc:
        log.error("Samsung scrape error: %s", exc)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    log.info("Samsung – %d matching jobs", len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Adobe – uses their public job search API (Workday-based)
# ---------------------------------------------------------------------------

def scrape_adobe() -> List[Job]:
    from scrapers.base import fetch_json
    log.info("Scraping Adobe career page…")
    jobs: List[Job] = []

    # Adobe uses Workday; their search API is:
    api_url = "https://careers.adobe.com/api/jobs"
    params  = {
        "keyword":  "HR People",
        "country":  "France",
        "page":     1,
        "per_page": 20,
    }
    data = fetch_json(api_url, params=params)
    if data and isinstance(data, dict):
        for item in data.get("jobs", data.get("results", [])):
            title = item.get("title", item.get("req_title", ""))
            if not _matches_title(title):
                continue
            location  = item.get("primary_location", item.get("location", ""))
            job_url   = item.get("meta_data", {}).get("url") or item.get("url") or ""
            job_id_raw= str(item.get("req_id", item.get("id", title)))
            jobs.append(Job(
                job_id      = make_job_id("adobe", job_id_raw),
                title       = title,
                company     = "Adobe",
                location    = location,
                url         = job_url or f"https://careers.adobe.com",
                date_posted = (item.get("posted_date", "") or "")[:10] or None,
                source      = "Adobe Careers",
            ))

    log.info("Adobe – %d matching jobs", len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

SCRAPERS = {
    "Apple":     scrape_apple,
    "Google":    scrape_google,
    "Meta":      scrape_meta,
    "Microsoft": scrape_microsoft,
    "Samsung":   scrape_samsung,
    "Adobe":     scrape_adobe,
}


def scrape_all() -> List[Job]:
    all_jobs: List[Job] = []
    for company, fn in SCRAPERS.items():
        try:
            jobs = fn()
            all_jobs.extend(jobs)
        except Exception as exc:
            log.error("Career pages – error scraping %s: %s", company, exc)
    return all_jobs
