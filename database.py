"""SQLite database – jobs, settings, run history."""
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from config import DB_PATH

log = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create or migrate all tables."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id        TEXT    NOT NULL UNIQUE,
                title         TEXT    NOT NULL,
                company       TEXT    DEFAULT '',
                location      TEXT    DEFAULT '',
                url           TEXT    DEFAULT '',
                date_posted   TEXT,
                salary_text   TEXT    DEFAULT '',
                salary_min    INTEGER,
                salary_max    INTEGER,
                remote_policy TEXT    DEFAULT 'unknown',
                onsite_days   INTEGER,
                sector        TEXT    DEFAULT '',
                source        TEXT    DEFAULT '',
                score         INTEGER DEFAULT 0,
                description   TEXT    DEFAULT '',
                status        TEXT    DEFAULT 'new',
                first_seen    TEXT    NOT NULL,
                applied_at    TEXT,
                ignored_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT NOT NULL,
                ended_at    TEXT,
                jobs_found  INTEGER DEFAULT 0,
                status      TEXT    DEFAULT 'running',
                error       TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_job_id    ON jobs(job_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status    ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_score     ON jobs(score);
            CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
            CREATE INDEX IF NOT EXISTS idx_jobs_company   ON jobs(company);
        """)

        # ── Migrate from old seen_jobs table (v1) ───────────────────────────
        old = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='seen_jobs'"
        ).fetchone()
        if old:
            conn.execute("""
                INSERT OR IGNORE INTO jobs
                    (job_id, title, company, location, url, first_seen, status)
                SELECT job_id,
                       COALESCE(title, ''),
                       COALESCE(company, ''),
                       COALESCE(location, ''),
                       COALESCE(url, ''),
                       first_seen,
                       'new'
                FROM seen_jobs
            """)
            conn.execute("DROP TABLE seen_jobs")
            log.info("Migrated seen_jobs → jobs")

    log.debug("Database ready at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Job storage
# ---------------------------------------------------------------------------

def is_seen(job_id: str) -> bool:
    with get_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone() is not None


def upsert_job(job) -> bool:
    """Insert job; return True if new, False if already existed."""
    now = datetime.utcnow().isoformat()
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO jobs
                    (job_id, title, company, location, url, date_posted,
                     salary_text, salary_min, salary_max, remote_policy,
                     onsite_days, sector, source, score, description, first_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                job.job_id,
                job.title,
                job.company or "",
                job.location or "",
                job.url or "",
                job.date_posted,
                job.salary_text or "",
                job.salary_min,
                job.salary_max,
                job.remote_policy or "unknown",
                job.onsite_days,
                job.sector or "",
                job.source or "",
                job.score,
                (job.description or "")[:3000],
                now,
            ))
        return True
    except sqlite3.IntegrityError:
        return False


def update_job_status(job_id: str, status: str) -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        if status == "applied":
            conn.execute(
                "UPDATE jobs SET status=?, applied_at=? WHERE job_id=?",
                (status, now, job_id),
            )
        elif status == "ignored":
            conn.execute(
                "UPDATE jobs SET status=?, ignored_at=? WHERE job_id=?",
                (status, now, job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET status=? WHERE job_id=?", (status, job_id)
            )


# ---------------------------------------------------------------------------
# Queries for the dashboard / history
# ---------------------------------------------------------------------------

def get_active_jobs() -> List[sqlite3.Row]:
    """status='new', ordered by score then recency."""
    with get_connection() as conn:
        return conn.execute("""
            SELECT * FROM jobs
            WHERE  status = 'new'
            ORDER  BY score DESC, date_posted DESC, first_seen DESC
        """).fetchall()


def get_history(
    days: int = 30,
    company: str = "",
    min_score: int = 0,
    status: str = "",
    search: str = "",
) -> List[sqlite3.Row]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    filters = ["first_seen >= ?"]
    params: list = [cutoff]

    if company:
        filters.append("company = ?"); params.append(company)
    if min_score:
        filters.append("score >= ?");  params.append(min_score)
    if status:
        filters.append("status = ?");  params.append(status)
    if search:
        filters.append("(title LIKE ? OR company LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]

    where = " AND ".join(filters)
    with get_connection() as conn:
        return conn.execute(
            f"SELECT * FROM jobs WHERE {where} ORDER BY score DESC, first_seen DESC",
            params,
        ).fetchall()


def get_all_companies() -> List[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT company FROM jobs WHERE company != '' ORDER BY company"
        ).fetchall()
    return [r[0] for r in rows]


def get_stats() -> dict:
    today = datetime.utcnow().date().isoformat()
    with get_connection() as conn:
        new_count     = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='new'").fetchone()[0]
        today_count   = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE first_seen >= ?", (today,)
        ).fetchone()[0]
        applied_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='applied'").fetchone()[0]
        ignored_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='ignored'").fetchone()[0]
        last_run      = conn.execute(
            "SELECT ended_at, jobs_found FROM runs WHERE status='ok' ORDER BY ended_at DESC LIMIT 1"
        ).fetchone()
        running_run   = conn.execute(
            "SELECT id FROM runs WHERE status='running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

    return {
        "new_count":      new_count,
        "today_count":    today_count,
        "applied_count":  applied_count,
        "ignored_count":  ignored_count,
        "last_run_at":    last_run["ended_at"]    if last_run else None,
        "last_run_found": last_run["jobs_found"]  if last_run else 0,
        "is_db_running":  running_run is not None,
    }


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

def start_run() -> int:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now,))
        return cur.lastrowid


def finish_run(run_id: int, jobs_found: int,
               status: str = "ok", error: str = None) -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE runs SET ended_at=?, jobs_found=?, status=?, error=? WHERE id=?",
            (now, jobs_found, status, error, run_id),
        )


# ---------------------------------------------------------------------------
# Back-compat shims (used by old main.py code path)
# ---------------------------------------------------------------------------

def mark_seen(job_id, title, company, location, url):
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO jobs (job_id, title, company, location, url, first_seen)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (job_id, title or "", company or "", location or "", url or "", now),
        )


def mark_sent(_job_id):
    pass  # email removed
