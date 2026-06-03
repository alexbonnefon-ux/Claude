"""
ATS platform scraper (Ashby, Lever, Greenhouse).
Searches HR/People roles across major ATS platforms used by tech companies.
"""
import asyncio
import re
from datetime import datetime
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup
from loguru import logger

from ..database import Job
from .base import BaseScraper

# HR-related keywords to search across ATS platforms
HR_KEYWORDS = [
    "HR", "Human Resources", "People", "HRBP",
    "Talent", "Recruiting", "Employee Experience",
]

# Greenhouse API endpoint (public, no auth required)
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"

# Known tech companies using Greenhouse with EU presence
GREENHOUSE_COMPANIES = [
    "adyen", "contentful", "personio", "getdbt", "algolia",
    "datadog", "elastic", "hashicorp", "klaviyo", "mongodb",
    "netlify", "notion", "segment", "zendesk", "zapier",
    "hubspot", "intercom", "lattice", "remote", "deel",
    "workday", "bamboohr", "hibob", "leapsome",
]

# Lever companies with EU presence
LEVER_BASE = "https://api.lever.co/v0/postings/{company}"
LEVER_COMPANIES = [
    "doctolib", "qonto", "swile", "spendesk", "payfit",
    "alan", "pennylane", "sumeria", "alma-fr", "contentsquare",
    "backmarket", "meero", "theodo", "l-atelier",
]

# Ashby companies
ASHBY_API = "https://jobs.ashbyhq.com/api/non-user-graphql"
ASHBY_COMPANIES = [
    "mistral", "huggingface", "dataiku", "ledger", "scaleway",
    "ovhcloud", "dailymotion", "blablacar", "vestiairecollective",
]


class ATSPlatformsScraper(BaseScraper):
    """Scrape HR jobs from Greenhouse, Lever, and Ashby ATS platforms."""

    name = "ats_platforms"

    async def scrape(self) -> List[Job]:
        jobs: List[Job] = []

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": self.get_user_agent()},
            follow_redirects=True,
        ) as client:
            # Run all platform scrapers concurrently
            results = await asyncio.gather(
                self._scrape_greenhouse(client),
                self._scrape_lever(client),
                self._scrape_ashby(client),
                return_exceptions=True,
            )

        for result in results:
            if isinstance(result, Exception):
                logger.error("ATS platform scraper error: {}", result)
            else:
                jobs.extend(result)

        seen: set[str] = set()
        unique: List[Job] = []
        for job in jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                unique.append(job)

        logger.info("ATS platforms: found {} unique jobs", len(unique))
        return unique

    # ------------------------------------------------------------------
    # Greenhouse
    # ------------------------------------------------------------------

    async def _scrape_greenhouse(self, client: httpx.AsyncClient) -> List[Job]:
        jobs: List[Job] = []
        for company in GREENHOUSE_COMPANIES:
            try:
                url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
                resp = await client.get(url)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("jobs", []):
                    if self._is_hr_role(item.get("title", "")):
                        job = self._greenhouse_to_job(item, company)
                        if job:
                            jobs.append(job)
                await self.handle_rate_limit()
            except Exception as exc:
                logger.debug("Greenhouse {}: {}", company, exc)
        return jobs

    def _greenhouse_to_job(self, item: dict, company_slug: str) -> Optional[Job]:
        title = item.get("title", "")
        if not title:
            return None
        location_data = item.get("location", {})
        location = location_data.get("name", "") if isinstance(location_data, dict) else str(location_data)
        url = item.get("absolute_url", f"https://boards.greenhouse.io/{company_slug}/jobs/{item.get('id', '')}")
        updated = item.get("updated_at", "")
        posted_date = None
        if updated:
            try:
                posted_date = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except ValueError:
                pass
        description = ""
        content = item.get("content", "")
        if content:
            description = re.sub(r"<[^>]+>", " ", content)[:500]

        return self.normalize_job(
            title=title,
            company=company_slug.replace("-", " ").title(),
            location=location,
            url=url,
            job_id=str(item.get("id", self.make_job_id(url))),
            description=description,
            posted_date=posted_date,
            raw_data={"platform": "greenhouse", "company_slug": company_slug},
        )

    # ------------------------------------------------------------------
    # Lever
    # ------------------------------------------------------------------

    async def _scrape_lever(self, client: httpx.AsyncClient) -> List[Job]:
        jobs: List[Job] = []
        for company in LEVER_COMPANIES:
            try:
                url = f"https://api.lever.co/v0/postings/{company}?mode=json"
                resp = await client.get(url)
                if resp.status_code in (404, 403):
                    continue
                resp.raise_for_status()
                postings = resp.json()
                for item in postings:
                    if self._is_hr_role(item.get("text", "") + " " + item.get("categories", {}).get("team", "")):
                        job = self._lever_to_job(item, company)
                        if job:
                            jobs.append(job)
                await self.handle_rate_limit()
            except Exception as exc:
                logger.debug("Lever {}: {}", company, exc)
        return jobs

    def _lever_to_job(self, item: dict, company_slug: str) -> Optional[Job]:
        title = item.get("text", "")
        if not title:
            return None
        url = item.get("hostedUrl", "")
        if not url:
            url = f"https://jobs.lever.co/{company_slug}/{item.get('id', '')}"
        location = item.get("categories", {}).get("location", "") or item.get("workplaceType", "")
        posted_ts = item.get("createdAt", 0)
        posted_date = None
        if posted_ts:
            try:
                posted_date = datetime.utcfromtimestamp(posted_ts / 1000)
            except (ValueError, OSError):
                pass
        description = ""
        lists = item.get("lists", [])
        if lists:
            description = " ".join(l.get("content", "") for l in lists[:2])
            description = re.sub(r"<[^>]+>", " ", description)[:500]

        return self.normalize_job(
            title=title,
            company=company_slug.replace("-", " ").title(),
            location=location,
            url=url,
            job_id=item.get("id", self.make_job_id(url)),
            description=description,
            posted_date=posted_date,
            raw_data={"platform": "lever", "company_slug": company_slug},
        )

    # ------------------------------------------------------------------
    # Ashby
    # ------------------------------------------------------------------

    async def _scrape_ashby(self, client: httpx.AsyncClient) -> List[Job]:
        jobs: List[Job] = []
        for company in ASHBY_COMPANIES:
            try:
                payload = {
                    "operationName": "ApiJobBoardWithTeams",
                    "variables": {"organizationHostedJobsPageName": company},
                    "query": """
                        query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
                            jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {
                                teams {
                                    name
                                    parentTeamName
                                    jobPostings {
                                        id title locationName isRemote
                                        employmentType
                                        publishedDate
                                        externalLink
                                    }
                                }
                            }
                        }
                    """,
                }
                resp = await client.post(ASHBY_API, json=payload)
                if resp.status_code in (404, 400, 403):
                    continue
                resp.raise_for_status()
                data = resp.json()
                board = (data.get("data") or {}).get("jobBoard") or {}
                for team in board.get("teams", []):
                    team_name = team.get("name", "")
                    for posting in team.get("jobPostings", []):
                        title = posting.get("title", "")
                        if self._is_hr_role(title + " " + team_name):
                            job = self._ashby_to_job(posting, company, team_name)
                            if job:
                                jobs.append(job)
                await self.handle_rate_limit()
            except Exception as exc:
                logger.debug("Ashby {}: {}", company, exc)
        return jobs

    def _ashby_to_job(self, posting: dict, company_slug: str, team_name: str) -> Optional[Job]:
        title = posting.get("title", "")
        if not title:
            return None
        job_id = posting.get("id", "")
        url = posting.get("externalLink") or f"https://jobs.ashbyhq.com/{company_slug}/{job_id}"
        location = posting.get("locationName", "")
        is_remote = posting.get("isRemote", False)
        if is_remote:
            remote_policy = "full"
        else:
            remote_policy = "unknown"
        published = posting.get("publishedDate", "")
        posted_date = None
        if published:
            try:
                posted_date = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                pass

        return self.normalize_job(
            title=title,
            company=company_slug.replace("-", " ").title(),
            location=location,
            url=url,
            job_id=job_id or self.make_job_id(url),
            remote_policy=remote_policy,
            posted_date=posted_date,
            raw_data={"platform": "ashby", "company_slug": company_slug, "team": team_name},
        )

    @staticmethod
    def _is_hr_role(text: str) -> bool:
        """Return True if the text looks like an HR/People role."""
        text_lower = text.lower()
        hr_terms = [
            "hr ", "h.r.", "human resources", "ressources humaines",
            "people", "hrbp", "talent", "recrutement", "recruiting",
            "employee experience", "culture", "l&d", "learning",
            "compensation", "benefits", "total rewards", "payroll",
            "rh ", " rh", "drh",
        ]
        return any(term in text_lower for term in hr_terms)
