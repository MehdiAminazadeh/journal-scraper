import sys
from pathlib import Path
import pandas as pd
from config import RAW, DATASET_FILE, ARTICLE_DIR, WP_DIR, TARGET_YEARS, TARGET_JOURNALS
from matcher import clean_filename
from models import PaperTask

sys.path.insert(0, str(RAW))
import scrape_v2 as sv2

def safe(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()

def parse_year(value):
    try:
        return int(value)
    except Exception:
        return None

def row_authors(row) -> list[str]:
    values = []
    for key in ["authors", "author", "paper_authors", "author_full", "author1_full"]:
        v = safe(row.get(key, ""))
        if v:
            values.extend([x.strip() for x in v.replace(" and ", ";").split(";") if x.strip()])
    first = safe(row.get("author1_first", ""))
    last = safe(row.get("author1_last", ""))
    if first or last:
        values.append(f"{first} {last}".strip())
    elif last:
        values.append(last)
    return list(dict.fromkeys([x for x in values if x.lower() not in {"nan", "none"}]))

def build_tasks_from_excel() -> list[PaperTask]:
    xl = pd.read_excel(DATASET_FILE, sheet_name=None)
    tasks = []
    for sheet_name, df in xl.items():
        for _, row in df.iterrows():
            journal = safe(row.get("journal", "") or sheet_name).upper()
            year_pub = parse_year(row.get("year_pub", None))
            if TARGET_YEARS and year_pub not in TARGET_YEARS:
                continue
            if TARGET_JOURNALS and journal not in TARGET_JOURNALS:
                continue
            row_id = safe(row.get("id") or f"{sheet_name}_unknown")
            title = safe(row.get("paper_title", ""))
            last = safe(row.get("author1_last", ""))
            authors = row_authors(row)
            if not authors and last:
                authors = [last]
            if not title or not authors:
                continue
            base = clean_filename(f"{journal}_{year_pub or ''}_{last or row_id}")
            wp_base = clean_filename(last or row_id)
            article_file = ARTICLE_DIR / f"{base}_Article.pdf"
            wp_file = WP_DIR / f"{wp_base}_wp.pdf"
            tasks.append(PaperTask(
                row_id=row_id,
                sheet=sheet_name,
                journal=journal,
                year_pub=str(year_pub or ""),
                title=title,
                authors=authors,
                author_last=last,
                article_file=str(article_file),
                wp_file=str(wp_file),
                row_data={k: safe(v) for k, v in row.to_dict().items()}
            ))
    return tasks
