import shutil
import time
import requests
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from urllib.parse import urlparse
from chrome_manager import ChromeSession
from config import WP_DIR
from matcher import strict_match
from models import SourceResult
from sources._job_utils import wait_for_new_pdf

    """
    problem with uchicago redirection : bypass anti-detect bot 
    add redirected website to code
    """



class IDEASJob:
    name = "ideas"

    def __init__(self):
        self.session = ChromeSession("ideas", WP_DIR / "_ideas_tmp", persistent=False)

    def _save_pdf_from_url(self, url, task):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=60,
                allow_redirects=True,
            )
            content_type = r.headers.get("content-type", "").lower()
            if r.status_code == 200 and (r.content[:4] == b"%PDF" or "application/pdf" in content_type):
                dest = Path(task.wp_file)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest.unlink()
                dest.write_bytes(r.content)
                return True
        except Exception:
            pass
        return False

    def _download_from_cepr_page(self, driver, task, candidate_title, ts, aus):
        current_url = driver.current_url
        before = set(self.session.download_dir.glob("*.pdf"))

        selectors = [
            "//a[contains(@href, '/system/files/publication-files/') and contains(@href, '.pdf')]",
            "//a[contains(@class, 'o-button') and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download')]",
            "//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') and contains(@href, '.pdf')]",
        ]

        for selector in selectors:
            try:
                buttons = driver.find_elements(By.XPATH, selector)
                for button in buttons:
                    try:
                        href = button.get_attribute("href") or ""
                        if href.startswith("/"):
                            href = "https://cepr.org" + href

                        if href and ".pdf" in href.lower():
                            if self._save_pdf_from_url(href, task):
                                return SourceResult(
                                    source=self.name,
                                    status="downloaded_cepr_redirect",
                                    found=True,
                                    downloaded=True,
                                    file=task.wp_file,
                                    candidate_title=candidate_title,
                                    title_score=ts,
                                    author_score=aus,
                                    url=href,
                                )

                        if not button.is_displayed():
                            continue

                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", button)
                        time.sleep(4)

                        pdf = wait_for_new_pdf(self.session.download_dir, before, 35)
                        if pdf:
                            dest = Path(task.wp_file)
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            if dest.exists():
                                dest.unlink()
                            shutil.move(str(pdf), str(dest))
                            return SourceResult(
                                source=self.name,
                                status="downloaded_cepr_redirect",
                                found=True,
                                downloaded=True,
                                file=task.wp_file,
                                candidate_title=candidate_title,
                                title_score=ts,
                                author_score=aus,
                                url=current_url,
                            )
                    except Exception:
                        continue
            except Exception:
                continue

        return SourceResult(
            source=self.name,
            status="cepr_redirect_download_not_found",
            found=True,
            candidate_title=candidate_title,
            title_score=ts,
            author_score=aus,
            url=current_url,
            error="cepr_download_button_or_pdf_not_found",
        )

    def search_and_download(self, task):
        if Path(task.wp_file).exists():
            return SourceResult(source=self.name, status="already_exists", found=True, downloaded=True, file=task.wp_file)

        try:
            driver = self.session.start()

            if not self.session.alive():
                driver = self.session.reset()

            self.session.close_extra_tabs()

            driver.get("https://ideas.repec.org/")
            time.sleep(2)

            box = driver.find_element(By.CSS_SELECTOR, "input[placeholder*='Search econ literature on IDEAS']")
            box.clear()
            box.send_keys(task.title)
            box.send_keys(Keys.ENTER)
            time.sleep(4)

            items = driver.find_elements(By.CSS_SELECTOR, "li.list-group-item")
            best = None

            for item in items:
                try:
                    link = item.find_element(By.CSS_SELECTOR, "a[href]")
                    candidate_title = link.text.strip()
                    text = item.text.strip()
                    ok, ts, aus = strict_match(task.title, candidate_title, text, task.authors)
                    href = link.get_attribute("href") or ""
                    current = (ok, ts, aus, candidate_title, href, link)

                    if best is None or ts + aus > best[1] + best[2]:
                        best = current
                except Exception:
                    continue

            if best is None:
                return SourceResult(source=self.name, status="not_found", error="no_results")

            ok, ts, aus, candidate_title, href, link = best

            if not ok:
                return SourceResult(
                    source=self.name,
                    status="not_found",
                    candidate_title=candidate_title,
                    title_score=ts,
                    author_score=aus,
                    url=href,
                    error="strict_match_failed",
                )

            old = driver.window_handles[:]
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
            driver.execute_script("arguments[0].click();", link)
            time.sleep(3)

            handles = driver.window_handles
            if len(handles) > len(old):
                driver.switch_to.window(handles[-1])

            domain = urlparse(driver.current_url).netloc.lower()

            if "cepr.org" in domain:
                return self._download_from_cepr_page(driver, task, candidate_title, ts, aus)

            if "ideas.repec.org" not in domain and "repec.org" not in domain:
                return SourceResult(
                    source=self.name,
                    status="redirected_external_unsupported",
                    found=True,
                    candidate_title=candidate_title,
                    title_score=ts,
                    author_score=aus,
                    url=driver.current_url,
                    error=f"unsupported_redirect_domain:{domain}",
                )

            try:
                tab = driver.find_element(By.XPATH, "//a[@id='download-tab' and @href='#download']")
                panel = driver.find_element(By.ID, "download")
                driver.execute_script("arguments[0].click();", tab)
                time.sleep(1)
                driver.execute_script(
                    "arguments[0].classList.add('active'); arguments[1].classList.add('active'); arguments[1].classList.add('show');",
                    tab,
                    panel,
                )
            except Exception:
                return SourceResult(
                    source=self.name,
                    status="download_tab_not_found",
                    candidate_title=candidate_title,
                    title_score=ts,
                    author_score=aus,
                    url=driver.current_url,
                )

            before = set(self.session.download_dir.glob("*.pdf"))
            buttons = driver.find_elements(
                By.XPATH,
                "//input[contains(@value, 'Download the selected file')] | //button[contains(., 'Download the selected file')] | //a[contains(., 'Download the selected file')]",
            )

            for button in buttons:
                try:
                    if not button.is_displayed():
                        continue

                    driver.execute_script("arguments[0].click();", button)
                    time.sleep(3)

                    pdf = wait_for_new_pdf(self.session.download_dir, before, 25)

                    if pdf:
                        dest = Path(task.wp_file)
                        dest.parent.mkdir(parents=True, exist_ok=True)

                        if dest.exists():
                            dest.unlink()

                        shutil.move(str(pdf), str(dest))

                        return SourceResult(
                            source=self.name,
                            status="downloaded",
                            found=True,
                            downloaded=True,
                            file=task.wp_file,
                            candidate_title=candidate_title,
                            title_score=ts,
                            author_score=aus,
                            url=driver.current_url,
                        )
                except Exception:
                    continue

            return SourceResult(
                source=self.name,
                status="download_not_detected",
                found=True,
                candidate_title=candidate_title,
                title_score=ts,
                author_score=aus,
                url=driver.current_url,
            )

        except Exception as exc:
            return SourceResult(source=self.name, status="error", error=str(exc))

    def close(self):
        self.session.close()