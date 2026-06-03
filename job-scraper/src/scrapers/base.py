"""Base scraper class and Job data model."""

import asyncio
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import USER_AGENTS, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, MAX_RETRIES


@dataclass
class Job:
    """Standardized job data model."""
    source: str
    job_id: str
    title: str
    company: str
    url: str
    location: Optional[str] = None
    remote_policy: Optional[str] = None  # "remote", "hybrid", "onsite"
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_estimated: bool = False
    posted_date: Optional[datetime] = None
    description: Optional[str] = None
    score: Optional[float] = None
    score_details: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None


def parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parse salary range from a string.
    Returns (min, max) as integers (annual EUR).
    """
    if not text:
        return None, None

    text = text.replace(" ", "").replace(" ", "").replace(",", "")

    # Detect monthly (k€/mois or /mois) and convert
    is_monthly = bool(re.search(r"mois|month", text, re.IGNORECASE))

    # Extract numbers
    numbers = re.findall(r"(\d{2,6})", text)
    if not numbers:
        return None, None

    values = [int(n) for n in numbers]

    # Handle k€ (thousands)
    if re.search(r"k€|k\s*€|K€", text, re.IGNORECASE):
        values = [v * 1000 for v in values]

    if is_monthly:
        values = [v * 12 for v in values]

    # Sanity check: plausible annual salaries between 15k and 500k
    values = [v for v in values if 15000 <= v <= 500000]
    if not values:
        return None, None

    salary_min = min(values)
    salary_max = max(values)
    if salary_min == salary_max:
        salary_max = None

    return salary_min, salary_max


def detect_remote_policy(text: str) -> Optional[str]:
    """Detect remote work policy from job text."""
    if not text:
        return None
    text_lower = text.lower()

    full_remote_patterns = [
        "full remote", "full-remote", "100% remote", "100% télétravail",
        "télétravail complet", "remote first", "remote-first",
        "entièrement en télétravail", "fully remote",
    ]
    hybrid_patterns = [
        "hybride", "hybrid", "télétravail partiel", "jours de télétravail",
        "jours par semaine en télétravail", "remote partiel",
    ]

    for pattern in full_remote_patterns:
        if pattern in text_lower:
            return "remote"

    for pattern in hybrid_patterns:
        if pattern in text_lower:
            return "hybrid"

    return "onsite"


class BaseScraper(ABC):
    """Abstract base class for all job scrapers."""

    SOURCE_NAME: str = "unknown"

    def __init__(self) -> None:
        self._user_agent = random.choice(USER_AGENTS)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_headers(self) -> Dict[str, str]:
        """Return HTTP headers with a rotated user agent."""
        return {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Return (or create) a shared async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self._get_headers(),
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _sleep_between_requests(self) -> None:
        """Wait a random delay between requests to be polite."""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        await asyncio.sleep(delay)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch(self, url: str, **kwargs) -> httpx.Response:
        """Fetch a URL with retries and exponential backoff."""
        client = await self._get_client()
        # Rotate user agent occasionally
        if random.random() < 0.3:
            self._user_agent = random.choice(USER_AGENTS)
            client.headers.update({"User-Agent": self._user_agent})
        await self._sleep_between_requests()
        response = await client.get(url, **kwargs)
        response.raise_for_status()
        return response

    @abstractmethod
    async def scrape(self) -> List[Job]:
        """Scrape jobs and return a list of Job objects."""
        ...

    def normalize_job(
        self,
        *,
        job_id: str,
        title: str,
        company: str,
        url: str,
        location: Optional[str] = None,
        salary_text: Optional[str] = None,
        description: Optional[str] = None,
        posted_date: Optional[datetime] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """Build a standardized Job from raw fields."""
        salary_min, salary_max = parse_salary(salary_text or "")

        combined_text = " ".join(filter(None, [title, location, description or ""]))
        remote_policy = detect_remote_policy(combined_text)

        return Job(
            source=self.SOURCE_NAME,
            job_id=job_id,
            title=title.strip(),
            company=company.strip(),
            url=url.strip(),
            location=location,
            remote_policy=remote_policy,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_estimated=False,
            posted_date=posted_date,
            description=description,
            raw_data=raw_data,
        )

    async def handle_rate_limit(self, retry_after: int = 60) -> None:
        """Handle a 429 response by waiting the specified number of seconds."""
        logger.warning(f"{self.SOURCE_NAME}: rate limited, waiting {retry_after}s")
        await asyncio.sleep(retry_after)
