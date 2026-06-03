# Job Scraper – Alexis Bonnefon

Automated daily job scraper for **Senior HR roles** in France.  
Runs every morning, emails a scored digest to `alexbonnefon@gmail.com`.

## What it does

1. Scrapes **7 sources** in parallel:
   - **France Travail API** – official job board via OAuth2
   - **Indeed RSS** – multiple queries (Tours, remote, Paris)
   - **HelloWork** – scrapes search results
   - **LinkedIn** – public job search pages
   - **ATS Platforms** – Greenhouse, Lever, Ashby APIs
   - **Startup Career Pages** – 50+ European tech/AI/FinTech/Health startups
   - **Public Sector** – emploi-territorial.fr, CHU Tours, Mairie de Tours, CD37, Région CVL

2. Deduplicates and filters jobs < 48 hours old

3. Scores each job **0–10** using Claude AI based on:
   - Role match (HRBP, DRH, Head of People…)
   - Location fit (Tours local / Full remote / Paris hybrid)
   - Salary vs. targets (€50K Tours, €60K remote)
   - Company type (tech startup preferred)
   - Freshness

4. Sends a **beautiful HTML email** organized in 3 sections:
   - 🎯 Top Picks (score 8–10)
   - 👍 Good Matches (score 6–7)
   - 🔍 Worth Checking (score 4–5)

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/job-scraper.git
cd job-scraper
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium   # Linux only
```

### 3. Get your API keys

#### Anthropic (Claude AI – for job scoring)
1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an account and generate an API key
3. Add credits (scoring ~200 jobs costs < $0.50/day)

#### Gmail App Password
1. Enable 2-Factor Authentication on your Google account
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an App Password for "Mail" / "Other"
4. Copy the 16-character password

#### France Travail API *(optional but recommended)*
1. Register at [francetravail.io](https://francetravail.io/)
2. Create an application
3. Request access to the **"Offres d'emploi v2"** API
4. Copy your Client ID and Client Secret

### 4. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your actual values
```

### 5. Test locally

```bash
python -m src.main
```

The first run will:
- Create `jobs.db` (SQLite database)
- Run all scrapers (~5–15 minutes depending on network)
- Score results with Claude
- Send the email digest

Check `scraper.log` for detailed output.

---

## GitHub Actions Setup (automated daily runs)

### 1. Push to GitHub

```bash
git add .
git commit -m "Initial setup"
git push origin main
```

### 2. Add repository secrets

Go to: `Settings → Secrets and variables → Actions → New repository secret`

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Claude API key |
| `GMAIL_USER` | your.email@gmail.com |
| `GMAIL_APP_PASSWORD` | 16-char app password |
| `RECIPIENT_EMAIL` | alexbonnefon@gmail.com |
| `FRANCE_TRAVAIL_CLIENT_ID` | *(optional)* |
| `FRANCE_TRAVAIL_CLIENT_SECRET` | *(optional)* |

### 3. Enable GitHub Actions

1. Go to the **Actions** tab in your repository
2. Click **"I understand my workflows, go ahead and enable them"**
3. The workflow will run automatically at **8:00 AM Paris time** every day

### 4. Test with manual trigger

Go to **Actions → Daily Job Scraper → Run workflow**

---

## Project Structure

```
job-scraper/
├── .github/workflows/
│   └── daily_scraper.yml    # GitHub Actions schedule
├── src/
│   ├── __init__.py
│   ├── config.py            # All constants and env var loading
│   ├── database.py          # SQLite layer (aiosqlite)
│   ├── scorer.py            # Claude API job scoring
│   ├── email_sender.py      # HTML email builder + Gmail/SendGrid sender
│   ├── main.py              # Pipeline orchestrator
│   └── scrapers/
│       ├── base.py          # Abstract BaseScraper (rate limiting, retries)
│       ├── france_travail.py  # France Travail OAuth2 API
│       ├── indeed_rss.py      # Indeed RSS feeds
│       ├── hellowork.py       # HelloWork scraper
│       ├── linkedin_rss.py    # LinkedIn job search
│       ├── ats_platforms.py   # Greenhouse / Lever / Ashby APIs
│       ├── startup_careers.py # 50+ startup career pages (Playwright)
│       └── public_sector.py   # Public sector job boards
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Configuration

All configuration is in `src/config.py`:

- **`TARGET_ROLES`** – list of French and English HR job titles to match
- **`TOURS_AREA_KEYWORDS`** – geographic keywords for Tours / Indre-et-Loire
- **`MIN_SALARY_REMOTE`** – `60000` (€/year)
- **`MIN_SALARY_TOURS`** – `50000` (€/year)
- **`JOB_MAX_AGE_HOURS`** – `48` (skip older jobs)
- **`MIN_SCORE_FOR_EMAIL`** – `4` (only email jobs scoring 4+)

---

## Troubleshooting

**Email not received?**
- Check spam folder
- Verify `GMAIL_APP_PASSWORD` is the App Password (not your Gmail login password)
- Check `scraper.log` for SMTP errors

**France Travail scraper skipped?**
- This is normal if you haven't set `FRANCE_TRAVAIL_CLIENT_ID`/`SECRET`
- Register at [francetravail.io](https://francetravail.io/) to enable it

**Playwright/Chromium issues on Linux?**
- Run `playwright install-deps chromium` to install system dependencies
- The GitHub Actions workflow handles this automatically

**Claude API rate limits?**
- The scorer uses a semaphore limiting to 5 concurrent requests
- On large batches (200+ jobs), it may take a few minutes

---

## Cost Estimate

| Service | Cost |
|---|---|
| Anthropic Claude (scoring ~200 jobs/day) | ~$0.20–0.50/day |
| GitHub Actions (60 min/day free tier) | Free |
| Gmail SMTP | Free |
| **Total** | **~$6–15/month** |
