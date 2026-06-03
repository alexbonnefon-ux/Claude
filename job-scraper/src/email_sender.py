"""
HTML email digest sender for job results.
Supports Gmail SMTP with App Password.
"""
import json
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List
from loguru import logger

from .config import (
    GMAIL_USER,
    GMAIL_APP_PASSWORD,
    RECIPIENT_EMAIL,
    SENDGRID_API_KEY,
)


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------

EMAIL_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; color: #333; }
.wrapper { max-width: 680px; margin: 0 auto; background: #fff; }
.header { background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%); color: white; padding: 32px 24px; text-align: center; }
.header h1 { margin: 0 0 8px 0; font-size: 24px; font-weight: 700; }
.header p { margin: 0; opacity: 0.85; font-size: 14px; }
.stats-bar { background: #e8f0fe; padding: 16px 24px; display: flex; gap: 24px; justify-content: center; flex-wrap: wrap; }
.stat { text-align: center; }
.stat-number { font-size: 28px; font-weight: 700; color: #1a73e8; }
.stat-label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }
.section { padding: 24px; }
.section-title { font-size: 18px; font-weight: 700; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 2px solid; }
.section-top .section-title { color: #137333; border-color: #34a853; }
.section-good .section-title { color: #b5770d; border-color: #fbbc04; }
.section-worth .section-title { color: #c5221f; border-color: #ea4335; }
.job-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin-bottom: 12px; background: #fafafa; }
.job-card:hover { border-color: #1a73e8; }
.job-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.job-title { font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 0 0 4px 0; }
.job-company { font-size: 14px; color: #555; margin: 0; }
.score-badge { flex-shrink: 0; width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; color: white; }
.score-green { background: #137333; }
.score-yellow { background: #b5770d; }
.score-orange { background: #e37400; }
.badges { margin: 8px 0; display: flex; flex-wrap: wrap; gap: 6px; }
.badge { font-size: 11px; padding: 3px 8px; border-radius: 12px; font-weight: 500; }
.badge-location { background: #e8f0fe; color: #1a73e8; }
.badge-remote-full { background: #e6f4ea; color: #137333; }
.badge-remote-hybrid { background: #fef7e0; color: #b5770d; }
.badge-remote-onsite { background: #fce8e6; color: #c5221f; }
.badge-salary { background: #f3e8fd; color: #7b1fa2; }
.badge-source { background: #f1f3f4; color: #555; }
.job-description { font-size: 13px; color: #666; margin: 8px 0; line-height: 1.5; }
.job-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; }
.job-date { font-size: 12px; color: #999; }
.apply-btn { background: #1a73e8; color: white; text-decoration: none; padding: 8px 16px; border-radius: 4px; font-size: 13px; font-weight: 500; }
.apply-btn:hover { background: #1557b0; }
.explanation { font-size: 12px; color: #555; font-style: italic; margin: 8px 0 0 0; padding: 8px; background: #f8f9fa; border-left: 3px solid #dadce0; border-radius: 0 4px 4px 0; }
.no-jobs { text-align: center; padding: 24px; color: #999; font-style: italic; }
.footer { background: #f8f9fa; padding: 20px 24px; text-align: center; font-size: 12px; color: #999; border-top: 1px solid #e0e0e0; }
.divider { height: 1px; background: #e0e0e0; margin: 0 24px; }
"""


def _score_badge_class(score: float) -> str:
    if score >= 8:
        return "score-green"
    elif score >= 6:
        return "score-yellow"
    return "score-orange"


def _remote_badge(remote_policy: str) -> str:
    labels = {
        "full": ("100% Remote", "badge-remote-full"),
        "hybrid": ("Hybride", "badge-remote-hybrid"),
        "onsite": ("Présentiel", "badge-remote-onsite"),
        "unknown": ("Remote ?", "badge-source"),
    }
    label, css = labels.get(remote_policy, ("?", "badge-source"))
    return f'<span class="badge {css}">{label}</span>'


def _salary_badge(job: dict) -> str:
    sal_min = job.get("salary_min")
    sal_max = job.get("salary_max")
    if not sal_min and not sal_max:
        return ""
    if sal_min and sal_max:
        text = f"€{sal_min // 1000}K – €{sal_max // 1000}K"
    elif sal_min:
        text = f"≥ €{sal_min // 1000}K"
    else:
        text = f"≤ €{sal_max // 1000}K"
    if job.get("salary_estimated"):
        text += " ~"
    return f'<span class="badge badge-salary">{text}</span>'


def _format_date(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y")
    except Exception:
        return date_str[:10]


def _source_label(source: str) -> str:
    labels = {
        "france_travail": "France Travail",
        "indeed_rss": "Indeed",
        "hellowork": "HelloWork",
        "linkedin_rss": "LinkedIn",
        "ats_platforms": "ATS",
        "startup_careers": "Startups",
        "public_sector": "Secteur Public",
    }
    return labels.get(source, source.replace("_", " ").title())


def _render_job_card(job: dict) -> str:
    score = job.get("score") or 0
    score_details = {}
    details_raw = job.get("score_details")
    if details_raw:
        try:
            score_details = json.loads(details_raw) if isinstance(details_raw, str) else details_raw
        except Exception:
            pass

    explanation = score_details.get("explanation", "")
    red_flags = score_details.get("red_flags", "")

    badge_cls = _score_badge_class(score)
    remote_badge = _remote_badge(job.get("remote_policy", "unknown"))
    salary_badge = _salary_badge(job)
    source_badge = f'<span class="badge badge-source">{_source_label(job.get("source", ""))}</span>'
    location_badge = f'<span class="badge badge-location">📍 {job.get("location", "")[:40]}</span>' if job.get("location") else ""

    description = (job.get("description") or "")[:200]
    if description and len(job.get("description", "")) > 200:
        description += "…"

    explanation_html = ""
    if explanation:
        explanation_html = f'<p class="explanation">💡 {explanation}</p>'
    if red_flags:
        explanation_html += f'<p class="explanation" style="border-left-color:#ea4335;">⚠️ {red_flags}</p>'

    return f"""
    <div class="job-card">
      <div class="job-header">
        <div>
          <p class="job-title">{job.get('title', '')}</p>
          <p class="job-company">{job.get('company', '')}</p>
        </div>
        <div class="score-badge {badge_cls}">{score:.1f}</div>
      </div>
      <div class="badges">
        {location_badge}
        {remote_badge}
        {salary_badge}
        {source_badge}
      </div>
      {"<p class='job-description'>" + description + "</p>" if description else ""}
      {explanation_html}
      <div class="job-footer">
        <span class="job-date">Publié le {_format_date(job.get('posted_date', ''))}</span>
        <a href="{job.get('url', '#')}" class="apply-btn" target="_blank">Postuler →</a>
      </div>
    </div>
    """


def _render_section(title: str, css_class: str, jobs: List[dict], emoji: str) -> str:
    if not jobs:
        no_jobs = '<p class="no-jobs">Aucune offre dans cette catégorie aujourd\'hui.</p>'
        cards = no_jobs
    else:
        cards = "\n".join(_render_job_card(j) for j in jobs)

    return f"""
    <div class="section {css_class}">
      <h2 class="section-title">{emoji} {title} ({len(jobs)})</h2>
      {cards}
    </div>
    """


def build_html_email(jobs: List[dict], run_date: datetime) -> str:
    """Build the full HTML email from a list of scored job dicts."""
    top_picks = [j for j in jobs if (j.get("score") or 0) >= 8]
    good_matches = [j for j in jobs if 6 <= (j.get("score") or 0) < 8]
    worth_checking = [j for j in jobs if 4 <= (j.get("score") or 0) < 6]

    date_str = run_date.strftime("%A %-d %B %Y").capitalize()
    total = len(jobs)

    stats_html = f"""
    <div class="stats-bar">
      <div class="stat"><div class="stat-number">{total}</div><div class="stat-label">Offres trouvées</div></div>
      <div class="stat"><div class="stat-number">{len(top_picks)}</div><div class="stat-label">Top picks (8+)</div></div>
      <div class="stat"><div class="stat-number">{len(good_matches)}</div><div class="stat-label">Bons matchs (6-7)</div></div>
      <div class="stat"><div class="stat-number">{len(worth_checking)}</div><div class="stat-label">À explorer (4-5)</div></div>
    </div>
    """

    sections = (
        _render_section("Top Picks", "section-top", top_picks, "🎯") +
        '<div class="divider"></div>' +
        _render_section("Bons Matchs", "section-good", good_matches, "👍") +
        '<div class="divider"></div>' +
        _render_section("À Explorer", "section-worth", worth_checking, "🔍")
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Offres RH – {date_str}</title>
  <style>{EMAIL_CSS}</style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>🎯 {total} nouvelles offres RH</h1>
      <p>{date_str} · Bonjour Alexis !</p>
    </div>
    {stats_html}
    {sections}
    <div class="footer">
      <p>Ce digest est généré automatiquement chaque matin par votre job scraper personnel.<br>
      Les scores sont calculés par IA en fonction de votre profil (Tours / Remote / Salaire).<br>
      <em>Job Scraper · Tours, France</em></p>
    </div>
  </div>
</body>
</html>"""


def send_email(jobs: List[dict], run_date: datetime) -> bool:
    """
    Send the HTML digest email via Gmail SMTP.
    Falls back to SendGrid if SENDGRID_API_KEY is set.
    Returns True on success, False on failure.
    """
    if not jobs:
        logger.info("No jobs to send, skipping email")
        return True

    html_body = build_html_email(jobs, run_date)
    total = len(jobs)
    subject = f"🎯 {total} nouvelles offres RH - {run_date.strftime('%-d %b %Y')}"

    # Try Gmail first
    if GMAIL_USER and GMAIL_APP_PASSWORD:
        return _send_via_gmail(subject, html_body)

    # Fallback to SendGrid
    if SENDGRID_API_KEY:
        return _send_via_sendgrid(subject, html_body)

    logger.error("No email credentials configured (GMAIL_USER/GMAIL_APP_PASSWORD or SENDGRID_API_KEY)")
    return False


def _send_via_gmail(subject: str, html_body: str) -> bool:
    """Send email via Gmail SMTP using an App Password."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL

    # Plain text fallback
    plain = "Ouvrez cet email dans un client compatible HTML pour voir les offres d'emploi RH."
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        logger.info("Email sent successfully to {} via Gmail", RECIPIENT_EMAIL)
        return True
    except Exception as exc:
        logger.error("Gmail SMTP error: {}", exc)
        return False


def _send_via_sendgrid(subject: str, html_body: str) -> bool:
    """Send email via SendGrid HTTP API."""
    try:
        import httpx
        payload = {
            "personalizations": [{"to": [{"email": RECIPIENT_EMAIL}]}],
            "from": {"email": GMAIL_USER or "noreply@jobscraper.local", "name": "Job Scraper"},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}],
        }
        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=30.0,
        )
        if resp.status_code in (200, 202):
            logger.info("Email sent successfully to {} via SendGrid", RECIPIENT_EMAIL)
            return True
        else:
            logger.error("SendGrid returned status {}: {}", resp.status_code, resp.text[:200])
            return False
    except Exception as exc:
        logger.error("SendGrid error: {}", exc)
        return False
