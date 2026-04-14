"""Relevance scorer (1–5) for job postings.

All thresholds and filter lists are read live from settings_db so that
changes made in the Settings UI take effect immediately on the next run.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import (
    REMOTE_SIGNALS, PARIS_SIGNALS, TOURS_SIGNALS, EMEA_SIGNALS,
    TARGET_SECTOR_KEYWORDS,
)
import settings_db

log = logging.getLogger(__name__)

_SALARY_RE = re.compile(
    r"(?:€\s*)?(\d[\d\s,\.]{1,8})\s*[kK]?(?:\s*(?:€|euros?|EUR))?",
    re.IGNORECASE,
)


@dataclass
class Job:
    job_id:        str
    title:         str
    company:       str
    location:      str
    url:           str
    date_posted:   Optional[str] = None
    description:   str = ""
    salary_text:   str = ""
    salary_min:    Optional[int] = None
    salary_max:    Optional[int] = None
    remote_policy: str = "unknown"
    onsite_days:   Optional[int] = None
    sector:        str = ""
    source:        str = ""
    score:         int = 0
    raw:           dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id, "title": self.title, "company": self.company,
            "location": self.location, "url": self.url,
            "date_posted": self.date_posted, "salary_text": self.salary_text,
            "salary_min": self.salary_min, "salary_max": self.salary_max,
            "remote_policy": self.remote_policy, "onsite_days": self.onsite_days,
            "sector": self.sector, "source": self.source, "score": self.score,
        }


# ---------------------------------------------------------------------------
# Salary parsing
# ---------------------------------------------------------------------------

def _parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    text_l = text.lower()
    numbers: list[int] = []
    for m in _SALARY_RE.finditer(text_l):
        raw = m.group(1).replace(" ", "").replace(",", "").replace(".", "")
        try:
            val = int(raw)
        except ValueError:
            continue
        # Check if followed by 'k'
        after = text_l[m.end():m.end() + 2].strip()
        if after.startswith("k") or "k" in m.group(0).lower():
            val *= 1000
        if 20_000 <= val <= 500_000:
            numbers.append(val)
    if not numbers:
        return None, None
    numbers.sort()
    return numbers[0], numbers[-1]


# ---------------------------------------------------------------------------
# Remote / location detection
# ---------------------------------------------------------------------------

def _detect_remote(location: str, description: str) -> tuple[str, Optional[int]]:
    combined = (location + " " + description).lower()
    if any(sig in combined for sig in REMOTE_SIGNALS):
        m = re.search(
            r"(\d)\s*(?:day|jour)s?\s*(?:per week|par semaine|on[- ]?site|sur site)",
            combined,
        )
        if m:
            return "hybrid", int(m.group(1))
        return "remote", 0
    m = re.search(
        r"(\d)\s*(?:day|jour)s?\s*(?:per week|par semaine|on[- ]?site|sur site|au bureau)",
        combined,
    )
    if m:
        days = int(m.group(1))
        return ("hybrid" if days < 5 else "onsite"), days
    if "hybrid" in combined or "hybride" in combined:
        return "hybrid", None
    if any(sig in combined for sig in TOURS_SIGNALS):
        return "onsite", 5
    return "unknown", None


def _detect_sector(company: str, description: str) -> str:
    combined = (company + " " + description).lower()
    for kw in TARGET_SECTOR_KEYWORDS:
        if kw in combined:
            if kw in ("ai", "artificial intelligence", "machine learning", "ml"):
                return "AI"
            if kw in ("saas", "software", "tech", "technology", "digital",
                      "cloud", "data", "platform"):
                return "Tech/SaaS"
            if kw in ("healthtech", "health tech", "medtech", "digital health"):
                return "HealthTech"
            if kw in ("cybersecurity", "cyber security", "infosec", "security"):
                return "Cybersecurity"
            if kw in ("aerospace", "space"):
                return "Aerospace"
            if kw in ("defense", "defence"):
                return "Defense"
            if kw == "fintech":
                return "Fintech"
            return "Tech"
    return ""


def _location_accepted(location: str, description: str,
                        remote_policy: str, onsite_days: Optional[int]) -> bool:
    combined = (location + " " + description).lower()
    max_days = settings_db.max_onsite_days()

    if remote_policy == "remote":
        return True   # full remote – accept regardless of geo
    if remote_policy == "hybrid":
        days = onsite_days if onsite_days is not None else max_days
        if days > max_days:
            return False
        return any(sig in combined for sig in PARIS_SIGNALS + TOURS_SIGNALS)
    if remote_policy == "onsite":
        return any(sig in combined for sig in TOURS_SIGNALS)
    # unknown – accept if any known location signal present
    return any(sig in combined for sig in
               REMOTE_SIGNALS + PARIS_SIGNALS + TOURS_SIGNALS + EMEA_SIGNALS)


# ---------------------------------------------------------------------------
# Main filter + scorer
# ---------------------------------------------------------------------------

def enrich_and_score(job: Job) -> Optional[Job]:
    """Enrich and score a Job in-place. Returns None to discard."""
    titles       = settings_db.job_titles()
    excl_titles  = settings_db.excluded_title_keywords()
    excl_desc    = settings_db.excluded_description_keywords()
    min_sal      = settings_db.min_salary()
    tgt_min      = settings_db.target_salary_min()
    tgt_max      = settings_db.target_salary_max()

    # --- Title match ---
    title_l = job.title.lower()
    if not any(t.lower() in title_l for t in titles):
        log.debug("SKIP title: %s – %s", job.company, job.title)
        return None
    if any(k in title_l for k in excl_titles):
        log.debug("SKIP excl title: %s – %s", job.company, job.title)
        return None
    desc_l = job.description.lower()
    if any(k in desc_l for k in excl_desc):
        log.debug("SKIP excl desc: %s – %s", job.company, job.title)
        return None

    # --- Salary ---
    sal_min, sal_max = _parse_salary(job.salary_text or job.description)
    job.salary_min, job.salary_max = sal_min, sal_max
    if sal_max is not None and sal_max < min_sal:
        log.debug("SKIP salary %s: %s – %s", sal_max, job.company, job.title)
        return None

    # --- Remote / location ---
    remote_policy, onsite_days = _detect_remote(job.location, job.description)
    job.remote_policy = remote_policy
    job.onsite_days   = onsite_days
    if not _location_accepted(job.location, job.description, remote_policy, onsite_days):
        log.debug("SKIP location: %s – %s @ %s", job.company, job.title, job.location)
        return None

    # --- Sector ---
    job.sector = _detect_sector(job.company, job.description)

    # --- Score 1–5 ---
    pts = 0.0

    # Salary (0–2 pts)
    if sal_max and sal_max >= tgt_max:
        pts += 2.0
    elif sal_min and sal_min >= tgt_min:
        pts += 1.5
    elif sal_min and sal_min >= min_sal:
        pts += 1.0
    else:
        pts += 0.5  # no salary info

    # Remote (0–1.5 pts)
    if remote_policy == "remote":
        pts += 1.5
    elif remote_policy == "hybrid":
        days = onsite_days if onsite_days is not None else settings_db.max_onsite_days()
        pts += max(0, 1.5 - days * 0.2)
    elif remote_policy == "onsite" and any(s in job.location.lower() for s in TOURS_SIGNALS):
        pts += 0.5

    # Sector (0–1 pt)
    if job.sector in {"AI", "Cybersecurity", "HealthTech", "Defense", "Aerospace"}:
        pts += 1.0
    elif job.sector:
        pts += 0.7

    # Seniority (0–0.5 pts)
    senior = ["vp ", "chief", "head of", "drh", "vice president"]
    mid    = ["lead", "manager", "business partner"]
    if any(s in title_l for s in senior):
        pts += 0.5
    elif any(s in title_l for s in mid):
        pts += 0.3

    job.score = max(1, min(5, round(pts)))
    return job
