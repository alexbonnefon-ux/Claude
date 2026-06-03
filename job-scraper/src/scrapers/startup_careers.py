"""
Startup careers page scraper.
Visits 50+ European startup career pages and extracts HR/People roles
using Playwright for JavaScript-heavy pages.
"""
import asyncio
import re
from datetime import datetime
from typing import List, Optional
from loguru import logger

from ..database import Job
from .base import BaseScraper

# fmt: off
STARTUP_CAREER_PAGES = [
    # AI / ML
    {"company": "Mistral AI",         "url": "https://mistral.ai/careers/",               "sector": "AI"},
    {"company": "Hugging Face",       "url": "https://apply.workable.com/huggingface/",    "sector": "AI"},
    {"company": "Cohere",             "url": "https://jobs.lever.co/cohere",               "sector": "AI"},
    {"company": "Stability AI",       "url": "https://stability.ai/careers",               "sector": "AI"},
    {"company": "Dataiku",            "url": "https://www.dataiku.com/company/careers/",   "sector": "AI"},
    {"company": "Contentsquare",      "url": "https://jobs.lever.co/contentsquare",        "sector": "AI"},
    {"company": "Pennylane",          "url": "https://jobs.lever.co/pennylane",            "sector": "Fintech"},
    {"company": "Alan",               "url": "https://jobs.lever.co/alan",                 "sector": "Health"},
    {"company": "Qonto",              "url": "https://jobs.lever.co/qonto",                "sector": "Fintech"},
    {"company": "Swile",              "url": "https://jobs.lever.co/swile",                "sector": "HR Tech"},
    {"company": "Spendesk",           "url": "https://jobs.lever.co/spendesk",             "sector": "Fintech"},
    {"company": "Payfit",             "url": "https://jobs.lever.co/payfit",               "sector": "HR Tech"},
    # HR Tech / People platforms
    {"company": "Lattice",            "url": "https://lattice.com/about/careers",          "sector": "HR Tech"},
    {"company": "Personio",           "url": "https://www.personio.com/about-personio/careers/", "sector": "HR Tech"},
    {"company": "Leapsome",           "url": "https://www.leapsome.com/careers",           "sector": "HR Tech"},
    {"company": "Hibob",              "url": "https://www.hibob.com/careers/",             "sector": "HR Tech"},
    {"company": "Factorial HR",       "url": "https://factorialhr.com/careers",            "sector": "HR Tech"},
    {"company": "Remote",             "url": "https://remote.com/careers",                 "sector": "HR Tech"},
    {"company": "Deel",               "url": "https://www.deel.com/careers",               "sector": "HR Tech"},
    {"company": "Workable",           "url": "https://apply.workable.com/workable/",       "sector": "HR Tech"},
    # Defense / Deep Tech
    {"company": "Helsing",            "url": "https://helsing.ai/careers",                 "sector": "Defense"},
    {"company": "Palantir EU",        "url": "https://jobs.lever.co/palantir",             "sector": "Defense"},
    {"company": "Exail Technologies", "url": "https://www.exail.com/careers",              "sector": "Defense"},
    {"company": "Preligens",          "url": "https://www.preligens.com/en/jobs",          "sector": "Defense"},
    # Sport Tech
    {"company": "Stats Perform",      "url": "https://www.statsperform.com/careers/",      "sector": "Sport"},
    {"company": "Catapult",           "url": "https://catapultsports.com/careers",         "sector": "Sport"},
    {"company": "Playermaker",        "url": "https://www.playermaker.com/careers/",       "sector": "Sport"},
    {"company": "Hudl",               "url": "https://www.hudl.com/jobs",                  "sector": "Sport"},
    # Fintech
    {"company": "Lydia / Sumeria",    "url": "https://sumeria.com/en/careers",             "sector": "Fintech"},
    {"company": "Alma",               "url": "https://jobs.lever.co/alma-fr",              "sector": "Fintech"},
    {"company": "Younited Credit",    "url": "https://www.younited-credit.com/jobs",       "sector": "Fintech"},
    {"company": "Ledger",             "url": "https://jobs.ashbyhq.com/ledger",            "sector": "Fintech"},
    {"company": "Adyen",              "url": "https://careers.adyen.com/vacancies",        "sector": "Fintech"},
    {"company": "Mollie",             "url": "https://jobs.mollie.com/",                   "sector": "Fintech"},
    {"company": "Checkout.com",       "url": "https://www.checkout.com/careers",           "sector": "Fintech"},
    # Health Tech
    {"company": "Doctolib",           "url": "https://careers.doctolib.fr/",               "sector": "Health"},
    {"company": "Owkin",              "url": "https://jobs.lever.co/owkin",                "sector": "Health"},
    {"company": "Sophia Genetics",    "url": "https://www.sophiagenetics.com/careers/",    "sector": "Health"},
    {"company": "Withings",           "url": "https://www.withings.com/fr/fr/careers",     "sector": "Health"},
    {"company": "Bioptimus",          "url": "https://bioptimus.com/careers",              "sector": "Health"},
    # Green Tech
    {"company": "Carbonfact",         "url": "https://www.carbonfact.com/careers",         "sector": "GreenTech"},
    {"company": "Sweep",              "url": "https://jobs.lever.co/sweep",                "sector": "GreenTech"},
    {"company": "Greenly",            "url": "https://www.greenly.earth/careers",          "sector": "GreenTech"},
    {"company": "Lune",               "url": "https://lune.co/jobs",                       "sector": "GreenTech"},
    {"company": "Pledge",             "url": "https://www.pledge.io/careers",              "sector": "GreenTech"},
    # E-Commerce / Marketplace
    {"company": "Back Market",        "url": "https://jobs.lever.co/backmarket",           "sector": "E-Commerce"},
    {"company": "Vestiaire Collective","url": "https://jobs.ashbyhq.com/vestiairecollective", "sector": "E-Commerce"},
    {"company": "ManoMano",           "url": "https://www.manomano.fr/jobs",               "sector": "E-Commerce"},
    {"company": "Mirakl",             "url": "https://www.mirakl.com/careers/",            "sector": "E-Commerce"},
    # Infrastructure / Cloud
    {"company": "OVH Cloud",          "url": "https://www.ovhcloud.com/fr/about-us/careers/", "sector": "Cloud"},
    {"company": "Scaleway",           "url": "https://jobs.ashbyhq.com/scaleway",          "sector": "Cloud"},
    {"company": "Exoscale",           "url": "https://www.exoscale.com/careers/",          "sector": "Cloud"},
    # Other notable French tech
    {"company": "BlaBlaCar",          "url": "https://blog.blablacar.com/jobs",            "sector": "Tech"},
    {"company": "Deezer",             "url": "https://www.deezer.com/en/company/jobs",     "sector": "Tech"},
    {"company": "Dailymotion",        "url": "https://jobs.ashbyhq.com/dailymotion",       "sector": "Tech"},
    {"company": "Meero",              "url": "https://jobs.lever.co/meero",                "sector": "Tech"},
    {"company": "Dashlane",           "url": "https://www.dashlane.com/fr/about/jobs",     "sector": "Tech"},
]
# fmt: on

# HR/People role keywords (case-insensitive)
HR_TITLE_KEYWORDS = [
    "hr", "human resource", "ressources humaines", "people",
    "hrbp", "talent", "recrutement", "recruiting", "payroll",
    "compensation", "benefits", "employee experience", "l&d",
    "learning", "culture", "drh", "rh",
]


class StartupCareersScraper(BaseScraper):
    """Visit startup career pages and extract HR/People role listings."""

    name = "startup_careers"

    async def scrape(self) -> List[Job]:
        """
        Use Playwright to load career pages and extract HR job listings.
        Runs browsers in parallel batches to keep speed reasonable.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed – skipping startup careers scraper")
            return []

        jobs: List[Job] = []
        # Process in batches of 5 concurrent browsers
        batch_size = 5
        pages_list = STARTUP_CAREER_PAGES

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.get_user_agent(),
                viewport={"width": 1280, "height": 800},
                locale="fr-FR",
            )

            for i in range(0, len(pages_list), batch_size):
                batch = pages_list[i:i + batch_size]
                tasks = [
                    self._scrape_career_page(context, entry)
                    for entry in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for entry, result in zip(batch, results):
                    if isinstance(result, Exception):
                        logger.debug(
                            "Startup careers: {} failed: {}", entry["company"], result
                        )
                    else:
                        jobs.extend(result)
                await self.handle_rate_limit()

            await context.close()
            await browser.close()

        seen: set[str] = set()
        unique: List[Job] = []
        for job in jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                unique.append(job)

        logger.info("Startup careers: found {} unique jobs", len(unique))
        return unique

    async def _scrape_career_page(self, context, entry: dict) -> List[Job]:
        """Visit a single career page and extract HR role listings."""
        from playwright.async_api import Page, TimeoutError as PWTimeout

        company = entry["company"]
        url = entry["url"]
        sector = entry.get("sector", "Tech")
        jobs: List[Job] = []

        page: Page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Wait a little for JS to hydrate
            await page.wait_for_timeout(2000)

            # Try to find job listings via various common patterns
            content = await page.content()
            extracted = self._extract_jobs_from_html(content, url, company, sector)
            jobs.extend(extracted)

            # If we found no jobs, try clicking/searching for HR
            if not jobs:
                extracted = await self._try_search_hr(page, url, company, sector)
                jobs.extend(extracted)

        except PWTimeout:
            logger.debug("Startup careers: {} timed out", company)
        except Exception as exc:
            logger.debug("Startup careers: {} error: {}", company, exc)
        finally:
            await page.close()

        logger.debug("Startup careers: {}: {} HR jobs found", company, len(jobs))
        return jobs

    def _extract_jobs_from_html(
        self, html: str, base_url: str, company: str, sector: str
    ) -> List[Job]:
        """Parse HTML and return HR jobs."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        jobs: List[Job] = []

        # Generic approach: find all links/headings that look like job listings
        candidates = (
            soup.select("a[href]") +
            list(soup.select("h2")) +
            list(soup.select("h3")) +
            list(soup.select("[class*='job']")) +
            list(soup.select("[class*='position']")) +
            list(soup.select("[class*='opening']")) +
            list(soup.select("[class*='role']"))
        )

        for el in candidates:
            text = el.get_text(strip=True)
            if not text or len(text) < 5 or len(text) > 200:
                continue
            if not self._is_hr_title(text):
                continue

            href = el.get("href", "") if el.name == "a" else ""
            if href:
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(base_url, href)
            else:
                # Try to find nearest link
                link = el.find_parent("a") or el.find("a")
                if link:
                    href = link.get("href", "")
                    if href and not href.startswith("http"):
                        from urllib.parse import urljoin
                        href = urljoin(base_url, href)
            if not href:
                href = base_url

            # Try to extract location from nearby elements
            location = self._extract_nearby_location(el)

            jobs.append(self.normalize_job(
                title=text,
                company=company,
                location=location,
                url=href,
                job_id=self.make_job_id(href, text, company),
                posted_date=datetime.utcnow(),  # assume recent since we just scraped
                raw_data={"sector": sector, "source_page": base_url},
            ))

        return jobs

    async def _try_search_hr(self, page, base_url: str, company: str, sector: str) -> List[Job]:
        """Try to search for HR roles on pages that have a search box."""
        jobs: List[Job] = []
        try:
            # Look for a search input
            search_input = await page.query_selector("input[type='search'], input[placeholder*='search'], input[placeholder*='Search'], input[placeholder*='Filter']")
            if search_input:
                await search_input.click()
                await search_input.fill("HR")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(2000)
                content = await page.content()
                jobs.extend(self._extract_jobs_from_html(content, base_url, company, sector))
        except Exception:
            pass
        return jobs

    @staticmethod
    def _is_hr_title(text: str) -> bool:
        text_lower = text.lower()
        for kw in HR_TITLE_KEYWORDS:
            if kw in text_lower:
                return True
        return False

    @staticmethod
    def _extract_nearby_location(el) -> str:
        """Try to find a location string near the given element."""
        # Check siblings and parent children for location-like text
        candidates = []
        parent = el.parent
        if parent:
            for sibling in parent.children:
                sibling_text = getattr(sibling, "get_text", lambda **kw: "")()
                candidates.append(sibling_text)
        location_keywords = ["remote", "paris", "tours", "france", "europe", "hybrid", "télétravail"]
        for c in candidates:
            if c and any(kw in c.lower() for kw in location_keywords):
                return c.strip()[:100]
        return "France"
