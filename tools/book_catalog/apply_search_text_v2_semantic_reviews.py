#!/usr/bin/env python3
"""Apply independent semantic-review decisions to compact SearchText v2 rows.

Review files are deliberately separate from the editable catalog rows so several
reviewers can work in parallel without touching the same JSONL files.  Accepted
or rewritten decisions replace the complete reader-facing card and may add
short, manually verified source excerpts.  Unresolved decisions keep the card
in the review queue.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "book_catalog" / "search-text-v2"
COMPACT_FILES = [
    DATA / "editorial-001-250.jsonl",
    DATA / "editorial-154-203.jsonl",
    DATA / "editorial-251-500.jsonl",
    DATA / "editorial-501-750.jsonl",
    DATA / "editorial-751-1000.jsonl",
]
MANUAL_SOURCES = DATA / "manual-sources.json"
DEFAULT_REPORT = DATA / "semantic-review-apply-report.json"
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
SOURCE_ID_RE = re.compile(r"[^a-z0-9-]+")
ALLOWED_VERDICTS = {"accept", "rewrite", "unresolved"}
ALLOWED_PACE = {"slow", "medium", "fast", "mixed", "not_applicable"}
CARD_FIELDS = ("description", "distinctiveDetails", "topics", "tone", "pace")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: JSON object expected")
        rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def default_review_files() -> list[Path]:
    return sorted(DATA.glob("semantic-review-*.jsonl"))


def load_compact_rows() -> tuple[dict[Path, list[dict[str, Any]]], dict[int, dict[str, Any]]]:
    rows_by_file: dict[Path, list[dict[str, Any]]] = {}
    rows_by_id: dict[int, dict[str, Any]] = {}
    for path in COMPACT_FILES:
        rows = read_jsonl(path)
        rows_by_file[path] = rows
        for row in rows:
            catalog_id = int(row["catalogId"])
            if catalog_id in rows_by_id:
                raise ValueError(f"duplicate compact catalogId {catalog_id}")
            rows_by_id[catalog_id] = row
    return rows_by_file, rows_by_id


def load_reviews(paths: list[Path]) -> dict[int, dict[str, Any]]:
    reviews: dict[int, dict[str, Any]] = {}
    for path in paths:
        for review in read_jsonl(path):
            catalog_id = int(review.get("catalogId", 0))
            if catalog_id in reviews:
                raise ValueError(f"duplicate semantic review for catalogId {catalog_id}")
            reviews[catalog_id] = review
    return reviews


def validate_string_list(catalog_id: int, field: str, value: Any, low: int, high: int) -> list[str]:
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise ValueError(f"{catalog_id}: {field} must contain {low}..{high} values")
    cleaned = [str(item).strip() for item in value]
    if any(not item for item in cleaned):
        raise ValueError(f"{catalog_id}: {field} contains an empty value")
    if len({item.casefold().replace("ё", "е") for item in cleaned}) != len(cleaned):
        raise ValueError(f"{catalog_id}: {field} contains duplicates")
    return cleaned


def normalized_source_id(catalog_id: int, index: int, requested: Any) -> str:
    suffix = SOURCE_ID_RE.sub("-", str(requested or "source").strip().casefold()).strip("-")
    suffix = suffix.removeprefix("manual-") or "source"
    return f"manual-semantic-{catalog_id}-{index}-{suffix}"[:96].rstrip("-")


def apply_reviews(
    rows_by_id: dict[int, dict[str, Any]],
    reviews: dict[int, dict[str, Any]],
) -> tuple[set[int], dict[int, list[dict[str, str]]], Counter[str]]:
    changed: set[int] = set()
    manual_sources: dict[int, list[dict[str, str]]] = {}
    verdicts: Counter[str] = Counter()
    for catalog_id, review in sorted(reviews.items()):
        if catalog_id not in rows_by_id:
            raise ValueError(f"semantic review references unknown compact catalogId {catalog_id}")
        row = rows_by_id[catalog_id]
        verdict = str(review.get("verdict", "")).strip().casefold()
        if verdict not in ALLOWED_VERDICTS:
            raise ValueError(f"{catalog_id}: invalid verdict {verdict!r}")
        verdicts[verdict] += 1
        before = json.dumps(row, ensure_ascii=False, sort_keys=True)

        # Every verdict carries a complete reviewed card.  Even when identity or
        # edition metadata remains unresolved, the conservative replacement is
        # still safer than keeping a known bad or mismatched description.
        description = str(review.get("description", "")).strip()
        word_count = len(WORD_RE.findall(description))
        if not 40 <= word_count <= 80:
            raise ValueError(f"{catalog_id}: description has {word_count} words; expected 40..80")
        row["description"] = description
        row["distinctiveDetails"] = validate_string_list(
            catalog_id, "distinctiveDetails", review.get("distinctiveDetails"), 3, 4
        )
        row["topics"] = validate_string_list(catalog_id, "topics", review.get("topics"), 3, 4)
        row["tone"] = validate_string_list(catalog_id, "tone", review.get("tone"), 2, 3)
        pace = str(review.get("pace", "")).strip().casefold()
        if pace not in ALLOWED_PACE:
            raise ValueError(f"{catalog_id}: invalid pace {pace!r}")
        row["pace"] = pace

        sources = review.get("sources", [])
        if not isinstance(sources, list):
            raise ValueError(f"{catalog_id}: sources must be an array")
        prefix = f"manual-semantic-{catalog_id}-"
        row["sourceIds"] = [
            source_id for source_id in row.get("sourceIds", []) if not str(source_id).startswith(prefix)
        ]
        prepared: list[dict[str, str]] = []
        for index, source in enumerate(sources, 1):
            if not isinstance(source, dict):
                raise ValueError(f"{catalog_id}: source #{index} must be an object")
            text = str(source.get("text", "")).strip()
            url = str(source.get("url", "")).strip()
            if not text or not url.startswith("https://"):
                raise ValueError(f"{catalog_id}: source #{index} needs text and an https URL")
            source_id = normalized_source_id(catalog_id, index, source.get("sourceId"))
            prepared.append({
                "sourceId": source_id,
                "language": str(source.get("language", "mixed")).strip() or "mixed",
                "url": url,
                "text": text,
            })
            row["sourceIds"].append(source_id)
        if prepared:
            manual_sources[catalog_id] = prepared

        if verdict == "unresolved":
            reasons = validate_string_list(
                catalog_id, "reviewReasons", review.get("reviewReasons") or row.get("reviewReasons"), 1, 6
            )
            row["needsReview"] = True
            row["reviewReasons"] = reasons
        else:
            row["needsReview"] = False
            row["reviewReasons"] = []

        after = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if after != before:
            changed.add(catalog_id)
    return changed, manual_sources, verdicts


def merge_manual_sources(additions: dict[int, list[dict[str, str]]]) -> list[dict[str, Any]]:
    current = json.loads(MANUAL_SOURCES.read_text(encoding="utf-8")) if MANUAL_SOURCES.exists() else []
    by_id = {int(entry["catalogId"]): entry for entry in current}
    for catalog_id, sources in additions.items():
        entry = by_id.setdefault(catalog_id, {"catalogId": catalog_id, "sources": []})
        prefix = f"manual-semantic-{catalog_id}-"
        preserved = [source for source in entry.get("sources", []) if not source.get("sourceId", "").startswith(prefix)]
        entry["sources"] = [*preserved, *sources]
    return [by_id[catalog_id] for catalog_id in sorted(by_id)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", help="semantic-review JSONL files; defaults to semantic-review-*.jsonl")
    parser.add_argument("--check", action="store_true", help="validate and report without writing")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    review_paths = [Path(value) for value in args.inputs] or default_review_files()
    if not review_paths:
        raise SystemExit("no semantic-review JSONL files found")
    rows_by_file, rows_by_id = load_compact_rows()
    reviews = load_reviews(review_paths)
    changed, additions, verdicts = apply_reviews(rows_by_id, reviews)
    merged_manual_sources = merge_manual_sources(additions)

    report = {
        "inputs": [str(path) for path in review_paths],
        "reviews": len(reviews),
        "verdicts": dict(sorted(verdicts.items())),
        "changed": len(changed),
        "changedIds": sorted(changed),
        "manualSourceProfiles": len(additions),
        "checkOnly": bool(args.check),
    }
    if not args.check:
        for path, rows in rows_by_file.items():
            write_jsonl(path, rows)
        write_json(MANUAL_SOURCES, merged_manual_sources)
        write_json(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
