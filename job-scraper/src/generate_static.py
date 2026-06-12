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
from .database import init_db, get_jobs_by_category, get_stats

DOCS_DIR = Path(__file__).parent.parent / "docs"


TARGET_ROLES_LOWER = {
    "hrbp", "hr business partner", "responsable rh", "responsable ressources humaines",
    "drh", "directeur rh", "directrice rh", "rrh", "head of people", "head of hr",
    "people manager", "people partner", "hr manager", "hr generalist", "rh généraliste",
    "people operations", "hr lead", "people lead", "vp people", "vp rh",
    "responsable formation", "talent", "chargé rh", "chargée rh",
}
REMOTE_TERMS = {"remote", "télétravail", "full remote", "distributed", "wfh"}
TECH_TERMS = {"startup", "saas", "tech", "ai", "fintech", "healthtech", "greentech", "scale-up", "scaleup"}
TOURS_TERMS = {"tours", "indre-et-loire", "touraine", "37"}


def rule_based_score(job: dict) -> float:
    """Fallback scorer using keyword rules, no API needed."""
    title = (job.get("title") or "").lower()
    company = (job.get("company") or "").lower()
    location = (job.get("location") or "").lower()
    remote = (job.get("remote_policy") or "").lower()
    description = (job.get("description") or "").lower()
    combined = f"{title} {company} {location} {description}"

    # Role match (0-3)
    role_score = 0
    if any(r in title for r in TARGET_ROLES_LOWER):
        role_score = 3
    elif any(r in combined for r in TARGET_ROLES_LOWER):
        role_score = 2
    elif any(w in title for w in ("rh", "hr", "people", "human resources", "ressources humaines")):
        role_score = 1

    # Location match (0-2)
    loc_score = 0
    if remote == "full" or any(t in combined for t in REMOTE_TERMS):
        loc_score = 2
    elif any(t in combined for t in TOURS_TERMS):
        loc_score = 2
    elif remote == "hybrid" or "hybride" in combined or "hybrid" in combined:
        loc_score = 1

    # Salary match (0-2): benefit of doubt if unknown
    sal_min = job.get("salary_min") or 0
    sal_score = 1  # default: unknown = benefit of doubt
    if sal_min >= 65000:
        sal_score = 2
    elif sal_min > 0 and sal_min < 45000:
        sal_score = 0

    # Company match (0-2)
    comp_score = 0
    if any(t in combined for t in TECH_TERMS):
        comp_score = 2
    else:
        comp_score = 1

    # Freshness (0-1)
    fresh_score = 0.5  # default: unknown date

    total = role_score + loc_score + sal_score + comp_score + fresh_score
    return round(min(10.0, total), 1)


def _apply_fallback_scores(jobs: list[dict]) -> list[dict]:
    """Apply rule_based_score() to any job that has no AI score."""
    for job in jobs:
        if job.get("score") is None:
            job["score"] = rule_based_score(job)
            job["score_estimated"] = True
        else:
            job["score_estimated"] = False
    return sorted(jobs, key=lambda j: (-(j.get("score") or 0), -(
        _parse_ts(j.get("posted_date")) or 0
    )))


def _parse_ts(date_str) -> float:
    """Parse an ISO date string to a Unix timestamp for sorting, or 0 on failure."""
    if not date_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


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
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
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
        return str(date_str)[:10] if date_str else "?"


def score_color(score: float) -> str:
    if score >= 8:
        return "#22c55e"   # green
    if score >= 6:
        return "#eab308"   # yellow
    return "#f97316"       # orange


def remote_badge(policy: str) -> str:
    badges = {
        "full":    '<span class="badge badge-remote">🌍 Full Remote</span>',
        "hybrid":  '<span class="badge badge-hybrid">🏢 Hybride</span>',
        "onsite":  '<span class="badge badge-onsite">📍 Présentiel</span>',
    }
    return badges.get(policy, '<span class="badge badge-unknown">❓ Non précisé</span>')


def job_card(job: dict, category: str) -> str:
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
            breakdown_lines += (
                f"<div class='bd-row'><span>{label}</span>"
                f"<span>{details[k]}/{'3' if k=='role_match' else '2' if k!='freshness' else '1'}</span></div>"
            )

    score_details_html = f"<div class='score-breakdown'>{breakdown_lines}</div>" if breakdown_lines else ""

    estimated = job.get("score_estimated", False)
    score_label = f"~{score:.0f}" if estimated else f"{score:.0f}"
    score_title = f"Score estimé {score}/10 (pas encore scoré par IA)" if estimated else f"Score IA {score}/10"

    # --- Category-specific extras ---
    extra_html = ""

    if category == "paris_hybrid":
        meta = json.loads(job.get("category_meta") or "{}")
        if not meta.get("paris_days_specified", True):
            extra_html = '<div class="extra-warning"><span class="warn-tag">⚠️ jours non précisés</span></div>'

    elif category == "full_remote":
        meta = json.loads(job.get("category_meta") or "{}")
        c1 = meta.get("remote_check1", False)
        c2 = meta.get("remote_check2", False)
        c3 = meta.get("remote_check3", False)

        def _chk(passed: bool, label: str) -> str:
            cls = "check pass" if passed else "check fail"
            symbol = "✓" if passed else "✗"
            return f'<span class="{cls}">{symbol} {label}</span>'

        extra_html = (
            '<div class="remote-checks">'
            + _chk(c1, "keyword")
            + _chk(c2, "no location")
            + _chk(c3, "AI vérifié")
            + "</div>"
        )

    return f"""
    <div class="job-card" data-score="{score}">
      <div class="card-left">
        <div class="score-badge" style="background:{color}" title="{score_title}">{score_label}</div>
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
        {extra_html}
        {score_details_html}
      </div>
      <div class="card-right">
        <div class="posted-date">{rel_date}</div>
        <a href="{job['url']}" target="_blank" rel="noopener" class="apply-btn">Postuler →</a>
      </div>
    </div>"""


def section_html(title: str, emoji: str, color: str, category: str, jobs: list[dict]) -> str:
    if not jobs:
        return f"""
    <section class="section">
      <h2 class="section-title" style="color:{color}">{emoji} {title} <span class="count">0</span></h2>
      <div class="empty-section">Aucune offre dans cette catégorie aujourd'hui.</div>
    </section>"""

    cards = "\n".join(job_card(j, category) for j in jobs)
    return f"""
    <section class="section">
      <h2 class="section-title" style="color:{color}">{emoji} {title} <span class="count">{len(jobs)}</span></h2>
      {cards}
    </section>"""


def build_html(tours: list, paris: list, remote: list, total_db: int, generated_at: datetime) -> str:
    gen_str = generated_at.strftime("%d/%m/%Y à %H:%M UTC")

    sections = (
        section_html("Tours & Indre-et-Loire", "📍", "#22c55e", "tours", tours)
        + section_html("Paris — Hybride (max 3j/sem)", "🏙️", "#eab308", "paris_hybrid", paris)
        + section_html("Full Remote", "🌍", "#3b82f6", "full_remote", remote)
    )

    total_shown = len(tours) + len(paris) + len(remote)

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

  .extra-warning {{ margin-top: 6px; }}
  .warn-tag {{ font-size: 0.72rem; padding: 2px 8px; border-radius: 6px; background: #431407; color: #fdba74; font-weight: 600; }}

  .remote-checks {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }}
  .check {{ font-size: 0.72rem; padding: 2px 8px; border-radius: 6px; font-weight: 600; }}
  .check.pass {{ background: #14532d; color: #86efac; }}
  .check.fail  {{ background: #3b1f1f; color: #fca5a5; }}

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
    <strong>{total_shown} offres filtrées</strong>
    Mis à jour le {gen_str}
  </div>
</header>

<div class="stats-bar">
  <div class="stat"><div class="stat-num" style="color:var(--text)">{total_db}</div><div class="stat-label">Trouvées</div></div>
  <div class="stat"><div class="stat-num" style="color:var(--green)">{len(tours)}</div><div class="stat-label">Tours</div></div>
  <div class="stat"><div class="stat-num" style="color:var(--yellow)">{len(paris)}</div><div class="stat-label">Paris hybride</div></div>
  <div class="stat"><div class="stat-num" style="color:var(--blue)">{len(remote)}</div><div class="stat-label">Full remote</div></div>
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

    tours = _apply_fallback_scores(await get_jobs_by_category("tours", db_path))
    paris = _apply_fallback_scores(await get_jobs_by_category("paris_hybrid", db_path))
    remote = _apply_fallback_scores(await get_jobs_by_category("full_remote", db_path))

    stats = await get_stats(db_path)
    total_db = stats.get("total", 0)

    now = datetime.now(timezone.utc)
    html = build_html(tours, paris, remote, total_db, now)

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Static site generated: {out} ({len(tours)} tours, {len(paris)} paris, {len(remote)} remote)")
    return out


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    asyncio.run(generate(db))
