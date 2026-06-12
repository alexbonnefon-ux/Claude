"""Abstract base class for all job scrapers."""
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


_TITLE_NOISE_PATTERNS = [
    re.compile(r'\s*[-–—]\s*(?:Full[- ]time|Part[- ]time|Contract|Freelance|Interim|CDI|CDD|Stage|Alternance)\s*.*$', re.IGNORECASE),
    re.compile(r'\s*(?:Hybrid|Remote|On[- ]site|Onsite|Présentiel|Télétravail)\s*[-–—].*$', re.IGNORECASE),
    re.compile(r'\s+(?:Hybrid|Remote|On[- ]site|Onsite)\s*$', re.IGNORECASE),
    re.compile(r'\s+[A-Z][a-z]+,\s+[A-Z]{2,}$'),
    re.compile(r'\s+[A-Z][a-z]+,\s+[A-Z][a-z]+$'),
]


def clean_title(title: str) -> str:
    for pattern in _TITLE_NOISE_PATTERNS:
        title = pattern.sub('', title).strip()
    return title


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self) -> None:
        self._user_agents = USER_AGENTS.copy()
        self._request_count = 0

    @abstractmethod
    async def scrape(self) -> List[Job]: ...

    def get_user_agent(self) -> str:
        return random.choice(self._user_agents)

    async def handle_rate_limit(self, attempt: int = 0) -> None:
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX) if attempt == 0 else min(REQUEST_DELAY_MIN * (BACKOFF_FACTOR ** attempt) + random.uniform(0, 1), 60)
        logger.debug("{} rate limit delay: {:.1f}s (attempt={})", self.name, delay, attempt)
        await asyncio.sleep(delay)

    async def retry(self, coro_func, *args, **kwargs):
        last_exc: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                if attempt > 0:
                    await self.handle_rate_limit(attempt)
                return await coro_func(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                logger.warning("{} attempt {}/{} failed: {}", self.name, attempt + 1, MAX_RETRIES, exc)
        raise last_exc

    @staticmethod
    def make_job_id(url: str, title: str = "", company: str = "") -> str:
        return hashlib.sha256((url + title + company).strip().lower().encode()).hexdigest()[:16]

    def normalize_job(self, *, title: str, company: str, location: str, url: str,
                      job_id: Optional[str] = None, description: str = "",
                      remote_policy: str = "unknown", salary_min: Optional[int] = None,
                      salary_max: Optional[int] = None, salary_estimated: bool = False,
                      posted_date: Optional[datetime] = None, raw_data: Optional[dict] = None) -> Job:
        if remote_policy == "unknown":
            remote_policy = self._infer_remote_policy(location, description)
        return Job(
            source=self.name,
            job_id=job_id or self.make_job_id(url, title, company),
            title=clean_title(title.strip()),
            company=company.strip(), location=location.strip(), url=url.strip(),
            description=description, remote_policy=remote_policy,
            salary_min=salary_min, salary_max=salary_max,
            salary_estimated=salary_estimated, posted_date=posted_date,
            raw_data=raw_data or {},
        )

    @staticmethod
    def _infer_remote_policy(location: str, description: str) -> str:
        combined = (location + " " + description).lower()
        for sig in ["full remote", "fully remote", "100% remote", "100% télétravail", "remote only", "distributed"]:
            if sig in combined: return "full"
        for sig in ["hybrid", "hybride", "télétravail partiel", "partial remote", "flex"]:
            if sig in combined: return "hybrid"
        for sig in ["sur site", "on-site", "onsite", "présentiel", "no remote"]:
            if sig in combined: return "onsite"
        if "remote" in combined or "télétravail" in combined:
            return "hybrid"
        return "unknown"

    @staticmethod
    def parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
        if not text:
            return None, None
        text_clean = text.lower().replace(" ", "").replace("\xa0", "").replace(",", ".")
        numbers = []
        for match in re.finditer(r"(\d[\d\s]{0,5})\s*k", text_clean):
            numbers.append(int(float(match.group(1).replace(" ", "").replace(".", "")) * 1000))
        if not numbers:
            for match in re.finditer(r"(\d{2,6})\s*(?:€|eur|euros?)", text_clean):
                val = int(match.group(1).replace(" ", ""))
                if val >= 1000:
                    numbers.append(val)
        if not numbers: return None, None
        if len(numbers) == 1: return numbers[0], None
        return min(numbers[:2]), max(numbers[:2])
