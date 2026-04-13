"""LinkedIn Jobs scraper using Selenium.

LinkedIn's public job search is accessible without login, but it aggressively
blocks bots. This implementation uses Selenium with stealth settings.

Search URL pattern (last 24h, France):
  https://www.linkedin.com/jobs/search/?keywords={query}&location=France
  &f_TPR=r86400&f_JT=F&sortBy=DD

Note: LinkedIn does not offer a "last 12h" filter – we use last 24h and
      de-duplicate against the DB to avoid re-sending jobs.
"""
import logging
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from config import (
    SEARCH_KEYWORDS, LOOKBACK_HOURS,
    LINKEDIN_EMAIL, LINKEDIN_PASSWORD,
)
from scorer import Job
from scrapers.base import make_job_id

log = logging.getLogger(__name__)

SEARCH_BASE = "https://www.linkedin.com/jobs/search/"
LOGIN_URL   = "https://www.linkedin.com/login"


def _build_search_url(keyword: str) -> str:
    params = {
        "keywords": keyword,
        "location": "France",
        "f_TPR":    "r86400",   # last 24 hours
        "f_JT":     "F",        # full-time
        "sortBy":   "DD",       # most recent first
    }
    return SEARCH_BASE + "?" + urllib.parse.urlencode(params)


def _try_login(driver) -> bool:
    """Attempt LinkedIn login if credentials are provided."""
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        return False
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver.get(LOGIN_URL)
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "username")))
        driver.find_element(By.ID, "username").send_keys(LINKEDIN_EMAIL)
        driver.find_element(By.ID, "password").send_keys(LINKEDIN_PASSWORD)
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        time.sleep(3)
        return "feed" in driver.current_url or "mynetwork" in driver.current_url
    except Exception as exc:
        log.warning("LinkedIn login failed: %s", exc)
        return False


def _parse_posted_ago(text: str) -> Optional[str]:
    """Convert '2 hours ago', '1 day ago' etc. to an ISO date string."""
    text_l = text.lower().strip()
    now    = datetime.now(timezone.utc)
    try:
        if "minute" in text_l or "hour" in text_l:
            n    = int(text_l.split()[0])
            unit = "hours" if "hour" in text_l else "minutes"
            dt   = now - timedelta(**{unit: n})
            return dt.date().isoformat()
        if "day" in text_l:
            n  = int(text_l.split()[0])
            dt = now - timedelta(days=n)
            return dt.date().isoformat()
        if "week" in text_l:
            n  = int(text_l.split()[0])
            dt = now - timedelta(weeks=n)
            return dt.date().isoformat()
    except (ValueError, IndexError):
        pass
    return None


def _scrape_keyword(driver, keyword: str) -> List[Job]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException

    url = _build_search_url(keyword)
    log.info("LinkedIn – searching: %s", keyword)
    driver.get(url)
    time.sleep(3)

    jobs: List[Job] = []

    # Scroll to load more results (LinkedIn lazy-loads)
    for _ in range(3):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

    # Find job cards
    try:
        card_selector = (
            "ul.jobs-search__results-list li, "
            ".base-search-card, "
            ".job-search-card"
        )
        cards = driver.find_elements(By.CSS_SELECTOR, card_selector)
    except Exception:
        cards = []

    log.info("LinkedIn – %d cards found for '%s'", len(cards), keyword)

    cutoff_hours = LOOKBACK_HOURS * 2  # Use 2x since we filter last 24h

    for card in cards[:50]:  # Cap at 50 per keyword to avoid overload
        try:
            title_el = card.find_element(
                By.CSS_SELECTOR,
                "h3.base-search-card__title, .job-search-card__title, h3"
            )
            title = title_el.text.strip()

            company_el = card.find_element(
                By.CSS_SELECTOR,
                "h4.base-search-card__subtitle, .job-search-card__company-name, h4"
            )
            company = company_el.text.strip()

            location_el = card.find_element(
                By.CSS_SELECTOR,
                ".job-search-card__location, .base-search-card__metadata span"
            )
            location = location_el.text.strip()

            link_el = card.find_element(By.CSS_SELECTOR, "a.base-card__full-link, a")
            href    = link_el.get_attribute("href") or ""

            # Posted time
            posted = None
            try:
                time_el = card.find_element(By.CSS_SELECTOR, "time, .job-search-card__listdate")
                posted  = (
                    time_el.get_attribute("datetime")
                    or _parse_posted_ago(time_el.text)
                )
            except NoSuchElementException:
                pass

            if not title or not href:
                continue

            job_id = make_job_id("linkedin", href.split("?")[0])
            jobs.append(Job(
                job_id      = job_id,
                title       = title,
                company     = company,
                location    = location,
                url         = href,
                date_posted = posted,
                source      = "LinkedIn",
            ))

        except Exception as exc:
            log.debug("LinkedIn card parse error: %s", exc)
            continue

    return jobs


def scrape_all() -> List[Job]:
    try:
        from scrapers.base import get_driver
    except ImportError:
        log.error("Selenium not available – skipping LinkedIn scraper.")
        return []

    driver = None
    all_jobs: List[Job] = []
    seen_ids: set = set()

    try:
        driver = get_driver(headless=True)
        _try_login(driver)

        for keyword in SEARCH_KEYWORDS:
            try:
                jobs = _scrape_keyword(driver, keyword)
                for j in jobs:
                    if j.job_id not in seen_ids:
                        seen_ids.add(j.job_id)
                        all_jobs.append(j)
                time.sleep(2)
            except Exception as exc:
                log.error("LinkedIn – error for keyword '%s': %s", keyword, exc)

    except Exception as exc:
        log.error("LinkedIn – driver error: %s", exc)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    log.info("LinkedIn – total: %d unique jobs", len(all_jobs))
    return all_jobs
