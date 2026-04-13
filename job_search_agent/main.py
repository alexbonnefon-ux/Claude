"""Job Search Agent – main orchestrator.

Run directly:
    python main.py

Or via the cron wrapper script (see run.sh / setup_cron.sh).
"""
import logging
import sys
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent))

# Load .env before importing anything that reads os.getenv()
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from typing import List

import database as db
from config import LOOKBACK_HOURS
from scorer import Job, enrich_and_score
from email_sender import send_digest

# Scrapers
from scrapers import greenhouse, lever, ashby, linkedin, welcome_jungle, career_pages

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def gather_all_jobs() -> List[Job]:
    """Run all scrapers and return a flat list of raw Job objects."""
    all_raw: List[Job] = []

    sources = [
        ("Greenhouse",         greenhouse.scrape_all),
        ("Lever",              lever.scrape_all),
        ("Ashby",              ashby.scrape_all),
        ("Welcome to Jungle",  welcome_jungle.scrape_all),
        ("Career Pages",       career_pages.scrape_all),
        ("LinkedIn",           linkedin.scrape_all),   # Selenium last (slowest)
    ]

    for name, fn in sources:
        log.info("─── Running scraper: %s ───", name)
        try:
            jobs = fn()
            log.info("%s returned %d jobs", name, len(jobs))
            all_raw.extend(jobs)
        except Exception as exc:
            log.error("Scraper %s crashed: %s", name, exc, exc_info=True)

    return all_raw


def filter_and_score(raw_jobs: List[Job]) -> List[Job]:
    """
    1. Deduplicate by job_id
    2. Skip jobs already in the DB (already sent in a previous run)
    3. Enrich and score; drop jobs that fail filters
    """
    seen_in_run: set = set()
    new_jobs: List[Job] = []

    for job in raw_jobs:
        # Dedup within this run
        if job.job_id in seen_in_run:
            continue
        seen_in_run.add(job.job_id)

        # Already sent in a previous run?
        if db.is_seen(job.job_id):
            log.debug("SKIP (already seen): %s – %s", job.company, job.title)
            continue

        # Enrich + filter + score
        enriched = enrich_and_score(job)
        if enriched is None:
            continue

        new_jobs.append(enriched)

    return new_jobs


def record_and_send(jobs: List[Job], run_id: int) -> int:
    """Persist jobs to DB and send email digest. Returns number of jobs sent."""
    if not jobs:
        log.info("No new matching jobs – skipping email.")
        return 0

    # Sort by score desc, then company
    jobs.sort(key=lambda j: (-j.score, j.company))

    log.info("Sending digest with %d jobs…", len(jobs))
    try:
        send_digest(jobs)
        sent_count = len(jobs)
    except Exception as exc:
        log.error("Email send failed: %s", exc, exc_info=True)
        sent_count = 0

    # Mark all jobs as seen regardless of email success (avoid duplicates)
    for job in jobs:
        db.mark_seen(job.job_id, job.title, job.company, job.location, job.url)
        if sent_count > 0:
            db.mark_sent(job.job_id)

    return sent_count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=" * 60)
    log.info("Job Search Agent starting (lookback: %dh)", LOOKBACK_HOURS)
    log.info("=" * 60)

    db.init_db()
    run_id = db.start_run()

    try:
        raw_jobs   = gather_all_jobs()
        log.info("Total raw jobs collected: %d", len(raw_jobs))

        new_jobs   = filter_and_score(raw_jobs)
        log.info("New matching jobs after filtering: %d", len(new_jobs))

        sent_count = record_and_send(new_jobs, run_id)

        db.finish_run(run_id, jobs_found=len(new_jobs), jobs_sent=sent_count)
        log.info("Run complete – found %d, sent %d.", len(new_jobs), sent_count)

    except Exception as exc:
        log.error("Fatal error in main: %s", exc, exc_info=True)
        db.finish_run(run_id, jobs_found=0, jobs_sent=0, status="error")
        sys.exit(1)


if __name__ == "__main__":
    main()
