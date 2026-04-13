"""Ashby job board scraper.

Ashby embeds all job data in a __NEXT_DATA__ JSON blob on their public
job board pages (https://jobs.ashbyhq.com/{company}).
No API key is required for reading public listings.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import settings_db
from config import LOOKBACK_HOURS
from scorer import Job
from scrapers.base import fetch_soup, make_job_id

log = logging.getLogger(__name__)

BOARD_BASE = "https://jobs.ashbyhq.com/{company}"


def _matches_title(title: str) -> bool:
    t = title.lower()
    return any(kw.lower() in t for kw in settings_db.job_titles())


def _parse_ashby_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_next_data(soup) -> Optional[dict]:
    """Extract the JSON payload from Next.js __NEXT_DATA__ script tag."""
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return None
    try:
        return json.loads(script.string)
    except json.JSONDecodeError as exc:
        log.warning("Ashby – JSON parse error: %s", exc)
        return None


def scrape_company(company_name: str, identifier: str) -> List[Job]:
    url = BOARD_BASE.format(company=identifier)
    log.info("Ashby – %s (%s)", company_name, identifier)

    soup = fetch_soup(url)
    if not soup:
        log.warning("Ashby – could not fetch %s", url)
        return []

    next_data = _extract_next_data(soup)
    if not next_data:
        log.warning("Ashby – no __NEXT_DATA__ for %s", company_name)
        return []

    # Navigate the Next.js data tree to find job postings
    try:
        props       = next_data.get("props", {})
        page_props  = props.get("pageProps", {})
        # Structure varies – try common paths
        job_postings = (
            page_props.get("jobPostings")
            or page_props.get("jobs")
            or page_props.get("initialData", {}).get("jobPostings")
            or []
        )
        # Some boards nest by department
        if not job_postings:
            departments = page_props.get("jobBoard", {}).get("jobPostingsByDepartment", [])
            for dept in departments:
                job_postings.extend(dept.get("jobPostings", []))
    except (AttributeError, KeyError) as exc:
        log.warning("Ashby – data structure unexpected for %s: %s", company_name, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    jobs: List[Job] = []

    for item in job_postings:
        title = item.get("title", "")
        if not _matches_title(title):
            continue

        published_raw = item.get("publishedDate") or item.get("createdAt")
        published     = _parse_ashby_date(published_raw)
        if published and published < cutoff:
            continue

        # Location
        location_parts = []
        for loc in item.get("locationIds", []) or []:
            location_parts.append(str(loc))
        location = item.get("primaryLocation", {})
        if isinstance(location, dict):
            city    = location.get("city", "")
            country = location.get("country", "")
            location_str = ", ".join(filter(None, [city, country]))
        else:
            location_str = str(location) if location else "Unknown"
        if not location_str and location_parts:
            location_str = "; ".join(location_parts)

        is_remote = item.get("isRemote", False) or item.get("locationRequirement", "") == "Remote"
        if is_remote and not location_str:
            location_str = "Remote"

        # Compensation
        comp = item.get("compensation", {}) or {}
        sal_text = ""
        if comp:
            min_v = comp.get("minValue") or comp.get("min")
            max_v = comp.get("maxValue") or comp.get("max")
            currency = comp.get("currency", "EUR")
            if min_v or max_v:
                sal_text = f"{currency} {min_v or '?'}–{max_v or '?'}"

        # Description
        description = item.get("descriptionHtml") or item.get("description") or ""

        # Job URL
        job_slug = item.get("id") or item.get("slug") or title.lower().replace(" ", "-")
        job_url  = item.get("jobUrl") or f"{url}/{job_slug}"

        job_id = make_job_id("ashby", str(item.get("id", title + company_name)))

        jobs.append(Job(
            job_id      = job_id,
            title       = title,
            company     = company_name,
            location    = location_str,
            url         = job_url,
            date_posted = published_raw[:10] if published_raw else None,
            description = description,
            salary_text = sal_text,
            source      = f"Ashby ({company_name})",
            raw         = item,
        ))

    log.info("Ashby – %s: %d matching jobs", company_name, len(jobs))
    return jobs


def scrape_all() -> List[Job]:
    all_jobs: List[Job] = []
    for company_name, identifier in settings_db.ashby_companies().items():
        try:
            all_jobs.extend(scrape_company(company_name, identifier))
        except Exception as exc:
            log.error("Ashby – error scraping %s: %s", company_name, exc)
    return all_jobs
