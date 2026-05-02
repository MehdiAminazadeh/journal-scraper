

import time
import re
import random
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from difflib import SequenceMatcher

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys




TITLE = "Migration and Labor Market Integration in Europe"
AUTHOR = "David Dorn"
CHROME_MAJOR_VERSION = 147

_driver = None
_profile_dir_in_use = None

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)



def norm(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def author_match_score(text: str, author: str) -> float:
    return 1.0 if norm(author) in norm(text) else 0.0


def li(msg: str):
    print(f"[i] {msg}")


def lok(msg: str):
    print(f"[ok] {msg}")


def lwarn(msg: str):
    print(f"[warn] {msg}")




def get_random_user_agent() -> str:
    """
    Kept here, but not used by default.

    Important:
    Do not force old Chrome 119-122 user agents if your real Chrome is 147.
    That mismatch can make Cloudflare/Turnstile fail to render.
    """
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    ]
    return random.choice(user_agents)


def _inject_stealth_scripts(driver):
    """
    Inject JavaScript to reduce common automation signals.
    This does not solve interactive verification pages by itself.
    """
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


def get_profile_dir():
    """
    Persistent profile.

    This is important because a new temporary profile every run can make the browser
    look like a completely new suspicious device each time.
    """
    global _profile_dir_in_use

    profile_dir = Path.cwd() / "ssrn_chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    _profile_dir_in_use = profile_dir
    li(f"Using Chrome profile: {profile_dir}")
    return profile_dir


def clear_undetected_chromedriver_cache():
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
                    li(f"Cleared cache: {cache_path}")
                except Exception:
                    pass

    except Exception:
        pass


def kill_leftover_chrome_processes():
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


def get_driver():
    global _driver

    if _driver is not None:
        return _driver

    profile_dir = get_profile_dir()

    opts = uc.ChromeOptions()

    opts.add_argument("--start-maximized")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"--user-data-dir={profile_dir.resolve()}")


    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.popups": 0,
    }

    opts.add_experimental_option("prefs", prefs)

    _driver = uc.Chrome(
        options=opts,
        version_main=CHROME_MAJOR_VERSION,
        suppress_welcome=True,
    )

    _inject_stealth_scripts(_driver)

    lok("Chrome initialized")
    return _driver


def close_driver(delete_profile: bool = False):
    """
    By default, do not delete the profile.

    Keeping the same profile helps because once you manually pass verification,
    cookies/session data can remain available for the next run.
    """
    global _driver, _profile_dir_in_use

    try:
        if _driver is not None:
            _driver.quit()
    except Exception:
        pass
    finally:
        _driver = None

    time.sleep(2)

    if delete_profile and _profile_dir_in_use:
        try:
            shutil.rmtree(_profile_dir_in_use, ignore_errors=True)
            li(f"Deleted Chrome profile: {_profile_dir_in_use}")
        except Exception:
            pass
        finally:
            _profile_dir_in_use = None



def is_cloudflare_or_verification_page(driver) -> bool:
    try:
        page_source = (driver.page_source or "").lower()
        title = (driver.title or "").lower()
        current_url = (driver.current_url or "").lower()

        cf_indicators = [
            "checking your browser",
            "just a moment",
            "please wait",
            "verifying you are human",
            "security challenge",
            "ray id",
            "cloudflare ray",
            "verify you are human",
            "cf-browser-verification",
            "cf-challenge",
            "turnstile",
            "challenge-platform",
            "challenges.cloudflare.com",
        ]

        combined = f"{title}\n{current_url}\n{page_source}"
        return any(ind in combined for ind in cf_indicators)

    except Exception:
        return False


def wait_for_cloudflare_bypass(driver, timeout: int = 45) -> bool:
    """
    Passive wait only.

    It waits until the page is complete and no Cloudflare/security challenge
    text is detected.
    """
    li(f"Waiting for page to become ready (timeout: {timeout}s)")
    start = time.time()

    while time.time() - start < timeout:
        try:
            ready = driver.execute_script("return document.readyState")

            if ready == "complete" and not is_cloudflare_or_verification_page(driver):
                lok("Page is ready")
                return True

            time.sleep(2)

        except Exception:
            time.sleep(2)

    lwarn("Page-ready wait timed out")
    return False


def wait_until_real_ssrn_page(driver, timeout: int = 45) -> bool:
    """
    Real success condition:
    SSRN search input with ID='term' is visible.
    """
    li("Checking whether the real SSRN search page is visible...")

    start = time.time()

    while time.time() - start < timeout:
        try:
            elems = driver.find_elements(By.ID, "term")
            visible_terms = [el for el in elems if el.is_displayed()]

            if visible_terms:
                lok("Real SSRN search page detected")
                return True

            time.sleep(1)

        except Exception:
            time.sleep(1)

    return False


def debug_cloudflare_widget_status(driver):
    """
    Helpful when the Cloudflare rectangle/Turnstile box does not load.
    It prints iframe/script hints so you know whether the widget exists at all.
    """
    print("\n" + "=" * 70)
    print("[debug] Cloudflare / page status")
    print("=" * 70)

    try:
        print(f"[debug] title: {driver.title}")
        print(f"[debug] url:   {driver.current_url}")
    except Exception:
        pass

    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"[debug] iframe count: {len(iframes)}")

        for i, frame in enumerate(iframes[:10], start=1):
            try:
                src = frame.get_attribute("src") or ""
                title = frame.get_attribute("title") or ""
                print(f"[debug] iframe #{i}: title='{title}' src='{src[:180]}'")
            except Exception:
                pass

    except Exception as e:
        print(f"[debug] could not inspect iframes: {e}")

    try:
        scripts = driver.find_elements(By.TAG_NAME, "script")
        cf_scripts = []

        for s in scripts:
            src = s.get_attribute("src") or ""
            if "cloudflare" in src.lower() or "turnstile" in src.lower() or "challenge" in src.lower():
                cf_scripts.append(src)

        print(f"[debug] cloudflare/turnstile script count: {len(cf_scripts)}")

        for src in cf_scripts[:10]:
            print(f"[debug] script: {src[:200]}")

    except Exception as e:
        print(f"[debug] could not inspect scripts: {e}")

    print("=" * 70 + "\n")


def wait_or_manual_continue(driver, timeout: int = 45):
    """
    First waits normally.
    If still stuck on Cloudflare / verification page, pauses for manual solving.

    If the rectangle does not load:
    - do not disable images
    - do not fake old UA
    - use persistent profile
    - test https://challenges.cloudflare.com/ manually in the same browser
    """
    ok = wait_for_cloudflare_bypass(driver, timeout=timeout)

    if ok:
        usable = wait_until_real_ssrn_page(driver, timeout=10)
        if usable:
            return True

    lwarn("Still not on the real SSRN search page.")
    debug_cloudflare_widget_status(driver)

    print("\nManual step:")
    print("1. Look at the opened Chrome window.")
    print("2. If Cloudflare verification appears, complete it manually.")
    print("3. If the rectangle does not load, open this in the same Selenium Chrome tab:")
    print("   https://challenges.cloudflare.com/")
    print("4. Then go back to SSRN if needed.")
    print("5. When the real SSRN search page is visible, press ENTER here.\n")

    input("Press ENTER after the SSRN search page is visible...")

    usable = wait_until_real_ssrn_page(driver, timeout=30)

    if not usable:
        debug_cloudflare_widget_status(driver)
        raise Exception("SSRN search page is still not usable after manual verification")

    return True


def click_cloudflare_challenge(driver, timeout: int = 10) -> bool:
    """
    Kept from your code, but not used automatically.
    """
    try:
        log.debug("Looking for Cloudflare challenge elements...")

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
                        log.info("Found and clicking challenge element")
                        ActionChains(driver).move_to_element(el).click(el).perform()
                        time.sleep(2)
                        return True

            except Exception as ex:
                log.debug(f"Could not interact with {xp}: {ex}")

        return False

    except Exception as e:
        log.debug(f"Challenge click error: {e}")
        return False


def accept_all_cookies(driver):
    selectors = [
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'allow')]",
        "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
        "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
    ]

    for xp in selectors:
        try:
            buttons = driver.find_elements(By.XPATH, xp)

            for btn in buttons:
                if btn.is_displayed() and btn.is_enabled():
                    try:
                        btn.click()
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", btn)
                        except Exception:
                            continue

                    time.sleep(1)
                    lok("Cookies accepted")
                    return True

        except Exception:
            pass

    return False



def find_author_input(driver):
    xpaths = [
        "//input[contains(@aria-label, 'Author')]",
        "//label[contains(., 'Author')]/following::input[1]",
        "//input[contains(@name, 'author')]",
    ]

    for xp in xpaths:
        try:
            elems = driver.find_elements(By.XPATH, xp)

            for el in elems:
                if el.is_displayed():
                    return el

        except Exception:
            pass

    try:
        inputs = [
            x for x in driver.find_elements(By.XPATH, "//input[@type='text']")
            if x.is_displayed()
        ]

        if len(inputs) >= 2:
            return inputs[1]

    except Exception:
        pass

    return None


def click_search_button(driver, fallback_input):
    li("Clicking Advanced Search blue button...")

    term_input = WebDriverWait(driver, 20).until(
        EC.visibility_of_element_located((By.ID, "term"))
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        term_input
    )
    time.sleep(0.5)

    xpaths = [
        "//input[@id='term']/following::button[.//*[name()='svg' and @data-icon-name='search']][1]",

        "//input[@id='term']/following::button[@aria-label='Search'][1]",

        "//input[@id='term']/following::*[name()='svg' and @data-icon-name='search']/ancestor::button[1]",

        "//main//button[@aria-label='Search']",
        "//main//button[.//*[name()='svg' and @data-icon-name='search']]",

        "//input[@id='term']/following::button[contains(@class, 'primary')][1]",
    ]

    for xp in xpaths:
        try:
            buttons = driver.find_elements(By.XPATH, xp)

            for btn in buttons:
                try:
                    if not btn.is_displayed():
                        continue

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                        btn
                    )
                    time.sleep(0.5)

                    driver.execute_script("arguments[0].click();", btn)

                    lok("Advanced Search blue button clicked")
                    time.sleep(4)
                    return True

                except Exception:
                    continue

        except Exception:
            continue

    lwarn("Could not click blue search button directly. Pressing ENTER in title field.")
    fallback_input.send_keys(Keys.ENTER)
    time.sleep(4)
    return False


def main():
    driver = None

    try:
        li("Preparing Chrome...")

        kill_leftover_chrome_processes()
        clear_undetected_chromedriver_cache()

        driver = get_driver()

        li("Opening SSRN search page...")
        driver.get("https://papers.ssrn.com/sol3/DisplayAbstractSearch.cfm")

        wait_or_manual_continue(driver, timeout=45)
        accept_all_cookies(driver)

        search_boxes = driver.find_elements(By.ID, "term")
        if not search_boxes:
            raise Exception("Search page did not load correctly")

        print(f"Searching for: {TITLE}")

        search_box = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.ID, "term"))
        )

        search_box.clear()
        search_box.send_keys(TITLE)
        time.sleep(0.5)

        author_box = find_author_input(driver)

        if author_box is not None:
            author_box.clear()
            author_box.send_keys(AUTHOR)
            time.sleep(0.5)
            lok(f"Author field filled: {AUTHOR}")
        else:
            lwarn("Author field not found")

        click_search_button(driver, search_box)
        time.sleep(4)

        li("Analyzing search results...")

        result_links = driver.find_elements(
            By.XPATH,
            "//a[contains(@href, 'abstract_id=')]"
        )

        print(f"Found {len(result_links)} results")

        best_link = None
        best_score = -1.0

        for i, link in enumerate(result_links):
            try:
                text = link.text.strip()
                href = link.get_attribute("href") or ""

                if not text or "abstract_id=" not in href:
                    continue

                title_score = sim(TITLE, text)

                try:
                    block = link.find_element(
                        By.XPATH,
                        "./ancestor::*[self::div or self::article][1]"
                    )
                    block_text = block.text.strip()
                except Exception:
                    block_text = text

                a_score = author_match_score(block_text, AUTHOR)
                total = 0.75 * title_score + 0.25 * a_score

                if total > 0.3:
                    print(f"\nResult #{i + 1}:")
                    print(f"  Title: {text[:120]}")
                    print(f"  Title score:  {title_score:.3f}")
                    print(f"  Author score: {a_score:.3f}")
                    print(f"  Total score:  {total:.3f}")

                if total > best_score:
                    best_score = total
                    best_link = link

            except Exception:
                continue

        if best_link is None:
            raise Exception("No matching paper found in results")

        print(f"\n{'=' * 60}")
        print(f"Best match found with score {best_score:.3f}")
        print(f"{'=' * 60}")

        li("Clicking paper link...")

        old_tabs = driver.window_handles[:]

        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});",
            best_link
        )

        time.sleep(1)

        try:
            best_link.click()
        except Exception:
            driver.execute_script("arguments[0].click();", best_link)

        time.sleep(3)

        if len(driver.window_handles) > len(old_tabs):
            driver.switch_to.window(driver.window_handles[-1])

        wait_for_cloudflare_bypass(driver, timeout=20)
        accept_all_cookies(driver)

        li("Locating download button...")

        download_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//a[contains(., 'Download This Paper')] | //button[contains(., 'Download This Paper')]"
            ))
        )

        li("Clicking download button...")

        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});",
            download_btn
        )

        time.sleep(1)

        try:
            download_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", download_btn)

        time.sleep(5)
        lok("Done")

    except Exception as e:
        print(f"\n[err] {e}")

        import traceback
        traceback.print_exc()

    finally:
        close_driver(delete_profile=False)


if __name__ == "__main__":
    main()
    
    
    

