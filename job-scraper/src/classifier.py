"""
Classifies scraped jobs into one of three geographic categories:
  - tours: Tours & Indre-et-Loire area (any work arrangement)
  - paris_hybrid: Paris / Île-de-France with hybrid remote policy (max 3 days onsite)
  - full_remote: Genuinely full-remote roles (3-check verification)

Jobs that don't match any category are discarded (return None).
"""
import asyncio
import re
from typing import List, Optional

from loguru import logger

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .database import update_job_category, get_all_jobs


# ---------------------------------------------------------------------------
# Tours keywords
# ---------------------------------------------------------------------------

TOURS_KEYWORDS = [
    "Tours",
    "Indre-et-Loire",
    "37",
    "Amboise",
    "Blois",
    "Chinon",
    "Loches",
    "Joué-lès-Tours",
    "Saint-Cyr-sur-Loire",
    "Chambray-lès-Tours",
    "La Riche",
    "Saint-Pierre-des-Corps",
    "Fondettes",
    "Ballan-Miré",
    "Montlouis-sur-Loire",
]

# ---------------------------------------------------------------------------
# Paris keywords
# ---------------------------------------------------------------------------

PARIS_KEYWORDS = [
    "Paris",
    "Île-de-France",
    "Ile-de-France",
    "75",
    "92",
    "93",
    "94",
    "Boulogne",
    "Levallois",
    "Neuilly",
    "Issy",
    "Courbevoie",
    "La Défense",
    "La Defense",
    "Massy",
    "Vélizy",
    "Velizy",
    "Saclay",
]

# ---------------------------------------------------------------------------
# Full-remote positive keywords (CHECK 1)
# ---------------------------------------------------------------------------

FULL_REMOTE_KEYWORDS = [
    "full remote",
    "100% remote",
    "fully remote",
    "télétravail complet",
    "100% télétravail",
    "entièrement en télétravail",
    "remote-first",
    "remote only",
    "work from anywhere",
    "anywhere in Europe",
    "anywhere in France",
    "no office required",
]

# ---------------------------------------------------------------------------
# Full-remote exclusion phrases (CHECK 2)
# ---------------------------------------------------------------------------

FULL_REMOTE_EXCLUSIONS_LITERAL = [
    "must be based in",
    "office presence required",
    "required to commute",
    "on-site required",
    "présentiel obligatoire",
]

_BASEE_OBLIGATOIRE_RE = re.compile(r"bas[ée]\(e\)\s+à.*obligatoire", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Onsite-days detector (for paris_hybrid)
# ---------------------------------------------------------------------------

_ONSITE_DAYS_RE = re.compile(r"(\d)\s*(?:jour|day)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Individual category checks
# ---------------------------------------------------------------------------


def _matches_tours(job: dict) -> bool:
    """Return True if the job is in the Tours / Indre-et-Loire area."""
    location = (job.get("location") or "").lower()
    description = (job.get("description") or "").lower()
    combined = location + " " + description
    for kw in TOURS_KEYWORDS:
        if kw.lower() in combined:
            return True
    return False


def _matches_paris_location(job: dict) -> bool:
    """Return True if the job location is in Paris / Île-de-France."""
    location = (job.get("location") or "").lower()
    for kw in PARIS_KEYWORDS:
        if kw.lower() in location:
            return True
    return False


def _is_hybrid(job: dict) -> bool:
    """
    Return True if the job is hybrid (not full-remote, not onsite-only).
    Accepts remote_policy == 'hybrid', or description/title containing
    'hybride'/'hybrid' without 'full remote' or '100%'.
    """
    policy = (job.get("remote_policy") or "").lower()
    description = (job.get("description") or "").lower()
    title = (job.get("title") or "").lower()
    combined = description + " " + title

    if policy == "hybrid":
        return True
    if policy in ("full", "onsite"):
        return False
    # Infer from text
    has_hybrid = "hybride" in combined or "hybrid" in combined
    has_full_remote = "full remote" in combined or "100%" in combined
    return has_hybrid and not has_full_remote


def _paris_onsite_days(job: dict) -> Optional[int]:
    """
    Try to detect the number of onsite days from the description.
    Returns the integer if found, or None if not mentioned.
    """
    description = (job.get("description") or "")
    match = _ONSITE_DAYS_RE.search(description)
    if match:
        return int(match.group(1))
    return None


def _check_full_remote_kw(job: dict) -> bool:
    """CHECK 1: description or title contains a full-remote keyword."""
    text = ((job.get("description") or "") + " " + (job.get("title") or "")).lower()
    for kw in FULL_REMOTE_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def _check_no_mandatory_location(job: dict) -> bool:
    """CHECK 2: description does NOT contain mandatory-location phrases."""
    description = (job.get("description") or "").lower()
    for phrase in FULL_REMOTE_EXCLUSIONS_LITERAL:
        if phrase.lower() in description:
            return False
    if _BASEE_OBLIGATOIRE_RE.search(description):
        return False
    return True


async def _check_claude_full_remote(job: dict, semaphore: asyncio.Semaphore) -> bool:
    """
    CHECK 3: Ask Claude API whether the job is genuinely full-remote.
    Falls back to True (pass) if ANTHROPIC_API_KEY is not set.
    """
    if not ANTHROPIC_API_KEY:
        return True

    title = job.get("title") or ""
    location = job.get("location") or ""
    description = (job.get("description") or "")[:500]

    prompt = (
        "Is this job genuinely full remote with no required office attendance? "
        "Answer only YES or NO.\n"
        f"Title: {title}\n"
        f"Location field: {location}\n"
        f"Description excerpt: {description}"
    )

    async with semaphore:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            message = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = (message.content[0].text if message.content else "").strip().upper()
            return "YES" in answer
        except Exception as exc:
            logger.warning("Claude full-remote check failed for job {}: {}", job.get("id"), exc)
            return False


# ---------------------------------------------------------------------------
# Main classify_job
# ---------------------------------------------------------------------------


async def classify_job(job: dict, semaphore: asyncio.Semaphore) -> Optional[dict]:
    """
    Classify a single job dict into a category.

    Returns a dict:
      {
        "category": "tours" | "paris_hybrid" | "full_remote" | None,
        "paris_days_specified": bool,          # only for paris_hybrid
        "remote_check1": bool,                 # only for full_remote
        "remote_check2": bool,                 # only for full_remote
        "remote_check3": bool,                 # only for full_remote
      }
    Returns None if the job should be discarded.
    """
    # --- Tours ---
    if _matches_tours(job):
        return {"category": "tours", "paris_days_specified": True}

    # --- Paris Hybrid ---
    if _matches_paris_location(job) and _is_hybrid(job):
        onsite_days = _paris_onsite_days(job)
        if onsite_days is not None and onsite_days > 3:
            # Too many onsite days → discard
            return None
        days_specified = onsite_days is not None
        return {"category": "paris_hybrid", "paris_days_specified": days_specified}

    # --- Full Remote ---
    check1 = _check_full_remote_kw(job)
    check2 = _check_no_mandatory_location(job)

    if check1 and check2:
        check3 = await _check_claude_full_remote(job, semaphore)
    else:
        check3 = False

    if check1 and check2 and check3:
        return {
            "category": "full_remote",
            "remote_check1": check1,
            "remote_check2": check2,
            "remote_check3": check3,
        }

    # Discard
    return None


# ---------------------------------------------------------------------------
# Batch classify
# ---------------------------------------------------------------------------


async def classify_jobs(jobs: List[dict], db_path: str) -> List[dict]:
    """
    Classify all jobs, persist the category to DB, and return the annotated list.
    Uses a semaphore to limit concurrent Claude API calls to 3.
    """
    semaphore = asyncio.Semaphore(3)

    async def _classify_and_save(job: dict) -> dict:
        result = await classify_job(job, semaphore)
        if result is None:
            job["category"] = None
            job["category_meta"] = {}
        else:
            category = result.get("category")
            meta = {k: v for k, v in result.items() if k != "category"}
            job["category"] = category
            job["category_meta"] = meta
            if category:
                await update_job_category(job["id"], category, meta, db_path)
        return job

    tasks = [_classify_and_save(job) for job in jobs]
    classified = await asyncio.gather(*tasks)
    counts = {"tours": 0, "paris_hybrid": 0, "full_remote": 0, None: 0}
    for j in classified:
        cat = j.get("category")
        counts[cat] = counts.get(cat, 0) + 1
    logger.info(
        "Classification done: tours={} paris_hybrid={} full_remote={} discarded={}",
        counts.get("tours", 0),
        counts.get("paris_hybrid", 0),
        counts.get("full_remote", 0),
        counts.get(None, 0),
    )
    return list(classified)
