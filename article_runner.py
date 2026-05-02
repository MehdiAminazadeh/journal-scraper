import sys
from pathlib import Path
from config import RAW
from input_loader import build_tasks_from_excel
from logger_setup import get_logger
from state_manager import StateManager

sys.path.insert(0, str(RAW))
import scrape_v2 as sv2

log = get_logger("article_runner")

def download_articles_and_build_memory() -> list:
    tasks = build_tasks_from_excel()
    state = StateManager()
    for index, task in enumerate(tasks, start=1):
        article_path = Path(task.article_file)
        article_path.parent.mkdir(parents=True, exist_ok=True)
        if article_path.exists():
            log.info("article exists [%s/%s] %s", index, len(tasks), task.title)
            continue
        try:
            import pandas as pd
            row = pd.Series(task.row_data)
            result = sv2.download_article(row, article_path)
            log.info("article result [%s/%s] %s | %s", index, len(tasks), task.row_id, result.get("status", ""))
        except Exception as exc:
            log.warning("article error [%s/%s] %s | %s", index, len(tasks), task.row_id, exc)
    state.save_article_memory(tasks)
    return tasks
