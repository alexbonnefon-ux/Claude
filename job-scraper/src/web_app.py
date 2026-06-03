"""
FastAPI web application for the HR Job Radar dashboard.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .config import DB_PATH
from .database import init_db, get_stats

app = FastAPI(title="HR Job Radar", version="1.0.0")

# In-memory scrape job tracking
_scrape_jobs: dict = {}

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def on_startup() -> None:
    await init_db(DB_PATH)
    logger.info("HR Job Radar started. DB: {}", DB_PATH)


@app.get("/", include_in_schema=False)
async def serve_dashboard() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(str(index_path))


# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.post("/api/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks) -> JSONResponse:
    """Trigger all scrapers in the background. Returns a job_id to poll status."""
    for jid, info in _scrape_jobs.items():
        if info["status"] == "running":
            return JSONResponse({"job_id": jid, "status": "already_running",
                                  "message": "A scrape is already in progress"})

    job_id = str(uuid.uuid4())
    _scrape_jobs[job_id] = {
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "jobs_found": 0,
        "jobs_scored": 0,
        "error": None,
    }
    background_tasks.add_task(_run_scrape_pipeline, job_id)
    logger.info("Scrape triggered: job_id={}", job_id)
    return JSONResponse({"job_id": job_id, "status": "started"})


@app.get("/api/scrape/status/{job_id}")
async def scrape_status(job_id: str) -> JSONResponse:
    """Check the status of a scrape run."""
    info = _scrape_jobs.get(job_id)
    if not info:
        raise HTTPException(status_code=404, detail="Scrape job not found")
    return JSONResponse(info)


@app.get("/api/scrape/latest")
async def latest_scrape_status() -> JSONResponse:
    """Return the status of the most recent scrape job."""
    if not _scrape_jobs:
        return JSONResponse({"status": "idle", "message": "No scrape has been triggered yet"})
    latest_id, latest_info = max(
        _scrape_jobs.items(),
        key=lambda kv: kv[1].get("started_at", "")
    )
    return JSONResponse({"job_id": latest_id, **latest_info})


@app.get("/api/jobs")
async def get_jobs(
    min_score: float = Query(default=0.0, ge=0.0, le=10.0),
    section: Optional[str] = Query(default=None, description="top|good|worth|all"),
    limit: int = Query(default=200, ge=1, le=500),
) -> JSONResponse:
    """Return all jobs from DB as JSON, optionally filtered."""
    score_min = min_score
    score_max = 10.0

    if section == "top":
        score_min = max(score_min, 8.0)
    elif section == "good":
        score_min = max(score_min, 6.0)
        score_max = 7.99
    elif section == "worth":
        score_min = max(score_min, 4.0)
        score_max = 5.99

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            if section in ("good", "worth"):
                cursor = await db.execute(
                    "SELECT * FROM jobs WHERE score >= ? AND score <= ? "
                    "ORDER BY score DESC, posted_date DESC LIMIT ?",
                    (score_min, score_max, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM jobs WHERE score >= ? "
                    "ORDER BY score DESC, posted_date DESC LIMIT ?",
                    (score_min, limit),
                )
            rows = await cursor.fetchall()
            jobs = []
            for row in rows:
                job = dict(row)
                try:
                    job["score_details"] = json.loads(job.get("score_details") or "{}")
                except (json.JSONDecodeError, TypeError):
                    job["score_details"] = {}
                try:
                    job["raw_data"] = json.loads(job.get("raw_data") or "{}")
                except (json.JSONDecodeError, TypeError):
                    job["raw_data"] = {}
                jobs.append(job)

        return JSONResponse({"jobs": jobs, "count": len(jobs)})
    except Exception as exc:
        logger.error("Error fetching jobs: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/stats")
async def get_stats_endpoint() -> JSONResponse:
    """Return aggregate stats."""
    try:
        stats = await get_stats(DB_PATH)
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT MAX(scraped_at) FROM jobs")
            row = await cursor.fetchone()
            last_scraped = row[0] if row else None
        stats["last_scraped"] = last_scraped
        return JSONResponse(stats)
    except Exception as exc:
        logger.error("Error fetching stats: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/jobs/clear")
async def clear_jobs(
    older_than_days: int = Query(default=7, ge=1, le=365)
) -> JSONResponse:
    """Clear jobs older than N days."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM jobs WHERE scraped_at < datetime('now', ? || ' days')",
                (f"-{older_than_days}",),
            )
            await db.commit()
            deleted = cursor.rowcount
        logger.info("Cleared {} jobs older than {} days", deleted, older_than_days)
        return JSONResponse({"deleted": deleted, "message": f"Cleared {deleted} old jobs"})
    except Exception as exc:
        logger.error("Error clearing jobs: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))


async def _run_scrape_pipeline(job_id: str) -> None:
    """Run all scrapers and score results."""
    from .main import run_pipeline

    info = _scrape_jobs[job_id]
    try:
        result = await run_pipeline()
        info["status"] = "done"
        info["finished_at"] = datetime.utcnow().isoformat()
        info["jobs_found"] = result.get("jobs_found", 0)
        info["jobs_scored"] = result.get("jobs_scored", 0)
        logger.info("Scrape job {} complete: {} found, {} scored",
                    job_id, info["jobs_found"], info["jobs_scored"])
    except Exception as exc:
        logger.error("Scrape job {} failed: {}", job_id, exc)
        info["status"] = "error"
        info["finished_at"] = datetime.utcnow().isoformat()
        info["error"] = str(exc)

    # Keep only last 20 scrape jobs
    if len(_scrape_jobs) > 20:
        oldest_keys = sorted(_scrape_jobs.keys(),
                              key=lambda k: _scrape_jobs[k].get("started_at", ""))[:10]
        for k in oldest_keys:
            del _scrape_jobs[k]
