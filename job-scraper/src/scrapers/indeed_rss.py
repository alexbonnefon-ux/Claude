"""
Indeed RSS feed scraper.
Parses multiple RSS feeds for different role / location combinations.
"""
import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List
from urllib.parse import quote_plus
import httpx
import feedparser
from loguru import logger

from ..database import Job
from .base import BaseScraper


# RSS feed definitions: (query, location, extra_params)
_RSS_FEEDS = [
    # Tours area
    ("HRBP", "Tours", ""),
    ("responsable RH", "Tours", ""),
    ("responsable ressources humaines", "Tours", ""),
    ("DRH", "Tours", ""),
    ("HR manager", "Tours", ""),
    ("people manager", "Tours", ""),
    # Remote / all France
    ("HRBP", "France", "&remotejobs=1"),
    ("HR business partner", "France", "&remotejobs=1"),
    ("responsable RH", "France", "&remotejobs=1"),
    ("head of people", "France", "&remotejobs=1"),
    ("head of HR", "France", "&remotejobs=1"),
    ("people operations manager", "France", "&remotejobs=1"),
    ("DRH télétravail", "France", ""),
    ("responsable ressources humaines télétravail", "France", ""),
    # Paris (for hybrid opportunities)
    ("HRBP", "Paris", ""),
    ("HR business partner", "Paris", ""),
    ("responsable RH senior", "Paris", ""),
    ("directeur ressources humaines", "Paris", ""),
]


class IndeedRSSScraper(BaseScraper):
    """Parse Indeed France RSS feeds."""

    name = "indeed_rss"

    async def scrape(self) -> List[Job]:
        jobs: List[Job] = []
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": self.get_user_agent()},
            follow_redirects=True,
        ) as client:
            for query, location, extra in _RSS_FEEDS:
                try:
                    batch = await self.retry(self._fetch_feed, client, query, location, extra)
                    jobs.extend(batch)
                    await self.handle_rate_limit()
                except Exception as exc:
                    logger.error(
                        "Indeed RSS feed failed for query='{}' loc='{}': {}",
                        query, location, exc
                    )

        seen: set[str] = set()
        unique: List[Job] = []
        for job in jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                unique.append(job)

        logger.info("Indeed RSS: found {} unique jobs", len(unique))
        return unique

    async def _fetch_feed(
        self,
        client: httpx.AsyncClient,
        query: str,
        location: str,
        extra_params: str,
    ) -> List[Job]:
        url = (
            f"https://fr.indeed.com/rss"
            f"?q={quote_plus(query)}"
            f"&l={quote_plus(location)}"
            f"&sort=date"
            f"{extra_params}"
        )
        resp = await client.get(url)
        resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        jobs: List[Job] = []
        for entry in feed.entries:
            try:
                job = self._parse_entry(entry)
                jobs.append(job)
            except Exception as exc:
                logger.debug("Indeed: failed to parse entry: {}", exc)

        logger.debug("Indeed: {} results for query='{}' loc='{}'", len(jobs), query, location)
        return jobs

    def _parse_entry(self, entry) -> Job:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "")

        # Indeed RSS format: "Title - Company (Location)"
        company = ""
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            title_clean = parts[0].strip()
            company_loc = parts[1]
            if "(" in company_loc:
                company = company_loc[:company_loc.rfind("(")].strip()
            else:
                company = company_loc.strip()
        else:
            title_clean = title

        # Extract location from summary
        location = ""
        import re
        loc_match = re.search(r"<b>Lieu\s*:</b>\s*([^<]+)", summary)
        if loc_match:
            location = loc_match.group(1).strip()
        else:
            # Try to find location in the title parenthetical
            paren_match = re.search(r"\(([^)]+)\)\s*$", title)
            if paren_match:
                location = paren_match.group(1).strip()

        # Parse posted date
        posted_date = None
        published = entry.get("published", "")
        if published:
            try:
                posted_date = parsedate_to_datetime(published)
            except Exception:
                pass

        # Strip HTML from summary for description
        description = re.sub(r"<[^>]+>", " ", summary).strip()

        return self.normalize_job(
            title=title_clean,
            company=company or "Unknown",
            location=location or "France",
            url=link,
            job_id=self.make_job_id(link),
            description=description,
            posted_date=posted_date,
        )
