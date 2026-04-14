"""Job Search Agent – core pipeline.

Can be run directly (CLI) or called by the APScheduler via scheduler.py.

CLI:  cd job_search_agent && python main.py
Web:  cd job_search_agent && python app.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from typing import List

import database as db
import settings_db
from scorer import Job, enrich_and_score
from scrapers import greenhouse, lever, ashby, career_pages, serpapi_jobs

# ---------------------------------------------------------------------------
# Logging – WARNING+ to console, full INFO to file
# ---------------------------------------------------------------------------
_log_file = Path(__file__).parent / "agent.log"
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
_fh = logging.FileHandler(_log_file, encoding="utf-8")
_fh.setLevel(logging.INFO)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s – %(message)s", "%Y-%m-%d %H:%M:%S",
))
logging.getLogger().addHandler(_fh)
log = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def gather_all_jobs() -> List[Job]:
    all_raw: List[Job] = []
    sources = [
        # Direct ATS API scrapers – reliable, no auth needed
        ("Greenhouse",   greenhouse.scrape_all),
        ("Lever",        lever.scrape_all),
        ("Ashby",        ashby.scrape_all),
        ("Career Pages", career_pages.scrape_all),
        # SerpAPI: Google Jobs engine + Google site: search fallback
        # (replaces blocked LinkedIn / WTTJ scrapers)
        ("Google Jobs / SerpAPI", serpapi_jobs.scrape_all),
    ]
    for name, fn in sources:
        log.info("── Scraper: %s ──", name)
        try:
            jobs = fn()
            log.info("%s → %d raw jobs", name, len(jobs))
            all_raw.extend(jobs)
        except Exception as exc:
            log.error("Scraper %s crashed: %s", name, exc, exc_info=True)
    return all_raw


def filter_and_score(raw_jobs: List[Job]) -> List[Job]:
    seen_ids: set = set()
    new_jobs: List[Job] = []
    for job in raw_jobs:
        if job.job_id in seen_ids:
            continue
        seen_ids.add(job.job_id)
        if db.is_seen(job.job_id):
            log.debug("SKIP (seen): %s – %s", job.company, job.title)
            continue
        enriched = enrich_and_score(job)
        if enriched is None:
            continue
        new_jobs.append(enriched)
    return new_jobs


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run_scrape() -> int:
    """Run the full pipeline. Returns count of new jobs saved. Used by scheduler."""
    log.info("run_scrape() started")
    db.init_db()
    run_id = db.start_run()
    try:
        raw   = gather_all_jobs()
        new   = filter_and_score(raw)
        saved = sum(1 for j in new if db.upsert_job(j))
        db.finish_run(run_id, jobs_found=saved)
        log.info("run_scrape() done – %d new jobs saved", saved)
        return saved
    except Exception as exc:
        log.error("run_scrape() error: %s", exc, exc_info=True)
        db.finish_run(run_id, jobs_found=0, status="error", error=str(exc))
        return 0


# ---------------------------------------------------------------------------
# CLI: print digest to terminal
# ---------------------------------------------------------------------------

_STARS = {5: "★★★★★", 4: "★★★★☆", 3: "★★★☆☆", 2: "★★☆☆☆", 1: "★☆☆☆☆"}
_W = 70


def _salary(job):
    if job.salary_text: return job.salary_text
    if job.salary_min and job.salary_max:
        return f"€{job.salary_min:,}–€{job.salary_max:,}"
    if job.salary_min: return f"From €{job.salary_min:,}"
    return "Not specified"


def _remote(job):
    if job.remote_policy == "remote": return "Full remote"
    if job.remote_policy == "hybrid":
        d = job.onsite_days
        return f"Hybrid ({d}d/wk)" if d else "Hybrid"
    if job.remote_policy == "onsite": return "On-site"
    return "Unknown"


def print_digest(jobs: List[Job]) -> None:
    print("\n" + "═" * _W)
    print(f"  JOB SEARCH DIGEST  –  {len(jobs)} new matching job{'s' if len(jobs) != 1 else ''}")
    print("═" * _W)
    by_score: dict = {}
    for j in jobs:
        by_score.setdefault(j.score, []).append(j)
    for score in sorted(by_score.keys(), reverse=True):
        stars = _STARS.get(score, str(score))
        group = by_score[score]
        print(f"\n  {stars}  Score {score}/5  ({len(group)} job{'s' if len(group) != 1 else ''})")
        print("  " + "─" * (_W - 2))
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
    print("\n" + "═" * _W + "\n")


def main() -> None:
    lookback = settings_db.lookback_hours()
    print(f"\nSearching for jobs (last {lookback}h)…  (full log → agent.log)")
    db.init_db()
    saved = run_scrape()
    jobs = db.get_active_jobs()
    if not jobs:
        print("\n  No new matching jobs found.\n")
    else:
        # Convert sqlite3.Row objects to Job-like objects for print_digest
        class _Row:
            def __init__(self, r):
                for k in r.keys():
                    setattr(self, k, r[k])
        print_digest([_Row(r) for r in jobs])   # type: ignore


if __name__ == "__main__":
    main()
