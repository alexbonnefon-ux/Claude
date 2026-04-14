"""Greenhouse job board scraper.

Uses the public Greenhouse API:
  GET https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true
No authentication required.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List

import settings_db
from config import LOOKBACK_HOURS
from scorer import Job
from scrapers.base import fetch_json, make_job_id

log = logging.getLogger(__name__)

API_BASE = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"


def _matches_title(title: str) -> bool:
    title_l = title.lower()
    return any(kw.lower() in title_l for kw in settings_db.job_titles())


def _parse_date(date_str: str) -> datetime | None:
    """Parse ISO-8601 date string from Greenhouse."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def scrape_company(company_name: str, token: str) -> List[Job]:
    url = API_BASE.format(company=token)
    log.info("Greenhouse – %s (%s)", company_name, token)
    data = fetch_json(url, params={"content": "true"})
    if not data or "jobs" not in data:
        log.warning("Greenhouse – no data for %s", company_name)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    jobs: List[Job] = []

    for item in data["jobs"]:
        title = item.get("title", "")
        if not _matches_title(title):
            continue

        updated_raw = item.get("updated_at", "")
        updated = _parse_date(updated_raw)
        if updated and updated < cutoff:
            continue  # Too old

        # Location
        location_obj = item.get("location", {})
        location = location_obj.get("name", "") if isinstance(location_obj, dict) else str(location_obj)

        # Salary (Greenhouse rarely exposes salary via the API – try metadata)
        salary_text = ""
        content = item.get("content", "")  # HTML description
        metadata = item.get("metadata", []) or []
        for meta in metadata:
            if "salary" in (meta.get("name", "") or "").lower():
                salary_text = str(meta.get("value", ""))
                break

        job_id = make_job_id("greenhouse", str(item.get("id", item.get("absolute_url", title))))

        jobs.append(Job(
            job_id      = job_id,
            title       = title,
            company     = company_name,
            location    = location,
            url         = item.get("absolute_url", ""),
            date_posted = updated_raw[:10] if updated_raw else None,
            description = content,
            salary_text = salary_text,
            source      = f"Greenhouse ({company_name})",
            raw         = item,
        ))

    log.info("Greenhouse – %s: %d matching jobs", company_name, len(jobs))
    return jobs


def scrape_all() -> List[Job]:
    all_jobs: List[Job] = []
    for company_name, token in settings_db.greenhouse_companies().items():
        try:
            all_jobs.extend(scrape_company(company_name, token))
        except Exception as exc:
            log.error("Greenhouse – error scraping %s: %s", company_name, exc)
    return all_jobs
