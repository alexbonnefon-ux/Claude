"""SQLite database for tracking seen jobs and run history."""
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import DB_PATH

log = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT    NOT NULL UNIQUE,
                title       TEXT,
                company     TEXT,
                location    TEXT,
                url         TEXT,
                first_seen  TEXT    NOT NULL,
                sent_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                ended_at   TEXT,
                jobs_found INTEGER DEFAULT 0,
                jobs_sent  INTEGER DEFAULT 0,
                status     TEXT DEFAULT 'running'
            );

            CREATE INDEX IF NOT EXISTS idx_seen_jobs_job_id ON seen_jobs(job_id);
        """)
    log.debug("Database initialised at %s", DB_PATH)


def is_seen(job_id: str) -> bool:
    """Return True if this job_id was already processed."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return row is not None


def mark_seen(job_id: str, title: str, company: str,
              location: str, url: str) -> None:
    """Record a job as seen (upsert)."""
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO seen_jobs (job_id, title, company, location, url, first_seen)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_id) DO NOTHING""",
            (job_id, title, company, location, url, now),
        )


def mark_sent(job_id: str) -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE seen_jobs SET sent_at = ? WHERE job_id = ?",
            (now, job_id),
        )


def start_run() -> int:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at) VALUES (?)", (now,)
        )
        return cur.lastrowid


def finish_run(run_id: int, jobs_found: int, jobs_sent: int,
               status: str = "ok") -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """UPDATE runs
               SET ended_at=?, jobs_found=?, jobs_sent=?, status=?
               WHERE id=?""",
            (now, jobs_found, jobs_sent, status, run_id),
        )
