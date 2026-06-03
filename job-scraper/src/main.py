"""
Main orchestrator for the job scraper pipeline.

Can be called:
  - From the web app: await run_pipeline()
  - As a standalone CLI: python -m src.main
  - With web server: python -m src.main --web
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import List
from loguru import logger

from .config import JOB_MAX_AGE_HOURS, DB_PATH, ANTHROPIC_API_KEY
from .database import Job, init_db, save_job, get_unscored_jobs, get_stats
from .scorer import JobScorer


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    logger.add(
        "scraper.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} - {message}",
        level="DEBUG",
        rotation="7 days",
        retention="30 days",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_recent(job: Job) -> bool:
    """Return True if the job was posted within JOB_MAX_AGE_HOURS."""
    if job.posted_date is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=JOB_MAX_AGE_HOURS)
    posted = job.posted_date
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return posted >= cutoff


def deduplicate(jobs: List[Job]) -> List[Job]:
    """Remove duplicates by URL (case-insensitive, strip trailing slash)."""
    seen_urls: set = set()
    unique: List[Job] = []
    for job in jobs:
        url_key = job.url.rstrip("/").lower()
        if url_key not in seen_urls:
            seen_urls.add(url_key)
            unique.append(job)
    return unique


# ---------------------------------------------------------------------------
# Pipeline (async, callable from web app or CLI)
# ---------------------------------------------------------------------------

async def run_pipeline(db_path: str = DB_PATH) -> dict:
    """
    Full scrape + score pipeline.

    Returns a dict with:
        jobs_found: int   – total new/updated jobs from scrapers
        jobs_scored: int  – jobs scored in this run
    """
    # Lazy imports to avoid circular imports when used as a library
    from .scrapers.france_travail import FranceTravailScraper
    from .scrapers.indeed_rss import IndeedRSSScraper
    from .scrapers.hellowork import HelloWorkScraper
    from .scrapers.linkedin_rss import LinkedInRSSScraper
    from .scrapers.ats_platforms import ATSPlatformsScraper
    from .scrapers.startup_careers import StartupCareersScraper
    from .scrapers.public_sector import PublicSectorScraper

    logger.info("=== HR Job Radar pipeline starting ===")
    start_time = datetime.utcnow()

    await init_db(db_path)

    # ------------------------------------------------------------------
    # 1. Run light scrapers concurrently; heavy scraper separately
    # ------------------------------------------------------------------
    light_scrapers = [
        FranceTravailScraper(),
        IndeedRSSScraper(),
        HelloWorkScraper(),
        LinkedInRSSScraper(),
        ATSPlatformsScraper(),
        PublicSectorScraper(),
    ]

    light_results = await asyncio.gather(
        *[s.scrape() for s in light_scrapers],
        return_exceptions=True,
    )

    all_jobs: List[Job] = []
    for scraper, result in zip(light_scrapers, light_results):
        if isinstance(result, Exception):
            logger.error("Scraper {} failed: {}", scraper.name, result)
        else:
            logger.info("Scraper {}: {} jobs", scraper.name, len(result))
            all_jobs.extend(result)

    # Playwright-based scraper runs separately to avoid resource contention
    try:
        startup_jobs = await StartupCareersScraper().scrape()
        logger.info("Scraper startup_careers: {} jobs", len(startup_jobs))
        all_jobs.extend(startup_jobs)
    except Exception as exc:
        logger.error("StartupCareersScraper failed: {}", exc)

    logger.info("Total raw jobs collected: {}", len(all_jobs))

    # ------------------------------------------------------------------
    # 2. Deduplicate, freshness-filter, save
    # ------------------------------------------------------------------
    unique_jobs = deduplicate(all_jobs)
    recent_jobs = [j for j in unique_jobs if is_recent(j)]
    logger.info("After dedup + freshness filter: {} jobs", len(recent_jobs))

    saved_count = 0
    for job in recent_jobs:
        row_id = await save_job(job, db_path)
        if row_id:
            saved_count += 1

    logger.info("Saved/updated {} jobs to DB", saved_count)

    # ------------------------------------------------------------------
    # 3. Score unscored jobs
    # ------------------------------------------------------------------
    jobs_scored = 0
    if ANTHROPIC_API_KEY:
        unscored = await get_unscored_jobs(db_path)
        if unscored:
            logger.info("Scoring {} unscored jobs with Claude...", len(unscored))
            scorer = JobScorer()
            scored = await scorer.score_jobs(unscored, db_path)
            jobs_scored = sum(1 for j in scored if j.get("score") is not None)
            logger.info("Scored {} jobs", jobs_scored)
    else:
        logger.warning("ANTHROPIC_API_KEY not set – skipping scoring")

    elapsed = (datetime.utcnow() - start_time).total_seconds()
    stats = await get_stats(db_path)
    logger.info(
        "=== Pipeline complete in {:.1f}s | found={} saved={} scored={} | db_stats={} ===",
        elapsed, len(all_jobs), saved_count, jobs_scored, stats
    )

    return {
        "jobs_found": len(all_jobs),
        "jobs_saved": saved_count,
        "jobs_scored": jobs_scored,
        "elapsed_seconds": round(elapsed, 1),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    setup_logging()
    parser = argparse.ArgumentParser(description="HR Job Radar")
    parser.add_argument("--db", default=DB_PATH, help="SQLite database path")
    parser.add_argument("--web", action="store_true", help="Launch the web dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Web server host")
    parser.add_argument("--port", type=int, default=8080, help="Web server port")
    args = parser.parse_args()

    if args.web:
        import uvicorn
        logger.info("Starting HR Job Radar web dashboard on {}:{}", args.host, args.port)
        uvicorn.run("src.web_app:app", host=args.host, port=args.port, reload=False, log_level="info")
    else:
        result = asyncio.run(run_pipeline(args.db))
        print(f"\nDone! Jobs found: {result['jobs_found']}, scored: {result['jobs_scored']}")


if __name__ == "__main__":
    main()
