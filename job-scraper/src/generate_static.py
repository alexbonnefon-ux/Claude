"""
Generate a self-contained static index.html from the jobs database.
Called by the GitHub Actions workflow after scraping to produce the
GitHub Pages dashboard.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH
from .database import init_db, get_stats

DOCS_DIR = Path(__file__).parent.parent / "docs"


async def load_jobs(db_path: str = DB_PATH) -> list[dict]:
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM jobs
            WHERE score IS NOT NULL AND score >= 4
            ORDER BY score DESC, posted_date DESC
        """)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


def salary_display(job: dict) -> str:
    lo, hi = job.get("salary_min"), job.get("salary_max")
    est = job.get("salary_estimated", 0)
    prefix = "~" if est else ""
    if lo and hi:
        return f"{prefix}{lo//1000}–{hi//1000}k€"
    if lo:
        return f"{prefix}{lo//1000}k€+"
    return "N/A"


def relative_date(date_str: str | None) -> str:
    if not date_str:
        return "Date inconnue"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (now - dt).days
        if delta == 0:
            return "Aujourd'hui"
        if delta == 1:
            return "Hier"
        if delta <= 7:
            return f"Il y a {delta} jours"
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return date_str[:10] if date_str else "?"


def score_color(score: float) -> str:
    if score >= 8:
        return "#22c55e"   # green
    if score >= 6:
        return "#eab308"   # yellow
    return "#f97316"       # orange


def remote_badge(policy: str) -> str:
    badges = {
        "full":    ('<span class="badge badge-remote">🌍 Full Remote</span>', ),
        "hybrid":  ('<span class="badge badge-hybrid">🏢 Hybride</span>', ),
        "onsite":  ('<span class="badge badge-onsite">📍 Présentiel</span>', ),
    }
    return badges.get(policy, ('<span class="badge badge-unknown">❓ Non précisé</span>', ))[0]


def job_card(job: dict) -> str:
    score = job.get("score") or 0
    details = json.loads(job.get("score_details") or "{}")
    color = score_color(score)
    sal = salary_display(job)
    rel_date = relative_date(job.get("posted_date"))
    remote = remote_badge(job.get("remote_policy", "unknown"))

    breakdown_lines = ""
    label_map = {
        "role_match": "Rôle",
        "location_match": "Lieu",
        "salary_match": "Salaire",
        "company_match": "Entreprise",
        "freshness": "Fraîcheur",
    }
    for k, label in label_map.items():
        if k in details:
            breakdown_lines += f"<div class='bd-row'><span>{label}</span><span>{details[k]}/{'3' if k=='role_match' else '2' if k!='freshness' else '1'}</span></div>"

    score_details_html = f"<div class='score-breakdown'>{breakdown_lines}</div>" if breakdown_lines else ""

    return f"""
    <div class="job-card" data-score="{score}">
      <div class="card-left">
        <div class="score-badge" style="background:{color}" title="Score {score}/10">{score:.0f}</div>
      </div>
      <div class="card-body">
        <div class="job-title">{job['title']}</div>
        <div class="job-company">{job['company']}</div>
        <div class="job-meta">
          <span class="badge badge-location">📍 {job['location']}</span>
          {remote}
          <span class="badge badge-salary">💶 {sal}</span>
          <span class="badge badge-source">{job['source']}</span>
        </div>
        {score_details_html}
      </div>
      <div class="card-right">
        <div class="posted-date">{rel_date}</div>
        <a href="{job['url']}" target="_blank" rel="noopener" class="apply-btn">Postuler →</a>
      </div>
    </div>"""


def section_html(title: str, emoji: str, color: str, jobs: list[dict]) -> str:
    if not jobs:
        return f"""
    <section class="section">
      <h2 class="section-title" style="color:{color}">{emoji} {title} <span class="count">0</span></h2>
      <div class="empty-section">Aucune offre dans cette catégorie aujourd'hui.</div>
    </section>"""

    cards = "\n".join(job_card(j) for j in jobs)
    return f"""
    <section class="section">
      <h2 class="section-title" style="color:{color}">{emoji} {title} <span class="count">{len(jobs)}</span></h2>
      {cards}
    </section>"""


def build_html(jobs: list[dict], stats: dict, generated_at: datetime) -> str:
    top     = [j for j in jobs if (j.get("score") or 0) >= 8]
    good    = [j for j in jobs if 6 <= (j.get("score") or 0) < 8]
    worth   = [j for j in jobs if 4 <= (j.get("score") or 0) < 6]

    total_db = stats.get("total", 0)
    gen_str  = generated_at.strftime("%d/%m/%Y à %H:%M UTC")

    sections = (
        section_html("Top Picks", "🏆", "#22c55e", top) +
        section_html("Bons Matchs", "✅", "#eab308", good) +
        section_html("À Surveiller", "👀", "#f97316", worth)
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🎯 HR Job Radar – Alexis Bonnefon</title>
<style>
  :root {{
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #f1f5f9; --muted: #94a3b8;
    --green: #22c55e; --yellow: #eab308; --orange: #f97316;
    --blue: #3b82f6;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; }}

  header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 24px 32px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; }}
  .header-left h1 {{ font-size: 1.6rem; font-weight: 700; }}
  .header-left p {{ color: var(--muted); margin-top: 4px; font-size: 0.9rem; }}
  .header-right {{ text-align: right; font-size: 0.85rem; color: var(--muted); }}
  .header-right strong {{ color: var(--text); display: block; font-size: 1rem; margin-bottom: 4px; }}

  .stats-bar {{ display: flex; gap: 16px; padding: 20px 32px; flex-wrap: wrap; }}
  .stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 20px; flex: 1; min-width: 120px; text-align: center; }}
  .stat-num {{ font-size: 1.8rem; font-weight: 700; }}
  .stat-label {{ font-size: 0.75rem; color: var(--muted); margin-top: 2px; text-transform: uppercase; letter-spacing: .05em; }}

  .trigger-bar {{ padding: 0 32px 20px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
  .trigger-note {{ font-size: 0.85rem; color: var(--muted); }}
  .trigger-link {{ display: inline-flex; align-items: center; gap: 6px; background: var(--blue); color: #fff; text-decoration: none; padding: 8px 18px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; transition: opacity .15s; }}
  .trigger-link:hover {{ opacity: .85; }}

  main {{ padding: 0 32px 48px; max-width: 1000px; margin: 0 auto; }}

  .section {{ margin-bottom: 40px; }}
  .section-title {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }}
  .count {{ background: var(--border); color: var(--muted); border-radius: 999px; padding: 2px 10px; font-size: 0.8rem; font-weight: 600; }}
  .empty-section {{ color: var(--muted); font-style: italic; padding: 20px; background: var(--surface); border-radius: 10px; border: 1px dashed var(--border); text-align: center; }}

  .job-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; margin-bottom: 12px; display: flex; gap: 16px; align-items: flex-start; transition: border-color .15s; }}
  .job-card:hover {{ border-color: var(--blue); }}

  .card-left {{ flex-shrink: 0; }}
  .score-badge {{ width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 1.25rem; font-weight: 800; color: #0f172a; cursor: default; }}

  .card-body {{ flex: 1; min-width: 0; }}
  .job-title {{ font-size: 1rem; font-weight: 600; margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .job-company {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 8px; }}
  .job-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}

  .badge {{ font-size: 0.75rem; padding: 3px 8px; border-radius: 6px; font-weight: 500; white-space: nowrap; }}
  .badge-location {{ background: #1e3a5f; color: #93c5fd; }}
  .badge-remote   {{ background: #14532d; color: #86efac; }}
  .badge-hybrid   {{ background: #3b2f00; color: #fde68a; }}
  .badge-onsite   {{ background: #3b1f1f; color: #fca5a5; }}
  .badge-unknown  {{ background: #1e1e2e; color: var(--muted); }}
  .badge-salary   {{ background: #1a2e1a; color: #86efac; }}
  .badge-source   {{ background: #1e1e2e; color: var(--muted); }}

  .score-breakdown {{ margin-top: 8px; display: none; background: #0f1a2b; border-radius: 8px; padding: 8px 12px; font-size: 0.78rem; color: var(--muted); }}
  .job-card:hover .score-breakdown {{ display: block; }}
  .bd-row {{ display: flex; justify-content: space-between; padding: 2px 0; }}

  .card-right {{ flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }}
  .posted-date {{ font-size: 0.78rem; color: var(--muted); white-space: nowrap; }}
  .apply-btn {{ display: inline-block; background: var(--blue); color: #fff; text-decoration: none; padding: 7px 14px; border-radius: 8px; font-size: 0.82rem; font-weight: 600; white-space: nowrap; transition: opacity .15s; }}
  .apply-btn:hover {{ opacity: .85; }}

  footer {{ text-align: center; padding: 24px; color: var(--muted); font-size: 0.8rem; border-top: 1px solid var(--border); }}

  @media (max-width: 600px) {{
    header, .stats-bar, .trigger-bar, main {{ padding-left: 16px; padding-right: 16px; }}
    .card-right {{ display: none; }}
    .job-title {{ white-space: normal; }}
    .apply-btn-mobile {{ display: block; margin-top: 8px; }}
  }}
</style>
</head>
<body>

<header>
  <div class="header-left">
    <h1>🎯 HR Job Radar</h1>
    <p>Alexis Bonnefon · Tours, France · Offres HRBP, DRH, People Manager</p>
  </div>
  <div class="header-right">
    <strong>{len(jobs)} offres filtrées</strong>
    Mis à jour le {gen_str}
  </div>
</header>

<div class="stats-bar">
  <div class="stat"><div class="stat-num" style="color:var(--text)">{total_db}</div><div class="stat-label">Trouvées</div></div>
  <div class="stat"><div class="stat-num" style="color:var(--green)">{len(top)}</div><div class="stat-label">Top Picks</div></div>
  <div class="stat"><div class="stat-num" style="color:var(--yellow)">{len(good)}</div><div class="stat-label">Bons matchs</div></div>
  <div class="stat"><div class="stat-num" style="color:var(--orange)">{len(worth)}</div><div class="stat-label">À surveiller</div></div>
</div>

<div class="trigger-bar">
  <span class="trigger-note">⏰ Mis à jour automatiquement chaque matin à 8h (heure de Paris)</span>
  <a class="trigger-link" href="https://github.com/alexbonnefon-ux/Claude/actions/workflows/daily_scraper.yml" target="_blank" rel="noopener">
    ▶ Lancer maintenant
  </a>
</div>

<main>
{sections}
</main>

<footer>
  Généré le {gen_str} · <a href="https://github.com/alexbonnefon-ux/Claude" style="color:var(--blue)">Code source</a>
</footer>

</body>
</html>"""


async def generate(db_path: str = DB_PATH, output_dir: Path = DOCS_DIR) -> Path:
    await init_db(db_path)
    jobs = await load_jobs(db_path)
    stats = await get_stats(db_path)
    now = datetime.now(timezone.utc)
    html = build_html(jobs, stats, now)

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Static site generated: {out} ({len(jobs)} jobs)")
    return out


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    asyncio.run(generate(db))
