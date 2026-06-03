"""SQLite database layer for storing and retrieving job listings."""

import json
import aiosqlite
from datetime import datetime
from typing import List, Optional
from dataclasses import asdict
from loguru import logger

from src.config import DB_PATH
from src.scrapers.base import Job


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    job_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    remote_policy TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_estimated BOOLEAN DEFAULT 0,
    url TEXT NOT NULL,
    posted_date TEXT,
    scraped_at TEXT NOT NULL,
    score REAL,
    score_details TEXT,
    emailed BOOLEAN DEFAULT 0,
    raw_data TEXT,
    UNIQUE(source, job_id)
)
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_source_job_id ON jobs(source, job_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_emailed ON jobs(emailed)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at)",
]


async def init_db() -> None:
    """Initialize the database, creating tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE_SQL)
        for index_sql in CREATE_INDEX_SQL:
            await db.execute(index_sql)
        await db.commit()
    logger.info(f"Database initialized at {DB_PATH}")


async def job_exists(source: str, job_id: str) -> bool:
    """Check if a job already exists in the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM jobs WHERE source = ? AND job_id = ?",
            (source, job_id),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def save_job(job: Job) -> bool:
    """
    Save a job to the database.
    Returns True if inserted, False if it already existed.
    """
    now = datetime.utcnow().isoformat()
    raw_data_str = json.dumps(job.raw_data) if job.raw_data else None
    score_details_str = json.dumps(job.score_details) if job.score_details else None

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO jobs
                    (source, job_id, title, company, location, remote_policy,
                     salary_min, salary_max, salary_estimated, url, posted_date,
                     scraped_at, score, score_details, emailed, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    job.source,
                    job.job_id,
                    job.title,
                    job.company,
                    job.location,
                    job.remote_policy,
                    job.salary_min,
                    job.salary_max,
                    job.salary_estimated,
                    job.url,
                    job.posted_date.isoformat() if job.posted_date else None,
                    now,
                    job.score,
                    score_details_str,
                    raw_data_str,
                ),
            )
            changes = db.total_changes
            await db.commit()
            return changes > 0
    except Exception as e:
        logger.error(f"Error saving job {job.job_id} from {job.source}: {e}")
        return False


async def update_job_score(source: str, job_id: str, score: float, score_details: dict) -> None:
    """Update the score for an existing job."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET score = ?, score_details = ? WHERE source = ? AND job_id = ?",
            (score, json.dumps(score_details), source, job_id),
        )
        await db.commit()


async def get_unsent_jobs(min_score: float = 4.0) -> List[dict]:
    """Retrieve all jobs that haven't been emailed and meet the score threshold."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM jobs
            WHERE emailed = 0
              AND score >= ?
            ORDER BY score DESC, posted_date DESC
            """,
            (min_score,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_unscored_jobs() -> List[dict]:
    """Retrieve jobs that haven't been scored yet."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs WHERE score IS NULL ORDER BY scraped_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def mark_as_sent(job_ids: List[int]) -> None:
    """Mark a list of jobs (by DB id) as emailed."""
    if not job_ids:
        return
    placeholders = ",".join("?" * len(job_ids))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE jobs SET emailed = 1 WHERE id IN ({placeholders})",
            job_ids,
        )
        await db.commit()
    logger.info(f"Marked {len(job_ids)} jobs as sent")


async def get_stats() -> dict:
    """Return summary statistics about the job database."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM jobs") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM jobs WHERE emailed = 1") as cur:
            sent = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM jobs WHERE score >= 8") as cur:
            top = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT source, COUNT(*) as cnt FROM jobs GROUP BY source ORDER BY cnt DESC"
        ) as cur:
            by_source = {row[0]: row[1] for row in await cur.fetchall()}

    return {
        "total": total,
        "sent": sent,
        "top_picks": top,
        "by_source": by_source,
    }
