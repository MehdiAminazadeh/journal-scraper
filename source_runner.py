from pathlib import Path
from logger_setup import get_logger
from state_manager import StateManager

log = get_logger("source_runner")

class SourceRunner:
    def __init__(self, sources):
        self.sources = sources
        self.state = StateManager()

    def remaining(self, tasks):
        return [task for task in tasks if not Path(task.wp_file).exists()]

    def run(self, tasks):
        for source in self.sources:
            todo = self.remaining(tasks)
            if not todo:
                break
            log.info("source start %s | tasks=%s", source.name, len(todo))
            try:
                for index, task in enumerate(todo, start=1):
                    log.info("source task %s [%s/%s] %s", source.name, index, len(todo), task.title)
                    result = source.search_and_download(task)
                    self.state.update_task_memory(task, source.name, result.status)
                    self.state.append_source_log(task, result)
                    if result.downloaded:
                        log.info("source downloaded %s | %s", source.name, task.wp_file)
                    else:
                        log.info("source not resolved %s | %s | %s", source.name, result.status, result.error)
            finally:
                source.close()
                self.state.save_article_memory(tasks)
        self.state.write_summary(tasks)
