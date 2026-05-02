import sys
import shutil
from pathlib import Path
from config import RAW
from models import SourceResult

sys.path.insert(0, str(RAW))

class IZAJob:
    name = "iza"
    
    def search_and_download(self, task):
        if Path(task.wp_file).exists():
            return SourceResult(source=self.name, status="already_exists", found=True, downloaded=True, file=task.wp_file)
        try:
            import iza
            driver = iza.get_driver()
            try:
                iza.perform_iza_left_search(driver, task.title)
                match = iza.choose_strict_iza_match(driver, task.title, task.authors)
                pdf_path = iza.download_iza_pdf(str(match["dp_no"]), task.title)
                dest = Path(task.wp_file)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest.unlink()
                shutil.move(str(pdf_path), str(dest))
                return SourceResult(source=self.name, status="downloaded", found=True, downloaded=True, file=str(dest), candidate_title=match.get("title_line", ""), title_score=float(match.get("title_score", 0.0)), author_score=1.0, url=f"https://docs.iza.org/dp{match['dp_no']}.pdf")
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception as exc:
            return SourceResult(source=self.name, status="error", error=str(exc))

    def close(self):
        pass
