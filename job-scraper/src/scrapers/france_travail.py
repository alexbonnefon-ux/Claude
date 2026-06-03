"""
France Travail (formerly Pôle Emploi) API scraper.
Uses the official offres-emploi v2 API with OAuth2 client_credentials.
"""
import asyncio
from datetime import datetime
from typing import List, Optional
import httpx
from loguru import logger

from ..config import (
    FRANCE_TRAVAIL_CLIENT_ID,
    FRANCE_TRAVAIL_CLIENT_SECRET,
    FRANCE_TRAVAIL_TOKEN_URL,
    FRANCE_TRAVAIL_API_BASE,
    FRANCE_TRAVAIL_KEYWORDS,
    FRANCE_TRAVAIL_DEPT_CODES,
)
from ..database import Job
from .base import BaseScraper


class FranceTravailScraper(BaseScraper):
    """Scrape job offers from the France Travail (francetravail.io) API."""

    name = "france_travail"
    _TOKEN_SCOPE = "api_offresdemploiv2 o2dsoffre"

    def __init__(self) -> None:
        super().__init__()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        """Obtain or refresh the OAuth2 bearer token."""
        import time
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        resp = await client.post(
            FRANCE_TRAVAIL_TOKEN_URL,
            params={"realm": "/partenaire"},
            data={
                "grant_type": "client_credentials",
                "client_id": FRANCE_TRAVAIL_CLIENT_ID,
                "client_secret": FRANCE_TRAVAIL_CLIENT_SECRET,
                "scope": self._TOKEN_SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 1499))
        logger.debug("France Travail token obtained, expires in {}s", payload.get("expires_in"))
        return self._access_token

    # ------------------------------------------------------------------
    # Core scraping
    # ------------------------------------------------------------------

    async def scrape(self) -> List[Job]:
        if not FRANCE_TRAVAIL_CLIENT_ID or not FRANCE_TRAVAIL_CLIENT_SECRET:
            logger.warning("France Travail credentials not set – skipping scraper")
            return []

        jobs: List[Job] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for keyword in FRANCE_TRAVAIL_KEYWORDS:
                for dept in FRANCE_TRAVAIL_DEPT_CODES:
                    try:
                        batch = await self.retry(
                            self._search_offers, client, keyword, dept
                        )
                        jobs.extend(batch)
                        await self.handle_rate_limit()
                    except Exception as exc:
                        logger.error(
                            "France Travail search failed for '{}' dept {}: {}",
                            keyword, dept, exc
                        )

            # Also search for télétravail without département filter
            for keyword in FRANCE_TRAVAIL_KEYWORDS[:4]:
                try:
                    batch = await self.retry(
                        self._search_offers, client, keyword, None, remote_only=True
                    )
                    jobs.extend(batch)
                    await self.handle_rate_limit()
                except Exception as exc:
                    logger.error("France Travail remote search failed for '{}': {}", keyword, exc)

        # Deduplicate by job_id within this scraper
        seen: set[str] = set()
        unique: List[Job] = []
        for job in jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                unique.append(job)

        logger.info("France Travail: found {} unique jobs", len(unique))
        return unique

    async def _search_offers(
        self,
        client: httpx.AsyncClient,
        keyword: str,
        departement: Optional[str],
        remote_only: bool = False,
        start: int = 0,
    ) -> List[Job]:
        """
        Fetch one page of offers and recursively paginate.
        France Travail returns max 150 results per page (range 0-149).
        """
        token = await self._get_token(client)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        params: dict = {
            "motsCles": keyword,
            "range": f"{start}-{start + 49}",
            "sort": "1",  # most recent first
        }
        if departement:
            params["departement"] = departement
        if remote_only:
            params["modesTravailLibelle"] = "Télétravail total"

        resp = await client.get(
            f"{FRANCE_TRAVAIL_API_BASE}/offres/search",
            headers=headers,
            params=params,
        )

        # 204 = no results
        if resp.status_code == 204:
            return []
        resp.raise_for_status()

        data = resp.json()
        offers = data.get("resultats", [])
        jobs = [self._parse_offer(o) for o in offers]

        # Check if there are more pages
        content_range = resp.headers.get("Content-Range", "")
        total = self._parse_total(content_range)
        next_start = start + len(offers)
        if total and next_start < min(total, 150) and len(offers) == 50:
            await self.handle_rate_limit()
            more = await self._search_offers(client, keyword, departement, remote_only, next_start)
            jobs.extend(more)

        return jobs

    @staticmethod
    def _parse_total(content_range: str) -> Optional[int]:
        """Parse the total count from 'Content-Range: offres 0-49/312'."""
        if "/" in content_range:
            try:
                return int(content_range.split("/")[1])
            except (ValueError, IndexError):
                pass
        return None

    def _parse_offer(self, offer: dict) -> Job:
        """Convert a raw France Travail API offer dict to a Job."""
        location_raw = offer.get("lieuTravail", {})
        location = location_raw.get("libelle", "")
        if location_raw.get("codePostal"):
            location = f"{location} ({location_raw['codePostal']})"

        salary_info = offer.get("salaire", {})
        salary_text = salary_info.get("libelle", "")
        salary_min, salary_max = self.parse_salary(salary_text)

        # Detect remote
        remote_raw = offer.get("experienceLibelle", "")
        mode_travail = offer.get("modeTravailLibelle", "").lower()
        if "télétravail total" in mode_travail:
            remote_policy = "full"
        elif "télétravail partiel" in mode_travail:
            remote_policy = "hybrid"
        else:
            remote_policy = "unknown"

        posted_str = offer.get("dateCreation", "")
        posted_date = None
        if posted_str:
            try:
                posted_date = datetime.fromisoformat(posted_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        description = offer.get("description", "")
        if remote_policy == "unknown":
            remote_policy = self._infer_remote_policy(location, description)

        return self.normalize_job(
            title=offer.get("intitule", ""),
            company=offer.get("entreprise", {}).get("nom", "Entreprise confidentielle"),
            location=location,
            url=offer.get("origineOffre", {}).get("urlOrigine", f"https://francetravail.fr/offres/recherche/detail/{offer.get('id', '')}"),
            job_id=offer.get("id", ""),
            description=description,
            remote_policy=remote_policy,
            salary_min=salary_min,
            salary_max=salary_max,
            posted_date=posted_date,
            raw_data=offer,
        )
