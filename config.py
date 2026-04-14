"""Configuration for the Job Search Agent."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Job criteria
# ---------------------------------------------------------------------------
JOB_TITLES = [
    "Head of People",
    "HRBP",
    "HR Business Partner",
    "Strategic HRBP",
    "L&D Manager",
    "Learning and Development Manager",
    "Talent Development Manager",
    "DRH",
    "People Lead",
    "VP People",
    "Chief People Officer",
]

# Keywords used when building free-text search queries
SEARCH_KEYWORDS = [
    "Head of People",
    "HRBP",
    "HR Business Partner",
    "L&D Manager",
    "Learning Development Manager",
    "Talent Development Manager",
    "DRH",
    "People Lead",
    "VP People",
    "Chief People Officer",
]

# Accepted location signals (lowercase)
REMOTE_SIGNALS = ["remote", "full remote", "100% remote", "télétravail",
                  "travail à distance", "fully remote", "remote first",
                  "remote-first", "fully distributed"]
PARIS_SIGNALS  = ["paris", "île-de-france", "ile-de-france", "idf", "greater paris"]
TOURS_SIGNALS  = ["tours", "tours (37)", "tours, france"]
EMEA_SIGNALS   = ["emea", "europe", "pan-european"]

HYBRID_MAX_DAYS_ONSITE = 3   # reject roles requiring > 3 days/week on-site

# ---------------------------------------------------------------------------
# Sector keywords (company description or job tags)
# ---------------------------------------------------------------------------
TARGET_SECTOR_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "ml",
    "saas", "software", "tech", "technology", "digital",
    "cloud", "data", "platform",
    "healthtech", "health tech", "medtech", "digital health",
    "cybersecurity", "cyber security", "infosec", "security",
    "aerospace", "space", "defense", "defence",
    "fintech",  # adjacent / acceptable
    "startup", "scale-up", "scaleup",
]

# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------
MIN_SALARY        = 55_000
TARGET_SALARY_MIN = 75_000
TARGET_SALARY_MAX = 90_000

# ---------------------------------------------------------------------------
# Exclusion filters
# ---------------------------------------------------------------------------
EXCLUDE_TITLE_KEYWORDS = [
    "coordinator", "coordinateur",
    "assistant", "assistante",
    "administrator", "administrateur",
    "payroll specialist", "specialist paie", "gestionnaire paie",
    "hr generalist i ",   # entry level variants
    "people ops coordinator",
]

EXCLUDE_DESCRIPTION_KEYWORDS = [
    "purely payroll", "paie uniquement", "no strategic",
    "5 days on-site", "5 jours sur site", "full on-site",
    "100% on-site", "100% présentiel",
]

# ---------------------------------------------------------------------------
# Sources – ATS company identifiers
# ---------------------------------------------------------------------------
GREENHOUSE_COMPANIES = {
    "Anthropic":       "anthropic",
    "OpenAI":          "openai",
    "Datadog":         "datadoghq",
    "HubSpot":         "hubspot",
    "Canva":           "canva",
    "Booking.com":     "booking",
    "Contentsquare":   "contentsquare",
    "Spotify":         "spotify",
    "Doctolib":        "doctolib",
}

LEVER_COMPANIES = {
    "Naboo":      "naboo",
    "Salesforce": "salesforce",
}

ASHBY_COMPANIES = {
    "Linear":     "linear",
    "Qonto":      "qonto",
    "Pennylane":  "pennylane",
}

# Companies that use their own or other ATS – scraped via Selenium/BS4
DIRECT_CAREER_PAGES = {
    "Apple": (
        "https://jobs.apple.com/en-us/search"
        "?team=human-resources-HUMRES&location=FRA"
    ),
    "Samsung": (
        "https://www.samsung.com/global/business/careers/"
        "search-results/?searchitem=HR&location=France"
    ),
    "Google": (
        "https://careers.google.com/jobs/results/"
        "?category=PEOPLE_OPERATIONS&location=France"
    ),
    "Meta": (
        "https://www.metacareers.com/jobs"
        "?q=HR+People&offices=Paris%2C+France&division=People"
    ),
    "Microsoft": (
        "https://jobs.microsoft.com/en-us/search"
        "?q=HR+People&lc=France&l=en_us"
    ),
    "Adobe": (
        "https://careers.adobe.com/us/en/search-results"
        "?keywords=HR+People&country=France"
    ),
}

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
RECIPIENT_EMAIL = "alexbonnefon@gmail.com"
SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD", "")   # Gmail App Password

# ---------------------------------------------------------------------------
# SerpAPI (replaces LinkedIn / WTTJ scrapers)
# Sign up at https://serpapi.com – free plan: 100 searches / month
# ---------------------------------------------------------------------------
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

# ---------------------------------------------------------------------------
# Optional LinkedIn credentials (kept for reference, no longer used)
# ---------------------------------------------------------------------------
LINKEDIN_EMAIL    = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

# ---------------------------------------------------------------------------
# Runtime settings
# ---------------------------------------------------------------------------
DB_PATH         = BASE_DIR / "jobs.db"
LOOKBACK_HOURS  = 12          # search window
REQUEST_DELAY   = float(os.getenv("REQUEST_DELAY", "2.0"))
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
