from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_scripts"
DATASET_FILE = ROOT / "dataset 2025-08-18.xlsx"
ARTICLE_DIR = ROOT / "articles"
WP_DIR = ROOT / "working_papers"
TMP_DIR = ROOT / "downloads_tmp"
REPORT_DIR = ROOT / "reports"
STATE_DIR = ROOT / "state"
MANUAL_DIR = ROOT / "manual_review"

ARTICLE_MEMORY_FILE = STATE_DIR / "article_memory.json"
WP_STATE_FILE = STATE_DIR / "wp_state.json"
SOURCE_LOG_FILE = REPORT_DIR / "source_attempts.csv"
SUMMARY_FILE = REPORT_DIR / "wp_download_summary.csv"
MANUAL_FILE = MANUAL_DIR / "manual_review_needed.csv"

TARGET_YEARS = {2023}
TARGET_JOURNALS = {"AER", "QJE", "JPE", "ECMA", "RESTUD", "RES"}

TITLE_THRESHOLD = 0.90
AUTHOR_THRESHOLD = 1.00
DOWNLOAD_TIMEOUT = 60
CHROME_MAJOR_VERSION = 147

SOURCE_ORDER = ["nber", "ssrn", "ideas", "cepr", "iza"]

for path in [ARTICLE_DIR, WP_DIR, TMP_DIR, REPORT_DIR, STATE_DIR, MANUAL_DIR]:
    path.mkdir(parents=True, exist_ok=True)
