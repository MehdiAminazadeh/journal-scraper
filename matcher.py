import re
from difflib import SequenceMatcher
from config import TITLE_THRESHOLD, AUTHOR_THRESHOLD

def norm(text: str) -> str:
    text = str(text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()

def author_variants(author: str) -> list[str]:
    a = norm(author)
    if not a:
        return []
    parts = a.split()
    values = [a]
    if parts:
        values.append(parts[-1])
    return list(dict.fromkeys(values))

def author_score(text: str, authors: list[str]) -> float:
    if not authors:
        return 0.0
    text_n = norm(text)
    total = 0
    hits = 0
    for author in authors:
        variants = author_variants(author)
        if not variants:
            continue
        total += 1
        if any(v in text_n for v in variants):
            hits += 1
    if total == 0:
        return 0.0
    return hits / total

def strict_match(title: str, candidate_title: str, candidate_text: str, authors: list[str]) -> tuple[bool, float, float]:
    ts = similarity(title, candidate_title)
    aus = author_score(candidate_text, authors)
    return ts >= TITLE_THRESHOLD and aus >= AUTHOR_THRESHOLD, ts, aus

def clean_filename(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", str(text or ""))
    text = re.sub(r"\s+", "_", text).strip("_")
    return text[:120] or "paper"
