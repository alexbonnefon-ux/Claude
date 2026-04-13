"""Lever job board scraper.

Uses the public Lever postings API:
  GET https://api.lever.co/v0/postings/{company}?mode=json
No authentication required.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List

from config import LEVER_COMPANIES, LOOKBACK_HOURS, JOB_TITLES, SEARCH_KEYWORDS
from scorer import Job
from scrapers.base import fetch_json, make_job_id

log = logging.getLogger(__name__)

API_BASE = "https://api.lever.co/v0/postings/{company}?mode=json"


def _matches_title(title: str) -> bool:
    t = title.lower()
    return any(kw.lower() in t for kw in JOB_TITLES + SEARCH_KEYWORDS)


def scrape_company(company_name: str, identifier: str) -> List[Job]:
    url = API_BASE.format(company=identifier)
    log.info("Lever – %s (%s)", company_name, identifier)
    data = fetch_json(url)
    if not data:
        log.warning("Lever – no data for %s", company_name)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    jobs: List[Job] = []

    for item in data:
        title = item.get("text", "")
        if not _matches_title(title):
            continue

        # Lever timestamps are in milliseconds
        created_ms = item.get("createdAt", 0)
        created    = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
        if created < cutoff:
            continue

        categories = item.get("categories", {})
        location   = categories.get("location", "") or item.get("workplaceType", "")
        team       = categories.get("team", "")
        commitment = categories.get("commitment", "")  # e.g. "Full-time"

        # Build description from lists
        description_parts = []
        for block in item.get("lists", []):
            description_parts.append(block.get("text", ""))
            for li in block.get("content", "").split("<li>"):
                description_parts.append(li)

        additional = item.get("additional", "")
        description = " ".join(description_parts) + " " + additional

        # Salary – Lever rarely shows it; try text search
        salary_text = ""
        full_text   = item.get("descriptionPlain", "") or description
        if "€" in full_text or "salary" in full_text.lower() or "k€" in full_text.lower():
            salary_text = full_text[:500]

        job_id = make_job_id("lever", item.get("id", title + company_name))

        jobs.append(Job(
            job_id      = job_id,
            title       = title,
            company     = company_name,
            location    = location,
            url         = item.get("hostedUrl", item.get("applyUrl", "")),
            date_posted = created.date().isoformat(),
            description = full_text,
            salary_text = salary_text,
            source      = f"Lever ({company_name})",
            raw         = item,
        ))

    log.info("Lever – %s: %d matching jobs", company_name, len(jobs))
    return jobs


def scrape_all() -> List[Job]:
    all_jobs: List[Job] = []
    for company_name, identifier in LEVER_COMPANIES.items():
        try:
            all_jobs.extend(scrape_company(company_name, identifier))
        except Exception as exc:
            log.error("Lever – error scraping %s: %s", company_name, exc)
    return all_jobs
