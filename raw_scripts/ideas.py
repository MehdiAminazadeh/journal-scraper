






































































    
    











































































    














































































from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from difflib import SequenceMatcher
from urllib.parse import urlparse
import re
import csv
import time
from pathlib import Path


SEARCHES = [
    {
        "title": "Retail Pharmacies and Drug Diversion during the Opioid Epidemic",
        "authors": ["Janssen", "Zhang"],
    },
    {
        "title": "Board Specific Attributes and Financial Reporting Quality of Listed Consumer Goods Firms in Nigeria",
        "authors": ["Okeke"],
    },
]

TITLE_THRESHOLD = 0.88
AUTHOR_THRESHOLD = 1.00
WAIT_SHORT = 2
WAIT_MED = 3
WAIT_LONG = 8

DOWNLOAD_DIR = Path("ideas_downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

LOG_FILE = "ideas_download_log.csv"


def norm_text(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_text(a), norm_text(b)).ratio()


def author_score(full_text: str, authors: list[str]) -> float:
    full_text = norm_text(full_text)
    if not authors:
        return 0.0
    hits = 0
    for author in authors:
        if norm_text(author) in full_text:
            hits += 1
    return hits / len(authors)


def get_new_pdf(before_files: set[Path], timeout: int = 20) -> Path | None:
    start = time.time()
    while time.time() - start < timeout:
        current = set(DOWNLOAD_DIR.glob("*.pdf"))
        new_files = [p for p in current if p not in before_files]
        if new_files:
            return max(new_files, key=lambda p: p.stat().st_mtime)
        time.sleep(1)
    return None


def switch_to_new_tab_if_opened(driver, old_tabs):
    new_tabs = driver.window_handles
    if len(new_tabs) > len(old_tabs):
        driver.switch_to.window(new_tabs[-1])
        time.sleep(2)
        return True
    return False


def close_extra_tabs_and_return_main(driver):
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


def click_first_matching_result(driver, target_title: str, target_authors: list[str]) -> bool:
    items = driver.find_elements(By.CSS_SELECTOR, "li.list-group-item")

    best_link = None
    best_title_score = -1.0
    best_author_score = -1.0
    best_total = -1.0

    for item in items:
        try:
            blue_link = item.find_element(By.CSS_SELECTOR, "a[href]")
            link_text = blue_link.text.strip()
            full_text = item.text.strip()

            t_score = similarity(target_title, link_text)
            a_score = author_score(full_text, target_authors)
            total = 0.7 * t_score + 0.3 * a_score

            print("-" * 60)
            print("Candidate link text:", link_text)
            print("Title score:", round(t_score, 3))
            print("Author score:", round(a_score, 3))
            print("Total score:", round(total, 3))

            if total > best_total:
                best_total = total
                best_title_score = t_score
                best_author_score = a_score
                best_link = blue_link

        except Exception:
            continue

    if best_link is None:
        print("No result link found.")
        return False

    print("=" * 60)
    print("Best candidate selected")
    print("Title score:", round(best_title_score, 3))
    print("Author score:", round(best_author_score, 3))
    print("Total score:", round(best_total, 3))

    if best_title_score >= TITLE_THRESHOLD and best_author_score >= AUTHOR_THRESHOLD:
        old_tabs = driver.window_handles[:]
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", best_link)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", best_link)
        time.sleep(WAIT_MED)
        switch_to_new_tab_if_opened(driver, old_tabs)
        return True

    print("Rejected. Scores not good enough.")
    return False


def click_download_tab(driver) -> bool:
    try:
        download_tab = driver.find_element(
            By.XPATH,
            "//a[@id='download-tab' and @href='#download' and contains(@class,'download-tab')]"
        )
        download_panel = driver.find_element(By.ID, "download")

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", download_tab)
        time.sleep(0.5)

        driver.execute_script("""
            arguments[0].click();
            arguments[0].dispatchEvent(new MouseEvent('click', {
                view: window,
                bubbles: true,
                cancelable: true
            }));
        """, download_tab)

        time.sleep(1.5)

        panel_class = download_panel.get_attribute("class") or ""
        aria_selected = download_tab.get_attribute("aria-selected") or ""

        if "show" not in panel_class and "active" not in panel_class:
            driver.execute_script("""
                const tab = arguments[0];
                const panel = document.getElementById('download');

                tab.classList.add('active');
                tab.setAttribute('aria-selected', 'true');
                panel.classList.add('active');
                panel.classList.add('show');
            """, download_tab)
            time.sleep(1)

        panel_class = download_panel.get_attribute("class") or ""
        aria_selected = download_tab.get_attribute("aria-selected") or ""

        return ("show" in panel_class or "active" in panel_class or aria_selected == "true")

    except Exception as e:
        print("click_download_tab error:", e)
        return False


def click_download_selected_file(driver) -> tuple[bool, str]:
    before_files = set(DOWNLOAD_DIR.glob("*.pdf"))
    old_tabs = driver.window_handles[:]
    current_domain = urlparse(driver.current_url).netloc.lower()

    try:
        download_button = driver.find_element(
            By.XPATH,
            "//input[@type='SUBMIT' and contains(@value, 'Download the selected file')]"
        )

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", download_button)
        time.sleep(0.5)

        try:
            download_button.click()
        except Exception:
            driver.execute_script("arguments[0].click();", download_button)

        time.sleep(2)

        opened_new_tab = switch_to_new_tab_if_opened(driver, old_tabs)

        new_pdf = get_new_pdf(before_files, timeout=8)
        if new_pdf is not None:
            return True, "downloaded"

        try:
            form = download_button.find_element(By.XPATH, "./ancestor::form")
            driver.execute_script("arguments[0].submit();", form)
            time.sleep(2)
        except Exception:
            pass

        opened_new_tab = switch_to_new_tab_if_opened(driver, old_tabs)

        new_pdf = get_new_pdf(before_files, timeout=8)
        if new_pdf is not None:
            return True, "downloaded"

        current_url = driver.current_url
        current_domain_after = urlparse(current_url).netloc.lower()

        if current_domain_after and current_domain_after != current_domain:
            return False, current_domain_after

        if opened_new_tab:
            new_tab_domain = urlparse(driver.current_url).netloc.lower()
            if new_tab_domain:
                return False, new_tab_domain
            return False, "redirected_new_tab"

        return False, "no_pdf_downloaded"

    except Exception as e:
        print("click_download_selected_file error:", e)
        return False, "download_button_not_found"


def write_log(rows: list[dict]) -> None:
    fieldnames = ["title", "authors", "status", "site"]
    with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


options = Options()
options.add_argument("--start-maximized")

prefs = {
    "download.default_directory": str(DOWNLOAD_DIR.resolve()),
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "plugins.always_open_pdf_externally": True,
}
options.add_experimental_option("prefs", prefs)

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

logs = []

try:
    for i, query in enumerate(SEARCHES, start=1):
        title = query["title"]
        authors = query["authors"]

        print("\n" + "=" * 80)
        print(f"Search {i}: {title}")
        print("Authors:", authors)

        close_extra_tabs_and_return_main(driver)

        driver.get("https://ideas.repec.org/")
        time.sleep(WAIT_SHORT)

        search_box = driver.find_element(
            By.CSS_SELECTOR,
            "input[placeholder*='Search econ literature on IDEAS']"
        )
        search_box.clear()
        search_box.send_keys(title)
        search_box.send_keys(Keys.ENTER)
        time.sleep(WAIT_MED)

        matched = click_first_matching_result(driver, title, authors)
        if not matched:
            logs.append({
                "title": title,
                "authors": "; ".join(authors),
                "status": "passed_no_good_match",
                "site": "",
            })
            continue

        opened_domain = urlparse(driver.current_url).netloc.lower()
        if "ideas.repec.org" not in opened_domain and "repec.org" not in opened_domain:
            logs.append({
                "title": title,
                "authors": "; ".join(authors),
                "status": "redirected_before_download",
                "site": opened_domain,
            })
            continue

        clicked_tab = click_download_tab(driver)
        if not clicked_tab:
            logs.append({
                "title": title,
                "authors": "; ".join(authors),
                "status": "download_tab_not_found",
                "site": "",
            })
            continue

        ok, info = click_download_selected_file(driver)

        if ok:
            logs.append({
                "title": title,
                "authors": "; ".join(authors),
                "status": "downloaded_pdf",
                "site": "",
            })
            print("PDF downloaded. Moving to next search.")
        else:
            logs.append({
                "title": title,
                "authors": "; ".join(authors),
                "status": "redirected_or_not_downloaded",
                "site": info,
            })
            print(f"No direct PDF download. Logged site: {info}. Moving to next search.")

    write_log(logs)
    print("\nDone. Log file written to:", LOG_FILE)

finally:
    driver.quit()
