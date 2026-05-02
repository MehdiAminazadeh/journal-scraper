from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class PaperTask:
    row_id: str
    sheet: str
    journal: str
    year_pub: str
    title: str
    authors: list[str]
    author_last: str
    article_file: str
    wp_file: str
    row_data: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, str] = field(default_factory=dict)

@dataclass
class SourceResult:
    source: str
    status: str
    found: bool = False
    downloaded: bool = False
    file: str = ""
    url: str = ""
    candidate_title: str = ""
    title_score: float = 0.0
    author_score: float = 0.0
    error: str = ""
