"""
HelloWork scraper using httpx + BeautifulSoup.
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

_SEARCHES = [
    ("responsable rh", "Tours"),
    ("HRBP", "Tours"),
    ("DRH", "Tours"),
    ("responsable ressources humaines", "Tours"),
    ("people manager", "Tours"),
    ("HR manager", "Tours"),
    # Remote
    ("HRBP", ""),
    ("responsable rh", ""),
    ("head of people", ""),
    ("HR business partner", ""),
]

BASE_URL = "https://www.hellowork.com"


class HelloWorkScraper(BaseScraper):
    """Scrape HelloWork job listings."""

    name = "hellowork"

    async def scrape(self) -> List[Job]:
        jobs: List[Job] = []
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            follow_redirects=True,
        ) as client:
            for keyword, location in _SEARCHES:
                try:
                    batch = await self.retry(self._fetch_page, client, keyword, location)
                    jobs.extend(batch)
                    await self.handle_rate_limit()
                except Exception as exc:
                    logger.error(
                        "HelloWork failed for keyword='{}' loc='{}': {}", keyword, location, exc
                    )

        seen: set[str] = set()
        unique: List[Job] = []
        for job in jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                unique.append(job)

        logger.info("HelloWork: found {} unique jobs", len(unique))
        return unique

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        keyword: str,
        location: str,
        page: int = 1,
    ) -> List[Job]:
        params: dict = {
            "k": keyword,
            "p": str(page),
        }
        if location:
            params["l"] = location

        url = f"{BASE_URL}/fr-fr/emploi/recherche.html"
        resp = await client.get(url, params=params)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        jobs: List[Job] = []

        # HelloWork job cards have data-id attributes
        job_cards = soup.select("[data-id], .job-card, article[class*='job'], li[class*='job']")
        if not job_cards:
            # Fallback: look for any card-like structure
            job_cards = soup.select("article, .offer, .job-item, [class*='offer']")

        for card in job_cards[:20]:  # limit per page
            try:
                job = self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("HelloWork: failed to parse card: {}", exc)

        # Paginate if there's a next page (up to 3 pages)
        if page < 3 and len(job_cards) >= 15:
            await self.handle_rate_limit()
            try:
                more = await self._fetch_page(client, keyword, location, page + 1)
                jobs.extend(more)
            except Exception:
                pass

        logger.debug(
            "HelloWork: {} results p{} for keyword='{}' loc='{}'",
            len(jobs), page, keyword, location
        )
        return jobs

    def _parse_card(self, card) -> Optional[Job]:
        """Extract job data from a BeautifulSoup card element."""
        # Try various selectors that HelloWork might use
        title_el = (
            card.select_one("h2 a") or
            card.select_one("h3 a") or
            card.select_one("a[class*='title']") or
            card.select_one(".job-title") or
            card.select_one("[class*='title'] a") or
            card.select_one("a[href*='/emploi/']")
        )
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        if not href:
            return None
        url = href if href.startswith("http") else BASE_URL + href

        company_el = (
            card.select_one("[class*='company']") or
            card.select_one("[class*='employer']") or
            card.select_one(".company-name")
        )
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        location_el = (
            card.select_one("[class*='location']") or
            card.select_one("[class*='localisation']") or
            card.select_one(".location")
        )
        location = location_el.get_text(strip=True) if location_el else ""

        salary_el = card.select_one("[class*='salary']") or card.select_one("[class*='salaire']")
        salary_text = salary_el.get_text(strip=True) if salary_el else ""
        salary_min, salary_max = self.parse_salary(salary_text)

        date_el = (
            card.select_one("time") or
            card.select_one("[class*='date']") or
            card.select_one("[datetime]")
        )
        posted_date = self._parse_date(date_el)

        description_el = card.select_one("[class*='description']") or card.select_one("p")
        description = description_el.get_text(strip=True) if description_el else ""

        return self.normalize_job(
            title=title,
            company=company,
            location=location,
            url=url,
            job_id=self.make_job_id(url),
            description=description,
            salary_min=salary_min,
            salary_max=salary_max,
            posted_date=posted_date,
        )

    @staticmethod
    def _parse_date(el) -> Optional[datetime]:
        """Try to extract a datetime from a time element."""
        if el is None:
            return None
        dt_attr = el.get("datetime", "")
        if dt_attr:
            try:
                return datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
            except ValueError:
                pass
        # Try relative like "il y a 2 jours"
        text = el.get_text(strip=True).lower()
        now = datetime.utcnow()
        if "aujourd" in text or "today" in text:
            return now
        m = re.search(r"(\d+)\s*jour", text)
        if m:
            return now - timedelta(days=int(m.group(1)))
        m = re.search(r"(\d+)\s*heure", text)
        if m:
            return now - timedelta(hours=int(m.group(1)))
        return None
