"""SQLite database layer for storing and managing job listings."""
import json
import aiosqlite
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, field
from loguru import logger

from .config import DB_PATH


@dataclass
class Job:
    source: str
    job_id: str
    title: str
    company: str
    location: str
    url: str
    remote_policy: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_estimated: bool = False
    posted_date: Optional[datetime] = None
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    score: Optional[float] = None
    score_details: dict = field(default_factory=dict)
    emailed: bool = False
    raw_data: dict = field(default_factory=dict)
    description: str = ""


async def init_db(db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                job_id TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                remote_policy TEXT DEFAULT 'unknown',
                salary_min INTEGER,
                salary_max INTEGER,
                salary_estimated BOOLEAN DEFAULT 0,
                url TEXT NOT NULL,
                posted_date TEXT,
                scraped_at TEXT NOT NULL,
                score REAL,
                score_details TEXT DEFAULT '{}',
                emailed BOOLEAN DEFAULT 0,
                raw_data TEXT DEFAULT '{}',
                description TEXT DEFAULT '',
                category TEXT,
                category_meta TEXT DEFAULT '{}',
                UNIQUE(source, job_id)
            )
        """)
        for col_def in (
            "ALTER TABLE jobs ADD COLUMN category TEXT",
            "ALTER TABLE jobs ADD COLUMN category_meta TEXT DEFAULT '{}'",
        ):
            try:
                await db.execute(col_def)
            except Exception:
                pass
        for idx in (
            "CREATE INDEX IF NOT EXISTS idx_emailed ON jobs(emailed)",
            "CREATE INDEX IF NOT EXISTS idx_score ON jobs(score)",
            "CREATE INDEX IF NOT EXISTS idx_scraped_at ON jobs(scraped_at)",
            "CREATE INDEX IF NOT EXISTS idx_category ON jobs(category)",
        ):
            await db.execute(idx)
        await db.commit()
        logger.debug("Database initialized at {}", db_path)


async def job_exists(source: str, job_id: str, db_path: str = DB_PATH) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT 1 FROM jobs WHERE source = ? AND job_id = ?", (source, job_id))
        return await cursor.fetchone() is not None


async def save_job(job: Job, db_path: str = DB_PATH) -> Optional[int]:
    async with aiosqlite.connect(db_path) as db:
        try:
            cursor = await db.execute("""
                INSERT INTO jobs (
                    source, job_id, title, company, location, remote_policy,
                    salary_min, salary_max, salary_estimated, url, posted_date,
                    scraped_at, score, score_details, emailed, raw_data, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, job_id) DO UPDATE SET
                    title = excluded.title, company = excluded.company,
                    location = excluded.location, remote_policy = excluded.remote_policy,
                    salary_min = COALESCE(excluded.salary_min, jobs.salary_min),
                    salary_max = COALESCE(excluded.salary_max, jobs.salary_max),
                    salary_estimated = excluded.salary_estimated, url = excluded.url,
                    posted_date = COALESCE(excluded.posted_date, jobs.posted_date),
                    score = COALESCE(excluded.score, jobs.score),
                    score_details = CASE WHEN excluded.score IS NOT NULL THEN excluded.score_details ELSE jobs.score_details END,
                    description = CASE WHEN excluded.description != '' THEN excluded.description ELSE jobs.description END,
                    raw_data = excluded.raw_data
            """, (
                job.source, job.job_id, job.title, job.company, job.location, job.remote_policy,
                job.salary_min, job.salary_max, 1 if job.salary_estimated else 0,
                job.url, job.posted_date.isoformat() if job.posted_date else None,
                job.scraped_at.isoformat(), job.score, json.dumps(job.score_details),
                1 if job.emailed else 0, json.dumps(job.raw_data), job.description,
            ))
            await db.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("Error saving job {}/{}: {}", job.source, job.job_id, e)
            return None


async def get_unsent_jobs(min_score: float = 4.0, db_path: str = DB_PATH) -> List[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM jobs WHERE emailed = 0 AND score IS NOT NULL AND score >= ?
            ORDER BY score DESC, posted_date DESC
        """, (min_score,))
        return [dict(r) for r in await cursor.fetchall()]


async def get_unscored_jobs(db_path: str = DB_PATH) -> List[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM jobs WHERE score IS NULL ORDER BY scraped_at DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def update_job_score(job_id_db: int, score: float, score_details: dict, db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE jobs SET score = ?, score_details = ? WHERE id = ?",
                         (score, json.dumps(score_details), job_id_db))
        await db.commit()


async def mark_as_sent(job_ids: List[int], db_path: str = DB_PATH) -> None:
    if not job_ids:
        return
    async with aiosqlite.connect(db_path) as db:
        placeholders = ",".join("?" * len(job_ids))
        await db.execute(f"UPDATE jobs SET emailed = 1 WHERE id IN ({placeholders})", job_ids)
        await db.commit()


async def update_job_category(job_id: int, category: str, meta: dict, db_path: str = DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE jobs SET category = ?, category_meta = ? WHERE id = ?",
                         (category, json.dumps(meta), job_id))
        await db.commit()


async def get_jobs_by_category(category: str, db_path: str = DB_PATH, min_score: float = 0) -> List[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM jobs WHERE category = ? AND COALESCE(score, 0) >= ?
            ORDER BY COALESCE(score, 0) DESC, posted_date DESC
        """, (category, min_score))
        return [dict(r) for r in await cursor.fetchall()]


async def get_all_jobs(db_path: str = DB_PATH) -> List[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM jobs ORDER BY scraped_at DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def get_stats(db_path: str = DB_PATH) -> dict:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN emailed = 1 THEN 1 ELSE 0 END) as total_sent,
                SUM(CASE WHEN category = 'tours' THEN 1 ELSE 0 END) as tours_count,
                SUM(CASE WHEN category = 'paris_hybrid' THEN 1 ELSE 0 END) as paris_count,
                SUM(CASE WHEN category = 'full_remote' THEN 1 ELSE 0 END) as remote_count
            FROM jobs
        """)
        row = await cursor.fetchone()
        return dict(row) if row else {}
