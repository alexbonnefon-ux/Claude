"""Base scraper utilities shared by all scrapers."""
import hashlib
import logging
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import REQUEST_DELAY, REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def make_job_id(source: str, unique_part: str) -> str:
    """Generate a stable job ID from source + unique identifier."""
    raw = f"{source}:{unique_part}"
    return hashlib.sha1(raw.encode()).hexdigest()


def fetch(url: str, params: Optional[dict] = None,
          headers: Optional[dict] = None,
          delay: bool = True) -> Optional[requests.Response]:
    """GET a URL, respecting the configured delay. Returns None on error."""
    if delay:
        time.sleep(REQUEST_DELAY)
    try:
        resp = SESSION.get(
            url, params=params, headers=headers, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        log.warning("GET %s failed: %s", url, exc)
        return None


def fetch_json(url: str, params: Optional[dict] = None,
               headers: Optional[dict] = None) -> Optional[dict | list]:
    resp = fetch(url, params=params, headers=headers)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        log.warning("JSON decode failed for %s: %s", url, exc)
        return None


def fetch_soup(url: str, params: Optional[dict] = None) -> Optional[BeautifulSoup]:
    resp = fetch(url, params=params)
    if resp is None:
        return None
    return BeautifulSoup(resp.text, "html.parser")


def get_driver(headless: bool = True):
    """Return a configured Selenium Chrome WebDriver."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={USER_AGENT}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
    except Exception:
        # Fallback: assume chromedriver is on PATH
        driver = webdriver.Chrome(options=opts)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    return driver
