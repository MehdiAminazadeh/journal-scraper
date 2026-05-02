import re
import time
import requests
from pathlib import Path
from difflib import SequenceMatcher

from bs4 import BeautifulSoup

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc


PAPERS = [
    {
        
        "title": "Retail Pharmacies and Drug Diversion during the Opioid Epidemic",
        "author": "Janssen"
    },
    {
        "title": "Narratives of Migration and Political Polarization: Private Preferences, Public Preferences and Social Media",
        "authors": ["Eugenio Levi", "Michael Bayerlein", "Gianluca Grimalda", "Tommaso G. Reggiani"],
    },
    {
        "title": "Migration and Labor Market Integration in Europe",
        "authors": ["David Dorn", "Josef Zweimüller"],
    },
    {
        "title": "The Causal Effects of the Minimum Wage Introduction in Germany: An Overview",
        "authors": ["Marco Caliendo", "Alexandra Fedorets", "Malte Preuß", "Carsten Schröder", "Linda Wittbrodt"],
    },
    {
        "title": "Migration and Culture",
        "authors": ["Gil S. Epstein", "Ira N. Gang"],
    },
    {
        "title": "Minimum Wage in Germany: Countering the Wage and Employment Gap between Migrants and Natives?",
        "authors": ["Kai Ingwersen", "Stephan L. Thomsen"],
    },
    {
        "title": "The Great Migration and Educational Opportunity",
        "authors": ["Cavit Baran", "Eric Chyn", "Bryan Andrew Stuart"],
    },
    {
        "title": "Migration and Globalization: What's in it for Developing Countries?",
        "authors": ["Hillel Rapoport"],
    },
    {
        "title": "Migration and Stratification",
        "authors": ["Guillermina Jasso"],
    },
    {
        "title": "Minimum Wages and Employment",
        "authors": ["David Neumark", "William Wascher"],
    },
    {
        "title": "Minimum Wages, Productivity, and Reallocation",
        "authors": ["Mirja Haelbig", "Matthias Mertens", "Steffen Müller"],
    },
]

OUT_DIR = Path("iza_downloads")
OUT_DIR.mkdir(exist_ok=True)

IZA_URL = "https://www.iza.org/publications/dp"

TITLE_THRESHOLD = 0.90
AUTHOR_REQUIRED = True



def li(msg: str):
    print(f"[i] {msg}")


def lok(msg: str):
    print(f"[ok] {msg}")


def lwarn(msg: str):
    print(f"[warn] {msg}")


def norm(text: str) -> str:
    text = str(text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def slugify(text: str) -> str:
    text = norm(text)
    text = re.sub(r"\s+", "_", text)
    return text[:120] or "paper"


def author_found(text: str, authors: list[str]) -> bool:
    text_n = norm(text)

    for author in authors:
        author_n = norm(author)

        if author_n in text_n:
            return True

        parts = author_n.split()
        if parts:
            last = parts[-1]
            if last in text_n:
                return True

    return False



CHROME_MAJOR_VERSION = 147

def get_driver():
    opts = uc.ChromeOptions()

    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")

    driver = uc.Chrome(
        options=opts,
        version_main=CHROME_MAJOR_VERSION,
        suppress_welcome=True,
    )

    return driver



def accept_iza_cookies(driver):
    li("Checking IZA cookie popup...")

    xpaths = [
        "//button[contains(., 'Accept all')]",
        "//a[contains(., 'Accept all')]",
        "//*[self::button or self::a or @role='button'][contains(., 'Accept all')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept all')]",
    ]

    for xp in xpaths:
        try:
            buttons = driver.find_elements(By.XPATH, xp)

            for btn in buttons:
                try:
                    if btn.is_displayed() and btn.is_enabled():
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                            btn
                        )
                        time.sleep(0.3)

                        try:
                            btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", btn)

                        time.sleep(1)
                        lok("IZA cookies accepted")
                        return True

                except Exception:
                    continue

        except Exception:
            pass

    lwarn("No IZA cookie popup found")
    return False

def find_left_side_search_input(driver):
    """
    Find the left-side filter search input on IZA DP page.
    It scrolls down because the input is not visible at the top of the page.
    """
    li("Finding the left-side IZA search input...")

    scroll_positions = [300, 600, 900, 1200, 1500, 1800]

    for y in scroll_positions:
        driver.execute_script(f"window.scrollTo(0, {y});")
        time.sleep(1)

        inputs = driver.find_elements(
            By.XPATH,
            "//input[@placeholder='SUCHE' or @placeholder='Search' or @data-typeahead-input]"
        )

        visible = []

        for inp in inputs:
            try:
                if inp.is_displayed() and inp.is_enabled():
                    rect = inp.rect
                    visible.append((inp, rect))
            except Exception:
                pass

        if visible:
            print(f"[debug] visible search inputs found: {len(visible)}")

            for idx, (inp, rect) in enumerate(visible, start=1):
                print(
                    f"[debug] input #{idx}: "
                    f"x={rect.get('x')}, y={rect.get('y')}, "
                    f"w={rect.get('width')}, h={rect.get('height')}, "
                    f"placeholder={inp.get_attribute('placeholder')}"
                )

            left_candidates = []

            for inp, rect in visible:
                x = rect.get("x", 9999)
                width = rect.get("width", 0)

                if x < 500 and width > 100:
                    left_candidates.append((inp, rect))

            if left_candidates:
                left_candidates.sort(key=lambda item: item[1]["y"])
                lok("Left-side search input found")
                return left_candidates[0][0]

            lok("Visible search input found by fallback")
            return visible[0][0]

    print("[debug] Page title:", driver.title)
    print("[debug] Current URL:", driver.current_url)

    all_inputs = driver.find_elements(By.XPATH, "//input")
    print(f"[debug] total input elements on page: {len(all_inputs)}")

    for idx, inp in enumerate(all_inputs, start=1):
        try:
            print(
                f"[debug] input #{idx}: "
                f"displayed={inp.is_displayed()}, "
                f"enabled={inp.is_enabled()}, "
                f"type={inp.get_attribute('type')}, "
                f"placeholder={inp.get_attribute('placeholder')}, "
                f"class={inp.get_attribute('class')[:80]}"
            )
        except Exception:
            pass

    raise Exception("Could not find visible IZA search input")


def click_nearby_left_search_icon(driver, input_el):
    """
    Click the magnifying glass icon near the left-side filter input.
    Avoids the top website search icon.
    """
    li("Clicking nearby left-side magnifying-glass icon...")

    xpaths = [
        ".//ancestor::div[1]//img[contains(@src, 'magnifying-glass-icon')]",
        ".//ancestor::div[2]//img[contains(@src, 'magnifying-glass-icon')]",
        ".//ancestor::div[3]//img[contains(@src, 'magnifying-glass-icon')]",
        ".//ancestor::form[1]//img[contains(@src, 'magnifying-glass-icon')]",
        ".//following::img[contains(@src, 'magnifying-glass-icon')][1]",
    ]

    for xp in xpaths:
        try:
            icons = input_el.find_elements(By.XPATH, xp)

            for icon in icons:
                if icon.is_displayed():
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                        icon
                    )
                    time.sleep(0.3)

                    try:
                        icon.click()
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", icon)
                        except Exception:
                            ActionChains(driver).move_to_element(icon).click().perform()

                    lok("Search icon clicked")
                    return True

        except Exception:
            pass

    try:
        driver.execute_script("""
            const input = arguments[0];
            let container = input.closest('form, div');
            for (let i = 0; i < 6 && container; i++) {
                const img = container.querySelector('img[src*="magnifying-glass-icon"]');
                if (img) {
                    const clickable = img.closest('button, a, div') || img;
                    clickable.click();
                    return true;
                }
                container = container.parentElement;
            }
            return false;
        """, input_el)

        time.sleep(1)
        lok("Search icon clicked by JS fallback")
        return True

    except Exception:
        pass

    lwarn("Could not click icon directly. Pressing ENTER in input.")
    input_el.send_keys(Keys.ENTER)
    return False


def perform_iza_left_search(driver, title: str):
    wait = WebDriverWait(driver, 30)

    li("Opening IZA DP page...")
    driver.get(IZA_URL)

    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(3)

    accept_iza_cookies(driver)
    time.sleep(1)

    driver.execute_script("window.scrollTo(0, 900);")
    time.sleep(2)

    search_input = find_left_side_search_input(driver)

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        search_input
    )
    time.sleep(0.5)

    search_input.clear()
    search_input.send_keys(title)
    time.sleep(0.5)

    lok(f"Filled left-side search input with title: {title}")

    click_nearby_left_search_icon(driver, search_input)

    li("Waiting for results...")
    time.sleep(5)
    

def extract_dp_number(text: str) -> str | None:
    patterns = [
        r"IZA\s+Discussion\s+Paper\s+No\.?\s*(\d+)",
        r"Discussion\s+Paper\s+No\.?\s*(\d+)",
        r"\bDP\s*No\.?\s*(\d+)",
        r"\bdp(\d{3,6})\b",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1)

    return None


def get_result_blocks(driver):
    """
    Tries to extract result cards/blocks from the rendered IZA page.
    """
    candidates = []

    xpaths = [
        "//a[contains(@href, '/publications/dp/')]",
        "//*[contains(text(), 'IZA Discussion Paper No.')]",
        "//*[contains(text(), 'Discussion Paper No.')]",
    ]

    for xp in xpaths:
        try:
            elems = driver.find_elements(By.XPATH, xp)

            for el in elems:
                try:
                    if not el.is_displayed():
                        continue

                    block = None

                    for ancestor_level in [1, 2, 3, 4, 5, 6]:
                        try:
                            b = el.find_element(
                                By.XPATH,
                                f"./ancestor::div[{ancestor_level}]"
                            )
                            txt = b.text.strip()

                            if len(txt) > 50:
                                block = b
                                break
                        except Exception:
                            pass

                    if block is None:
                        block = el

                    txt = block.text.strip()
                    if txt and txt not in [x["text"] for x in candidates]:
                        candidates.append(
                            {
                                "element": block,
                                "text": txt,
                            }
                        )

                except Exception:
                    pass

        except Exception:
            pass

    return candidates


def choose_strict_iza_match(driver, target_title: str, target_authors: list[str]):
    li("Checking IZA result papers strictly...")

    blocks = get_result_blocks(driver)

    if not blocks:
        raise Exception("No IZA result blocks found")

    best = None
    best_score = -1.0

    for i, block in enumerate(blocks, start=1):
        text = block["text"]
        text_clean = re.sub(r"\s+", " ", text)

        dp_no = extract_dp_number(text_clean)

        lines = [x.strip() for x in text.splitlines() if x.strip()]
        line_scores = [(line, sim(target_title, line)) for line in lines]
        best_line, title_score = max(line_scores, key=lambda x: x[1])

        has_author = author_found(text_clean, target_authors)

        total = title_score + (0.10 if has_author else 0.0)

        print("\nCandidate result:")
        print(f"  Best title line: {best_line[:150]}")
        print(f"  Title score: {title_score:.3f}")
        print(f"  Author found: {has_author}")
        print(f"  DP number: {dp_no}")
        print(f"  Text preview: {text_clean[:250]}")

        if total > best_score:
            best_score = total
            best = {
                "text": text_clean,
                "title_line": best_line,
                "title_score": title_score,
                "author_found": has_author,
                "dp_no": dp_no,
                "total_score": total,
            }

    if best is None:
        raise Exception("No usable result candidate found")

    print("\nBest candidate:")
    print(f"  Title line: {best['title_line']}")
    print(f"  Title score: {best['title_score']:.3f}")
    print(f"  Author found: {best['author_found']}")
    print(f"  DP number: {best['dp_no']}")

    if best["title_score"] < TITLE_THRESHOLD:
        raise Exception(
            f"Best result title is too weak: {best['title_score']:.3f}. "
            "Skipping to avoid wrong paper."
        )

    if AUTHOR_REQUIRED and not best["author_found"]:
        raise Exception("Author not found in best IZA result. Skipping.")

    if not best["dp_no"]:
        raise Exception("Could not extract IZA Discussion Paper number from matched result.")

    lok(f"Strict IZA match accepted: DP {best['dp_no']}")
    return best




def build_iza_docs_pdf_url(dp_no: str) -> str:
    dp_no = str(dp_no).strip()
    dp_no = re.sub(r"\D", "", dp_no)
    return f"https://docs.iza.org/dp{dp_no}.pdf"


def download_iza_pdf(dp_no: str, title: str) -> Path:
    pdf_url = build_iza_docs_pdf_url(dp_no)
    out_path = OUT_DIR / f"iza_dp{dp_no}_{slugify(title)}.pdf"

    li(f"Downloading from IZA docs: {pdf_url}")

    r = requests.get(
        pdf_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=60,
        allow_redirects=True,
    )

    ct = r.headers.get("content-type", "").lower()

    if r.status_code == 200 and ("application/pdf" in ct or r.content[:4] == b"%PDF"):
        out_path.write_bytes(r.content)
        lok(f"Downloaded: {out_path}")
        return out_path

    raise Exception(
        f"IZA docs download failed. status={r.status_code}, content-type={ct}"
    )




def main():
    driver = None

    try:
        driver = get_driver()

        for i, paper in enumerate(PAPERS, start=1):
            print("\n" + "=" * 100)
            print(f"[{i}/{len(PAPERS)}] Searching IZA:")
            print(paper["title"])
            print("=" * 100)

            try:
                perform_iza_left_search(driver, paper["title"])

                match = choose_strict_iza_match(
                    driver=driver,
                    target_title=paper["title"],
                    target_authors=paper["authors"],
                )

                found_dp = str(match["dp_no"])

                print(f"[ok] Found IZA Discussion Paper No.: {found_dp}")

                pdf_path = download_iza_pdf(
                    dp_no=found_dp,
                    title=paper["title"],
                )

                print("[DONE]")
                print(f"Title: {paper['title']}")
                print(f"IZA DP No.: {found_dp}")
                print(f"PDF: {pdf_path}")

                time.sleep(2)

            except Exception as e:
                print(f"[paper failed] {paper['title']}")
                print(f"[reason] {e}")
                continue

    except Exception as e:
        print(f"\n[err] {e}")
        import traceback
        traceback.print_exc()

    finally:
        if driver:
            driver.quit()
            
if __name__ == "__main__":
    main()
