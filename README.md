# Job Search Agent

Automated job search agent for senior HR/People roles in France and EMEA.
Scrapes multiple job boards twice a day and displays results in a local web dashboard.

---

## Features

- **Multi-source scraping** – Greenhouse, Lever, Ashby, LinkedIn, Welcome to the Jungle, and direct career pages (Apple, Google, Meta, Microsoft, Samsung, Adobe)
- **Smart filtering** – job titles, location rules (remote/hybrid/on-site), salary floor, sector, excluded keywords
- **Relevance scoring** – 1–5 stars based on salary, remote policy, sector fit, seniority
- **Deduplication** – SQLite database prevents re-showing already-seen jobs
- **Web dashboard** – live feed, history view, mark-as-applied / ignore buttons
- **Settings UI** – edit all search criteria without touching code
- **APScheduler** – auto-runs at 08:00 and 18:00 Paris time while the app is running

---

## Quick Start

### 1 – Clone and install

```bash
git clone <repo-url>
cd job_search_agent

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2 – Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
# Optional – only needed if you want LinkedIn scraping to work better
LINKEDIN_EMAIL=your@email.com
LINKEDIN_PASSWORD=yourpassword

# Delay between HTTP requests (be polite to servers)
REQUEST_DELAY=2.0
```

> **No email setup needed.** Results appear directly in the web dashboard.

### 3 – Start the web dashboard

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

The first time you visit, click **Run Now** to trigger an immediate scrape.

---

## Usage

### Dashboard (`/`)

| Element | Description |
|---|---|
| Status cards | Last scrape time · jobs found today · next scheduled run |
| **Run Now** | Triggers an immediate scrape in the background |
| Search / filter | Filter cards by keyword or minimum score |
| **Apply →** | Opens the job application in a new tab |
| **✓** | Marks job as applied (removes from live feed) |
| **✕** | Ignores job (removes from live feed) |

### History (`/history`)

Shows all jobs found in the past 30 days (configurable). Filter by company, score, status, or date range. Undo applied/ignored from here.

### Settings (`/settings`)

Change any search criteria live — no restart needed:

- **Job Titles** – add or remove titles to match
- **Salary** – minimum and target range
- **Location** – max on-site days, lookback window
- **Excluded keywords** – title and description filters
- **Schedule** – two daily run times (Paris time)
- **Companies** – toggle or add companies per ATS (Greenhouse / Lever / Ashby)

---

## Running without the web UI (CLI)

```bash
python main.py
```

Results print to the terminal, grouped by relevance score.

---

## Scheduling (server / always-on machine)

APScheduler runs inside the Flask process, so the schedule is active as long as `app.py` is running.

For a server deployment, use a process manager:

**systemd** (`/etc/systemd/system/job-agent.service`):
```ini
[Unit]
Description=Job Search Agent
After=network.target

[Service]
WorkingDirectory=/path/to/job_search_agent
ExecStart=/path/to/venv/bin/python app.py
Restart=on-failure
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now job-agent
```

**Or** keep using the old cron wrapper for CLI-only mode:
```bash
./setup_cron.sh   # adds cron jobs at 08:00 and 18:00 Paris time
```

---

## Project Structure

```
job_search_agent/
├── app.py               Flask web app + routes
├── scheduler.py         APScheduler (08:00 & 18:00 Paris time)
├── main.py              Core pipeline (CLI entry point)
├── config.py            Static defaults (locations, user-agent…)
├── settings_db.py       Dynamic settings read/write (SQLite)
├── database.py          Job storage, history, stats
├── scorer.py            Job enrichment + 1–5 relevance score
├── scrapers/
│   ├── greenhouse.py    Greenhouse public API
│   ├── lever.py         Lever public API
│   ├── ashby.py         Ashby __NEXT_DATA__ JSON
│   ├── linkedin.py      LinkedIn (Selenium)
│   ├── welcome_jungle.py Algolia API + HTML fallback
│   └── career_pages.py  Apple, Google, Meta, Microsoft, Samsung, Adobe
├── templates/
│   ├── base.html        Navigation, toast, layout
│   ├── index.html       Live feed dashboard
│   ├── history.html     30-day history table
│   └── settings.html    Settings panel
├── static/
│   └── app.js           Shared JS (Run Now, status updates, toasts)
├── jobs.db              SQLite database (auto-created)
├── agent.log            Scraper log file (auto-created)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Notes on LinkedIn

LinkedIn actively blocks automated access. The Selenium scraper works best when:
- `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` are set in `.env`
- A matching Chrome/ChromeDriver version is installed (webdriver-manager handles this automatically if it can reach the internet)

If LinkedIn is consistently blocked, the other sources (Greenhouse, Lever, Ashby, WTTJ) will still work fine.

---

## Salary filter behaviour

| Condition | Action |
|---|---|
| Salary explicitly below 55 k€ | Job rejected |
| No salary mentioned | Job kept, gets neutral score |
| 55–75 k€ | Kept, score 1–2 |
| 75–90 k€ | Kept, score 3–4 |
| 90 k€+ | Kept, score 4–5 |

All thresholds are editable in the Settings UI.
