import json
from dataclasses import asdict
from pathlib import Path
import pandas as pd
from config import ARTICLE_MEMORY_FILE, WP_STATE_FILE, SOURCE_LOG_FILE, SUMMARY_FILE, MANUAL_FILE
from models import PaperTask, SourceResult

class StateManager:
    def __init__(self):
        self.article_memory_file = ARTICLE_MEMORY_FILE
        self.wp_state_file = WP_STATE_FILE
        self.source_log_file = SOURCE_LOG_FILE
        self.summary_file = SUMMARY_FILE
        self.manual_file = MANUAL_FILE

    def save_article_memory(self, tasks: list[PaperTask]):
        data = [asdict(task) for task in tasks]
        self.article_memory_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_article_memory(self) -> list[PaperTask]:
        if not self.article_memory_file.exists():
            return []
        data = json.loads(self.article_memory_file.read_text(encoding="utf-8"))
        return [PaperTask(**item) for item in data]

    def update_task_memory(self, task: PaperTask, source: str, status: str):
        task.memory[source] = status

    def append_source_log(self, task: PaperTask, result: SourceResult):
        row = {
            "row_id": task.row_id,
            "sheet": task.sheet,
            "journal": task.journal,
            "year_pub": task.year_pub,
            "title": task.title,
            "authors": "; ".join(task.authors),
            "source": result.source,
            "status": result.status,
            "found": result.found,
            "downloaded": result.downloaded,
            "file": result.file,
            "url": result.url,
            "candidate_title": result.candidate_title,
            "title_score": result.title_score,
            "author_score": result.author_score,
            "error": result.error
        }
        df = pd.DataFrame([row])
        df.to_csv(self.source_log_file, mode="a", header=not self.source_log_file.exists(), index=False)

    def write_summary(self, tasks: list[PaperTask]):
        rows = []
        for task in tasks:
            rows.append({
                "row_id": task.row_id,
                "sheet": task.sheet,
                "journal": task.journal,
                "year_pub": task.year_pub,
                "title": task.title,
                "authors": "; ".join(task.authors),
                "article_file": task.article_file,
                "wp_file": task.wp_file,
                "wp_status": "downloaded" if Path(task.wp_file).exists() else "missing",
                "source_memory": " | ".join(f"{k}:{v}" for k, v in task.memory.items())
            })
        df = pd.DataFrame(rows)
        df.to_csv(self.summary_file, index=False)
        missing = df[df["wp_status"] == "missing"]
        if not missing.empty:
            missing.to_csv(self.manual_file, index=False)
