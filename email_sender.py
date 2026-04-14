"""Email digest sender – SMTP with Gmail App Password."""
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, RECIPIENT_EMAIL,
)
from scorer import Job

log = logging.getLogger(__name__)

SCORE_LABELS = {
    5: "★★★★★ Exceptional match",
    4: "★★★★☆ Great match",
    3: "★★★☆☆ Good match",
    2: "★★☆☆☆ Decent match",
    1: "★☆☆☆☆ Minimum threshold",
}

SCORE_COLORS = {5: "#1a7f37", 4: "#3b82f6", 3: "#f59e0b", 2: "#6b7280", 1: "#9ca3af"}


def _salary_display(job: Job) -> str:
    if job.salary_text:
        return job.salary_text
    if job.salary_min and job.salary_max:
        return f"€{job.salary_min:,} – €{job.salary_max:,}"
    if job.salary_min:
        return f"From €{job.salary_min:,}"
    if job.salary_max:
        return f"Up to €{job.salary_max:,}"
    return "Not specified"


def _remote_display(job: Job) -> str:
    if job.remote_policy == "remote":
        return "Full remote"
    if job.remote_policy == "hybrid":
        days = job.onsite_days
        return f"Hybrid ({days} day{'s' if days != 1 else ''}/week on-site)" if days else "Hybrid"
    if job.remote_policy == "onsite":
        return "On-site"
    return "Unknown"


def _build_html(jobs: List[Job], run_time: str) -> str:
    by_score: dict[int, list[Job]] = {}
    for j in jobs:
        by_score.setdefault(j.score, []).append(j)

    sections = []
    for score in sorted(by_score.keys(), reverse=True):
        label = SCORE_LABELS.get(score, f"Score {score}")
        color = SCORE_COLORS.get(score, "#6b7280")
        cards = []
        for j in by_score[score]:
            salary  = _salary_display(j)
            remote  = _remote_display(j)
            posted  = j.date_posted or "Unknown"
            sector  = j.sector or "–"
            cards.append(f"""
            <div style="border:1px solid #e5e7eb;border-radius:8px;padding:16px;
                        margin-bottom:12px;background:#fff;">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                  <h3 style="margin:0 0 4px;font-size:16px;color:#111827;">
                    <a href="{j.url}" style="color:#1d4ed8;text-decoration:none;">
                      {j.title}
                    </a>
                  </h3>
                  <p style="margin:0;font-size:14px;color:#4b5563;font-weight:600;">
                    {j.company}
                  </p>
                </div>
                <span style="background:{color};color:#fff;padding:2px 8px;
                             border-radius:12px;font-size:12px;white-space:nowrap;">
                  Score {score}/5
                </span>
              </div>
              <table style="margin-top:10px;width:100%;font-size:13px;color:#374151;
                            border-collapse:collapse;">
                <tr>
                  <td style="padding:2px 8px 2px 0;white-space:nowrap;">
                    <strong>📍 Location</strong>
                  </td>
                  <td>{j.location}</td>
                </tr>
                <tr>
                  <td style="padding:2px 8px 2px 0;white-space:nowrap;">
                    <strong>🏠 Remote</strong>
                  </td>
                  <td>{remote}</td>
                </tr>
                <tr>
                  <td style="padding:2px 8px 2px 0;white-space:nowrap;">
                    <strong>💰 Salary</strong>
                  </td>
                  <td>{salary}</td>
                </tr>
                <tr>
                  <td style="padding:2px 8px 2px 0;white-space:nowrap;">
                    <strong>🏭 Sector</strong>
                  </td>
                  <td>{sector}</td>
                </tr>
                <tr>
                  <td style="padding:2px 8px 2px 0;white-space:nowrap;">
                    <strong>📅 Posted</strong>
                  </td>
                  <td>{posted}</td>
                </tr>
                <tr>
                  <td style="padding:2px 8px 2px 0;white-space:nowrap;">
                    <strong>🔗 Source</strong>
                  </td>
                  <td>{j.source}</td>
                </tr>
              </table>
              <a href="{j.url}"
                 style="display:inline-block;margin-top:10px;padding:7px 14px;
                        background:#1d4ed8;color:#fff;border-radius:6px;
                        text-decoration:none;font-size:13px;">
                Apply →
              </a>
            </div>""")

        sections.append(f"""
        <div style="margin-bottom:28px;">
          <h2 style="font-size:18px;color:{color};margin:0 0 12px;padding:8px 12px;
                     background:#f9fafb;border-left:4px solid {color};border-radius:2px;">
            {label} &nbsp;
            <span style="font-size:14px;font-weight:normal;color:#6b7280;">
              ({len(by_score[score])} job{'s' if len(by_score[score])!=1 else ''})
            </span>
          </h2>
          {''.join(cards)}
        </div>""")

    total = len(jobs)
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Search Digest</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             background:#f3f4f6;margin:0;padding:20px;">
  <div style="max-width:680px;margin:0 auto;">
    <div style="background:#1d4ed8;color:#fff;padding:24px;border-radius:8px 8px 0 0;">
      <h1 style="margin:0;font-size:22px;">🔍 Job Search Digest</h1>
      <p style="margin:6px 0 0;opacity:.85;font-size:14px;">
        {run_time} &nbsp;·&nbsp; {total} new matching job{'s' if total!=1 else ''} found
      </p>
    </div>
    <div style="background:#f9fafb;padding:20px;border-radius:0 0 8px 8px;">
      {''.join(sections) if sections else '<p style="color:#6b7280;">No new jobs found in this run.</p>'}
    </div>
    <p style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px;">
      Automated digest · Job Search Agent · Unsubscribe by stopping the cron job
    </p>
  </div>
</body>
</html>"""


def _build_plain(jobs: List[Job], run_time: str) -> str:
    lines = [
        f"Job Search Digest – {run_time}",
        f"{len(jobs)} new matching job(s) found",
        "=" * 60,
    ]
    by_score: dict[int, list[Job]] = {}
    for j in jobs:
        by_score.setdefault(j.score, []).append(j)

    for score in sorted(by_score.keys(), reverse=True):
        lines.append(f"\n{'=' * 60}")
        lines.append(SCORE_LABELS.get(score, f"Score {score}"))
        lines.append("=" * 60)
        for j in by_score[score]:
            lines += [
                f"\n{j.title} @ {j.company}",
                f"  Location : {j.location}",
                f"  Remote   : {_remote_display(j)}",
                f"  Salary   : {_salary_display(j)}",
                f"  Sector   : {j.sector or '–'}",
                f"  Posted   : {j.date_posted or 'Unknown'}",
                f"  Source   : {j.source}",
                f"  Apply    : {j.url}",
            ]
    return "\n".join(lines)


def send_digest(jobs: List[Job]) -> None:
    """Send the email digest. Raises on SMTP error."""
    if not SMTP_USER or not SMTP_PASSWORD:
        log.error(
            "SMTP_USER / SMTP_PASSWORD not set – skipping email. "
            "Set them in your .env file."
        )
        return

    run_time = datetime.now().strftime("%d %b %Y %H:%M")
    subject  = (
        f"[Job Agent] {len(jobs)} new HR job{'s' if len(jobs)!=1 else ''} "
        f"– {run_time}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = RECIPIENT_EMAIL

    plain = _build_plain(jobs, run_time)
    html  = _build_html(jobs, run_time)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))

    log.info("Sending digest to %s (%d jobs)…", RECIPIENT_EMAIL, len(jobs))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, RECIPIENT_EMAIL, msg.as_string())
    log.info("Digest sent successfully.")
