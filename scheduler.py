"""APScheduler wrapper – runs scrapes at configured Paris-time schedule."""
import logging
import threading
from typing import Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_PARIS = pytz.timezone("Europe/Paris")
_scheduler: Optional[BackgroundScheduler] = None
_scrape_lock = threading.Lock()
_running = threading.Event()


# ---------------------------------------------------------------------------
# Core scrape wrapper
# ---------------------------------------------------------------------------

def _run_scrape() -> None:
    if _running.is_set():
        log.warning("Scrape already in progress – skipping scheduled trigger.")
        return
    _running.set()
    try:
        # Import here to avoid circular imports at module load time
        import main as agent
        agent.run_scrape()
    except Exception as exc:
        log.error("Scheduled scrape failed: %s", exc, exc_info=True)
    finally:
        _running.clear()


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    global _scheduler
    import settings_db

    _scheduler = BackgroundScheduler(timezone=_PARIS)

    for time_str in settings_db.schedule_times():
        _add_job(time_str)

    _scheduler.start()
    log.info("APScheduler started. Jobs: %s",
             [str(j.next_run_time) for j in _scheduler.get_jobs()])


def _add_job(time_str: str) -> None:
    if not _scheduler:
        return
    try:
        hour, minute = map(int, time_str.split(":"))
        _scheduler.add_job(
            _run_scrape,
            CronTrigger(hour=hour, minute=minute, timezone=_PARIS),
            id=f"scrape_{time_str.replace(':', '')}",
            replace_existing=True,
            misfire_grace_time=300,
        )
        log.info("Scrape scheduled at %s (Paris)", time_str)
    except Exception as exc:
        log.error("Could not schedule %s: %s", time_str, exc)


def reschedule(times: list) -> None:
    """Called after settings change to update the schedule."""
    if not _scheduler:
        return
    for job in _scheduler.get_jobs():
        if job.id.startswith("scrape_"):
            job.remove()
    for t in times:
        _add_job(t)
    log.info("Schedule updated: %s", times)


def trigger_now() -> None:
    """Synchronous run (called in a background thread from the web UI)."""
    _run_scrape()


def is_running() -> bool:
    return _running.is_set()


def get_next_run_time() -> Optional[str]:
    if not _scheduler:
        return None
    jobs = [j for j in _scheduler.get_jobs() if j.next_run_time]
    if not jobs:
        return None
    next_dt = min(j.next_run_time for j in jobs).astimezone(_PARIS)
    return next_dt.strftime("%d %b %Y %H:%M")


def shutdown() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
