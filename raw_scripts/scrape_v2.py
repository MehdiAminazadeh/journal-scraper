"""
v9.4 — AER + QJE + JPE + WP + Cloudflare stealth bypass - anti-bot

Run as Administrator:
    python scrape_v2.py
"""

import re
import sys
import time
import signal
import logging
import shutil
import subprocess
import random
import tempfile
import gc
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import quote_plus, urljoin

import requests
import pandas as pd
from tqdm import tqdm

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, WebDriverException

from working_paper import NBERWorkingPaperDownloader

INPUT_FILE = "dataset 2025-08-18.xlsx"
ARTICLE_DIR = Path("pdfs/articles")
WP_DIR = Path("pdfs/wps")
LOG_FILE = "download_log.csv"
MANUAL_FILE = "manual_downloads_needed.csv"

YOUR_EMAIL = "m.aminazadeh@edu.rptu.de"

WG_CONF = r"G:\scrape_economic_pdf\config\wgtuk-Full-Wind.conf"
WG_TUNNEL = Path(WG_CONF).stem
WG_EXE = r"C:\Program Files\WireGuard\wireguard.exe"

DELAY = 1.5
TIMEOUT = 45

TARGET_YEARS = {2023}
TARGET_JOURNALS = {"AER", "QJE", "JPE", "ECMA", "RESTUD", "RES"}
CHROME_MAJOR_VERSION = 146
SELENIUM_TMP_DIR = Path("pdfs/_selenium_tmp")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
WP_DIR.mkdir(parents=True, exist_ok=True)
SELENIUM_TMP_DIR.mkdir(parents=True, exist_ok=True)




def get_nber_downloader() -> NBERWorkingPaperDownloader:
    global _nber_downloader

    if _nber_downloader is None:
        _nber_downloader = NBERWorkingPaperDownloader(
            download_dir=WP_DIR,
            headless=False,
            wait_seconds=12,
            login_wait_seconds=10,
            search_wait_seconds=1.5,
            page_wait_seconds=1.5,
            download_timeout=55,
            similarity_threshold=0.50,
        )
        _nber_downloader.prepare_session()

    return _nber_downloader


def close_nber_downloader():
    global _nber_downloader

    try:
        if _nber_downloader is not None:
            _nber_downloader.close()
    except Exception as e:
        lwarn(f"NBER downloader close warning: {e}")
    finally:
        _nber_downloader = None



HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

AEA_COOKIES = {
    "AEA_member": "",
    "PHPSESSID": "",
}

OUP_COOKIES = {
    "oxford_session": "",
    "SalesforceSession": "",
}

UCHICAGO_COOKIES = {
    "jCookieCheck": "",
    "JournalSSOSid": "",
}

SERIES_PRIORITY = {
    "NBER": 100,
    "IZA": 90,
    "CESIFO": 80,
    "CEPR": 70,
    "SSRN": 60,
    "BFI": 55,
    "FEDRESERVE": 50,
    "FEDERAL RESERVE": 50,
    "UCD": 45,
    "HKUST": 40,
    "BOSTONCOLLEGE": 40,
    "CAMBRIDGE": 35,
    "ECONSTOR": 35,
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

_driver = None
_profile_dir_in_use = None
_nber_downloader = None




def li(msg: str):
    log.info(f"[i] {msg}")

def lok(msg: str):
    log.info(f"[ok] {msg}")

def lwarn(msg: str):
    log.info(f"[warn] {msg}")

def lerr(msg: str):
    log.error(f"[err] {msg}")





def sleep():
    time.sleep(DELAY)


def is_pdf(content: bytes) -> bool:
    return content[:4] == b"%PDF" or b"%PDF" in content[:20]


def sanitize_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "_", str(s))
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_text(s: str) -> str:
    s = str(s).lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def text_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_text(a), norm_text(b)).ratio()


def normalize_series_name(s: str) -> str:
    s = str(s or "").upper().strip()
    s = s.replace("MINNEAPOLI", "MINNEAPOLIS")
    s = s.replace("CESINFO", "CESIFO")
    return s


def series_rank(series: str) -> int:
    s = normalize_series_name(series)
    return SERIES_PRIORITY.get(s, 10)


def choose_preferred_series(series_raw: str) -> list[str]:
    parts = [
        normalize_series_name(x)
        for x in re.split(r"[/,;|]", str(series_raw or ""))
        if str(x).strip()
    ]
    parts = list(dict.fromkeys(parts))
    parts.sort(key=series_rank, reverse=True)
    return parts


def wp_available_flag(row: pd.Series) -> bool:
    v = str(row.get("wp_yes", "")).strip().lower()
    return v not in ("", "0", "0.0", "false", "no", "nan", "none")


def parse_year(value):
    try:
        return int(value)
    except Exception:
        return None


def safe_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def absolutize(base: str, href: str) -> str:
    return urljoin(base, href)


def accept_cookies_if_present(driver, timeout: int = 5):
    labels = [
        "Accept", "Accept all", "Accept All", "I agree", "Agree",
        "Allow all", "OK", "Continue", "Got it"
    ]
    end = time.time() + timeout
    while time.time() < end:
        clicked = False
        for txt in labels:
            xpaths = [
                f"//button[normalize-space()='{txt}']",
                f"//a[normalize-space()='{txt}']",
                f"//*[self::button or self::a or self::span][contains(translate(normalize-space(.),"
                f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{txt.lower()}')]",
            ]
            for xp in xpaths:
                try:
                    els = driver.find_elements(By.XPATH, xp)
                    for el in els:
                        if el.is_displayed() and el.is_enabled():
                            driver.execute_script("arguments[0].click();", el)
                            time.sleep(1)
                            clicked = True
                            break
                    if clicked:
                        break
                except Exception:
                    pass
            if clicked:
                break
        if not clicked:
            break


def fetch_html(url: str) -> str:
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""



def vpn_connect() -> bool:
    li(f"Connecting WireGuard tunnel {WG_TUNNEL}")
    try:
        r = subprocess.run(
            [WG_EXE, "/installtunnelservice", WG_CONF],
            capture_output=True, text=True, timeout=30,
        )
        combined = (r.stdout or "") + " " + (r.stderr or "")
        if r.returncode == 0 or "already exists" in combined.lower():
            lok("WireGuard connected")
            time.sleep(4)
            return True
        lerr(f"WireGuard failed: {combined.strip()}")
        return False
    except FileNotFoundError:
        lerr(f"wireguard.exe not found at {WG_EXE}")
        return False
    except subprocess.TimeoutExpired:
        lerr("WireGuard timed out")
        return False


def vpn_disconnect():
    try:
        subprocess.run(
            [WG_EXE, "/uninstalltunnelservice", WG_TUNNEL],
            capture_output=True,
            timeout=15
        )
        lok("WireGuard disconnected")
    except Exception as e:
        lwarn(f"VPN disconnect warning: {e}")



def get_random_user_agent() -> str:
    """Get a random realistic user agent"""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ]
    
    return random.choice(user_agents)


def _inject_stealth_scripts(driver):
    """Inject JavaScript to hide automation signals"""
    stealth_scripts = [
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
        "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})",
        "Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})",
        "window.chrome = {runtime: {}}",
        "Object.defineProperty(navigator, 'permissions', {get: () => ({query: () => Promise.resolve({state: Notification.permission})})})",
    ]
    for script in stealth_scripts:
        try:
            driver.execute_script(script)
        except Exception as e:
            log.debug(f"Stealth script note: {e}")


def wait_for_cloudflare_bypass(driver, timeout: int = 45) -> bool:
    """Wait for Cloudflare challenge to complete automatically"""
    li(f"Waiting for Cloudflare to complete (timeout: {timeout}s)")
    
    start = time.time()
    check_count = 0
    
    while time.time() - start < timeout:
        try:
            page_source = driver.page_source.lower()
            title = driver.title.lower()
            
            cf_indicators = [
                "checking your browser",
                "just a moment",
                "please wait",
                "verifying you are human",
                "security challenge",
                "ray id",
                "cloudflare ray",
            ]
            
            if not any(ind in page_source for ind in cf_indicators):
                if not any(ind in title for ind in cf_indicators):
                    lok("Cloudflare verification passed")
                    return True
            
            check_count += 1
            if check_count % 5 == 0:
                log.debug(f"Still waiting for CF bypass ({int(time.time() - start)}s)")
            
            time.sleep(2)
            
        except Exception as e:
            log.debug(f"CF check error: {e}")
            time.sleep(2)
    
    lwarn("Cloudflare bypass timeout - continuing anyway")
    return False


def click_cloudflare_challenge(driver, timeout: int = 10) -> bool:
    """Try to click Cloudflare Turnstile challenge if present"""
    try:
        log.debug(" Looking for Cloudflare challenge elements...")
        xpaths = [
            "//input[@type='checkbox'][@id='challenge-checkbox']",
            "//input[@type='checkbox'][contains(@id, 'turnstile')]",
            "//input[@type='checkbox']",
            "//iframe[contains(@src, 'challenges.cloudflare.com')]",
        ]
        for xp in xpaths:
            try:
                els = driver.find_elements(By.XPATH, xp)
                for el in els:
                    if el.is_displayed() and el.is_enabled():
                        log.info(" ✓ Found and clicking Cloudflare challenge element")
                        ActionChains(driver).move_to_element(el).click(el).perform()
                        time.sleep(2)
                        return True
            except Exception as ex:
                log.debug(f" Could not interact with {xp}: {ex}")
        return False
    except Exception as e:
        log.debug(f"Challenge click error: {e}")
        return False




def get_fresh_profile_dir():
    """Create a fresh temporary profile directory for each phase"""
    global _profile_dir_in_use
    
    profile_dir = Path(tempfile.gettempdir()) / f"chrome_profile_{int(time.time() * 1000)}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    _profile_dir_in_use = profile_dir
    li(f"Created fresh Chrome profile: {profile_dir}")
    return profile_dir


def clear_undetected_chromedriver_cache():
    """Clear UC's cached driver state to prevent restart conflicts"""
    try:
        cache_paths = [
            Path.home() / "AppData" / "Local" / "undetected_chromedriver",
            Path(tempfile.gettempdir()) / "undetected_chromedriver",
            Path.home() / ".undetected_chromedriver",
        ]
        
        for cache_path in cache_paths:
            if cache_path.exists():
                try:
                    shutil.rmtree(cache_path, ignore_errors=True)
                    log.debug(f"Cleared UC cache: {cache_path}")
                except Exception as e:
                    log.debug(f"UC cache clear note: {e}")
    except Exception:
        pass


def kill_leftover_chrome_processes():
    """Force kill any leftover Chrome/driver processes on Windows"""
    commands = [
        ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
        ["taskkill", "/F", "/IM", "chromedriver.exe", "/T"],
        ["taskkill", "/F", "/IM", "undetected_chromedriver.exe", "/T"],
    ]
    for cmd in commands:
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
        except Exception:
            pass
    time.sleep(2)





def get_driver(download_dir=SELENIUM_TMP_DIR, headless=False):
    """Setup undetected Chrome driver to bypass Cloudflare bot detection (fresh profile)"""
    global _driver
    if _driver is not None:
        return _driver

    download_dir = Path(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)

    profile_dir = get_fresh_profile_dir()

    opts = uc.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-web-security") #unsafe - not recommended
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--window-size=1920,1080") # size can be changed to minimize the process
    opts.add_argument(f"user-agent={get_random_user_agent()}")
    opts.add_argument(f"--user-data-dir={profile_dir.resolve()}")

    prefs = {
        "download.default_directory": str(download_dir.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_setting_values.cookies": 1,
        "profile.block_third_party_cookies": False,
        "profile.default_content_setting_values": {
            "notifications": 2,
            "media_stream": 2,
        },
        "profile.managed_default_content_settings": {
            "images": 2
        }
    }
    opts.add_experimental_option("prefs", prefs)

    try:
        _driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, suppress_welcome=True)
        _inject_stealth_scripts(_driver)
        log.info(" Undetected Chrome driver initialized (Cloudflare bypass ready, fresh profile)")
        return _driver
    except Exception as e:
        log.error(f" Failed to create undetected driver: {e}")
        raise

def close_driver():
    """
    Close the global driver instance with complete cleanup.
    Removes temporary profile and kills leftover processes.
    """
    global _driver, _profile_dir_in_use

    try:
        if _driver is not None:
            try:
                _driver.quit()
            except Exception as e:
                log.debug(f"Driver quit error: {e}")
    except Exception:
        pass
    finally:
        _driver = None

    time.sleep(2)

    if _profile_dir_in_use:
        try:
            shutil.rmtree(_profile_dir_in_use, ignore_errors=True)
            li(f"Cleaned up profile: {_profile_dir_in_use}")
        except Exception as e:
            log.debug(f"Profile cleanup note: {e}")
        finally:
            _profile_dir_in_use = None

    gc.collect()


def cleanup_between_phases(phase_name: str):
    """Complete cleanup between phases"""
    li(f"\n[CLEANUP] Ending {phase_name} phase...")
    close_driver()
    time.sleep(1)
    
    li("[CLEANUP] Killing leftover Chrome processes...")
    kill_leftover_chrome_processes()
    time.sleep(1)
    
    li("[CLEANUP] Clearing UC cache...")
    clear_undetected_chromedriver_cache()
    time.sleep(1)
    
    li(f"[CLEANUP] Ready for next phase.\n")
    time.sleep(2)


def cleanup_extra_tabs(driver):
    try:
        handles = driver.window_handles
        if not handles:
            return

        main = handles[0]
        for h in handles[1:]:
            try:
                driver.switch_to.window(h)
                driver.close()
            except Exception:
                pass

        driver.switch_to.window(main)
    except Exception:
        pass


def safe_get(driver, url: str):
    cleanup_extra_tabs(driver)
    if not driver.window_handles:
        raise RuntimeError("No browser window available")
    driver.switch_to.window(driver.window_handles[0])
    driver.get(url)
    wait_for_cloudflare_bypass(driver, timeout=45)
    time.sleep(2)


def open_in_selenium(url: str, wait_for_cf: bool = True) -> bool:
    """Open URL in undetected Chrome, optionally wait for Cloudflare"""
    try:
        driver = get_driver(headless=False)
        log.info(f" ! Opening in Selenium: {url[:80]}")
        driver.get(url)
        time.sleep(3)
        if wait_for_cf:
            if not wait_for_cloudflare_bypass(driver, timeout=45):
                log.info("  CF timeout, continuing anyway...")
            click_cloudflare_challenge(driver, timeout=5)
            time.sleep(2)
        return True
    except Exception as e:
        log.error(f" ✗ Error opening URL in Selenium: {e}")
        return False

def selenium_download_pdf(url: str, dest: Path, wait_sec: int = 35) -> bool:
    driver = get_driver()
    tmp_dir = SELENIUM_TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)

    cleanup_extra_tabs(driver)
    before = {p.resolve() for p in tmp_dir.glob("*.pdf")}

    try:
        safe_get(driver, url)
        accept_cookies_if_present(driver, timeout=5)

        deadline = time.time() + wait_sec
        newest_pdf = None

        while time.time() < deadline:
            crdownloads = list(tmp_dir.glob("*.crdownload"))
            pdfs = [p for p in tmp_dir.glob("*.pdf") if p.resolve() not in before]

            if not crdownloads and pdfs:
                newest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
                break

            current_url = driver.current_url or ""
            if current_url.lower().endswith(".pdf"):
                try:
                    r = SESSION.get(current_url, timeout=TIMEOUT)
                    if r.status_code == 200 and is_pdf(r.content):
                        dest.write_bytes(r.content)
                        lok(f"Saved {dest.name} using selenium current URL")
                        cleanup_extra_tabs(driver)
                        return True
                except Exception:
                    pass

            time.sleep(1)

        if newest_pdf and newest_pdf.exists():
            shutil.copy2(newest_pdf, dest)
            lok(f"Saved {dest.name} using selenium download")
            cleanup_extra_tabs(driver)
            return True

        cleanup_extra_tabs(driver)

    except Exception as e:
        li(f"Selenium error: {e}")
        cleanup_extra_tabs(driver)

    return False


def selenium_qje_pdf_from_open_article(dest: Path, wait_sec: int = 40) -> bool:
    """
    Extract PDF from already-opened QJE article page after Cloudflare bypass.
    looks for PDF link in DOM and downloads it.
    """
    
    
    
    driver = get_driver()
    tmp_dir = SELENIUM_TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    before = {p.resolve() for p in tmp_dir.glob("*.pdf")}

    try:
        log.info(" [!] Extracting PDF from QJE article DOM...")
        
        xpaths = [
            "//a[contains(@class,'article-pdfLink')]",
            "//a[contains(@class,'article-pdf')]",
            "//a[contains(@href,'/article-pdf/')]",
            "//a[contains(@href, '/pdf')]",
            "//a[contains(., 'PDF')]",
            "//a[contains(., 'download')]",
            "//button[contains(., 'PDF')]",
            "//button[contains(., 'Download')]",
        ]

        pdf_el = None
        pdf_href = None

        for xp in xpaths:
            try:
                els = driver.find_elements(By.XPATH, xp)
                log.debug(f" Found {len(els)} elements for xpath: {xp[:50]}")
                for el in els:
                    try:
                        href = el.get_attribute("href") or ""
                        text = el.text or ""
                        log.debug(f" Element href: {href[:80]}, text: {text[:50]}")
                        if "/article-pdf/" in href or "/pdf" in href.lower() or "download" in text.lower():
                            pdf_el = el
                            pdf_href = href
                            log.info(f" ✓ Found PDF element: {href[:100]}")
                            break
                    except Exception as ex:
                        log.debug(f" Error processing element: {ex}")
                if pdf_el:
                    break
                
                
            except Exception as ex:
                log.debug(f" XPath query error: {ex}")
                
                

        if not pdf_el or not pdf_href:
            log.info(" Could not find QJE PDF link on page")
            return False

        if pdf_href.startswith("/"):
            pdf_href = "https://academic.oup.com" + pdf_href

        log.info(f"  QJE PDF href: {pdf_href[:100]}")

        try:
            driver.execute_script("arguments[0].scrollIntoView(true);", pdf_el)
            time.sleep(1)
            log.info(" Clicking PDF link...")
            driver.execute_script("arguments[0].click();", pdf_el)
            time.sleep(2)
        except Exception as ex:
            log.debug(f" Click failed, navigating directly to: {pdf_href}")
            driver.get(pdf_href)
            time.sleep(2)

        deadline = time.time() + wait_sec
        while time.time() < deadline:
            crdownloads = list(tmp_dir.glob("*.crdownload"))
            pdfs = [p for p in tmp_dir.glob("*.pdf") if p.resolve() not in before]

            if not crdownloads and pdfs:
                newest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
                shutil.copy2(newest_pdf, dest)
                log.info(f" # Saved {dest.name} [QJE_DOM_CF]")
                return True

            time.sleep(0.5)

        log.warning(f" [ii] No PDF downloaded after {wait_sec}s")

    except Exception as e:
        log.info(f" * QJE CF-aware PDF error: {e}")
        return False


def selenium_jpe_pdf_from_open_article(dest: Path, wait_sec: int = 40) -> bool:
    """
    Extract PDF from already-opened JPE article page after Cloudflare bypass.
    Uses the same run_qje-style DOM workflow adapted for UChicago.
    """
    driver = get_driver()
    tmp_dir = SELENIUM_TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cleanup_extra_tabs(driver)
    before = {p.resolve() for p in tmp_dir.glob("*.pdf")}

    try:
        li("Extracting PDF from JPE article DOM...")

        xpaths = [
            "//a[contains(@href,'/doi/pdf/')]",
            "//a[contains(@href,'/doi/pdfplus/')]",
            "//a[contains(@href,'/doi/epdf/')]",
            "//a[contains(@class,'pdf')]",
            "//a[contains(., 'PDF')]",
            "//a[contains(., 'download')]",
            "//button[contains(., 'PDF')]",
            "//button[contains(., 'Download')]",
        ]

        pdf_el = None
        pdf_href = None

        for xp in xpaths:
            try:
                els = driver.find_elements(By.XPATH, xp)
                log.debug(f" Found {len(els)} JPE elements for xpath: {xp[:50]}")
                for el in els:
                    try:
                        href = el.get_attribute("href") or ""
                        text = el.text or ""
                        log.debug(f" JPE element href: {href[:80]}, text: {text[:50]}")
                        if (
                            "/doi/pdf/" in href
                            or "/doi/pdfplus/" in href
                            or "/doi/epdf/" in href
                            or "download" in text.lower()
                        ):
                            pdf_el = el
                            pdf_href = href
                            li(f"Found JPE PDF element: {href[:100]}")
                            break
                    except Exception as ex:
                        log.debug(f" Error processing JPE element: {ex}")
                if pdf_el:
                    break
            except Exception as ex:
                log.debug(f" JPE XPath query error: {ex}")

        if not pdf_el or not pdf_href:
            li("Could not find JPE PDF link on page")
            return False

        if pdf_href.startswith("/"):
            pdf_href = "https://www.journals.uchicago.edu" + pdf_href

        li(f"JPE PDF href: {pdf_href[:100]}")



        try:
            driver.execute_script("arguments[0].scrollIntoView(true);", pdf_el)
            time.sleep(1)
            li("Clicking JPE PDF link...")
            driver.execute_script("arguments[0].click();", pdf_el)
            time.sleep(2)
            
        except Exception as ex:
            log.debug(f" JPE click failed, navigating directly to: {pdf_href}")
            driver.get(pdf_href)
            time.sleep(2)

        deadline = time.time() + wait_sec
        while time.time() < deadline:
            crdownloads = list(tmp_dir.glob("*.crdownload"))
            pdfs = [p for p in tmp_dir.glob("*.pdf") if p.resolve() not in before]


            if not crdownloads and pdfs:
                newest_pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
                shutil.copy2(newest_pdf, dest)
                lok(f"Saved {dest.name} [JPE_DOM_CF]")
                cleanup_extra_tabs(driver)
                return True


            current_url = driver.current_url or ""
            if current_url.lower().endswith(".pdf"):
                try:
                    r = SESSION.get(current_url, timeout=TIMEOUT)
                    if r.status_code == 200 and is_pdf(r.content):
                        dest.write_bytes(r.content)
                        lok(f"Saved {dest.name} using JPE current PDF URL")
                        cleanup_extra_tabs(driver)
                        return True
                except Exception:
                    pass

            time.sleep(0.5)

        lwarn(f"No JPE PDF downloaded after {wait_sec}s")

    except Exception as e:
        li(f"JPE DOM PDF error: {e}")
    finally:
        cleanup_extra_tabs(driver)

    return False

def _inject_cookies(domain: str):
    if domain == "aea" and any(AEA_COOKIES.values()):
        SESSION.cookies.update(AEA_COOKIES)
    elif domain == "oup" and any(OUP_COOKIES.values()):
        SESSION.cookies.update(OUP_COOKIES)
    elif domain == "uchicago" and any(UCHICAGO_COOKIES.values()):
        SESSION.cookies.update(UCHICAGO_COOKIES)



def oup_pdf_from_article_page(article_url: str) -> str | None:
    if not article_url:
        return None
    try:
        r = SESSION.get(article_url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return None
        html = r.text

        patterns = [
            r'href="([^"]+/article-pdf/[^"]+\.pdf[^"]*)"',
            r'href="([^"]+/pdf[^"]*)"',
            r'"pdfUrl":"([^"]+)"',
        ]

        for pat in patterns:
            matches = re.findall(pat, html, flags=re.I)
            for u in matches:
                u = u.replace("\\u002f", "/").replace("\\/", "/")
                if u.startswith("/"):
                    u = "https://academic.oup.com" + u
                if "article-pdf" in u or "/pdf" in u:
                    return u
    except Exception as e:
        log.debug(f"OUP article-page parse error: {e}")
    return None


def uchicago_pdf_from_article_page(article_url: str) -> str | None:
    if not article_url:
        return None
    try:
        r = SESSION.get(article_url, timeout=TIMEOUT, allow_redirects=True) #wait for the session - use time.sleep(1-5) not more
        if r.status_code != 200:
            return None
        html = r.text

        patterns = [
            r'href="([^"]+/doi/pdf/[^"]+)"',
            r'href="([^"]+/doi/pdfplus/[^"]+)"',
            r'"pdfUrl":"([^"]+)"',
        ]

        for pat in patterns:
            matches = re.findall(pat, html, flags=re.I)
            for u in matches:
                u = u.replace("\\u002f", "/").replace("\\/", "/")
                if u.startswith("/"):
                    u = "https://www.journals.uchicago.edu" + u
                if "/doi/pdf/" in u or "/doi/pdfplus/" in u:
                    return u
    except Exception as e:
        log.debug(f"UChicago article-page parse error: {e}")
    return None




def fetch(url: str, dest: Path, label: str = "") -> bool: #fetch https / https request
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)

        if r.status_code == 200 and is_pdf(r.content):
            dest.write_bytes(r.content)
            lok(f"Saved {dest.name} using {label}")
            return True

        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
            html = r.text

            embedded_patterns = [
                r'href="([^"]+/article-pdf/[^"]+\.pdf[^"]*)"',
                r'href="([^"]+/doi/pdf/[^"]+)"',
                r'href="([^"]+/doi/pdfplus/[^"]+)"',
                r'href="([^"]+\.pdf[^"]*)"',
                r'"pdfUrl":"([^"]+)"',
            ]

            for pat in embedded_patterns:
                matches = re.findall(pat, html, flags=re.I)
                for u in matches:
                    u = u.replace("\\u002f", "/").replace("\\/", "/")
                    if u.startswith("/"):
                        if "academic.oup.com" in r.url:
                            u = "https://academic.oup.com" + u
                        elif "journals.uchicago.edu" in r.url:
                            u = "https://www.journals.uchicago.edu" + u

                    try:
                        r2 = SESSION.get(u, timeout=TIMEOUT, allow_redirects=True)
                        if r2.status_code == 200 and is_pdf(r2.content):
                            dest.write_bytes(r2.content)
                            lok(f"Saved {dest.name} using embedded link from {label}")
                            return True
                    except Exception:
                        pass

        li(f"Request did not return a PDF for {label}: {url[:100]}")

        if r.status_code in (401, 403) or not is_pdf(r.content):
            li(f"Trying Selenium fallback for {label}")
            if selenium_download_pdf(url, dest):
                return True

    except Exception as e:
        li(f"Fetch error for {label}: {e} {url[:100]}")
        li(f"Trying Selenium fallback for {label}")
        if selenium_download_pdf(url, dest):
            return True

    return False


def crossref_metadata(title: str, author_last: str) -> dict:
    try:
        r = SESSION.get(
            "https://api.crossref.org/works",
            params={
                "query.title": title,
                "query.author": author_last,
                "rows": 5,
                "select": "DOI,title,URL,volume,issue,page,published",
                "mailto": YOUR_EMAIL,
            },
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])

        best = None
        best_score = -1.0
        for item in items:
            candidate_title = " ".join(item.get("title", [])) if isinstance(item.get("title"), list) else str(item.get("title", ""))
            score = text_sim(title, candidate_title)
            if score > best_score:
                best_score = score
                best = item

        return best or {}
    except Exception as e:
        log.debug(f"Crossref error: {e}")
        return {}


def unpaywall_url(doi: str) -> str | None:
    try:
        r = SESSION.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": YOUR_EMAIL},
            timeout=12,
        )
        r.raise_for_status()
        best = r.json().get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url")
    except Exception:
        return None


def semantic_scholar_url(title: str, author_last: str) -> str | None:
    try:
        r = SESSION.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": f"{title} {author_last}",
                "fields": "title,openAccessPdf",
                "limit": 5,
            },
            timeout=12,
        )
        r.raise_for_status()
        candidates = r.json().get("data", [])

        best_url = None
        best_score = -1.0
        for item in candidates:
            candidate_title = item.get("title", "") or ""
            url = (item.get("openAccessPdf") or {}).get("url")
            if not url:
                continue
            score = text_sim(title, candidate_title)
            if score > best_score:
                best_score = score
                best_url = url

        return best_url
    except Exception:
        return None




def doi_matches_article_journal(journal: str, doi: str) -> bool:
    
    
    
    """Validate DOI for ARTICLE download 
    strict journal-specific DOIs only"""
    
    
    if not doi:
        return False

    j = str(journal).upper().strip()
    doi = doi.lower()

    if j == "AER":
        return doi.startswith("10.1257/")
    if j == "QJE":
        return doi.startswith("10.1093/qje/")
    if j == "JPE":
        return doi.startswith("10.1086/")
    if j in ("RESTUD", "RES"):
        return doi.startswith("10.1093/restud/")
    if j == "ECMA":
        return doi.startswith("10.3982/")
    
    return False


def doi_is_valid_working_paper(doi: str) -> bool:
    """Validate DOI for WORKING PAPER 
    download accepts SSRN, NBER,"""
    
    if not doi:
        return False
    
    doi = doi.lower()
    
    valid_patterns = [
        "10.2139/ssrn.",
        "10.3386/w",
        "10.1016/j.",
        "10.48550/arxiv.",
    ]
    
    return any(doi.startswith(pattern) for pattern in valid_patterns)


def extract_wp_series_from_doi(doi: str) -> str | None:
    """Extract the working paper series from DOI"""
    if not doi:
        return None
    
    doi = doi.lower()
    
    if doi.startswith("10.2139/ssrn."):
        return "SSRN"
    if doi.startswith("10.3386/w"): # problem in log-in - to be solved with login bypass - selenium
        return "NBER"
    if doi.startswith("10.48550/arxiv."):
        return "ARXIV"
    
    return None


def aer_urls(doi: str) -> list[str]:
    return [
        f"https://pubs.aeaweb.org/doi/pdf/{doi}",
        f"https://pubs.aeaweb.org/doi/pdfplus/{doi}",
    ]


def qje_urls(doi: str, meta: dict) -> list[str]:
    urls = []
    vol = meta.get("volume", "")
    issue = meta.get("issue", "")
    page = (meta.get("page") or "").split("-")[0]
    suffix = doi.replace("10.1093/qje/", "")
    article_url = meta.get("URL", "") or ""

    if article_url:
        urls.append(article_url)
        real_pdf = oup_pdf_from_article_page(article_url)
        if real_pdf:
            urls.append(real_pdf)

    if vol and issue and page:
        guessed_article_page = f"https://academic.oup.com/qje/article-abstract/{vol}/{issue}/{page}/{suffix}"
        urls.append(guessed_article_page)
        real_pdf = oup_pdf_from_article_page(guessed_article_page)
        if real_pdf:
            urls.append(real_pdf)

    urls += [
        f"https://academic.oup.com/qje/article/{doi}/pdf",
        f"https://academic.oup.com/qje/advance-article-pdf/{suffix}",
        f"https://academic.oup.com/qje/article-pdf/{vol}/{issue}/{page}/{suffix}.pdf",
    ]

    out = []
    for u in urls:
        if u and u not in out:
            out.append(u)
    return out


def jpe_urls(doi: str, meta: dict) -> list[str]:
    urls = []
    article_url = meta.get("URL", "") or ""

    if article_url:
        urls.append(article_url)
        real_pdf = uchicago_pdf_from_article_page(article_url)
        if real_pdf:
            urls.append(real_pdf)

    urls += [
        f"https://www.journals.uchicago.edu/doi/pdf/{doi}",
        f"https://www.journals.uchicago.edu/doi/pdfplus/{doi}",
        f"https://www.journals.uchicago.edu/doi/epdf/{doi}",
    ]

    out = []
    for u in urls:
        if u and u not in out:
            out.append(u)
    return out


def restud_urls(doi: str, meta: dict) -> list[str]:
    suffix = doi.replace("10.1093/restud/", "")
    vol = meta.get("volume", "")
    issue = meta.get("issue", "")
    page = (meta.get("page") or "").split("-")[0]

    urls = []
    if vol and issue and page:
        urls.append(
            f"https://academic.oup.com/restud/article-pdf/{vol}/{issue}/{page}/{suffix}.pdf"
        )
    urls += [
        f"https://academic.oup.com/restud/article/{doi}/pdf",
        f"https://academic.oup.com/restud/advance-article-pdf/{suffix}",
    ]
    return [u for u in urls if u]


def ecma_urls(doi: str) -> list[str]:
    return [
        f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
        f"https://onlinelibrary.wiley.com/doi/pdf/{doi}",
        f"https://onlinelibrary.wiley.com/doi/epdf/{doi}",
    ]


def journal_urls(journal: str, doi: str, meta: dict) -> list[str]:
    j = str(journal).upper().strip()

    if j == "AER":
        _inject_cookies("aea")
        return aer_urls(doi)

    if j == "QJE":
        _inject_cookies("oup")
        return qje_urls(doi, meta)

    if j == "JPE":
        _inject_cookies("uchicago")
        return jpe_urls(doi, meta)

    if j in ("RESTUD", "RES"):
        _inject_cookies("oup")
        return restud_urls(doi, meta)

    if j == "ECMA":
        return ecma_urls(doi)

    return [f"https://doi.org/{doi}"]



def download_article(row: pd.Series, dest: Path) -> dict:
    if dest.exists():
        return {"status": "already_exists"}

    title = safe_str(row.get("paper_title", ""))
    last = safe_str(row.get("author1_last", ""))
    journal = safe_str(row.get("journal", ""))
    tried = []

    if not title or not last:
        return {"status": "SKIP_missing_info"}

    sleep()
    meta = crossref_metadata(title, last)
    doi = (meta.get("DOI") or "").lower() or None

    if doi and not doi_matches_article_journal(journal, doi):
        li(f"DOI rejected for {journal} (not a journal DOI): {doi}")
        doi = None
        meta = {}

    li(f"DOI: {doi or 'not found'}")

    if doi:
        sleep()
        oa = unpaywall_url(doi)
        if oa:
            tried.append(f"unpaywall:{oa[:100]}")
            if fetch(oa, dest, "unpaywall"):
                return {
                    "status": "downloaded_unpaywall",
                    "doi": doi,
                    "tried": "|".join(tried),
                }

    sleep()
    ss = semantic_scholar_url(title, last)
    if ss:
        tried.append(f"s2:{ss[:100]}")
        if fetch(ss, dest, "SemanticScholar"):
            return {
                "status": "downloaded_s2",
                "doi": doi or "",
                "tried": "|".join(tried),
            }

    if doi:
        for url in journal_urls(journal, doi, meta):
            tried.append(f"journal:{url[:100]}")
            sleep()

            if journal.upper() == "QJE" and (
                "academic.oup.com/qje/article" in url or
                "academic.oup.com/qje/article-abstract" in url
            ):
                li("QJE article page detected, using exact run_qje browser + DOM method")
                if open_in_selenium(url, wait_for_cf=True):
                    if selenium_qje_pdf_from_open_article(dest):
                        return {
                            "status": "downloaded_qje_cf_bypass",
                            "doi": doi,
                            "tried": "|".join(tried),
                        }
                li("QJE exact run_qje method did not complete, continuing to next URL")

            if journal.upper() == "JPE" and "journals.uchicago.edu" in url and "/doi/" in url:
                li("JPE article page detected, using run_qje-style browser + DOM method")
                if open_in_selenium(url, wait_for_cf=True):
                    if selenium_jpe_pdf_from_open_article(dest):
                        return {
                            "status": "downloaded_jpe_cf_bypass",
                            "doi": doi,
                            "tried": "|".join(tried),
                        }
                li("JPE run_qje-style method did not complete, continuing to next URL") # should be done in other module, soley on runqje.py | runjpe.py

            if fetch(url, dest, f"{journal}_VPN"):
                return {
                    "status": "downloaded_vpn",
                    "doi": doi,
                    "tried": "|".join(tried),
                }

    hint = f"https://doi.org/{doi}" if doi else ""
    return {
        "status": "MANUAL_NEEDED",
        "doi": doi or "",
        "hint": hint,
        "tried": "|".join(tried),
    }



def _series_from_handle(h: str) -> str:
    h = h.lower()
    if "nbr" in h:
        return "NBER"
    if "iza" in h:
        return "IZA"
    if "ces" in h:
        return "CESIFO"
    if "cpr" in h:
        return "CEPR"
    if "ssrn" in h:
        return "SSRN"
    if "bfi" in h:
        return "BFI"
    if "frb" in h or "frd" in h or "minneap" in h:
        return "FEDRESERVE"
    if "ucd" in h:
        return "UCD"
    if "hku" in h:
        return "HKUST"
    if "bos" in h:
        return "BOSTONCOLLEGE"
    if "cam" in h:
        return "CAMBRIDGE"
    if "econstor" in h:
        return "ECONSTOR"
    return ""


def repec_lookup(title: str, author_last: str, preferred_series: list[str] | None = None) -> dict:
    preferred_series = preferred_series or []

    try:
        r = SESSION.get(
            "https://api.repec.org/call.cgi",
            params={
                "code": "repecapi",
                "action": "search",
                "query": f"{title} {author_last}",
                "format": "json",
                "rows": 10,
            },
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get("items", [])

        best = None
        best_score = -1.0

        for item in items:
            item_title = item.get("title", "") or ""
            handle = item.get("handle", "") or ""
            found_series = normalize_series_name(_series_from_handle(handle))
            score = text_sim(title, item_title)

            authors_blob = str(item.get("authors", "") or "")
            if author_last.lower() in authors_blob.lower():
                score += 0.08

            if preferred_series and found_series in preferred_series:
                score += 0.12

            if score > best_score:
                best_score = score
                best = item

        if best and best_score >= 0.60:
            handle = best.get("handle", "")
            num = handle.split(":")[-1] if ":" in handle else ""
            return {
                "handle": handle,
                "paper_num": num,
                "pdf_url": best.get("file-url") or best.get("url") or "",
                "series": _series_from_handle(handle),
                "score": round(best_score, 3),
                "title": best.get("title", ""),
            }
    except Exception as e:
        log.debug(f"RePEc error: {e}")

    return {}


def ideas_search_url(title: str, author_last: str) -> str:
    q = quote_plus(f"{title} {author_last}")
    return f"https://ideas.repec.org/cgi-bin/htsearch?q={q}"


def nber_search_pdf(title: str) -> str | None:
    try:
        r = SESSION.get("https://www.nber.org/search", params={"q": title}, timeout=15)
        if r.status_code != 200:
            return None

        matches = re.findall(r'/papers/w(\d+)', r.text)
        if matches:
            for n in matches:
                return f"https://www.nber.org/papers/w{n}.pdf"
    except Exception:
        pass
    return None


def ssrn_search_abs(title: str) -> str | None:
    try:
        r = SESSION.get(
            "https://papers.ssrn.com/sol3/results.cfm",
            params={"txtKey_Words": title},
            timeout=15,
        )
        if r.status_code != 200:
            return None

        m = re.search(r'abstract_id=(\d+)', r.text)
        if m:
            return f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={m.group(1)}"
    except Exception:
        pass
    return None


def wp_candidate_urls(series: str, paper_num: str) -> list[str]:
    s = normalize_series_name(series)
    n = re.sub(r"^[wdp]+", "", str(paper_num).strip()) if paper_num else ""
    urls = []

    if "NBER" in s and n:
        urls += [
            f"https://www.nber.org/papers/w{n}.pdf",
            f"https://www.nber.org/system/files/working_papers/w{n}/w{n}.pdf",
        ]

    if "IZA" in s and n:
        urls += [
            f"https://docs.iza.org/dp{n}.pdf",
            f"https://ftp.iza.org/dp{n}.pdf",
        ]

    if ("CESIFO" in s or "CESINFO" in s) and n:
        urls += [
            f"https://www.cesifo.org/DocDL/cesifo1_wp{n}.pdf",
        ]

    if "SSRN" in s and n:
        urls += [
            f"https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID{n}_code.pdf",
            f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={n}",
        ]

    if "CEPR" in s and n:
        urls += [
            f"https://cepr.org/system/files/publication-files/dp{n}.pdf",
        ]

    return urls


def find_nber_paper_page(title: str) -> str | None:
    try:
        r = SESSION.get("https://www.nber.org/search", params={"q": title}, timeout=15)
        if r.status_code != 200:
            return None

        links = re.findall(r'href="(/papers/w\d+)"', r.text)
        seen = []
        for x in links:
            u = "https://www.nber.org" + x
            if u not in seen:
                seen.append(u)

        if seen:
            return seen[0]
    except Exception:
        pass
    return None


def nber_download_official(title: str, dest: Path) -> bool:
    try:
        downloader = get_nber_downloader()
        ok, note = downloader.download_by_title(title, dest)
        if ok:
            lok(f"Saved {dest.name} using NBER Selenium title search")
            return True
        li(f"NBER Selenium title-search failed: {note}")
    except Exception as e:
        lwarn(f"NBER Selenium module error: {e}")

    page = find_nber_paper_page(title)
    if not page:
        return False

    if fetch(page, dest, "NBER_page"):
        return True

    m = re.search(r'/papers/w(\d+)', page)
    if m:
        n = m.group(1)
        for u in [
            f"https://www.nber.org/papers/w{n}.pdf",
            f"https://www.nber.org/system/files/working_papers/w{n}/w{n}.pdf",
        ]:
            if fetch(u, dest, "NBER_direct"):
                return True

    return selenium_download_pdf(page, dest)


def find_iza_dp_page(title: str) -> str | None:
    try:
        r = SESSION.get("https://www.iza.org/search", params={"q": title}, timeout=15)
        if r.status_code != 200:
            return None

        links = re.findall(r'href="([^"]+/publications/dp/[^"]+)"', r.text)
        if links:
            return links[0]
    except Exception:
        pass
    return None


def iza_download_official(title: str, rp_num: str, dest: Path) -> bool:
    n = re.sub(r"^[wdp]+", "", str(rp_num).strip()) if rp_num else ""
    if n:
        for u in [f"https://docs.iza.org/dp{n}.pdf", f"https://ftp.iza.org/dp{n}.pdf"]:
            if fetch(u, dest, "IZA_direct"):
                return True

    page = find_iza_dp_page(title)
    if page:
        if fetch(page, dest, "IZA_page"):
            return True
        return selenium_download_pdf(page, dest)

    return False


def cesifo_download_official(title: str, rp_num: str, dest: Path) -> bool:
    n = re.sub(r"^[wdp]+", "", str(rp_num).strip()) if rp_num else ""
    if n:
        if fetch(f"https://www.cesifo.org/DocDL/cesifo1_wp{n}.pdf", dest, "CESIFO_direct"):
            return True

    try:
        r = SESSION.get("https://www.cesifo.org/en/search", params={"search_api_fulltext": title}, timeout=15)
        if r.status_code == 200:
            links = re.findall(r'href="([^"]+DocDL/[^"]+\.pdf)"', r.text)
            for u in links:
                full = absolutize("https://www.cesifo.org", u)
                if fetch(full, dest, "CESIFO_search"):
                    return True
    except Exception:
        pass

    return False


def ssrn_download_official(title: str, rp_num: str, dest: Path) -> bool:
    if rp_num:
        for u in [
            f"https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID{rp_num}_code.pdf",
            f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={rp_num}",
        ]:
            if fetch(u, dest, "SSRN_direct"):
                return True

    abs_url = ssrn_search_abs(title)
    if abs_url:
        if fetch(abs_url, dest, "SSRN_page"):
            return True
        return selenium_download_pdf(abs_url, dest)

    return False


def cepr_download_official(rp_num: str, dest: Path) -> bool:
    n = re.sub(r"^[wdp]+", "", str(rp_num).strip()) if rp_num else ""
    if not n:
        return False

    return fetch(f"https://cepr.org/system/files/publication-files/dp{n}.pdf", dest, "CEPR_direct")




def official_host_download(series: str, title: str, rp_num: str, dest: Path) -> tuple[bool, str]:
    s = normalize_series_name(series)
    

    if "NBER" in s:
        return nber_download_official(title, dest), "NBER"
    if "IZA" in s:
        return iza_download_official(title, rp_num, dest), "IZA"
    if "CESIFO" in s or "CESINFO" in s:
        return cesifo_download_official(title, rp_num, dest), "CESIFO"
    if "SSRN" in s:
        return ssrn_download_official(title, rp_num, dest), "SSRN"
    if "CEPR" in s:
        return cepr_download_official(rp_num, dest), "CEPR"

    return False, s







def download_wp(row: pd.Series, dest: Path) -> dict:
    if dest.exists():
        return {"status": "already_exists"}

    if not wp_available_flag(row):
        return {"status": "no_wp"}

    title = safe_str(row.get("paper_title", ""))
    last = safe_str(row.get("author1_last", ""))
    preferred_series = choose_preferred_series(row.get("wp_series", ""))
    wp_year = row.get("wp_year", None)
    wp_doi = safe_str(row.get("wp_doi", ""))
    tried = []

    if not title or not last:
        return {"status": "SKIP_missing_info"}

    li(f"Excel WP hints: series={preferred_series or 'none'} | wp_year={wp_year} | wp_doi={wp_doi or 'none'}")

    if wp_doi and doi_is_valid_working_paper(wp_doi):
        li(f"Excel WP DOI provided: {wp_doi}")
        wp_series = extract_wp_series_from_doi(wp_doi)
        
        if wp_series == "SSRN":
            ssrn_id = wp_doi.split(".")[-1]
            ssrn_url = f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}"
            tried.append(f"excel_ssrn_doi:{ssrn_url[:120]}")
            sleep()
            if fetch(ssrn_url, dest, f"Excel_SSRN_{ssrn_id}"):
                return {
                    "status": "downloaded_excel_wp_doi",
                    "wp_series_used": "SSRN",
                    "tried": "|".join(tried),
                }
        
        elif wp_series == "NBER":
            nber_id = wp_doi.split("w")[-1]
            nber_url = f"https://www.nber.org/papers/w{nber_id}.pdf"
            tried.append(f"excel_nber_doi:{nber_url[:120]}")
            sleep()
            if fetch(nber_url, dest, f"Excel_NBER_w{nber_id}"):
                return {
                    "status": "downloaded_excel_wp_doi",
                    "wp_series_used": "NBER",
                    "tried": "|".join(tried),
                }

    sleep()
    rp = repec_lookup(title, last, preferred_series=preferred_series)
    rp_pdf = rp.get("pdf_url", "")
    rp_num = rp.get("paper_num", "")
    rp_series = normalize_series_name(rp.get("series", ""))

    li(
        f"RePEc matched: series={rp_series or '?'} | "
        f"num={rp_num or '?'} | score={rp.get('score', '?')} | "
        f"title={rp.get('title', '')[:80]}"
    )

    candidate_series = preferred_series.copy()
    if rp_series and rp_series not in candidate_series:
        candidate_series.append(rp_series)

    candidate_series = sorted(set(candidate_series), key=series_rank, reverse=True)

    for series in candidate_series:
        tried.append(f"official_host:{series}")
        sleep()
        ok, used_series = official_host_download(series, title, rp_num, dest)
        if ok:
            return {
                "status": f"downloaded_{used_series.lower()}_official",
                "wp_series_used": used_series,
                "tried": "|".join(tried),
            }

    if rp_pdf:
        tried.append(f"repec_direct:{rp_pdf[:120]}")
        sleep()
        if fetch(rp_pdf, dest, "repec_direct"):
            return {
                "status": "downloaded_repec_direct",
                "wp_series_used": rp_series,
                "tried": "|".join(tried),
            }

    for series in candidate_series:
        for url in wp_candidate_urls(series, rp_num):
            tried.append(f"{series}:{url[:120]}")
            sleep()
            if fetch(url, dest, f"WP_{series}"):
                return {
                    "status": f"downloaded_{series.lower()}",
                    "wp_series_used": series,
                    "tried": "|".join(tried),
                }

    for series in ["NBER", "IZA", "CESIFO", "SSRN"]:
        if series not in candidate_series:
            tried.append(f"title_fallback:{series}")
            sleep()
            ok, used_series = official_host_download(series, title, rp_num, dest)
            if ok:
                return {
                    "status": f"downloaded_{used_series.lower()}_title_fallback",
                    "wp_series_used": used_series,
                    "tried": "|".join(tried),
                }

    sleep()
    ss = semantic_scholar_url(title, last)
    if ss:
        tried.append(f"s2:{ss[:120]}")
        if fetch(ss, dest, "SemanticScholar_WP"):
            return {
                "status": "downloaded_s2_wp",
                "tried": "|".join(tried),
            }

    if not rp_num:
        li("No WP paper number found")
    if not candidate_series:
        li("No WP series hint available from Excel/RePEc")

    return {
        "status": "MANUAL_NEEDED",
        "hint": ideas_search_url(title, last),
        "tried": "|".join(tried),
    }


def run_downloads():
    vpn_ok = vpn_connect()
    if not vpn_ok:
        lerr("WireGuard is required for this workflow. Stopping")
        sys.exit(1)

    time.sleep(3)
    lok("VPN is up. Starting downloads: AER → QJE → JPE → Others → WP (All with Fresh Profiles)")

    def on_interrupt(sig, frame):
        lwarn("Interrupted. Closing browser and disconnecting VPN")
        close_driver()
        vpn_disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_interrupt)

    try:
        xl = pd.read_excel(INPUT_FILE, sheet_name=None)

        all_work_rows = []

        for sheet_name, df in xl.items():
            li("=" * 80)
            li(f"Sheet: {sheet_name} ({len(df)} rows)")
            li("=" * 80)

            for _, row in df.iterrows():
                journal = safe_str(row.get("journal", "") or sheet_name).upper().strip()
                year_pub = parse_year(row.get("year_pub", None))

                if TARGET_YEARS and year_pub not in TARGET_YEARS:
                    continue
                if TARGET_JOURNALS and journal not in TARGET_JOURNALS:
                    continue

                row_id = safe_str(row.get("id") or f"{sheet_name}_unknown")
                year_str = str(year_pub or "")
                last = safe_str(row.get("author1_last", ""))
                title = safe_str(row.get("paper_title", ""))

                base = sanitize_filename(f"{journal}_{year_str}_{last}")
                art_dest = ARTICLE_DIR / f"{base}_Article.pdf"
                wp_dest = WP_DIR / f"{base}_WP.pdf"

                all_work_rows.append({
                    "sheet": sheet_name,
                    "row": row,
                    "id": row_id,
                    "title": title,
                    "journal": journal,
                    "year_pub": year_pub,
                    "art_dest": art_dest,
                    "wp_dest": wp_dest,
                })

        li(f"Total filtered rows to process: {len(all_work_rows)}\n")

        all_logs = {}

        
        
        aer_rows = [r for r in all_work_rows if r["journal"] == "AER"]
        
        if aer_rows:
            li("-" * 80)
            li(f"PHASE 1: DOWNLOADING AER ARTICLES ({len(aer_rows)} papers) - STEALTH MODE")
            li("-" * 80)

            for item in tqdm(aer_rows, total=len(aer_rows), desc="AER Articles"):
                row = item["row"]
                row_id = item["id"]
                title = item["title"]
                journal = item["journal"]
                year_pub = item["year_pub"]
                art_dest = item["art_dest"]
                wp_dest = item["wp_dest"]
                sheet_name = item["sheet"]

                li(f"\nAER {row_id} | {title[:90]}")
                art = download_article(row, art_dest)
                sleep()

                all_logs[row_id] = {
                    "sheet": sheet_name,
                    "id": row_id,
                    "title": title[:150],
                    "journal": journal,
                    "year_pub": year_pub,
                    "art_status": art.get("status", ""),
                    "art_doi": art.get("doi", ""),
                    "art_hint": art.get("hint", ""),
                    "art_tried": art.get("tried", ""),
                    "art_file": str(art_dest),
                    "wp_status": "",
                    "wp_series_used": "",
                    "wp_hint": "",
                    "wp_tried": "",
                    "wp_file": str(wp_dest),
                    "excel_wp_yes": safe_str(row.get("wp_yes", "")),
                    "excel_wp_doi": safe_str(row.get("wp_doi", "")),
                    "excel_wp_series": safe_str(row.get("wp_series", "")),
                    "excel_wp_year": safe_str(row.get("wp_year", "")),
                }

            li(f"\n AER phase complete ({len(aer_rows)} papers)\n")

        cleanup_between_phases("AER")

        
        qje_rows = [r for r in all_work_rows if r["journal"] == "QJE"]
        
        if qje_rows:
            li("-" * 80)
            li(f"PHASE 2: DOWNLOADING QJE ARTICLES ({len(qje_rows)} papers) - STEALTH MODE + CF")
            li("-" * 80)

            for item in tqdm(qje_rows, total=len(qje_rows), desc="QJE Articles"):
                row = item["row"]
                row_id = item["id"]
                title = item["title"]
                journal = item["journal"]
                year_pub = item["year_pub"]
                art_dest = item["art_dest"]
                wp_dest = item["wp_dest"]
                sheet_name = item["sheet"]

                li(f"\nQJE {row_id} | {title[:90]}")
                art = download_article(row, art_dest)
                sleep()

                all_logs[row_id] = {
                    "sheet": sheet_name,
                    "id": row_id,
                    "title": title[:150],
                    "journal": journal,
                    "year_pub": year_pub,
                    "art_status": art.get("status", ""),
                    "art_doi": art.get("doi", ""),
                    "art_hint": art.get("hint", ""),
                    "art_tried": art.get("tried", ""),
                    "art_file": str(art_dest),
                    "wp_status": "",
                    "wp_series_used": "",
                    "wp_hint": "",
                    "wp_tried": "",
                    "wp_file": str(wp_dest),
                    "excel_wp_yes": safe_str(row.get("wp_yes", "")),
                    "excel_wp_doi": safe_str(row.get("wp_doi", "")),
                    "excel_wp_series": safe_str(row.get("wp_series", "")),
                    "excel_wp_year": safe_str(row.get("wp_year", "")),
                }

            li(f"\n QJE phase complete ({len(qje_rows)} papers)\n")

        cleanup_between_phases("QJE")

        
        
        jpe_rows = [r for r in all_work_rows if r["journal"] == "JPE"]
        
        if jpe_rows:
            li("-" * 80)
            li(f"PHASE 3: DOWNLOADING JPE ARTICLES ({len(jpe_rows)} papers) - STEALTH MODE + CF")
            li("-" * 80)

            for item in tqdm(jpe_rows, total=len(jpe_rows), desc="JPE Articles"):
                row = item["row"]
                row_id = item["id"]
                title = item["title"]
                journal = item["journal"]
                year_pub = item["year_pub"]
                art_dest = item["art_dest"]
                wp_dest = item["wp_dest"]
                sheet_name = item["sheet"]

                li(f"\nJPE {row_id} | {title[:90]}")
                art = download_article(row, art_dest)
                sleep()

                all_logs[row_id] = {
                    "sheet": sheet_name,
                    "id": row_id,
                    "title": title[:150],
                    "journal": journal,
                    "year_pub": year_pub,
                    "art_status": art.get("status", ""),
                    "art_doi": art.get("doi", ""),
                    "art_hint": art.get("hint", ""),
                    "art_tried": art.get("tried", ""),
                    "art_file": str(art_dest),
                    "wp_status": "",
                    "wp_series_used": "",
                    "wp_hint": "",
                    "wp_tried": "",
                    "wp_file": str(wp_dest),
                    "excel_wp_yes": safe_str(row.get("wp_yes", "")),
                    "excel_wp_doi": safe_str(row.get("wp_doi", "")),
                    "excel_wp_series": safe_str(row.get("wp_series", "")),
                    "excel_wp_year": safe_str(row.get("wp_year", "")),
                }

            li(f"\n JPE phase complete ({len(jpe_rows)} papers)\n")

        cleanup_between_phases("JPE")

        
        
        other_rows = [r for r in all_work_rows if r["journal"] not in ["AER", "QJE", "JPE"]]
        
        if other_rows:
            li("-" * 80)
            li(f"PHASE 4: DOWNLOADING OTHER ARTICLES ({len(other_rows)} papers) - STEALTH MODE")
            li("-" * 80)

            for item in tqdm(other_rows, total=len(other_rows), desc="Other Articles"):
                row = item["row"]
                row_id = item["id"]
                title = item["title"]
                journal = item["journal"]
                year_pub = item["year_pub"]
                art_dest = item["art_dest"]
                wp_dest = item["wp_dest"]
                sheet_name = item["sheet"]

                li(f"\n{journal} {row_id} | {title[:90]}")
                art = download_article(row, art_dest)
                sleep()

                all_logs[row_id] = {
                    "sheet": sheet_name,
                    "id": row_id,
                    "title": title[:150],
                    "journal": journal,
                    "year_pub": year_pub,
                    "art_status": art.get("status", ""),
                    "art_doi": art.get("doi", ""),
                    "art_hint": art.get("hint", ""),
                    "art_tried": art.get("tried", ""),
                    "art_file": str(art_dest),
                    "wp_status": "",
                    "wp_series_used": "",
                    "wp_hint": "",
                    "wp_tried": "",
                    "wp_file": str(wp_dest),
                    "excel_wp_yes": safe_str(row.get("wp_yes", "")),
                    "excel_wp_doi": safe_str(row.get("wp_doi", "")),
                    "excel_wp_series": safe_str(row.get("wp_series", "")),
                    "excel_wp_year": safe_str(row.get("wp_year", "")),
                }

            li(f"\n Other phase complete ({len(other_rows)} papers)\n")

        cleanup_between_phases("Other Journals")

        
        
        li("-" * 80)
        li(f"PHASE 5: DOWNLOADING WORKING PAPERS (all journals) - STEALTH MODE")
        li("-" * 80)
        
        try:
            get_nber_downloader()
        except Exception as e:
            lwarn(f"NBER session could not be prepared at WP phase start: {e}")

        for item in tqdm(all_work_rows, total=len(all_work_rows), desc="Working Papers"):
            row = item["row"]
            row_id = item["id"]
            title = item["title"]

            if not wp_available_flag(row):
                continue

            li(f"\nWP {row_id} | {title[:90]}")
            wp = download_wp(row, item["wp_dest"])
            sleep()

            if row_id in all_logs:
                all_logs[row_id]["wp_status"] = wp.get("status", "")
                all_logs[row_id]["wp_series_used"] = wp.get("wp_series_used", "")
                all_logs[row_id]["wp_hint"] = wp.get("hint", "")
                all_logs[row_id]["wp_tried"] = wp.get("tried", "")

        li(f"\n Working paper phase complete\n")

        

        log_df = pd.DataFrame(list(all_logs.values()))
        log_df.to_csv(LOG_FILE, index=False)

        art_ok = log_df["art_status"].fillna("").str.startswith("downloaded").sum()
        art_ex = (log_df["art_status"] == "already_exists").sum()
        art_man = log_df["art_status"].fillna("").str.startswith("MANUAL").sum()

        wp_ok = log_df["wp_status"].fillna("").str.startswith("downloaded").sum()
        wp_ex = (log_df["wp_status"] == "already_exists").sum()
        wp_man = log_df["wp_status"].fillna("").str.startswith("MANUAL").sum()
        wp_none = (log_df["wp_status"] == "no_wp").sum()

        processed = len(log_df)
        ratio = round((wp_ok / art_ok) * 100, 2) if art_ok else 0.0

        li("")
        li("=" * 80)
        li("DOWNLOAD SUMMARY")
        li("=" * 80)
        li(f"Processed rows: {processed}")
        li(f"  AER:    {len(aer_rows) if aer_rows else 0}")
        li(f"  QJE:    {len(qje_rows) if qje_rows else 0}")
        li(f"  JPE:    {len(jpe_rows) if jpe_rows else 0}")
        li(f"  Other:  {len(other_rows) if other_rows else 0}")
        li("")
        li(f"Articles downloaded: {art_ok}")
        li(f"Articles already existed: {art_ex}")
        li(f"Articles manual needed: {art_man}")
        li("")
        li(f"Working papers downloaded: {wp_ok}")
        li(f"Working papers already existed: {wp_ex}")
        li(f"Working papers no WP available: {wp_none}")
        li(f"Working papers manual needed: {wp_man}")
        li(f"WP to Article ratio: {ratio}%")
        li(f"Log file: {LOG_FILE}")
        li("=" * 80)

        manual = log_df[
            log_df["art_status"].fillna("").str.startswith("MANUAL") |
            log_df["wp_status"].fillna("").str.startswith("MANUAL")
        ].copy()

        if not manual.empty:
            manual["art_url"] = manual["art_doi"].apply(
                lambda d: f"https://doi.org/{d}" if d else ""
            )
            manual["wp_url"] = manual["wp_hint"]
            manual[
                ["sheet", "id", "title", "journal", "year_pub",
                 "art_status", "art_url",
                 "wp_status", "wp_series_used", "wp_url"]
            ].to_csv(MANUAL_FILE, index=False)

            li(f"Manual downloads list saved to {MANUAL_FILE} with {len(manual)} rows")

    finally:
        li("\n[FINAL CLEANUP] Closing all resources...")
        close_nber_downloader()
        close_driver()
        kill_leftover_chrome_processes()
        vpn_disconnect()
        lok("Download workflow complete")







if __name__ == "__main__":
    run_downloads()
    
    
    
    


    """task summary:
    test 
    1- async - await 
    2- concurrent.futures - mapping method
    3- decrease time < 20 mins -
    
    """
