"""Configuration and constants for the HR job scraper."""

import os
from dotenv import load_dotenv

load_dotenv()

# Target job roles (French and English)
TARGET_ROLES = [
    # French titles
    "Responsable RH",
    "Directeur RH",
    "DRH",
    "HRBP",
    "HR Business Partner",
    "Responsable Ressources Humaines",
    "Directeur des Ressources Humaines",
    "Responsable Recrutement",
    "Chargé RH",
    "Responsable développement RH",
    "Responsable formation",
    "Responsable SIRH",
    "Responsable paie",
    "Responsable administration du personnel",
    "People Operations Manager",
    "People Partner",
    "HR Manager",
    "Senior HR Manager",
    "Head of HR",
    "Head of People",
    "VP People",
    "VP HR",
    "Chief People Officer",
    "CPO",
    "Talent Acquisition Manager",
    "Talent Manager",
    "HR Generalist",
    "Senior HR Generalist",
    "HR Director",
    "People Director",
    "HR Lead",
    "People Lead",
]

# Search keywords for API queries
SEARCH_KEYWORDS = [
    "HRBP",
    "HR Business Partner",
    "Responsable RH",
    "DRH",
    "Directeur RH",
    "Head of HR",
    "Head of People",
    "People Operations",
    "HR Manager",
    "People Manager",
]

# Location keywords for Tours area
TOURS_AREA_KEYWORDS = [
    "Tours",
    "Indre-et-Loire",
    "37",
    "37000",
    "37100",
    "37200",
    "37300",
    "Joué-lès-Tours",
    "Saint-Cyr-sur-Loire",
    "Amboise",
    "Blois",
    "Chinon",
    "Loches",
    "Centre-Val de Loire",
    "Touraine",
]

# Keywords indicating Paris hybrid work
PARIS_HYBRID_KEYWORDS = [
    "Paris",
    "Île-de-France",
    "IDF",
    "75",
    "92",
    "93",
    "94",
    "télétravail partiel",
    "hybrid",
    "hybride",
]

# Remote work keywords
REMOTE_KEYWORDS = [
    "full remote",
    "full-remote",
    "100% remote",
    "100% télétravail",
    "télétravail complet",
    "remote first",
    "remote-first",
    "travail à distance",
    "entièrement à distance",
    "distributed",
]

# Minimum salary thresholds (EUR/year)
MIN_SALARY_REMOTE = 60000
MIN_SALARY_TOURS = 50000

# Email configuration
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "alexbonnefon@gmail.com")
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")

# Anthropic API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# France Travail API
FRANCE_TRAVAIL_CLIENT_ID = os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "")
FRANCE_TRAVAIL_CLIENT_SECRET = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "")
FRANCE_TRAVAIL_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
FRANCE_TRAVAIL_JOBS_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

# Database
DB_PATH = os.getenv("DB_PATH", "jobs.db")

# Scraping settings
REQUEST_DELAY_MIN = 1.0  # seconds
REQUEST_DELAY_MAX = 2.5  # seconds
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0

# Job age filter (hours)
MAX_JOB_AGE_HOURS = 48

# Score threshold for email
MIN_SCORE_FOR_EMAIL = 4

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "scraper.log")
