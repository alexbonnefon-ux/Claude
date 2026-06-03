"""
LinkedIn jobs scraper.
Attempts RSS feed first; falls back to HTTP scraping with realistic headers.
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote_plus
import httpx
from bs4 import BeautifulSoup
from loguru import logger

from ..database import Job
from .base import BaseScraper

# LinkedIn job search URLs for remote HR roles in Europe
_LINKEDIN_SEARCHES = [
    # Remote roles across France/Europe (f_WT=2 = remote)
    {"keywords": "HRBP", "location": "France", "f_WT": "2"},
    {"keywords": "HR Business Partner", "location": "France", "f_WT": "2"},
    {"keywords": "Responsable RH", "location": "France", "f_WT": "2"},
    {"keywords": "Head of People", "location": "France", "f_WT": "2"},
    {"keywords": "People Operations Manager", "location": "France", "f_WT": "2"},
    {"keywords": "HR Manager", "location": "Europe", "f_WT": "2"},
    # Tours specific (all modes)
    {"keywords": "RH", "location": "Tours, Centre-Val de Loire, France"},
    {"keywords": "HRBP", "location": "Tours, Centre-Val de Loire, France"},
    {"keywords": "Responsable RH", "location": "Tours, Centre-Val de Loire, France"},
]


class LinkedInRSSScraper(BaseScraper):
    """
    LinkedIn job scraper.
    LinkedIn doesn't provide public RSS feeds anymore, so this scraper
    uses the public (non-authenticated) job search endpoints.
    """

    name = "linkedin_rss"

    async def scrape(self) -> List[Job]:
        jobs: List[Job] = []
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            },
            follow_redirects=True,
        ) as client:
            for search_params in _LINKEDIN_SEARCHES:
                try:
                    batch = await self.retry(self._fetch_search, client, search_params)
                    jobs.extend(batch)
                    await self.handle_rate_limit()
                except Exception as exc:
                    logger.error("LinkedIn search failed for {}: {}", search_params, exc)

        seen: set[str] = set()
        unique: List[Job] = []
        for job in jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                unique.append(job)

        logger.info("LinkedIn: found {} unique jobs", len(unique))
        return unique

    async def _fetch_search(
        self,
        client: httpx.AsyncClient,
        params: dict,
        start: int = 0,
    ) -> List[Job]:
        """Fetch LinkedIn public job search results."""
        query_params = {
            "keywords": params.get("keywords", ""),
            "location": params.get("location", ""),
            "start": str(start),
            "sortBy": "DD",  # date descending
        }
        if "f_WT" in params:
            query_params["f_WT"] = params["f_WT"]

        url = "https://www.linkedin.com/jobs/search/"
        resp = await client.get(url, params=query_params)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        jobs: List[Job] = []

        # LinkedIn public search uses various card classes
        job_cards = (
            soup.select(".jobs-search__results-list li") or
            soup.select("[class*='job-search-card']") or
            soup.select(".base-card") or
            soup.select("li[class*='result']")
        )

        for card in job_cards:
            try:
                job = self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("LinkedIn: failed to parse card: {}", exc)

        logger.debug(
            "LinkedIn: {} results (start={}) for {}",
            len(jobs), start, params.get("keywords")
        )
        return jobs

    def _parse_card(self, card) -> Optional[Job]:
        """Extract job data from a LinkedIn job card element."""
        # Title
        title_el = (
            card.select_one("h3.base-search-card__title") or
            card.select_one("h3") or
            card.select_one(".job-search-card__title") or
            card.select_one("[class*='title']")
        )
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        # URL
        link_el = card.select_one("a[href*='linkedin.com/jobs']") or card.select_one("a")
        if not link_el:
            return None
        href = link_el.get("href", "")
        if not href:
            return None
        url = href.split("?")[0]  # Strip tracking params

        # Company
        company_el = (
            card.select_one("h4.base-search-card__subtitle") or
            card.select_one(".job-search-card__company-name") or
            card.select_one("h4") or
            card.select_one("[class*='company']")
        )
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        # Location
        location_el = (
            card.select_one(".job-search-card__location") or
            card.select_one("[class*='location']") or
            card.select_one("span[class*='location']")
        )
        location = location_el.get_text(strip=True) if location_el else ""

        # Date
        date_el = card.select_one("time") or card.select_one("[datetime]")
        posted_date = None
        if date_el:
            dt_attr = date_el.get("datetime", "")
            if dt_attr:
                try:
                    posted_date = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if not posted_date:
                text = date_el.get_text(strip=True).lower()
                posted_date = self._parse_relative_date(text)

        return self.normalize_job(
            title=title,
            company=company,
            location=location,
            url=url,
            job_id=self.make_job_id(url),
            posted_date=posted_date,
        )

    @staticmethod
    def _parse_relative_date(text: str) -> Optional[datetime]:
        now = datetime.utcnow()
        if any(w in text for w in ["today", "today", "aujourd"]):
            return now
        m = re.search(r"(\d+)\s*(hour|heure)", text)
        if m:
            return now - timedelta(hours=int(m.group(1)))
        m = re.search(r"(\d+)\s*(day|jour)", text)
        if m:
            return now - timedelta(days=int(m.group(1)))
        m = re.search(r"(\d+)\s*(week|semaine)", text)
        if m:
            return now - timedelta(weeks=int(m.group(1)))
        return None
