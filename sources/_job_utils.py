from pathlib import Path
import time
import requests
from bs4 import BeautifulSoup
from matcher import strict_match, similarity, author_score
from models import SourceResult
from config import DOWNLOAD_TIMEOUT

def is_pdf_bytes(content: bytes) -> bool:
    return content[:4] == b"%PDF" or b"%PDF" in content[:20]

def download_pdf_url(url: str, dest: str | Path, source: str, timeout: int = 60) -> SourceResult:
    dest = Path(dest)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout, allow_redirects=True)
        content_type = r.headers.get("content-type", "").lower()
        if r.status_code == 200 and (is_pdf_bytes(r.content) or "application/pdf" in content_type):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest.unlink()
            dest.write_bytes(r.content)
            return SourceResult(source=source, status="downloaded", found=True, downloaded=True, file=str(dest), url=url)
        return SourceResult(source=source, status="pdf_request_failed", found=True, downloaded=False, url=url, error=f"status={r.status_code};content_type={content_type}")
    except Exception as exc:
        return SourceResult(source=source, status="pdf_request_error", found=True, downloaded=False, url=url, error=str(exc))

def wait_for_new_pdf(download_dir: Path, before: set[Path], timeout: int = DOWNLOAD_TIMEOUT) -> Path | None:
    start = time.time()
    while time.time() - start < timeout:
        cr = list(download_dir.glob("*.crdownload"))
        pdfs = [p for p in download_dir.glob("*.pdf") if p not in before]
        if not cr and pdfs:
            return max(pdfs, key=lambda p: p.stat().st_mtime)
        time.sleep(1)
    return None
