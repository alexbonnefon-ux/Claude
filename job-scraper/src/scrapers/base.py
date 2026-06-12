"""
Abstract base class for all job scrapers.
"""
import asyncio
import random
import re
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from loguru import logger

from ..config import USER_AGENTS, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, MAX_RETRIES, BACKOFF_FACTOR
from ..database import Job


# Patterns that indicate non-title content appended to the title string
_TITLE_NOISE_PATTERNS = [
    re.compile(
        r'\s*[-–—]\s*(?:Full[- ]time|Part[- ]time|Contract|Freelance|Interim|CDI|CDD|Stage|Alternance)\s*.*$',
        re.IGNORECASE,
    ),
    re.compile(
        r'\s*(?:Hybrid|Remote|On[- ]site|Onsite|Présentiel|Télétravail)\s*[-–—].*$',
        re.IGNORECASE,
    ),
    re.compile(
        r'\s+(?:Hybrid|Remote|On[- ]site|Onsite)\s*$',
        re.IGNORECASE,
    ),
    re.compile(r'\s+[A-Z][a-z]+,\s+[A-Z]{2,}$'),       # "City, STATE" at end
    re.compile(r'\s+[A-Z][a-z]+,\s+[A-Z][a-z]+$'),     # "City, Country" at end
]


def clean_title(title: str) -> str:
    """Strip appended location / contract-type noise from a job title."""
    for pattern in _TITLE_NOISE_PATTERNS:
        title = pattern.sub('', title).strip()
    return title


class BaseScraper(ABC):
    """Abstract base scraper providing rate limiting, retries and normalization."""

    name: str = "base"

    def __init__(self) -> None:
        self._user_agents = USER_AGENTS.copy()
        self._request_count = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def scrape(self) -> List[Job]:
        """
        Perform the scraping and return a list of Job objects.
        Must be implemented by every concrete scraper.
        """
        ...

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_user_agent(self) -> str:
        """Return a random user agent string from the pool."""
        return random.choice(self._user_agents)

    async def handle_rate_limit(self, attempt: int = 0) -> None:
        """
        Sleep with exponential backoff between requests.
        attempt=0 → normal inter-request delay
        attempt>0 → exponential backoff after a failure
        """
        if attempt == 0:
            delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        else:
            delay = min(REQUEST_DELAY_MIN * (BACKOFF_FACTOR ** attempt) + random.uniform(0, 1), 60)
        logger.debug("{} rate limit delay: {:.1f}s (attempt={})", self.name, delay, attempt)
        await asyncio.sleep(delay)

    async def retry(self, coro_func, *args, **kwargs):
        """
        Call an async function up to MAX_RETRIES times with exponential backoff.
        Returns the result or raises the last exception.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                if attempt > 0:
                    await self.handle_rate_limit(attempt)
                return await coro_func(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "{} attempt {}/{} failed: {}",
                    self.name, attempt + 1, MAX_RETRIES, exc
                )
        raise last_exc

    @staticmethod
    def make_job_id(url: str, title: str = "", company: str = "") -> str:
        """
        Generate a stable, unique job ID from the URL (and optionally title/company).
        Falls back to a hash when no structured ID is available.
        """
        raw = (url + title + company).strip().lower()
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def normalize_job(
        self,
        *,
        title: str,
        company: str,
        location: str,
        url: str,
        job_id: Optional[str] = None,
        description: str = "",
        remote_policy: str = "unknown",
        salary_min: Optional[int] = None,
        salary_max: Optional[int] = None,
        salary_estimated: bool = False,
        posted_date: Optional[datetime] = None,
        raw_data: Optional[dict] = None,
    ) -> Job:
        """
        Return a standardized Job dataclass from raw scraper data.
        Infers remote_policy from location/description text if not explicitly set.
        """
        if remote_policy == "unknown":
            remote_policy = self._infer_remote_policy(location, description)

        return Job(
            source=self.name,
            job_id=job_id or self.make_job_id(url, title, company),
            title=clean_title(title.strip()),
            company=company.strip(),
            location=location.strip(),
            url=url.strip(),
            description=description,
            remote_policy=remote_policy,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_estimated=salary_estimated,
            posted_date=posted_date,
            raw_data=raw_data or {},
        )

    @staticmethod
    def _infer_remote_policy(location: str, description: str) -> str:
        """Guess the remote policy from free-text location and description."""
        combined = (location + " " + description).lower()
        full_remote_signals = [
            "full remote", "fully remote", "100% remote",
            "100% télétravail", "entièrement à distance",
            "remote only", "distributed",
        ]
        hybrid_signals = [
            "hybrid", "hybride", "télétravail partiel",
            "partial remote", "remote partiel", "flex",
        ]
        onsite_signals = [
            "sur site", "on-site", "onsite", "présentiel",
            "no remote", "sans télétravail",
        ]
        for sig in full_remote_signals:
            if sig in combined:
                return "full"
        for sig in hybrid_signals:
            if sig in combined:
                return "hybrid"
        for sig in onsite_signals:
            if sig in combined:
                return "onsite"
        if "remote" in combined or "télétravail" in combined:
            return "hybrid"
        return "unknown"

    @staticmethod
    def parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
        """
        Extract salary min/max from a free-text string.
        Handles formats like "50K€", "50 000 €", "45 000 - 60 000 €", etc.
        Returns (min, max) in euros per year, or (None, None) if not found.
        """
        import re
        if not text:
            return None, None

        text_clean = text.lower().replace(" ", "").replace("\xa0", "").replace(",", ".")
        # Match patterns like "50k", "50 000", "50000"
        pattern = r"(\d[\d\s\.]*)\s*k?€?"
        numbers = []
        for match in re.finditer(r"(\d[\d\s]{0,5})\s*k", text_clean):
            val = float(match.group(1).replace(" ", "").replace(".", ""))
            numbers.append(int(val * 1000))
        if not numbers:
            for match in re.finditer(r"(\d{2,6})\s*(?:€|eur|euros?)", text_clean):
                val = int(match.group(1).replace(" ", ""))
                if val >= 1000:
                    numbers.append(val)

        if len(numbers) == 0:
            return None, None
        elif len(numbers) == 1:
            v = numbers[0]
            return v, None
        else:
            return min(numbers[:2]), max(numbers[:2])
