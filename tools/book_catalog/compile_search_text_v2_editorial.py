#!/usr/bin/env python3
"""Compile compact editorial rows into fully evidenced search-profile-v2 objects."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import search_text_v2 as pipeline


ROOT = Path(__file__).resolve().parents[2]
V2_DIR = ROOT / "data" / "book_catalog" / "search-text-v2"
DEFAULT_OUTPUT = V2_DIR / "editorial-profiles.jsonl"
NARRATIVE_KINDS = {
    "curated_profile",
    "curated_summary",
    "curated_source",
    "encyclopedia_extract",
    "machine_translation",
    "source_description",
}
COMPACT_KEYS = {
    "catalogId",
    "contentType",
    "description",
    "distinctiveDetails",
    "topics",
    "tone",
    "pace",
    "sourceIds",
    "needsReview",
    "reviewReasons",
}
WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\s*[;|]\s*")
URL_RE = re.compile(r"(?:https?://|\[[^]]+\]\[[0-9]+\]|\[[0-9]+\]:)", re.IGNORECASE)


def words(value: Any) -> list[str]:
    return WORD_RE.findall(pipeline.clean(value).casefold().replace("ё", "е"))


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: JSON object expected")
        rows.append(value)
    return rows


def source_fragments(source: dict[str, Any]) -> list[str]:
    text = pipeline.clean(source.get("text"))
    fragments: list[str] = []
    for part in SPLIT_RE.split(text):
        part = pipeline.clean(part).strip("-–— ")
        if len(part) < 12 or URL_RE.search(part):
            continue
        if len(part) <= 490:
            fragments.append(part)
            continue
        sentences = pipeline.SENTENCE_RE.split(part)
        fragments.extend(pipeline.clean(item) for item in sentences if 12 <= len(pipeline.clean(item)) <= 490)
    if not fragments and len(text) >= 12:
        fragments.append(text[:490].rsplit(" ", 1)[0])
    return fragments


def overlap_score(claim: str, fragment: str, source: dict[str, Any]) -> float:
    claim_tokens = {token for token in words(claim) if len(token) > 2}
    fragment_tokens = set(words(fragment))
    overlap = len(claim_tokens & fragment_tokens) / max(1, len(claim_tokens))
    kind_bonus = {
        "curated_profile": 0.35,
        "curated_summary": 0.32,
        "curated_source": 0.30,
        "encyclopedia_extract": 0.24,
        "machine_translation": 0.18,
        "source_description": 0.12,
        "subject_headings": 0.08,
    }.get(source.get("kind"), 0.0)
    noise_penalty = 0.4 if pipeline.SOURCE_NOISE_RE.search(fragment) else 0.0
    marketing_penalty = 0.5 if pipeline.MARKETING_RE.search(fragment) else 0.0
    spoiler_penalty = 0.8 if pipeline.SPOILER_RE.search(fragment) else 0.0
    return overlap + kind_bonus - noise_penalty - marketing_penalty - spoiler_penalty


def best_evidence(
    claim: str,
    sources: list[dict[str, Any]],
    *,
    narrative_only: bool = False,
) -> dict[str, str]:
    allowed = [source for source in sources if not narrative_only or source.get("kind") in NARRATIVE_KINDS]
    if not allowed:
        allowed = sources
    candidates: list[tuple[float, int, dict[str, Any], str]] = []
    for source_order, source in enumerate(allowed):
        for fragment in source_fragments(source):
            candidates.append((overlap_score(claim, fragment, source), -source_order, source, fragment))
    if not candidates:
        raise ValueError("no usable evidence fragment")
    _, _, source, quote = max(candidates, key=lambda item: (item[0], item[1]))
    return {"sourceId": source["sourceId"], "quote": quote}


def summary_evidence(description: str, sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    claims = [pipeline.clean(item) for item in pipeline.SENTENCE_RE.split(description) if pipeline.clean(item)]
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        ref = best_evidence(claim, sources, narrative_only=True)
        key = (ref["sourceId"], ref["quote"].casefold())
        if key not in seen:
            refs.append(ref)
            seen.add(key)
        if len(refs) == 3:
            break
    return refs


def field_claims(values: Any, sources: list[dict[str, Any]], *, narrative_only: bool) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [
        {
            "text": pipeline.clean(value),
            "evidence": [best_evidence(pipeline.clean(value), sources, narrative_only=narrative_only)],
        }
        for value in values
        if pipeline.clean(value)
    ]


def compile_row(row: dict[str, Any], pack: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    unexpected = sorted(set(row) - COMPACT_KEYS)
    missing = sorted(COMPACT_KEYS - set(row))
    if unexpected:
        errors.append("unexpected compact keys: " + ", ".join(unexpected))
    if missing:
        errors.append("missing compact keys: " + ", ".join(missing))

    source_map = {source["sourceId"]: source for source in pack.get("sources", [])}
    source_ids = row.get("sourceIds") if isinstance(row.get("sourceIds"), list) else []
    unknown_ids = [pipeline.clean(value) for value in source_ids if pipeline.clean(value) not in source_map]
    if unknown_ids:
        errors.append("unknown sourceIds: " + ", ".join(unknown_ids))
    selected = [source_map[pipeline.clean(value)] for value in source_ids if pipeline.clean(value) in source_map]
    if not any(source.get("kind") in NARRATIVE_KINDS for source in selected):
        fallback = next(
            (source for source in pack.get("sources", []) if source.get("kind") in NARRATIVE_KINDS and source.get("language") == "ru"),
            None,
        )
        if fallback:
            selected.insert(0, fallback)
        else:
            errors.append("no narrative source selected or available")
    subject = next((source for source in pack.get("sources", []) if source.get("kind") == "subject_headings"), None)
    if subject and subject not in selected:
        selected.append(subject)

    description = pipeline.clean(row.get("description"))
    details = field_claims(row.get("distinctiveDetails"), selected, narrative_only=True)
    topics = field_claims(row.get("topics"), selected, narrative_only=False)
    tones = field_claims(row.get("tone"), selected, narrative_only=False)
    content_type = pipeline.clean(row.get("contentType"))
    pace = pipeline.clean(row.get("pace"))
    profile = {
        "schemaVersion": pipeline.PROFILE_VERSION,
        "catalogId": int(row.get("catalogId", 0)),
        "contentType": content_type,
        "contentTypeEvidence": [best_evidence(content_type, selected)],
        "summary": {"text": description, "evidence": summary_evidence(description, selected)},
        "distinctiveDetails": details,
        "topics": topics,
        "tone": tones,
        "pace": pace,
        "paceEvidence": [best_evidence(" ".join(row.get("tone", [])) + " " + pace, selected)],
        "audience": [],
        "confidence": 0.74 if row.get("needsReview") else 0.88,
        "needsReview": bool(row.get("needsReview")),
        "reviewReasons": row.get("reviewReasons") if isinstance(row.get("reviewReasons"), list) else [],
    }
    errors.extend(pipeline.hard_validate_profile(profile, pack))
    rendered = pipeline.render_search_text(pack, profile) if not errors else ""
    if rendered:
        rendered_words = len(words(rendered))
        lower, upper = (60, 110) if content_type in {"fiction", "children", "play", "collection"} else (70, 130)
        if not lower <= rendered_words <= upper:
            errors.append(f"rendered searchText has {rendered_words} words; expected {lower}..{upper}")
    return profile, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="compact editorial JSONL files")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    packs = {int(pack["catalogId"]): pack for pack in pipeline.read_jsonl(pipeline.SOURCE_PACKS_PATH)}
    rows: dict[int, dict[str, Any]] = {}
    duplicate_ids: list[int] = []
    for input_name in args.inputs:
        for row in read_rows(Path(input_name)):
            catalog_id = int(row.get("catalogId", 0))
            if catalog_id in rows:
                duplicate_ids.append(catalog_id)
            rows[catalog_id] = row

    profiles: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for catalog_id, row in sorted(rows.items()):
        pack = packs.get(catalog_id)
        if not pack:
            failures.append({"catalogId": catalog_id, "errors": ["source pack not found"]})
            continue
        try:
            profile, errors = compile_row(row, pack)
        except Exception as exc:  # keep the complete batch audit visible
            failures.append({"catalogId": catalog_id, "errors": [str(exc)]})
            continue
        if errors:
            failures.append({"catalogId": catalog_id, "errors": errors})
        profiles.append(profile)

    output_path = Path(args.output)
    pipeline.write_jsonl(output_path, profiles)
    report_path = output_path.with_suffix(".report.json")
    pipeline.write_json(report_path, {
        "inputs": args.inputs,
        "rows": len(rows),
        "profiles": len(profiles),
        "valid": len(profiles) - len(failures),
        "invalid": len(failures),
        "duplicateIds": sorted(set(duplicate_ids)),
        "failures": failures,
    })
    print(json.dumps({
        "rows": len(rows),
        "profiles": len(profiles),
        "valid": len(profiles) - len(failures),
        "invalid": len(failures),
        "output": str(output_path),
        "report": str(report_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
