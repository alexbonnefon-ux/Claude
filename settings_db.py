"""Persistent settings stored in SQLite, with hardcoded defaults as fallback.

All scrapers and the scorer read live values from here so changes made
in the Settings UI take effect on the next scrape run without a restart.
"""
import json
import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults – mirror the values in config.py
# ---------------------------------------------------------------------------
_DEFAULTS: dict = {
    "job_titles": [
        "Head of People", "HRBP", "HR Business Partner", "Strategic HRBP",
        "L&D Manager", "Learning and Development Manager",
        "Talent Development Manager", "DRH", "People Lead",
        "VP People", "Chief People Officer",
    ],
    "min_salary":        55_000,
    "target_salary_min": 75_000,
    "target_salary_max": 90_000,
    "max_onsite_days":   3,
    "lookback_hours":    12,
    "excluded_title_keywords": [
        "coordinator", "coordinateur", "assistant", "assistante",
        "administrator", "administrateur", "payroll specialist",
        "specialist paie", "gestionnaire paie", "people ops coordinator",
    ],
    "excluded_description_keywords": [
        "purely payroll", "paie uniquement", "5 days on-site",
        "5 jours sur site", "full on-site", "100% on-site", "100% présentiel",
    ],
    "schedule_times": ["08:00", "18:00"],
    "greenhouse_companies": {
        "Anthropic":     "anthropic",
        "OpenAI":        "openai",
        "Datadog":       "datadoghq",
        "HubSpot":       "hubspot",
        "Canva":         "canva",
        "Booking.com":   "booking",
        "Contentsquare": "contentsquare",
        "Spotify":       "spotify",
        "Doctolib":      "doctolib",
    },
    "lever_companies": {
        "Naboo":      "naboo",
        "Salesforce": "salesforce",
    },
    "ashby_companies": {
        "Linear":    "linear",
        "Qonto":     "qonto",
        "Pennylane": "pennylane",
    },
}


def get(key: str, default: Any = None) -> Any:
    """Return setting from DB, falling back to _DEFAULTS then `default`."""
    from database import get_connection
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row:
            return json.loads(row[0])
    except Exception as exc:
        log.warning("settings_db.get(%s) error: %s", key, exc)
    return _DEFAULTS.get(key, default)


def set_value(key: str, value: Any) -> None:
    """Persist a setting to the DB (upsert)."""
    from database import get_connection
    now = datetime.utcnow().isoformat()
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE
                     SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, json.dumps(value), now),
            )
    except Exception as exc:
        log.error("settings_db.set(%s) error: %s", key, exc)


def get_all() -> dict:
    """Return all settings, DB values override defaults."""
    result = {k: v for k, v in _DEFAULTS.items()}
    from database import get_connection
    try:
        with get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except Exception:
                result[row["key"]] = row["value"]
    except Exception as exc:
        log.warning("settings_db.get_all() error: %s", exc)
    return result


# ---------------------------------------------------------------------------
# Convenience accessors used by scrapers / scorer
# ---------------------------------------------------------------------------

def job_titles() -> list:
    return get("job_titles") or _DEFAULTS["job_titles"]


def min_salary() -> int:
    return get("min_salary") or _DEFAULTS["min_salary"]


def target_salary_min() -> int:
    return get("target_salary_min") or _DEFAULTS["target_salary_min"]


def target_salary_max() -> int:
    return get("target_salary_max") or _DEFAULTS["target_salary_max"]


def max_onsite_days() -> int:
    return get("max_onsite_days") or _DEFAULTS["max_onsite_days"]


def lookback_hours() -> int:
    return get("lookback_hours") or _DEFAULTS["lookback_hours"]


def excluded_title_keywords() -> list:
    return get("excluded_title_keywords") or _DEFAULTS["excluded_title_keywords"]


def excluded_description_keywords() -> list:
    return get("excluded_description_keywords") or _DEFAULTS["excluded_description_keywords"]


def greenhouse_companies() -> dict:
    return get("greenhouse_companies") or _DEFAULTS["greenhouse_companies"]


def lever_companies() -> dict:
    return get("lever_companies") or _DEFAULTS["lever_companies"]


def ashby_companies() -> dict:
    return get("ashby_companies") or _DEFAULTS["ashby_companies"]


def schedule_times() -> list:
    return get("schedule_times") or _DEFAULTS["schedule_times"]
