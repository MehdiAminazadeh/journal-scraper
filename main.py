import argparse
from pathlib import Path
from article_runner import download_articles_and_build_memory
from input_loader import build_tasks_from_excel
from state_manager import StateManager
from source_runner import SourceRunner
from sources.nber_job import NBERJob
from sources.ssrn_job import SSRNJob
from sources.ideas_job import IDEASJob
from sources.cepr_job import CEPRJob
from sources.iza_job import IZAJob
from logger_setup import get_logger

log = get_logger("main")


def load_tasks_for_wps():
    state = StateManager()
    tasks = state.load_article_memory()
    if tasks:
        return tasks
    tasks = build_tasks_from_excel()
    state.save_article_memory(tasks)
    return tasks


def run_articles_only():
    tasks = download_articles_and_build_memory()
    StateManager().write_summary(tasks)
    log.info("articles_only_finished tasks=%s", len(tasks))


def run_wps_only():
    tasks = load_tasks_for_wps()
    run_wp_sources(tasks)


def run_full_pipeline():
    tasks = download_articles_and_build_memory()
    run_wp_sources(tasks)


def run_wp_sources(tasks):
    sources = [NBERJob(), SSRNJob(), IDEASJob(), CEPRJob(), IZAJob()]
    SourceRunner(sources).run(tasks)
    downloaded = sum(1 for task in tasks if Path(task.wp_file).exists())
    log.info("wp_finished tasks=%s downloaded=%s missing=%s", len(tasks), downloaded, len(tasks) - downloaded)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wps-only", action="store_true")
    parser.add_argument("--articles-only", action="store_true")
    args = parser.parse_args()
    if args.articles_only and args.wps_only:
        raise SystemExit("Use only one mode: --articles-only or --wps-only")
    if args.articles_only:
        run_articles_only()
        return
    if args.wps_only:
        run_wps_only()
        return
    run_full_pipeline()


if __name__ == "__main__":
    run()
