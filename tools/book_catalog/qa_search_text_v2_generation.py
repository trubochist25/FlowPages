#!/usr/bin/env python3
"""Produce a reproducible quality report for the complete SearchText v2 draft."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "book_catalog" / "search-text-v2"
RESULTS = DATA / "generation-results.jsonl"
PREVIEW = DATA / "generation-preview.json"
OUTPUT = DATA / "generation-quality-report.json"
COMPACT_FILES = [
    DATA / "editorial-001-250.jsonl",
    DATA / "editorial-154-203.jsonl",
    DATA / "editorial-251-500.jsonl",
    DATA / "editorial-501-750.jsonl",
    DATA / "editorial-751-1000.jsonl",
]
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
META_RE = re.compile(
    r"аннотаци|source\s*pack|предметн(?:ые|ая) рубрик|"
    r"доступн(?:ые|ая|ое|ый) источник|"
    r"источник (?:представляет|описывает|подтверждает|называет|характеризует|"
    r"сообщает|указывает|раскрывает|устанавливает)",
    re.IGNORECASE,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold().replace("ё", "е"))


def duplicate_groups(values: dict[int, Any]) -> list[dict[str, Any]]:
    grouped: dict[Any, list[int]] = {}
    for catalog_id, value in values.items():
        grouped.setdefault(value, []).append(catalog_id)
    return [
        {"catalogIds": ids, "value": value}
        for value, ids in grouped.items()
        if value and len(ids) > 1
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    results = read_jsonl(RESULTS)
    preview = json.loads(PREVIEW.read_text(encoding="utf-8"))
    editorial_audit_path = DATA / "editorial-audit.json"
    editorial_audit = (
        json.loads(editorial_audit_path.read_text(encoding="utf-8"))
        if editorial_audit_path.exists()
        else {}
    )
    compact_ids = {
        int(row["catalogId"])
        for path in COMPACT_FILES
        for row in read_jsonl(path)
    }
    profiles = {int(row["catalogId"]): row["profile"] for row in results}
    preview_entries = {int(row["catalogId"]): row for row in preview["entries"]}

    summaries = {catalog_id: profile["summary"]["text"] for catalog_id, profile in profiles.items()}
    summary_words = {catalog_id: len(WORD_RE.findall(text)) for catalog_id, text in summaries.items()}
    topic_sets = {
        catalog_id: tuple(normalized(value["text"]) for value in profile["topics"])
        for catalog_id, profile in profiles.items()
    }
    summary_sentences: dict[str, list[int]] = {}
    for catalog_id, summary in summaries.items():
        for sentence in SENTENCE_RE.split(summary):
            key = normalized(sentence)
            if len(WORD_RE.findall(key)) >= 8:
                summary_sentences.setdefault(key, []).append(catalog_id)

    duplicate_summaries = duplicate_groups({key: normalized(value) for key, value in summaries.items()})
    duplicate_topics = duplicate_groups(topic_sets)
    duplicate_sentences = [
        {"catalogIds": ids, "sentence": sentence}
        for sentence, ids in summary_sentences.items()
        if len(ids) > 1
    ]
    meta_descriptions = [catalog_id for catalog_id, text in summaries.items() if META_RE.search(text)]
    needs_review = [catalog_id for catalog_id, profile in profiles.items() if profile.get("needsReview")]
    needs_review_without_reason = [
        catalog_id for catalog_id in needs_review if not profiles[catalog_id].get("reviewReasons")
    ]
    hard_invalid = [
        int(row["catalogId"]) for row in results if not row.get("hardValidation", {}).get("ok")
    ]
    preview_invalid = [catalog_id for catalog_id, row in preview_entries.items() if not row.get("ok")]
    expected_ids = set(range(1, 1001))

    search_words = [int(row["wordCount"]) for row in preview_entries.values()]
    e5_tokens = [int(row["e5TokenCount"]) for row in preview_entries.values()]
    detail_counts = [len(profile["distinctiveDetails"]) for profile in profiles.values()]
    topic_counts = [len(profile["topics"]) for profile in profiles.values()]
    tone_counts = [len(profile["tone"]) for profile in profiles.values()]
    payload = {
        "profiles": len(profiles),
        "expectedIdsMissing": sorted(expected_ids - set(profiles)),
        "unexpectedIds": sorted(set(profiles) - expected_ids),
        "editorialProfiles": len(compact_ids),
        "preexistingCuratedProfiles": len(set(profiles) - compact_ids),
        "hardInvalid": hard_invalid,
        "previewInvalid": preview_invalid,
        "needsReview": len(needs_review),
        "needsReviewIds": sorted(needs_review),
        "needsReviewEntries": [
            {
                "catalogId": catalog_id,
                "title": preview_entries[catalog_id]["title"],
                "reviewReasons": profiles[catalog_id].get("reviewReasons", []),
            }
            for catalog_id in sorted(needs_review)
        ],
        "needsReviewWithoutReason": needs_review_without_reason,
        "lexicalGroundingAdvisory": {
            "flaggedEditorialProfiles": editorial_audit.get("weakGrounding"),
            "note": (
                "Conservative lexical overlap heuristic; it overflags Russian paraphrases "
                "and is a review aid, not a semantic verdict."
            ),
        },
        "summaryWords": {"min": min(summary_words.values()), "max": max(summary_words.values())},
        "searchTextWords": {"min": min(search_words), "max": max(search_words)},
        "e5Tokens": {"min": min(e5_tokens), "max": max(e5_tokens), "limit": 480},
        "characteristicCardinality": {
            "distinctiveDetails": {"min": min(detail_counts), "max": max(detail_counts)},
            "topics": {"min": min(topic_counts), "max": max(topic_counts)},
            "tone": {"min": min(tone_counts), "max": max(tone_counts)},
        },
        "duplicateSummaries": duplicate_summaries,
        "duplicateSummarySentences": duplicate_sentences,
        "duplicateCompleteTopicSets": duplicate_topics,
        "readerFacingMetaDescriptions": meta_descriptions,
        "paceCounts": dict(sorted(Counter(profile["pace"] for profile in profiles.values()).items())),
    }
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    concise = {
        "profiles": payload["profiles"],
        "hardInvalid": len(hard_invalid),
        "previewInvalid": len(preview_invalid),
        "needsReview": payload["needsReview"],
        "summaryWords": payload["summaryWords"],
        "searchTextWords": payload["searchTextWords"],
        "e5Tokens": payload["e5Tokens"],
        "duplicateSummaries": len(duplicate_summaries),
        "duplicateSummarySentences": len(duplicate_sentences),
        "duplicateCompleteTopicSets": len(duplicate_topics),
        "readerFacingMetaDescriptions": len(meta_descriptions),
        "output": str(output),
    }
    print(json.dumps(concise, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
