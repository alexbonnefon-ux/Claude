"""Relevance scorer (1–5) for job postings."""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import (
    MIN_SALARY, TARGET_SALARY_MIN, TARGET_SALARY_MAX,
    TARGET_SECTOR_KEYWORDS, HYBRID_MAX_DAYS_ONSITE,
    REMOTE_SIGNALS, PARIS_SIGNALS, TOURS_SIGNALS, EMEA_SIGNALS,
    EXCLUDE_TITLE_KEYWORDS, EXCLUDE_DESCRIPTION_KEYWORDS,
    JOB_TITLES,
)

log = logging.getLogger(__name__)

# Salary regex – matches patterns like "75k", "75 000", "€75,000", "75K€"
_SALARY_RE = re.compile(
    r"(?:€\s*)?(\d[\d\s,\.]*)\s*[kK€]?\s*(?:€|euros?|EUR)?",
    re.IGNORECASE,
)


@dataclass
class Job:
    job_id:       str
    title:        str
    company:      str
    location:     str
    url:          str
    date_posted:  Optional[str] = None
    description:  str = ""
    salary_text:  str = ""
    salary_min:   Optional[int] = None
    salary_max:   Optional[int] = None
    remote_policy: str = "unknown"   # "remote", "hybrid", "onsite", "unknown"
    onsite_days:  Optional[int] = None
    sector:       str = ""
    source:       str = ""
    score:        int = 0
    raw:          dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id":       self.job_id,
            "title":        self.title,
            "company":      self.company,
            "location":     self.location,
            "url":          self.url,
            "date_posted":  self.date_posted,
            "salary_text":  self.salary_text,
            "salary_min":   self.salary_min,
            "salary_max":   self.salary_max,
            "remote_policy": self.remote_policy,
            "onsite_days":  self.onsite_days,
            "sector":       self.sector,
            "source":       self.source,
            "score":        self.score,
        }


# ---------------------------------------------------------------------------
# Salary extraction
# ---------------------------------------------------------------------------

def _parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    """Extract (min, max) salary in euros from free text. Returns (None, None) if not found."""
    if not text:
        return None, None

    text_lower = text.lower()
    numbers: list[int] = []

    for m in _SALARY_RE.finditer(text_lower):
        raw = m.group(1).replace(" ", "").replace(",", "").replace(".", "")
        try:
            val = int(raw)
        except ValueError:
            continue
        # If followed by 'k' treat as thousands
        after = text_lower[m.end():m.end() + 2].strip()
        if after.startswith("k") or "k" in m.group(0).lower():
            val *= 1000
        # Sanity: realistic HR salary range
        if 20_000 <= val <= 500_000:
            numbers.append(val)

    if not numbers:
        return None, None
    numbers.sort()
    return numbers[0], numbers[-1]


# ---------------------------------------------------------------------------
# Location / remote detection
# ---------------------------------------------------------------------------

def _detect_remote(location: str, description: str) -> tuple[str, Optional[int]]:
    """Return (remote_policy, onsite_days_per_week)."""
    combined = (location + " " + description).lower()

    # Full remote
    if any(sig in combined for sig in REMOTE_SIGNALS):
        # Check if it's remote-friendly but actually hybrid
        hybrid_override = re.search(
            r"(\d)\s*(?:day|jour)s?\s*(?:per week|par semaine|on[- ]?site|sur site)",
            combined,
        )
        if hybrid_override:
            days = int(hybrid_override.group(1))
            return "hybrid", days
        return "remote", 0

    # Onsite days mentioned explicitly
    hybrid_match = re.search(
        r"(\d)\s*(?:day|jour)s?\s*(?:per week|par semaine|on[- ]?site|sur site|au bureau)",
        combined,
    )
    if hybrid_match:
        days = int(hybrid_match.group(1))
        policy = "hybrid" if days < 5 else "onsite"
        return policy, days

    if "hybrid" in combined or "hybride" in combined:
        return "hybrid", None

    if any(sig in combined for sig in TOURS_SIGNALS):
        return "onsite", 5

    return "unknown", None


# ---------------------------------------------------------------------------
# Sector detection
# ---------------------------------------------------------------------------

def _detect_sector(company: str, description: str) -> str:
    combined = (company + " " + description).lower()
    for kw in TARGET_SECTOR_KEYWORDS:
        if kw in combined:
            # Map to canonical name
            if kw in ("ai", "artificial intelligence", "machine learning", "ml"):
                return "AI"
            if kw in ("saas", "software", "tech", "technology", "digital", "cloud", "data", "platform"):
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


# ---------------------------------------------------------------------------
# Title match
# ---------------------------------------------------------------------------

def _title_matches(title: str) -> bool:
    title_l = title.lower()
    return any(jt.lower() in title_l for jt in JOB_TITLES)


def _title_is_excluded(title: str) -> bool:
    title_l = title.lower()
    return any(kw in title_l for kw in EXCLUDE_TITLE_KEYWORDS)


def _description_is_excluded(description: str) -> bool:
    desc_l = description.lower()
    return any(kw in desc_l for kw in EXCLUDE_DESCRIPTION_KEYWORDS)


# ---------------------------------------------------------------------------
# Location acceptance
# ---------------------------------------------------------------------------

def _location_accepted(location: str, description: str,
                        remote_policy: str, onsite_days: Optional[int]) -> bool:
    combined = (location + " " + description).lower()

    if remote_policy == "remote":
        # Full remote from France – check France signal
        france_signals = ["france", "french", "fr", "paris", "lyon", "toulouse"]
        if any(s in combined for s in france_signals):
            return True
        # EMEA / no specific country restriction also OK
        if any(sig in combined for sig in EMEA_SIGNALS):
            return True
        # Generic "remote" without geo restriction – accept
        return True

    if remote_policy == "hybrid":
        days = onsite_days if onsite_days is not None else HYBRID_MAX_DAYS_ONSITE
        if days > HYBRID_MAX_DAYS_ONSITE:
            return False
        return any(sig in combined for sig in PARIS_SIGNALS + TOURS_SIGNALS)

    if remote_policy == "onsite":
        return any(sig in combined for sig in TOURS_SIGNALS)

    # Unknown – check location string loosely
    if any(sig in combined for sig in REMOTE_SIGNALS):
        return True
    if any(sig in combined for sig in PARIS_SIGNALS + TOURS_SIGNALS):
        return True
    if any(sig in combined for sig in EMEA_SIGNALS):
        return True
    return False


# ---------------------------------------------------------------------------
# Main filter + scorer
# ---------------------------------------------------------------------------

def enrich_and_score(job: Job) -> Optional[Job]:
    """
    Enrich a Job in-place (salary, remote, sector) and compute a relevance
    score 1–5.  Returns None if the job should be discarded.
    """
    # --- Title filter ---
    if not _title_matches(job.title):
        log.debug("SKIP (title mismatch): %s – %s", job.company, job.title)
        return None
    if _title_is_excluded(job.title):
        log.debug("SKIP (excluded title): %s – %s", job.company, job.title)
        return None
    if _description_is_excluded(job.description):
        log.debug("SKIP (excluded description): %s – %s", job.company, job.title)
        return None

    # --- Salary ---
    sal_min, sal_max = _parse_salary(job.salary_text or job.description)
    if sal_min is None and sal_max is None:
        # Try location/title text as a last resort
        sal_min, sal_max = _parse_salary(job.title)
    job.salary_min = sal_min
    job.salary_max = sal_max

    # Reject if salary is explicitly below minimum
    if sal_max is not None and sal_max < MIN_SALARY:
        log.debug("SKIP (salary too low %s): %s – %s", sal_max, job.company, job.title)
        return None

    # --- Remote / location ---
    remote_policy, onsite_days = _detect_remote(job.location, job.description)
    job.remote_policy = remote_policy
    job.onsite_days   = onsite_days

    if not _location_accepted(job.location, job.description, remote_policy, onsite_days):
        log.debug("SKIP (location): %s – %s @ %s", job.company, job.title, job.location)
        return None

    # --- Sector ---
    job.sector = _detect_sector(job.company, job.description)

    # --- Score (1–5) ---
    points = 0.0

    # Salary (0–2 pts)
    if sal_max and sal_max >= TARGET_SALARY_MAX:
        points += 2.0
    elif sal_min and sal_min >= TARGET_SALARY_MIN:
        points += 1.5
    elif sal_min and sal_min >= MIN_SALARY:
        points += 1.0
    else:
        points += 0.5   # no salary info – neutral penalty

    # Remote policy (0–1.5 pts)
    if remote_policy == "remote":
        points += 1.5
    elif remote_policy == "hybrid":
        days = onsite_days if onsite_days is not None else HYBRID_MAX_DAYS_ONSITE
        points += 1.5 - (days * 0.2)
    elif remote_policy == "onsite" and any(
        sig in job.location.lower() for sig in TOURS_SIGNALS
    ):
        points += 0.5   # Tours onsite – acceptable but lower pref

    # Sector (0–1 pt)
    high_value_sectors = {"AI", "Cybersecurity", "HealthTech", "Defense", "Aerospace"}
    if job.sector in high_value_sectors:
        points += 1.0
    elif job.sector:
        points += 0.7

    # Title seniority (0–0.5 pts)
    senior_signals = ["vp ", "chief", "head of", "drh", "vice president"]
    if any(s in job.title.lower() for s in senior_signals):
        points += 0.5
    elif any(s in job.title.lower() for s in ["lead", "manager", "business partner"]):
        points += 0.3

    # Clamp to 1–5
    job.score = max(1, min(5, round(points)))
    return job
