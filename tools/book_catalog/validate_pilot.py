from __future__ import annotations

import json
import re
from pathlib import Path

from transformers import AutoTokenizer


ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = ROOT / "data" / "book_catalog" / "pilot"
CATALOG_PATH = ROOT / "data" / "book_catalog" / "catalog.json"
FACTS_PATH = PILOT_DIR / "book_facts.json"
DRAFT_PATH = PILOT_DIR / "draft_catalog.json"
REPORT_PATH = PILOT_DIR / "validation_report.json"
MODEL_PATH = ROOT / "data" / "ml_search" / "local-model"
FORBIDDEN = re.compile(
    r"award|winner|finalist|isbn|open\s*library|предметн\w*\s+рубри",
    re.IGNORECASE,
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def word_count(value: str) -> int:
    return len(re.findall(r"[\wЁё]+", value, re.UNICODE))


def main() -> None:
    catalog_list = read_json(CATALOG_PATH)
    catalog = {book["id"]: book for book in catalog_list}
    facts_list = read_json(FACTS_PATH)
    drafts = read_json(DRAFT_PATH)
    facts = {book["catalogId"]: book for book in facts_list}
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
    allowed_genres = {genre for book in catalog_list for genre in book["genres"]}
    allowed_moods = {mood for book in catalog_list for mood in book["mood"]}
    errors: list[str] = []
    measurements = []

    if len(drafts) != 20 or len({item["catalogId"] for item in drafts}) != 20:
        errors.append("Draft must contain exactly 20 unique books")

    for draft in drafts:
        catalog_id = draft["catalogId"]
        fact = facts.get(catalog_id)
        current = catalog.get(catalog_id)
        label = f"#{catalog_id} {draft['proposed']['title']}"
        if fact is None or current is None:
            errors.append(f"{label}: missing facts or source catalog item")
            continue
        if current["workKey"] != fact["workKey"] or draft["workKey"] != fact["workKey"]:
            errors.append(f"{label}: workKey mismatch")
        if len(fact["sources"]) < 2:
            errors.append(f"{label}: fewer than two sources")
        if any(not source["url"].startswith("https://") for source in fact["sources"]):
            errors.append(f"{label}: non-HTTPS source")
        if not set(draft["proposed"]["genres"]).issubset(allowed_genres):
            errors.append(f"{label}: genre outside controlled catalogue vocabulary")
        if not set(draft["proposed"]["mood"]).issubset(allowed_moods):
            errors.append(f"{label}: mood outside controlled catalogue vocabulary")
        if draft["proposed"]["pace"] not in {"медленный", "средний", "быстрый"}:
            errors.append(f"{label}: invalid pace")
        if draft["proposed"]["ageRating"] not in {"0+", "6+", "12+", "16+", "18+"}:
            errors.append(f"{label}: invalid age rating")

        annotation = draft["annotation"]
        search_text = draft["searchText"]
        annotation_words = word_count(annotation)
        search_words = word_count(search_text)
        search_tokens = len(tokenizer.encode("passage: " + search_text, truncation=False))
        if not 70 <= annotation_words <= 120:
            errors.append(f"{label}: annotation length {annotation_words} words")
        if not 75 <= search_words <= 200:
            errors.append(f"{label}: searchText length {search_words} words")
        if search_tokens > 512:
            errors.append(f"{label}: searchText exceeds E5 limit ({search_tokens} tokens)")
        if FORBIDDEN.search(annotation) or FORBIDDEN.search(search_text):
            errors.append(f"{label}: forbidden source or award vocabulary")
        if fact["title"].casefold() not in search_text.casefold():
            errors.append(f"{label}: title is absent from searchText")
        if any(theme.casefold() not in search_text.casefold() for theme in fact["themes"]):
            errors.append(f"{label}: not every verified theme reached searchText")

        measurements.append(
            {
                "catalogId": catalog_id,
                "title": fact["title"],
                "annotationWords": annotation_words,
                "searchTextWords": search_words,
                "searchTextTokens": search_tokens,
                "sourceCount": len(fact["sources"]),
                "changedFields": draft["changedFields"],
            }
        )

    report = {
        "status": "passed" if not errors else "failed",
        "books": len(drafts),
        "errors": errors,
        "summary": {
            "annotationWordsMin": min(item["annotationWords"] for item in measurements),
            "annotationWordsMax": max(item["annotationWords"] for item in measurements),
            "searchTextWordsMin": min(item["searchTextWords"] for item in measurements),
            "searchTextWordsMax": max(item["searchTextWords"] for item in measurements),
            "searchTextTokensMax": max(item["searchTextTokens"] for item in measurements),
        },
        "measurements": measurements,
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: report[key] for key in ("status", "books", "errors", "summary")}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
