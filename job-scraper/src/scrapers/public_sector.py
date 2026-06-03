"""
French public sector job scraper.
Targets emploi-territorial.fr, fonction-publique.gouv.fr, and
specific institutions in the Tours / Indre-et-Loire area.
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote_plus, urljoin
import httpx
from bs4 import BeautifulSoup
from loguru import logger

from ..database import Job
from .base import BaseScraper

# Public sector portals and specific employers
PUBLIC_SOURCES = [
    {
        "name": "emploi_territorial",
        "type": "portal",
        "search_url": "https://www.emploi-territorial.fr/offre-d-emploi/liste-offres-emploi.html",
        "params": {"kw": "ressources humaines", "dep": "37"},
    },
    {
        "name": "emploi_territorial_rh",
        "type": "portal",
        "search_url": "https://www.emploi-territorial.fr/offre-d-emploi/liste-offres-emploi.html",
        "params": {"kw": "DRH", "dep": "37"},
    },
    {
        "name": "fonction_publique",
        "type": "portal",
        "search_url": "https://place-emploi-public.gouv.fr/offre-emploi/liste-offres-emploi.html",
        "params": {"k": "ressources humaines", "libelleRegion": "Centre-Val de Loire"},
    },
    {
        "name": "chu_tours",
        "type": "direct",
        "url": "https://www.chu-tours.fr/recrutement/offres-demploi/",
        "hr_search": True,
    },
    {
        "name": "mairie_tours",
        "type": "direct",
        "url": "https://www.tours.fr/la-mairie/offres-demploi/",
        "hr_search": True,
    },
    {
        "name": "cd37",
        "type": "direct",
        "url": "https://www.indre-et-loire.fr/le-departement/travailler-au-conseil-departemental/nos-offres-demploi",
        "hr_search": True,
    },
    {
        "name": "region_cvl",
        "type": "direct",
        "url": "https://www.centrevaldeloire.fr/la-region/travailler-a-la-region/les-offres-demploi",
        "hr_search": True,
    },
    {
        "name": "mfp_centre",
        "type": "portal",
        "search_url": "https://www.mfp.fr/offres-d-emploi/",
        "params": {"keyword": "ressources humaines", "region": "Centre-Val de Loire"},
    },
]

HR_KEYWORDS_PUBLIC = [
    "ressources humaines", "rh", "drh", "hrbp", "responsable rh",
    "directeur rh", "responsable du personnel", "gestionnaire rh",
    "chargé rh", "attaché rh", "conseiller rh",
]


class PublicSectorScraper(BaseScraper):
    """Scrape French public sector job boards for HR roles."""

    name = "public_sector"

    async def scrape(self) -> List[Job]:
        jobs: List[Job] = []
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": self.get_user_agent(),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
            follow_redirects=True,
        ) as client:
            for source in PUBLIC_SOURCES:
                try:
                    if source["type"] == "portal":
                        batch = await self.retry(self._scrape_portal, client, source)
                    else:
                        batch = await self.retry(self._scrape_direct, client, source)
                    jobs.extend(batch)
                    await self.handle_rate_limit()
                except Exception as exc:
                    logger.error("Public sector {} failed: {}", source["name"], exc)

        seen: set[str] = set()
        unique: List[Job] = []
        for job in jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                unique.append(job)

        logger.info("Public sector: found {} unique jobs", len(unique))
        return unique

    async def _scrape_portal(self, client: httpx.AsyncClient, source: dict) -> List[Job]:
        """Scrape a search-based portal."""
        resp = await client.get(source["search_url"], params=source.get("params", {}))
        resp.raise_for_status()
        return self._parse_job_list(
            resp.text, source["search_url"], source["name"], "Secteur Public"
        )

    async def _scrape_direct(self, client: httpx.AsyncClient, source: dict) -> List[Job]:
        """Scrape a direct employer jobs page."""
        resp = await client.get(source["url"])
        resp.raise_for_status()
        jobs = self._parse_job_list(
            resp.text, source["url"], source["name"], self._employer_name(source["name"])
        )
        # Filter for HR roles if flag is set
        if source.get("hr_search"):
            jobs = [j for j in jobs if self._is_hr_title(j.title)]
        return jobs

    @staticmethod
    def _employer_name(slug: str) -> str:
        names = {
            "chu_tours": "CHU de Tours",
            "mairie_tours": "Mairie de Tours",
            "cd37": "Conseil Départemental 37",
            "region_cvl": "Région Centre-Val de Loire",
            "emploi_territorial": "Emploi Territorial",
            "emploi_territorial_rh": "Emploi Territorial",
            "fonction_publique": "Fonction Publique",
            "mfp_centre": "MFP Centre-Val de Loire",
        }
        return names.get(slug, slug.replace("_", " ").title())

    def _parse_job_list(
        self, html: str, base_url: str, source_name: str, default_company: str
    ) -> List[Job]:
        soup = BeautifulSoup(html, "lxml")
        jobs: List[Job] = []

        # Try common job-list selectors
        items = (
            soup.select("article.job") or
            soup.select(".job-item") or
            soup.select(".offre") or
            soup.select("li.offre") or
            soup.select(".offer-card") or
            soup.select("[class*='offre']") or
            soup.select("[class*='job']") or
            soup.select("li") or
            soup.select("article")
        )

        for item in items[:50]:
            try:
                job = self._parse_item(item, base_url, default_company)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Public sector parse error: {}", exc)

        return jobs

    def _parse_item(self, el, base_url: str, default_company: str) -> Optional[Job]:
        """Extract job info from a list item."""
        title_el = (
            el.select_one("h2 a") or
            el.select_one("h3 a") or
            el.select_one("h4 a") or
            el.select_one(".title a") or
            el.select_one("[class*='title']") or
            el.select_one("a[href*='offre']") or
            el.select_one("a[href*='emploi']")
        )
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title or len(title) < 5:
            return None

        href = title_el.get("href", "") if title_el.name == "a" else ""
        if not href:
            link = el.find("a")
            href = link.get("href", "") if link else ""
        url = urljoin(base_url, href) if href else base_url

        # Company / employer
        company_el = (
            el.select_one("[class*='employer']") or
            el.select_one("[class*='organisation']") or
            el.select_one("[class*='collectivite']")
        )
        company = company_el.get_text(strip=True) if company_el else default_company

        # Location
        location_el = (
            el.select_one("[class*='location']") or
            el.select_one("[class*='lieu']") or
            el.select_one("[class*='localisation']")
        )
        location = location_el.get_text(strip=True) if location_el else "Tours, Indre-et-Loire"

        # Date
        date_el = el.select_one("time") or el.select_one("[class*='date']")
        posted_date = self._parse_date_el(date_el)

        return self.normalize_job(
            title=title,
            company=company,
            location=location,
            url=url,
            job_id=self.make_job_id(url, title, company),
            posted_date=posted_date,
            remote_policy="onsite",  # public sector usually onsite
        )

    @staticmethod
    def _parse_date_el(el) -> Optional[datetime]:
        if el is None:
            return None
        dt_attr = el.get("datetime", "")
        if dt_attr:
            try:
                return datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
            except ValueError:
                pass
        text = el.get_text(strip=True).lower()
        now = datetime.utcnow()
        if "aujourd" in text:
            return now
        m = re.search(r"(\d+)[/ -](\d+)[/ -](\d{4})", text)
        if m:
            try:
                return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
        return None

    @staticmethod
    def _is_hr_title(title: str) -> bool:
        tl = title.lower()
        return any(kw in tl for kw in HR_KEYWORDS_PUBLIC)
