"""France Travail (Pôle Emploi) API scraper."""

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import httpx
from loguru import logger

from src.config import (
    FRANCE_TRAVAIL_CLIENT_ID,
    FRANCE_TRAVAIL_CLIENT_SECRET,
    FRANCE_TRAVAIL_TOKEN_URL,
    FRANCE_TRAVAIL_JOBS_URL,
    SEARCH_KEYWORDS,
)
from src.scrapers.base import BaseScraper, Job


DEPARTEMENT_CODES = ["37"]  # Indre-et-Loire (Tours)
# No departement filter for remote roles — use keyword "télétravail"

HR_ROME_CODES = [
    "M1501",  # Assistanat en ressources humaines
    "M1502",  # Développement des ressources humaines
    "M1503",  # Management des ressources humaines
]


class FranceTravailScraper(BaseScraper):
    """Scraper for the France Travail (formerly Pôle Emploi) job API."""

    SOURCE_NAME = "france_travail"

    def __init__(self) -> None:
        super().__init__()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _get_access_token(self) -> str:
        """Obtain or refresh the OAuth2 bearer token."""
        import time

        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        if not FRANCE_TRAVAIL_CLIENT_ID or not FRANCE_TRAVAIL_CLIENT_SECRET:
            raise RuntimeError(
                "FRANCE_TRAVAIL_CLIENT_ID and FRANCE_TRAVAIL_CLIENT_SECRET must be set"
            )

        client = await self._get_client()
        response = await client.post(
            FRANCE_TRAVAIL_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": FRANCE_TRAVAIL_CLIENT_ID,
                "client_secret": FRANCE_TRAVAIL_CLIENT_SECRET,
                "scope": "api_offresdemploiv2 o2dsoffre",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        data = response.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 1500)
        logger.info("France Travail: obtained access token")
        return self._access_token

    async def _search_jobs(
        self,
        keyword: str,
        departement: Optional[str] = None,
        distance: int = 30,
        remote_only: bool = False,
        page: int = 0,
    ) -> Dict[str, Any]:
        """
        Call the France Travail search API.
        Returns the raw JSON response.
        """
        token = await self._get_access_token()

        params: Dict[str, Any] = {
            "motsCles": keyword,
            "range": f"{page * 150}-{page * 150 + 149}",  # max 150 per page
            "sort": "1",  # sort by date
        }

        if departement:
            params["departement"] = departement
            params["distance"] = distance

        if remote_only:
            params["modesTravail"] = "T"  # Télétravail

        client = await self._get_client()
        await self._sleep_between_requests()

        response = await client.get(
            FRANCE_TRAVAIL_JOBS_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

        if response.status_code == 204:
            return {"resultats": [], "Content-Range": "0-0/0"}

        if response.status_code == 429:
            await self.handle_rate_limit(retry_after=60)
            return await self._search_jobs(keyword, departement, distance, remote_only, page)

        response.raise_for_status()
        return response.json()

    def _parse_job(self, raw: Dict[str, Any]) -> Optional[Job]:
        """Parse a single job dict from the France Travail API."""
        try:
            job_id = raw.get("id", "")
            if not job_id:
                return None

            title = raw.get("intitule", "").strip()
            company_name = raw.get("entreprise", {}).get("nom", "Entreprise confidentielle").strip()
            url = raw.get("origineOffre", {}).get("urlOrigine") or f"https://www.francetravail.fr/offres/recherche/detail/{job_id}"

            # Location
            lieu = raw.get("lieuTravail", {})
            location_parts = [lieu.get("libelle", ""), lieu.get("codePostal", "")]
            location = ", ".join(p for p in location_parts if p) or None

            # Salary
            salaire = raw.get("salaire", {})
            salary_text = salaire.get("libelle", "")
            salary_complement = salaire.get("complement1", "")
            full_salary_text = f"{salary_text} {salary_complement}".strip()

            # Remote
            remote_raw = raw.get("modeTravail", {})
            remote_libelle = remote_raw.get("libelle", "") if isinstance(remote_raw, dict) else ""
            if "télétravail" in remote_libelle.lower() or "complet" in remote_libelle.lower():
                remote_policy = "remote"
            elif "hybride" in remote_libelle.lower() or "partiel" in remote_libelle.lower():
                remote_policy = "hybrid"
            else:
                remote_policy = "onsite"

            # Posted date
            date_str = raw.get("dateCreation") or raw.get("dateActualisation")
            posted_date: Optional[datetime] = None
            if date_str:
                try:
                    posted_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            job = self.normalize_job(
                job_id=job_id,
                title=title,
                company=company_name,
                url=url,
                location=location,
                salary_text=full_salary_text,
                description=raw.get("description", ""),
                posted_date=posted_date,
                raw_data=raw,
            )
            # Override remote_policy with the API's explicit value if present
            if remote_libelle:
                job.remote_policy = remote_policy

            return job

        except Exception as e:
            logger.warning(f"France Travail: failed to parse job: {e}")
            return None

    async def _scrape_query(self, keyword: str, departement: Optional[str] = None, remote_only: bool = False) -> List[Job]:
        """Scrape all pages for a single keyword/location combination."""
        jobs: List[Job] = []
        page = 0

        while True:
            try:
                data = await self._search_jobs(keyword, departement, remote_only=remote_only, page=page)
            except httpx.HTTPStatusError as e:
                logger.warning(f"France Travail: HTTP error for '{keyword}' page {page}: {e}")
                break
            except Exception as e:
                logger.error(f"France Travail: unexpected error for '{keyword}': {e}")
                break

            results = data.get("resultats", [])
            if not results:
                break

            for raw in results:
                job = self._parse_job(raw)
                if job:
                    jobs.append(job)

            # Check if there are more pages
            content_range = data.get("Content-Range", "")
            try:
                # Format: "0-149/523"
                total = int(content_range.split("/")[-1])
                fetched_so_far = (page + 1) * 150
                if fetched_so_far >= total or fetched_so_far >= 300:  # cap at 2 pages / 300 jobs per query
                    break
            except (ValueError, IndexError):
                break

            page += 1
            await asyncio.sleep(1)

        logger.info(f"France Travail: '{keyword}' dept={departement} remote={remote_only} -> {len(jobs)} jobs")
        return jobs

    async def scrape(self) -> List[Job]:
        """Run all France Travail queries and return deduplicated jobs."""
        all_jobs: List[Job] = []
        seen_ids: set = set()

        tasks = []
        for keyword in SEARCH_KEYWORDS:
            # Search in Indre-et-Loire
            tasks.append(self._scrape_query(keyword, departement="37"))
            # Search remote jobs nationwide
            tasks.append(self._scrape_query(keyword, remote_only=True))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"France Travail scrape task failed: {result}")
                continue
            for job in result:
                key = (job.source, job.job_id)
                if key not in seen_ids:
                    seen_ids.add(key)
                    all_jobs.append(job)

        logger.info(f"France Travail: total unique jobs scraped: {len(all_jobs)}")
        return all_jobs
