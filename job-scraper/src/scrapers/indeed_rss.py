"""
Indeed RSS feed scraper.
Parses multiple RSS feeds for different role / location combinations.
Uses stdlib xml.etree.ElementTree to avoid feedparser/sgmllib Python 3.11 issues.
"""
import asyncio
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List
from urllib.parse import quote_plus
from xml.etree import ElementTree
import httpx
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

        jobs: List[Job] = []
        try:
            root = ElementTree.fromstring(resp.text)
        except ElementTree.ParseError as exc:
            logger.debug("Indeed: XML parse error for query='{}': {}", query, exc)
            return jobs

        # RSS 2.0: channel/item
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//item")
        for item in items:
            try:
                job = self._parse_item(item)
                jobs.append(job)
            except Exception as exc:
                logger.debug("Indeed: failed to parse item: {}", exc)

        logger.debug("Indeed: {} results for query='{}' loc='{}'", len(jobs), query, location)
        return jobs

    def _parse_item(self, item: ElementTree.Element) -> Job:
        def _text(tag: str) -> str:
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        title_raw = _text("title")
        link = _text("link")
        summary = _text("description")
        published = _text("pubDate")

        # Indeed RSS format: "Title - Company (Location)"
        company = ""
        title_clean = title_raw
        if " - " in title_raw:
            parts = title_raw.rsplit(" - ", 1)
            title_clean = parts[0].strip()
            company_loc = parts[1]
            if "(" in company_loc:
                company = company_loc[:company_loc.rfind("(")].strip()
            else:
                company = company_loc.strip()

        # Extract location from HTML summary
        location = ""
        loc_match = re.search(r"<b>Lieu\s*:</b>\s*([^<]+)", summary)
        if loc_match:
            location = loc_match.group(1).strip()
        else:
            paren_match = re.search(r"\(([^)]+)\)\s*$", title_raw)
            if paren_match:
                location = paren_match.group(1).strip()

        # Parse posted date (RFC 2822)
        posted_date = None
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
