"""Job Search Agent – main orchestrator.

Run directly:
    python main.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from typing import List

import database as db
from config import LOOKBACK_HOURS
from scorer import Job, enrich_and_score

# Scrapers
from scrapers import greenhouse, lever, ashby, linkedin, welcome_jungle, career_pages

# ---------------------------------------------------------------------------
# Logging – INFO only to file; WARNING+ to console so results stay readable
# ---------------------------------------------------------------------------
log_file = Path(__file__).parent / "agent.log"
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Full detail goes to the log file
file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s – %(message)s", "%Y-%m-%d %H:%M:%S"
))
logging.getLogger().addHandler(file_handler)
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


SCORE_STARS = {5: "★★★★★", 4: "★★★★☆", 3: "★★★☆☆", 2: "★★☆☆☆", 1: "★☆☆☆☆"}


def _salary(job: Job) -> str:
    if job.salary_text:
        return job.salary_text
    if job.salary_min and job.salary_max:
        return f"€{job.salary_min:,}–€{job.salary_max:,}"
    if job.salary_min:
        return f"From €{job.salary_min:,}"
    return "Not specified"


def _remote(job: Job) -> str:
    if job.remote_policy == "remote":
        return "Full remote"
    if job.remote_policy == "hybrid":
        d = job.onsite_days
        return f"Hybrid ({d}d/wk on-site)" if d else "Hybrid"
    if job.remote_policy == "onsite":
        return "On-site"
    return "Unknown"


def print_digest(jobs: List[Job]) -> None:
    """Print a formatted digest to the terminal."""
    WIDTH = 70
    print("\n" + "═" * WIDTH)
    print(f"  JOB SEARCH DIGEST  –  {len(jobs)} new matching job{'s' if len(jobs)!=1 else ''}")
    print("═" * WIDTH)

    by_score: dict[int, list[Job]] = {}
    for j in jobs:
        by_score.setdefault(j.score, []).append(j)

    for score in sorted(by_score.keys(), reverse=True):
        stars = SCORE_STARS.get(score, str(score))
        group = by_score[score]
        print(f"\n  {stars}  Score {score}/5  ({len(group)} job{'s' if len(group)!=1 else ''})")
        print("  " + "─" * (WIDTH - 2))

        for j in group:
            print(f"\n  {j.title}")
            print(f"  {j.company}")
            print(f"    Location : {j.location}")
            print(f"    Remote   : {_remote(j)}")
            print(f"    Salary   : {_salary(j)}")
            print(f"    Sector   : {j.sector or '–'}")
            print(f"    Posted   : {j.date_posted or 'Unknown'}")
            print(f"    Source   : {j.source}")
            print(f"    Link     : {j.url}")

    print("\n" + "═" * WIDTH + "\n")


def record_jobs(jobs: List[Job]) -> None:
    """Print results and mark jobs as seen in the DB."""
    if not jobs:
        print("\n  No new matching jobs found.\n")
        return

    jobs.sort(key=lambda j: (-j.score, j.company))
    print_digest(jobs)

    for job in jobs:
        db.mark_seen(job.job_id, job.title, job.company, job.location, job.url)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\nSearching for jobs (last {LOOKBACK_HOURS}h)…")

    db.init_db()
    run_id = db.start_run()

    try:
        raw_jobs = gather_all_jobs()
        new_jobs = filter_and_score(raw_jobs)

        record_jobs(new_jobs)
        db.finish_run(run_id, jobs_found=len(new_jobs), jobs_sent=0)

    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        log.error("Fatal error: %s", exc, exc_info=True)
        db.finish_run(run_id, jobs_found=0, jobs_sent=0, status="error")
        sys.exit(1)


if __name__ == "__main__":
    main()
