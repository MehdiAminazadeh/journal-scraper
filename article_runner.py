import json
import signal
import sys
import time
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from raw_scripts import scrape_v2 as sv2
from input_loader import build_tasks_from_excel
from config import STATE_DIR


ARTICLE_MEMORY_FILE = STATE_DIR / "article_memory.json"


def _load_memory():
    if ARTICLE_MEMORY_FILE.exists():
        try:
            return json.loads(ARTICLE_MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_memory(memory):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARTICLE_MEMORY_FILE.write_text(
        json.dumps(memory, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _safe_row_value(row, key):
    try:
        value = row.get(key, "")
        if pd.isna(value):
            return ""
        return str(value).strip()
    except Exception:
        return ""


def _authors_from_row(row):
    authors = []

    for key in [
        "authors",
        "author",
        "paper_authors",
        "author_full",
        "author1_full",
        "author1",
    ]:
        value = _safe_row_value(row, key)
        if value:
            parts = value.replace(" and ", ";").split(";")
            authors.extend([p.strip() for p in parts if p.strip()])

    first = _safe_row_value(row, "author1_first")
    last = _safe_row_value(row, "author1_last")

    if first or last:
        full = f"{first} {last}".strip()
        if full:
            authors.append(full)

    if last:
        authors.append(last)

    return list(dict.fromkeys([a for a in authors if a]))


def _build_article_dest(task):
    row = task.row
    journal = _safe_row_value(row, "journal") or str(task.journal or "")
    year_pub = _safe_row_value(row, "year_pub") or str(task.year_pub or "")
    last = _safe_row_value(row, "author1_last") or task.author_last or ""
    base = sv2.sanitize_filename(f"{journal}_{year_pub}_{last}")
    return sv2.ARTICLE_DIR / f"{base}_Article.pdf"


def _memory_entry(task, article_result, article_dest):
    row = task.row
    title = task.title or _safe_row_value(row, "paper_title")
    authors = task.authors if getattr(task, "authors", None) else _authors_from_row(row)

    return {
        "row_id": task.row_id,
        "sheet": task.sheet,
        "journal": task.journal,
        "year_pub": task.year_pub,
        "title": title,
        "authors": authors,
        "author_last": task.author_last,
        "article_file": str(article_dest),
        "article_exists": article_dest.exists(),
        "article_status": article_result.get("status", ""),
        "article_doi": article_result.get("doi", ""),
        "article_hint": article_result.get("hint", ""),
        "article_tried": article_result.get("tried", ""),
        "wp_file": task.wp_file,
        "wp_yes": _safe_row_value(row, "wp_yes"),
        "wp_doi": _safe_row_value(row, "wp_doi"),
        "wp_series": _safe_row_value(row, "wp_series"),
        "wp_year": _safe_row_value(row, "wp_year"),
    }


def download_articles_and_build_memory():
    vpn_ok = sv2.vpn_connect()

    if not vpn_ok:
        sv2.lerr("WireGuard is required for the article workflow. Stopping.")
        sys.exit(1)

    time.sleep(3)
    sv2.lok("VPN is up. Starting article-only workflow using raw scrape_v2.py logic")

    def on_interrupt(sig, frame):
        sv2.lwarn("Interrupted. Closing browser and disconnecting VPN")
        try:
            sv2.close_driver()
        finally:
            sv2.vpn_disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_interrupt)

    memory = _load_memory()

    try:
        tasks = build_tasks_from_excel()
        sv2.li(f"Total article tasks loaded: {len(tasks)}")

        groups = [
            ("AER", [t for t in tasks if str(t.journal).upper() == "AER"]),
            ("QJE", [t for t in tasks if str(t.journal).upper() == "QJE"]),
            ("JPE", [t for t in tasks if str(t.journal).upper() == "JPE"]),
            ("Other", [t for t in tasks if str(t.journal).upper() not in {"AER", "QJE", "JPE"}]),
        ]

        for phase_name, phase_tasks in groups:
            if not phase_tasks:
                continue

            sv2.li(f"[phase] {phase_name} articles | count={len(phase_tasks)}")

            for task in tqdm(phase_tasks, total=len(phase_tasks), desc=f"{phase_name} Articles"):
                article_dest = _build_article_dest(task)

                try:
                    sv2.li(f"[article] {task.row_id} | {task.title[:90]}")
                    result = sv2.download_article(task.row, article_dest)
                except Exception as exc:
                    result = {
                        "status": "error",
                        "hint": "",
                        "doi": "",
                        "tried": str(exc),
                    }

                memory[str(task.row_id)] = _memory_entry(task, result, article_dest)
                _save_memory(memory)
                time.sleep(sv2.DELAY)

            sv2.cleanup_between_phases(f"{phase_name} Articles")

        _save_memory(memory)
        sv2.lok(f"Article memory saved: {ARTICLE_MEMORY_FILE}")

        return memory

    finally:
        sv2.li("[cleanup] Closing article resources")
        try:
            sv2.close_driver()
        except Exception:
            pass
        try:
            sv2.vpn_disconnect()
        except Exception:
            pass
