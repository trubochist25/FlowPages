#!/usr/bin/env python3
"""Audit compact editorial book profiles before compiling searchText v2."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import search_text_v2 as pipeline


ROOT = Path(__file__).resolve().parents[2]
V2_DIR = ROOT / "data" / "book_catalog" / "search-text-v2"
DEFAULT_OUTPUT = V2_DIR / "editorial-audit.json"
WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
CYRILLIC_WORD_RE = re.compile(r"[а-яё]+", re.IGNORECASE)
STOPWORDS = {
    "автор", "герой", "героиня", "история", "книга", "который", "которая", "которые",
    "между", "после", "перед", "через", "чтобы", "этот", "эта", "эти", "свой", "свою",
    "вместе", "становится", "оказывается", "пытается", "приходится", "начинает", "постепенно",
    "одновременно", "однако", "пока", "когда", "тогда", "затем", "вновь", "снова",
}
GENERIC_TOPICS = {
    "анализ идей", "вера", "деньги и класс", "история вопроса", "личный выбор",
    "любовь и отношения", "наука и познание", "память и прошлое", "политика и общество",
    "человек и природа", "человеческие отношения", "внутренний конфликт",
}
NARRATIVE_KINDS = {
    "curated_profile", "curated_summary", "curated_source", "encyclopedia_extract",
    "machine_translation", "source_description",
}


def words(value: Any) -> list[str]:
    return WORD_RE.findall(pipeline.clean(value).casefold().replace("ё", "е"))


def stems(value: Any) -> set[str]:
    result = set()
    for token in words(value):
        if len(token) < 3 or token in STOPWORDS:
            continue
        result.add(token[:5] if len(token) > 5 else token)
    return result


def read_compact(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: JSON object expected")
            rows.append(value)
    return rows


def sentence_coverages(description: str, source_text: str) -> list[float]:
    source_stems = stems(source_text)
    coverages = []
    for sentence in pipeline.SENTENCE_RE.split(pipeline.clean(description)):
        claim_stems = stems(sentence)
        coverages.append(round(len(claim_stems & source_stems) / max(1, len(claim_stems)), 3))
    return coverages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="compact editorial JSONL files")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    input_paths = [Path(value) for value in args.inputs]
    rows = read_compact(input_paths)
    packs = {int(pack["catalogId"]): pack for pack in pipeline.read_jsonl(pipeline.SOURCE_PACKS_PATH)}
    duplicate_ids = sorted(key for key, count in Counter(int(row["catalogId"]) for row in rows).items() if count > 1)
    description_counts = Counter(pipeline.normalize(row.get("description")) for row in rows)
    topic_arrays = Counter(tuple(pipeline.normalize(value) for value in row.get("topics", [])) for row in rows)

    entries: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda value: int(value["catalogId"])):
        catalog_id = int(row["catalogId"])
        pack = packs[catalog_id]
        source_map = {source["sourceId"]: source for source in pack.get("sources", [])}
        selected = [source_map[value] for value in row.get("sourceIds", []) if value in source_map]
        narrative = [source for source in selected if source.get("kind") in NARRATIVE_KINDS]
        narrative_text = " ".join(source.get("text", "") for source in narrative)
        coverages = sentence_coverages(row.get("description", ""), narrative_text)
        description_words = len(words(row.get("description")))
        reasons: list[str] = []
        if not narrative:
            reasons.append("no selected narrative source")
        # Forty words is enough for a concrete 2--4 sentence synopsis.  A
        # higher mechanical minimum encouraged padding in otherwise complete
        # descriptions, which is worse for retrieval and editorial quality.
        if description_words < 40 or description_words > 80:
            reasons.append(f"description length {description_words}, expected 40..80")
        if coverages and min(coverages) < 0.12:
            reasons.append("one or more description sentences have weak lexical grounding")
        if sum(len(words(source.get("text"))) for source in narrative) < 30:
            reasons.append("selected narrative evidence is shorter than 30 words")
        generic_topics = sorted(GENERIC_TOPICS & set(row.get("topics", [])))
        if len(generic_topics) >= 2:
            reasons.append("multiple generic topics: " + ", ".join(generic_topics))
        if topic_arrays[tuple(pipeline.normalize(value) for value in row.get("topics", []))] > 1:
            reasons.append("complete topic set is duplicated across books")
        if description_counts[pipeline.normalize(row.get("description"))] > 1:
            reasons.append("description is duplicated")

        normalized_description = pipeline.normalize(row.get("description"))
        copied = False
        near_copy = 0.0
        for source in narrative:
            normalized_source = pipeline.normalize(source.get("text"))
            if normalized_description and normalized_description in normalized_source:
                copied = True
            if normalized_description and normalized_source:
                window = normalized_source[: max(len(normalized_description) * 2, 1)]
                near_copy = max(near_copy, SequenceMatcher(None, normalized_description, window).ratio())
        if copied:
            reasons.append("description is copied verbatim from a source")

        entries.append({
            "catalogId": catalog_id,
            "title": pack.get("identity", {}).get("title", ""),
            "descriptionWords": description_words,
            "sentenceLexicalCoverage": coverages,
            "selectedNarrativeWords": sum(len(words(source.get("text"))) for source in narrative),
            "genericTopics": generic_topics,
            "needsReview": bool(row.get("needsReview")),
            "reviewReasons": row.get("reviewReasons", []),
            "auditReasons": reasons,
            "nearCopyRatio": round(near_copy, 3),
        })

    payload = {
        "profiles": len(entries),
        "duplicateIds": duplicate_ids,
        "needsReview": sum(entry["needsReview"] for entry in entries),
        "auditFlagged": sum(bool(entry["auditReasons"]) for entry in entries),
        "weakGrounding": sum(any("grounding" in reason or "evidence" in reason for reason in entry["auditReasons"]) for entry in entries),
        "genericTopicProfiles": sum(bool(entry["genericTopics"]) for entry in entries),
        "verbatimCopies": sum("description is copied verbatim from a source" in entry["auditReasons"] for entry in entries),
        "entries": entries,
    }
    output = Path(args.output)
    pipeline.write_json(output, payload)
    print(json.dumps({key: payload[key] for key in (
        "profiles", "needsReview", "auditFlagged", "weakGrounding", "genericTopicProfiles", "verbatimCopies"
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
