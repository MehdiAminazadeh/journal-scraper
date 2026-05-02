from pathlib import Path
import shutil
import time
import tempfile
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from config import TMP_DIR, CHROME_MAJOR_VERSION

class ChromeSession:
    def __init__(self, name: str, download_dir: Path | None = None, persistent: bool = False):
        self.name = name
        self.download_dir = Path(download_dir or TMP_DIR / name)
        self.persistent = persistent
        self.profile_dir = None
        self.driver = None
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _profile(self) -> Path:
        if self.persistent:
            path = Path.cwd() / f"{self.name}_chrome_profile"
        else:
            path = Path(tempfile.gettempdir()) / f"{self.name}_profile_{int(time.time() * 1000)}"
        path.mkdir(parents=True, exist_ok=True)
        self.profile_dir = path
        return path

    def start(self):
        if self.driver is not None:
            return self.driver
        profile = self._profile()
        opts = uc.ChromeOptions()
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-popup-blocking")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(f"--user-data-dir={profile.resolve()}")
        prefs = {
            "download.default_directory": str(self.download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
            "profile.default_content_setting_values.notifications": 2,
            "profile.block_third_party_cookies": False
        }
        opts.add_experimental_option("prefs", prefs)
        self.driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, suppress_welcome=True)
        self._inject()
        return self.driver

    def _inject(self):
        scripts = [
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
            "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})",
            "Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})",
            "window.chrome = {runtime: {}}"
        ]
        for script in scripts:
            try:
                self.driver.execute_script(script)
            except Exception:
                pass

    def alive(self) -> bool:
        try:
            handles = self.driver.window_handles
            if not handles:
                return False
            self.driver.switch_to.window(handles[0])
            return True
        except Exception:
            return False

    def reset(self):
        self.close()
        return self.start()

    def close_extra_tabs(self):
        if self.driver is None:
            return
        handles = self.driver.window_handles
        if not handles:
            return
        main = handles[0]
        for handle in handles[1:]:
            try:
                self.driver.switch_to.window(handle)
                self.driver.close()
            except Exception:
                pass
        self.driver.switch_to.window(main)

    def close(self):
        try:
            if self.driver is not None:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None
        if self.profile_dir and not self.persistent:
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            self.profile_dir = None
