"""
Job scorer using Claude API (claude-sonnet-4-6).
Scores each job 0-10 based on fit for Alexis Bonnefon's profile.
"""
import json
import asyncio
from typing import List, Optional
from loguru import logger
import anthropic

from .config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    TOURS_AREA_KEYWORDS, REMOTE_KEYWORDS, PARIS_HYBRID_KEYWORDS,
    MIN_SALARY_REMOTE, MIN_SALARY_TOURS, MIN_SALARY_PARIS_HYBRID,
)
from .database import Job, update_job_score

# Candidate profile for scoring context
CANDIDATE_PROFILE = """
Alexis Bonnefon – Senior HR Professional
- Location: Tours, France (Indre-et-Loire, 37)
- Experience: 10+ years in HR, senior-level positions
- Target roles: HRBP, Responsable RH, DRH, Head of People, People Manager, HR Manager
- Preferred locations:
  1. Tours / Indre-et-Loire area (on-site or hybrid)
  2. Full remote (Europe) – especially for tech/startup roles
  3. Paris hybrid (2–3 days remote) – acceptable for the right role/salary
- Salary requirements:
  * Remote roles: minimum €60,000/year
  * Tours/local roles: minimum €50,000/year
  * Paris hybrid: minimum €55,000/year
- Preferred sectors: Tech startups, scale-ups, AI, FinTech, HealthTech (but open to all)
- Also open to: public sector in Tours area, large corps if role is strategic
- Languages: French (native), English (professional)
"""

SCORING_PROMPT = """You are an expert recruiter evaluating job fit. Score the following job for the candidate profile.

## Candidate Profile
{profile}

## Job Details
Title: {title}
Company: {company}
Location: {location}
Remote Policy: {remote_policy}
Salary: {salary}
Description excerpt: {description}
URL: {url}

## Scoring Criteria (total 0–10)

1. **Role Match (0–3)**
   - 3: Exact match (HRBP, Responsable RH, DRH, Head of People, HR Manager, People Manager)
   - 2: Related senior HR role (HR Director, Talent Director, People Ops lead, HR Generalist senior)
   - 1: Tangential (recruiter manager, L&D director, CHRO if not strategic)
   - 0: Not an HR role

2. **Location Match (0–2)**
   - 2: Tours/Indre-et-Loire area (local), OR full remote (European)
   - 1: Paris hybrid (explicitly 2–3 days remote), OR hybrid near Tours
   - 0: Full on-site Paris or other city with no remote option

3. **Salary Match (0–2)**
   - 2: Stated salary meets or exceeds the candidate's threshold for that location type
   - 1: Salary not stated (benefit of doubt) OR slightly below threshold
   - 0: Clearly below minimum (e.g., <45K for Tours role, <55K for remote)

4. **Company Match (0–2)**
   - 2: Tech startup/scale-up (ideally AI, FinTech, HR Tech, HealthTech, GreenTech, Defense Tech)
   - 1: Mid-size tech company, large corporation with modern HR, or strategic public sector
   - 0: Traditional SME, retail, or low-relevance sector

5. **Freshness (0–1)**
   - 1: Posted today or yesterday
   - 0.5: Posted 2–3 days ago
   - 0: Posted more than 3 days ago or date unknown

## Output Format
Respond with ONLY valid JSON in this exact format:
{{
  "score": <number 0-10, one decimal place>,
  "role_match": <0-3>,
  "location_match": <0-2>,
  "salary_match": <0-2>,
  "company_match": <0-2>,
  "freshness": <0 or 0.5 or 1>,
  "explanation": "<2-3 sentences explaining the score in French>",
  "red_flags": "<any concerns, or empty string>"
}}
"""


class JobScorer:
    """Score jobs using Claude API with batching and caching."""

    def __init__(self) -> None:
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._async_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    async def score_jobs(self, jobs: List[dict], db_path: str = "jobs.db") -> List[dict]:
        """
        Score a list of job dicts (from DB rows) and update scores in the database.
        Returns the jobs with scores populated.
        """
        if not jobs:
            return []

        logger.info("Scoring {} jobs with Claude {}", len(jobs), CLAUDE_MODEL)

        # Process concurrently but with a semaphore to avoid rate limits
        semaphore = asyncio.Semaphore(5)
        scored: List[dict] = []

        async def score_one(job: dict) -> dict:
            async with semaphore:
                try:
                    result = await self._score_single_job(job)
                    job["score"] = result["score"]
                    job["score_details"] = json.dumps(result)
                    await update_job_score(job["id"], result["score"], result, db_path)
                    scored.append(job)
                    return job
                except Exception as exc:
                    logger.error("Failed to score job {} ({}): {}", job.get("id"), job.get("title"), exc)
                    return job

        await asyncio.gather(*[score_one(j) for j in jobs])
        logger.info("Scoring complete: {}/{} jobs scored", len([j for j in jobs if j.get("score") is not None]), len(jobs))
        return jobs

    async def _score_single_job(self, job: dict) -> dict:
        """Call Claude API to score a single job."""
        salary_str = self._format_salary(job)
        description = (job.get("description") or "")[:800]

        prompt = SCORING_PROMPT.format(
            profile=CANDIDATE_PROFILE,
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            remote_policy=job.get("remote_policy", "unknown"),
            salary=salary_str,
            description=description,
            url=job.get("url", ""),
        )

        response = await self._async_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
            system="You are a precise job matching assistant. Always respond with valid JSON only.",
        )

        content = response.content[0].text.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        result = json.loads(content)

        # Validate and clamp score
        score = float(result.get("score", 0))
        score = max(0.0, min(10.0, score))
        result["score"] = round(score, 1)

        return result

    @staticmethod
    def _format_salary(job: dict) -> str:
        """Format salary info for the prompt."""
        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")
        estimated = job.get("salary_estimated", False)

        if salary_min and salary_max:
            s = f"€{salary_min:,} – €{salary_max:,}/an"
        elif salary_min:
            s = f"À partir de €{salary_min:,}/an"
        elif salary_max:
            s = f"Jusqu'à €{salary_max:,}/an"
        else:
            return "Non communiqué"

        if estimated:
            s += " (estimé)"
        return s

    def score_jobs_sync(self, jobs: List[dict], db_path: str = "jobs.db") -> List[dict]:
        """Synchronous wrapper for use in non-async contexts."""
        return asyncio.run(self.score_jobs(jobs, db_path))
