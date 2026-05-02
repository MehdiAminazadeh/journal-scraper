import os
import re
import time
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


NBER_URL = "https://www.nber.org/"
NBER_SEARCH_URL = "https://www.nber.org/search"


def _norm_text(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _text_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm_text(a), _norm_text(b)).ratio()


class NBERWorkingPaperDownloader:
    """
    Persistent Selenium session for NBER working-paper downloads.

    Workflow:
    
    
    - start one browser session
    - optionally auto-login using env vars
    - user can finish login manually once
    
    """

    def __init__(
        self,
        download_dir: Path,
        *,
        headless: bool = False,
        wait_seconds: int = 12,
        login_wait_seconds: int = 12,
        search_wait_seconds: float = 2.0,
        page_wait_seconds: float = 2.0,
        download_timeout: int = 60,
        similarity_threshold: float = 0.50,
    ):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.headless = headless
        self.wait_seconds = wait_seconds
        self.login_wait_seconds = login_wait_seconds
        self.search_wait_seconds = search_wait_seconds
        self.page_wait_seconds = page_wait_seconds
        self.download_timeout = download_timeout
        self.similarity_threshold = similarity_threshold

        self.driver = None
        self.wait = None
        self.session_prepared = False

    def _build_driver(self) -> webdriver.Chrome:
        options = Options()

        if self.headless:
            options.add_argument("--headless=new")

        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        prefs = {
            "download.default_directory": str(self.download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )
        return driver

    def start(self):
        if self.driver is not None:
            return

        self.driver = self._build_driver()
        self.wait = WebDriverWait(self.driver, self.wait_seconds)

    def close(self):
        try:
            if self.driver is not None:
                self.driver.quit()
        except Exception:
            pass
        finally:
            self.driver = None
            self.wait = None
            self.session_prepared = False

    def _safe_click(self, by: By, selector: str) -> bool:
        try:
            elem = self.wait.until(EC.element_to_be_clickable((by, selector)))
            elem.click()
            return True
        except Exception:
            return False

    def _safe_send_keys(self, by: By, selector: str, text: str) -> bool:
        try:
            elem = self.wait.until(EC.presence_of_element_located((by, selector)))
            elem.clear()
            elem.send_keys(text)
            return True
        except Exception:
            return False

    def _try_accept_cookies(self) -> None:
        possible_buttons = [
            (By.XPATH, "//button[contains(., 'Accept')]"),
            (By.XPATH, "//button[contains(., 'I agree')]"),
            (By.XPATH, "//button[contains(., 'Agree')]"),
            (By.XPATH, "//a[contains(., 'Accept')]"),
        ]

        for by, sel in possible_buttons:
            try:
                btn = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((by, sel))
                )
                btn.click()
                return
            except Exception:
                pass

    def _open_login_page(self) -> None:
        self.driver.get(NBER_URL)
        self._try_accept_cookies()

        login_selectors = [
            (By.XPATH, "//a[contains(., 'Log in')]"),
            (By.XPATH, "//a[contains(., 'Login')]"),
            (By.XPATH, "//a[contains(., 'Sign in')]"),
            (By.XPATH, "//button[contains(., 'Log in')]"),
            (By.XPATH, "//button[contains(., 'Sign in')]"),
            (By.CSS_SELECTOR, "a[href*='login']"),
            (By.CSS_SELECTOR, "a[href*='sign-in']"),
        ]

        for by, sel in login_selectors:
            try:
                elem = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((by, sel))
                )
                elem.click()
                return
            except Exception:
                continue

    def _fill_login_form(self, email: str, password: str) -> bool:
        email_selectors = [
            (By.NAME, "email"),
            (By.NAME, "username"),
            (By.ID, "email"),
            (By.ID, "username"),
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.CSS_SELECTOR, "input[name*='email']"),
            (By.CSS_SELECTOR, "input[name*='user']"),
        ]

        password_selectors = [
            (By.NAME, "password"),
            (By.ID, "password"),
            (By.CSS_SELECTOR, "input[type='password']"),
            (By.CSS_SELECTOR, "input[name*='pass']"),
        ]

        email_filled = False
        password_filled = False

        for by, sel in email_selectors:
            if self._safe_send_keys(by, sel, email):
                email_filled = True
                break

        for by, sel in password_selectors:
            if self._safe_send_keys(by, sel, password):
                password_filled = True
                break

        if not email_filled or not password_filled:
            return False

        submit_selectors = [
            (By.XPATH, "//button[@type='submit']"),
            (By.XPATH, "//input[@type='submit']"),
            (By.XPATH, "//button[contains(., 'Log in')]"),
            (By.XPATH, "//button[contains(., 'Login')]"),
            (By.XPATH, "//button[contains(., 'Sign in')]"),
        ]

        for by, sel in submit_selectors:
            if self._safe_click(by, sel):
                return True

        for by, sel in password_selectors:
            try:
                elem = self.driver.find_element(by, sel)
                elem.send_keys(Keys.ENTER)
                return True
            except Exception:
                continue

        return False

    def prepare_session(self):
        """
        opens the browser once for NBER WP phase.
        tries auto-login from env vars, then leaves a short window
        for manual confirmation or manual login completion.
        """
        
        if self.session_prepared:
            return

        self.start()
        self._open_login_page()

        email = os.getenv("NBER_EMAIL", "").strip()
        password = os.getenv("NBER_PASSWORD", "").strip()

        if email and password:
            try:
                self._fill_login_form(email, password)
                time.sleep(3)
            except Exception:
                pass

        print("\n[NBER] Browser opened for working-paper session.")
        print("[NBER] If login is not complete, finish it manually now.")
        print(f"[NBER] Waiting {self.login_wait_seconds} seconds before continuing...\n")
        time.sleep(self.login_wait_seconds)

        self.session_prepared = True

    def _collect_candidate_links(self):
        candidates = []
        link_elems = self.driver.find_elements(By.XPATH, "//a[@href]")

        for a in link_elems:
            try:
                href = a.get_attribute("href") or ""
                text = a.text.strip()
                if not text:
                    continue
                if "/papers/w" in href:
                    candidates.append((text, href))
            except Exception:
                continue

        unique = []
        seen = set()
        for item in candidates:
            if item not in seen:
                seen.add(item)
                unique.append(item)

        return unique

    def _choose_best_result(self, results, target_title: str):
        best = None
        best_score = -1.0

        for text, href in results:
            score = _text_sim(text, target_title)
            if score > best_score:
                best_score = score
                best = (text, href, score)

        return best

    def _find_pdf_link(self):
        pdf_link_candidates = [
            (By.XPATH, "//a[contains(@href, '.pdf')]"),
            (By.XPATH, "//a[contains(translate(., 'PDF', 'pdf'), 'pdf')]"),
            (By.XPATH, "//a[contains(@href, '/system/files/working_papers/')]"),
        ]

        for by, sel in pdf_link_candidates:
            elems = self.driver.find_elements(by, sel)
            for elem in elems:
                try:
                    href = elem.get_attribute("href") or ""
                    text = elem.text.strip().lower()
                    if ".pdf" in href.lower() or "pdf" in text:
                        return elem, href
                except Exception:
                    continue

        return None, None

    def _wait_for_download(self, timeout: int | None = None):
        timeout = timeout or self.download_timeout
        start = time.time()
        existing = {p.resolve() for p in self.download_dir.glob("*.pdf")}

        while time.time() - start < timeout:
            crdownloads = list(self.download_dir.glob("*.crdownload"))
            pdfs = [p for p in self.download_dir.glob("*.pdf") if p.resolve() not in existing]

            if not crdownloads and pdfs:
                return max(pdfs, key=lambda p: p.stat().st_mtime)

            time.sleep(0.8)

        return None

    def download_by_title(self, title: str, dest: Path) -> tuple[bool, str]:
        """
        Returns (success, note).
        """
        dest = Path(dest)

        if dest.exists():
            return True, "already_exists"

        if self.driver is None:
            self.prepare_session()

        search_url = f"{NBER_SEARCH_URL}?q={quote_plus(title)}"
        self.driver.get(search_url)
        time.sleep(self.search_wait_seconds)

        results = self._collect_candidate_links()
        if not results:
            return False, "no_search_results"

        best = self._choose_best_result(results, title)
        if best is None:
            return False, "no_best_result"

        best_text, best_href, best_score = best
        if best_score < self.similarity_threshold:
            return False, f"low_similarity:{best_score:.3f}"

        self.driver.get(best_href)
        time.sleep(self.page_wait_seconds)

        pdf_elem, pdf_href = self._find_pdf_link()
        if pdf_elem is None:
            return False, "pdf_link_not_found"

        try:
            self.driver.execute_script("arguments[0].click();", pdf_elem)
        except Exception:
            try:
                self.driver.get(pdf_href)
            except Exception:
                return False, "pdf_click_failed"

        downloaded = self._wait_for_download()
        if not downloaded:
            return False, "download_not_detected"

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest.unlink()
            downloaded.replace(dest)
            return True, f"downloaded:{best_href}"
        except Exception as e:
            return False, f"rename_failed:{e}"
























