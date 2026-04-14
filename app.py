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
# /test-scraper – debug endpoint
# ---------------------------------------------------------------------------

@app.route("/test-scraper")
def test_scraper():
    """
    Run one full scrape cycle synchronously and render a detailed HTML
    report showing per-scraper results, errors, timing, and matched jobs.
    Useful for debugging when deployed or running locally.
    """
    import time as _time
    import traceback as _tb
    import html as _html
    from config import SERPAPI_KEY
    from scrapers import greenhouse, lever, ashby, career_pages, serpapi_jobs
    from scorer import enrich_and_score

    SOURCES = [
        ("Greenhouse (direct API)",  greenhouse.scrape_all),
        ("Lever (direct API)",       lever.scrape_all),
        ("Ashby (direct API)",       ashby.scrape_all),
        ("Career Pages (Selenium)",  career_pages.scrape_all),
        ("Google Jobs / SerpAPI",    serpapi_jobs.scrape_all),
    ]

    env_checks = {
        "SERPAPI_KEY":    ("✓ Set" if SERPAPI_KEY else "✗ Not set – add to .env", bool(SERPAPI_KEY)),
        "Database path":  (str(db.DB_PATH), True),
        "Python path":    (str(Path(__file__).parent), True),
    }

    results = []
    all_raw = []

    for name, fn in SOURCES:
        t0 = _time.time()
        jobs, error = [], None
        try:
            jobs = fn()
        except Exception:
            error = _tb.format_exc()
        elapsed = round(_time.time() - t0, 2)
        all_raw.extend(jobs)
        results.append({
            "name":    name,
            "count":   len(jobs),
            "elapsed": elapsed,
            "error":   error,
            "samples": [
                {"title": j.title, "company": j.company,
                 "location": j.location, "url": j.url, "source": j.source}
                for j in jobs[:5]
            ],
        })

    # Dedup + filter + score (don't touch DB – read-only test)
    seen: set = set()
    matched = []
    skipped_seen = 0
    skipped_filter = 0
    for job in all_raw:
        if job.job_id in seen:
            continue
        seen.add(job.job_id)
        if db.is_seen(job.job_id):
            skipped_seen += 1
            continue
        enriched = enrich_and_score(job)
        if enriched is None:
            skipped_filter += 1
        else:
            matched.append(enriched)

    matched.sort(key=lambda j: (-j.score, j.company))

    # ── Build HTML inline (no template dependency) ──────────────────────────
    def esc(s): return _html.escape(str(s or ""))

    if not matched:
        matched_table_html = (
            "<p class='text-gray-400 text-sm py-4 text-center'>"
            "No jobs matched the current filters.</p>"
        )
    else:
        matched_table_html = (
            '<div class="overflow-x-auto">'
            '<table class="w-full text-sm">'
            '<thead><tr class="text-left text-xs text-gray-400 font-semibold">'
            '<th class="pb-2 pr-3">Score</th>'
            '<th class="pb-2 pr-3">Title</th>'
            '<th class="pb-2 pr-3">Company</th>'
            '<th class="pb-2 pr-3">Location</th>'
            '<th class="pb-2 pr-3">Remote</th>'
            '<th class="pb-2 pr-3">Salary</th>'
            '<th class="pb-2 pr-3">Sector</th>'
            '<th class="pb-2">Source</th>'
            '</tr></thead>'
            f'<tbody>{rows_matched}</tbody>'
            '</table></div>'
        )

    rows_scrapers = ""
    for r in results:
        status_cls = "text-red-600" if r["error"] else "text-emerald-600"
        status_txt = "ERROR" if r["error"] else "OK"
        sample_rows = "".join(
            f'<tr class="border-t border-gray-100">'
            f'<td class="py-1 pr-3 text-gray-700">{esc(s["title"])}</td>'
            f'<td class="py-1 pr-3 text-gray-500">{esc(s["company"])}</td>'
            f'<td class="py-1 pr-3 text-gray-400 text-xs">{esc(s["location"])}</td>'
            f'<td class="py-1 text-xs"><a href="{esc(s["url"])}" target="_blank" '
            f'class="text-blue-600 hover:underline truncate block max-w-xs">{esc(s["url"])}</a></td>'
            f'</tr>'
            for s in r["samples"]
        )
        error_block = (
            f'<pre class="mt-2 text-xs bg-red-50 text-red-800 p-3 rounded overflow-x-auto">'
            f'{esc(r["error"])}</pre>' if r["error"] else ""
        )
        rows_scrapers += f"""
        <div class="border border-gray-200 rounded-xl p-4 mb-3 bg-white shadow-sm">
          <div class="flex items-center justify-between mb-1">
            <h3 class="font-semibold text-gray-800">{esc(r["name"])}</h3>
            <div class="flex items-center gap-3 text-sm">
              <span class="{status_cls} font-bold">{status_txt}</span>
              <span class="text-gray-500">{r["count"]} raw jobs</span>
              <span class="text-gray-400">{r["elapsed"]}s</span>
            </div>
          </div>
          {error_block}
          {"" if not r["samples"] else f'''
          <details class="mt-2">
            <summary class="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
              Show {len(r["samples"])} sample(s)
            </summary>
            <div class="overflow-x-auto mt-2">
              <table class="text-xs w-full">
                <thead><tr class="text-left text-gray-400">
                  <th class="pr-3">Title</th><th class="pr-3">Company</th>
                  <th class="pr-3">Location</th><th>URL</th>
                </tr></thead>
                <tbody>{sample_rows}</tbody>
              </table>
            </div>
          </details>'''}
        </div>"""

    rows_matched = ""
    score_colors = {5:"text-emerald-600",4:"text-blue-600",3:"text-amber-500",
                    2:"text-gray-500",1:"text-gray-400"}
    for j in matched[:50]:
        sc = "★" * j.score + "☆" * (5 - j.score)
        sc_cls = score_colors.get(j.score, "text-gray-400")
        sal = j.salary_text or (
            f"€{j.salary_min:,}–€{j.salary_max:,}" if j.salary_min and j.salary_max else "–"
        )
        rows_matched += f"""
        <tr class="border-t border-gray-100 hover:bg-gray-50">
          <td class="py-2 pr-3 font-bold {sc_cls} whitespace-nowrap">{esc(sc)}</td>
          <td class="py-2 pr-3">
            <a href="{esc(j.url)}" target="_blank"
               class="text-blue-600 hover:underline font-medium">{esc(j.title)}</a>
          </td>
          <td class="py-2 pr-3 text-gray-600">{esc(j.company)}</td>
          <td class="py-2 pr-3 text-gray-500 text-xs">{esc(j.location)}</td>
          <td class="py-2 pr-3 text-gray-500 text-xs">{esc(j.remote_policy)}
            {"(" + str(j.onsite_days) + "d)" if j.onsite_days else ""}</td>
          <td class="py-2 pr-3 text-gray-500 text-xs">{esc(sal)}</td>
          <td class="py-2 pr-3 text-gray-400 text-xs">{esc(j.sector)}</td>
          <td class="py-2 text-gray-400 text-xs">{esc(j.source)}</td>
        </tr>"""

    env_rows = "".join(
        f'<tr class="border-t border-gray-100">'
        f'<td class="py-1.5 pr-6 font-mono text-xs text-gray-600">{esc(k)}</td>'
        f'<td class="py-1.5 text-xs {"text-emerald-600" if ok else "text-red-600"}">'
        f'{esc(v)}</td></tr>'
        for k, (v, ok) in env_checks.items()
    )

    def _stat_card(value, label):
        return (
            f'<div class="bg-white border border-gray-200 rounded-xl p-3 '
            f'shadow-sm text-center">'
            f'<p class="text-2xl font-bold text-gray-800">{value}</p>'
            f'<p class="text-xs text-gray-400 mt-0.5">{label}</p>'
            f'</div>'
        )

    summary_cards = "".join([
        _stat_card(sum(r["count"] for r in results), "Raw jobs found"),
        _stat_card(len(matched),   "Passed filters"),
        _stat_card(skipped_seen,   "Already in DB"),
        _stat_card(skipped_filter, "Filtered out"),
    ])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Scraper Test – Job Search Agent</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 text-gray-900 antialiased">
<div class="max-w-5xl mx-auto px-4 py-8">

  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-2xl font-bold text-gray-900">🔬 Scraper Test</h1>
      <p class="text-sm text-gray-500 mt-0.5">
        Run at {datetime.now().strftime("%d %b %Y %H:%M:%S")} (local time)
      </p>
    </div>
    <a href="/" class="text-sm text-blue-600 hover:underline">← Dashboard</a>
  </div>

  <!-- Environment -->
  <section class="bg-white border border-gray-200 rounded-xl p-4 shadow-sm mb-6">
    <h2 class="font-semibold text-gray-700 mb-3">Environment</h2>
    <table class="text-sm"><tbody>{env_rows}</tbody></table>
  </section>

  <!-- Summary -->
  <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
    {summary_cards}
  </div>

  <!-- Per-scraper results -->
  <section class="mb-6">
    <h2 class="font-semibold text-gray-700 mb-3">Scrapers</h2>
    {rows_scrapers}
  </section>

  <!-- Matched jobs -->
  <section class="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
    <h2 class="font-semibold text-gray-700 mb-3">
      Matched Jobs ({len(matched)})
      <span class="text-xs font-normal text-gray-400 ml-1">
        – not saved to DB during test
        {f"– showing first 50" if len(matched) > 50 else ""}
      </span>
    </h2>
    {matched_table_html}
  </section>

  <p class="text-center text-xs text-gray-400 mt-6">
    <a href="/test-scraper" class="hover:underline">🔄 Run again</a>
    &nbsp;·&nbsp;
    <a href="/" class="hover:underline">Dashboard</a>
    &nbsp;·&nbsp;
    <a href="/settings" class="hover:underline">Settings</a>
  </p>
</div>
</body>
</html>"""

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


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
