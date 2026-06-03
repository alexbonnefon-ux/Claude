"""
Configuration constants and settings for the job scraper.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Target roles in French and English
TARGET_ROLES = [
    "Responsable RH",
    "Responsable Ressources Humaines",
    "Directeur RH",
    "Directrice RH",
    "DRH",
    "HRBP",
    "HR Business Partner",
    "Chargé RH",
    "Chargée RH",
    "Chargé de Ressources Humaines",
    "Manager RH",
    "Responsable People",
    "People Partner",
    "People Manager",
    "Head of People",
    "Head of HR",
    "VP People",
    "VP RH",
    "Chief People Officer",
    "CPO",
    "Responsable Talent",
    "Talent Acquisition Manager",
    "Responsable Formation",
    "Responsable Développement RH",
    "HR Manager",
    "Senior HR Manager",
    "Senior HRBP",
    "Senior HR Business Partner",
    "Généraliste RH",
    "RRH",
    "HR Director",
    "Human Resources Manager",
    "Human Resources Director",
    "People Operations Manager",
    "HR Generalist",
    "Senior HR Generalist",
    "HR Lead",
    "People Lead",
    "HR Operations Manager",
    "Total Rewards Manager",
    "Compensation & Benefits Manager",
]

# Keywords indicating Tours/Indre-et-Loire area
TOURS_AREA_KEYWORDS = [
    "Tours",
    "Indre-et-Loire",
    "37",
    "37000",
    "37100",
    "37200",
    "37300",
    "Centre-Val de Loire",
    "Touraine",
    "Saint-Cyr-sur-Loire",
    "Joué-lès-Tours",
    "Chambray-lès-Tours",
    "La Riche",
    "Fondettes",
    "Amboise",
    "Blois",
    "Chinon",
]

# Keywords for Paris hybrid roles (acceptable)
PARIS_HYBRID_KEYWORDS = [
    "hybride",
    "hybrid",
    "télétravail partiel",
    "remote partiel",
    "2 jours",
    "3 jours",
    "flex",
    "flexible",
]

# Remote work keywords
REMOTE_KEYWORDS = [
    "télétravail",
    "remote",
    "full remote",
    "100% remote",
    "100% télétravail",
    "entièrement à distance",
    "fully remote",
    "distributed",
    "work from home",
    "WFH",
]

# Salary thresholds (euros per year)
MIN_SALARY_REMOTE = 60000
MIN_SALARY_TOURS = 50000
MIN_SALARY_PARIS_HYBRID = 55000

# Email configuration
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "alexbonnefon@gmail.com")
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Anthropic API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

# France Travail API
FRANCE_TRAVAIL_CLIENT_ID = os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "")
FRANCE_TRAVAIL_CLIENT_SECRET = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "")
FRANCE_TRAVAIL_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
FRANCE_TRAVAIL_API_BASE = "https://api.francetravail.io/partenaire/offresdemploi/v2"

# SendGrid (optional fallback)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")

# Database
DB_PATH = os.getenv("DB_PATH", "jobs.db")

# Scraper settings
REQUEST_DELAY_MIN = 1.0
REQUEST_DELAY_MAX = 2.5
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0
JOB_MAX_AGE_HOURS = 48

# Score threshold for inclusion in email
MIN_SCORE_FOR_EMAIL = 4

# User agents pool for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

# France Travail search keywords
FRANCE_TRAVAIL_KEYWORDS = [
    "responsable ressources humaines",
    "HRBP",
    "HR business partner",
    "directeur ressources humaines",
    "responsable RH",
    "manager RH",
    "people manager",
    "head of people",
]

# Département codes for France Travail searches
FRANCE_TRAVAIL_DEPT_CODES = [
    "37",
    "41",
    "36",
    "75",
    "92",
    "93",
    "94",
]
