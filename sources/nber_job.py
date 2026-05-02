import re
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup
from models import SourceResult
from matcher import strict_match
from sources._job_utils import download_pdf_url

class NBERJob:
    name = "nber"

    def search_and_download(self, task):
        if __import__("pathlib").Path(task.wp_file).exists():
            return SourceResult(source=self.name, status="already_exists", found=True, downloaded=True, file=task.wp_file)
        try:
            url = f"https://www.nber.org/search?q={quote_plus(task.title)}&page=1&perPage=50"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            if r.status_code != 200:
                return SourceResult(source=self.name, status="search_failed", error=f"status={r.status_code}", url=url)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("div.digest-card")
            best = None
            for card in cards:
                link = card.select_one("div.digest-card__title a[href*='/papers/w']")
                if not link:
                    continue
                candidate_title = link.get_text(" ", strip=True)
                text = card.get_text(" ", strip=True)
                ok, title_score, author_score_value = strict_match(task.title, candidate_title, text, task.authors)
                href = link.get("href", "")
                full_url = href if href.startswith("http") else "https://www.nber.org" + href
                current = (ok, title_score, author_score_value, candidate_title, full_url)
                if best is None or title_score + author_score_value > best[1] + best[2]:
                    best = current
            if best is None:
                return SourceResult(source=self.name, status="not_found", error="no_result_cards")
            ok, ts, aus, candidate_title, paper_url = best
            if not ok:
                return SourceResult(source=self.name, status="not_found", candidate_title=candidate_title, title_score=ts, author_score=aus, url=paper_url, error="strict_match_failed")
            match = re.search(r"/papers/w(\d+)", paper_url)
            if not match:
                return SourceResult(source=self.name, status="paper_number_missing", candidate_title=candidate_title, title_score=ts, author_score=aus, url=paper_url)
            number = match.group(1)
            pdf_urls = [
                f"https://www.nber.org/papers/w{number}.pdf",
                f"https://www.nber.org/system/files/working_papers/w{number}/w{number}.pdf"
            ]
            last = None
            for pdf_url in pdf_urls:
                result = download_pdf_url(pdf_url, task.wp_file, self.name)
                result.candidate_title = candidate_title
                result.title_score = ts
                result.author_score = aus
                if result.downloaded:
                    return result
                last = result
            return last or SourceResult(source=self.name, status="download_failed", url=paper_url)
        except Exception as exc:
            return SourceResult(source=self.name, status="error", error=str(exc))

    def close(self):
        pass
