import sys
import shutil
from pathlib import Path
from config import RAW
from models import SourceResult

sys.path.insert(0, str(RAW))

class SSRNJob:
    name = "ssrn"

    def __init__(self):
        self.before = set()

    def _snapshot(self):
        dirs = [Path.cwd(), Path.home() / "Downloads", Path.home() / "downloads"]
        files = set()
        for d in dirs:
            if d.exists():
                files.update(p.resolve() for p in d.glob("*.pdf"))
        return files

    def _move_new_pdf(self, before, dest):
        after = self._snapshot()
        new = [p for p in after if p not in before and p.exists()]
        if not new:
            return False
        src = max(new, key=lambda p: p.stat().st_mtime)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        shutil.move(str(src), str(dest))
        return True

    def search_and_download(self, task):
        if Path(task.wp_file).exists():
            return SourceResult(source=self.name, status="already_exists", found=True, downloaded=True, file=task.wp_file)
        try:
            import ssrn
            before = self._snapshot()
            if hasattr(ssrn, "download_ssrn_by_title_author"):
                ok, note = ssrn.download_ssrn_by_title_author(task.title, task.authors, Path(task.wp_file))
                if ok and Path(task.wp_file).exists():
                    return SourceResult(source=self.name, status="downloaded", found=True, downloaded=True, file=task.wp_file, error=str(note))
                if ok and self._move_new_pdf(before, task.wp_file):
                    return SourceResult(source=self.name, status="downloaded", found=True, downloaded=True, file=task.wp_file, error=str(note))
                return SourceResult(source=self.name, status="not_found", error=str(note))
            ssrn.TITLE = task.title
            ssrn.AUTHOR = task.authors[0] if task.authors else task.author_last
            ssrn.main()
            if Path(task.wp_file).exists():
                return SourceResult(source=self.name, status="downloaded", found=True, downloaded=True, file=task.wp_file)
            if self._move_new_pdf(before, task.wp_file):
                return SourceResult(source=self.name, status="downloaded", found=True, downloaded=True, file=task.wp_file)
            return SourceResult(source=self.name, status="not_found", error="ssrn_finished_no_pdf")
        except Exception as exc:
            return SourceResult(source=self.name, status="error", error=str(exc))

    def close(self):
        pass
