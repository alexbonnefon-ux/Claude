"""Flask web dashboard for the Job Search Agent."""
import atexit
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, flash,
)

import database as db
import settings_db
import scheduler as sched

log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "job-search-agent-secret-2026"   # change if exposing to internet


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

@app.template_filter("fmt_time")
def fmt_time(value: str | None) -> str:
    if not value:
        return "Never"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d %b %Y %H:%M")
    except Exception:
        return value


@app.template_filter("stars")
def stars(score: int) -> str:
    s = int(score or 0)
    return "★" * s + "☆" * (5 - s)


@app.context_processor
def inject_globals():
    return {"now": datetime.utcnow()}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    jobs     = db.get_active_jobs()
    stats    = db.get_stats()
    next_run = sched.get_next_run_time()
    return render_template("index.html", jobs=jobs, stats=stats,
                           next_run=next_run, is_running=sched.is_running())


@app.route("/history")
def history():
    company   = request.args.get("company", "")
    min_score = request.args.get("score", 0, type=int)
    days      = request.args.get("days", 30, type=int)
    status    = request.args.get("status", "")
    search    = request.args.get("search", "")

    jobs      = db.get_history(days=days, company=company, min_score=min_score,
                               status=status, search=search)
    companies = db.get_all_companies()

    return render_template(
        "history.html", jobs=jobs, companies=companies,
        company=company, min_score=min_score, days=days,
        status=status, search=search,
    )


@app.route("/settings")
def settings():
    s = settings_db.get_all()
    return render_template("settings.html", settings=s)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@app.route("/api/job/<job_id>/status", methods=["POST"])
def update_job_status(job_id: str):
    data   = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("applied", "ignored", "new"):
        return jsonify({"ok": False, "error": "Invalid status"}), 400
    db.update_job_status(job_id, status)
    return jsonify({"ok": True})


@app.route("/api/run", methods=["POST"])
def run_now():
    if sched.is_running():
        return jsonify({"ok": False, "message": "Scrape already in progress"}), 409
    t = threading.Thread(target=sched.trigger_now, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Scrape started"})


@app.route("/api/status")
def api_status():
    stats             = db.get_stats()
    stats["is_running"] = sched.is_running()
    stats["next_run"]   = sched.get_next_run_time()
    if stats["last_run_at"]:
        stats["last_run_at"] = fmt_time(stats["last_run_at"])
    return jsonify(stats)


@app.route("/api/settings", methods=["POST"])
def save_settings():
    data = request.get_json(silent=True) or {}
    for key, value in data.items():
        settings_db.set_value(key, value)
    # Reschedule if times changed
    if "schedule_times" in data:
        sched.reschedule(data["schedule_times"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    db.init_db()
    sched.start_scheduler()
    atexit.register(sched.shutdown)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(Path(__file__).parent / "agent.log", encoding="utf-8"),
        ],
    )
    create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
