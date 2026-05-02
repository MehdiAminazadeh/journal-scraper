import shutil
import time
import requests
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from urllib.parse import urljoin
from chrome_manager import ChromeSession
from config import WP_DIR
from matcher import strict_match
from models import SourceResult
from sources._job_utils import wait_for_new_pdf


class CEPRJob:
    name = "cepr"

    def __init__(self):
        self.session = ChromeSession("cepr", WP_DIR / "_cepr_tmp", persistent=False)

    def _save_pdf_from_url(self, url, task):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=60,
                allow_redirects=True,
            )

            content_type = r.headers.get("content-type", "").lower()

            if r.status_code == 200 and (
                r.content[:4] == b"%PDF" or "application/pdf" in content_type
            ):
                dest = Path(task.wp_file)
                dest.parent.mkdir(parents=True, exist_ok=True)

                if dest.exists():
                    dest.unlink()
                # resolve the cepr download link through ancestor tags
                dest.write_bytes(r.content)
                return True

        except Exception:
            pass

        return False

    def _download_from_article_page(self, driver, task, candidate_title, ts, aus):
        current_url = driver.current_url
        before = set(self.session.download_dir.glob("*.pdf"))

        selectors = [
            "//a[contains(@href, '/system/files/publication-files/') and contains(@href, '.pdf')]",
            "//a[contains(@class, 'o-button') and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download')]",
            "//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download') and contains(@href, '.pdf')]",
            "//a[contains(@href, '.pdf')]",
        ]
        #css needed to click, otherwise try href of each children
        for selector in selectors:
            try:
                buttons = driver.find_elements(By.XPATH, selector)

                for button in buttons:
                    try:
                        href = button.get_attribute("href") or ""

                        if href:
                            href = urljoin("https://cepr.org", href)

                        if href and ".pdf" in href.lower():
                            if self._save_pdf_from_url(href, task):
                                return SourceResult(
                                    source=self.name,
                                    status="downloaded",
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
                        # scroll needs full detection of appearing elements 
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});",
                            button,
                        )
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
                                status="downloaded",
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
            status="download_button_not_found",
            found=True,
            candidate_title=candidate_title,
            title_score=ts,
            author_score=aus,
            url=current_url,
            error="cepr_pdf_link_or_download_button_not_found",
        )

    def search_and_download(self, task):
        if Path(task.wp_file).exists():
            return SourceResult(
                source=self.name,
                status="already_exists",
                found=True,
                downloaded=True,
                file=task.wp_file,
            )

        try:
            driver = self.session.start()

            if not self.session.alive():
                driver = self.session.reset()

            self.session.close_extra_tabs()

            driver.get("https://cepr.org/publications/discussion-papers")
            time.sleep(2)

            search_inputs = driver.find_elements(
                By.XPATH,
                "//input[@type='search' or @name='search' or contains(@class, 'search')]"
            )

            search_box = None

            for box in search_inputs:
                try:
                    if box.is_displayed() and box.is_enabled():
                        search_box = box
                        break
                except Exception:
                    continue

            if search_box is None:
                return SourceResult(
                    source=self.name,
                    status="search_input_not_found",
                    error="cepr_search_input_not_found",
                )

            search_box.clear()
            search_box.send_keys(task.title)
            time.sleep(0.5)

            search_buttons = driver.find_elements(
                By.XPATH,
                "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'search')] | "
                "//input[@type='submit']"
            )

            clicked = False

            for button in search_buttons:
                try:
                    if button.is_displayed() and button.is_enabled():
                        driver.execute_script("arguments[0].click();", button)
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                search_box.send_keys(Keys.ENTER)

            time.sleep(4)

            links = driver.find_elements(By.XPATH, "//a[@href]")
            best = None

            for link in links:
                try:
                    candidate_title = link.text.strip()
                    href = link.get_attribute("href") or ""

                    if not candidate_title:
                        continue

                    if "/publications/" not in href and "/dp" not in href.lower():
                        continue

                    block_text = candidate_title

                    try:
                        block = link.find_element(
                            By.XPATH,
                            "./ancestor::*[self::article or self::div][1]",
                        )
                        block_text = block.text.strip()
                    except Exception:
                        pass

                    ok, ts, aus = strict_match(
                        task.title,
                        candidate_title,
                        block_text,
                        task.authors,
                    )

                    current = (ok, ts, aus, candidate_title, href, link)

                    if best is None or ts + aus > best[1] + best[2]:
                        best = current

                except Exception:
                    continue

            if best is None:
                return SourceResult(
                    source=self.name,
                    status="not_found",
                    error="no_cepr_results",
                )

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

            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});",
                link,
            )
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", link)
            time.sleep(3)

            return self._download_from_article_page(
                driver,
                task,
                candidate_title,
                ts,
                aus,
            )

        except Exception as exc:
            return SourceResult(
                source=self.name,
                status="error",
                error=str(exc),
            )

    def close(self):
        self.session.close()