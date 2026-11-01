from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = ROOT / "data" / "book_catalog" / "pilot"
CATALOG_PATH = ROOT / "data" / "book_catalog" / "catalog.json"
FACTS_PATH = PILOT_DIR / "book_facts.json"
ANNOTATIONS_PATH = PILOT_DIR / "pilot_annotations.json"
OUTPUT_PATH = PILOT_DIR / "draft_catalog.json"
REVIEW_PATH = PILOT_DIR / "REVIEW.md"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def semantic_list(values: list[str]) -> str:
    return "; ".join(values)


def build_search_text(facts: dict) -> str:
    original = facts["originalTitle"]
    original_sentence = (
        ""
        if original.casefold() == facts["title"].casefold()
        else f" Оригинальное название: {original}."
    )
    identity = (
        f"Книга «{facts['title']}».{original_sentence} "
        f"Автор: {semantic_list(facts['authors'])}. "
        f"Тип произведения: {facts['workType']}. "
        f"Первая публикация: {facts['firstPublicationYear']} год."
    )
    parts = [identity, facts["premise"], facts["conflict"]]

    protagonists = facts.get("protagonists", [])
    if protagonists:
        parts.append(f"Главные действующие лица: {semantic_list(protagonists)}.")

    parts.extend(
        [
            f"Место и контекст действия: {semantic_list(facts['setting'])}.",
            f"Ключевые темы: {semantic_list(facts['themes'])}.",
            f"Жанровый профиль: {semantic_list(facts['genres'])}.",
            (
                f"Атмосфера произведения: {semantic_list(facts['moods'])}; "
                f"темп — {facts['pace']}; возрастная категория — {facts['ageRating']}."
            ),
        ]
    )
    return " ".join(parts)


def proposed_values(facts: dict) -> dict:
    values = {
        "title": facts["title"],
        "author": ", ".join(facts["authors"]),
        "authors": facts["authors"],
        "year": facts["firstPublicationYear"],
        "genres": facts["genres"],
        "themes": facts["themes"],
        "mood": facts["moods"],
        "pace": facts["pace"],
        "ageRating": facts["ageRating"],
    }
    if "series" in facts:
        values["series"] = facts["series"]
    return values


def main() -> None:
    catalog = {book["id"]: book for book in read_json(CATALOG_PATH)}
    facts_list = read_json(FACTS_PATH)
    annotations = read_json(ANNOTATIONS_PATH)
    fact_ids = {item["catalogId"] for item in facts_list}
    annotation_ids = {int(item) for item in annotations}

    if len(facts_list) != 20 or len(fact_ids) != 20:
        raise ValueError("Pilot must contain exactly 20 unique books")
    if fact_ids != annotation_ids:
        raise ValueError("Facts and annotations contain different catalog IDs")

    output = []
    comparable_fields = (
        "title", "author", "authors", "year", "genres", "themes",
        "mood", "pace", "ageRating", "series",
    )

    for facts in facts_list:
        catalog_id = facts["catalogId"]
        current = catalog[catalog_id]
        proposed = proposed_values(facts)
        changed_fields = [
            field
            for field in comparable_fields
            if field in proposed and current.get(field) != proposed[field]
        ]
        output.append(
            {
                "catalogId": catalog_id,
                "workKey": facts["workKey"],
                "status": "draft",
                "confidence": facts["confidence"],
                "changedFields": changed_fields,
                "current": {field: current.get(field) for field in comparable_fields},
                "proposed": proposed,
                "annotation": annotations[str(catalog_id)],
                "searchText": build_search_text(facts),
                "sources": facts["sources"],
            }
        )

    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    review = [
        "# Пилотная партия книжных карточек",
        "",
        "Это черновики для рецензии. Основной `catalog.json`, база OpenCart и embeddings не изменены.",
        "",
    ]
    for item in output:
        title = item["proposed"]["title"]
        changed = ", ".join(item["changedFields"]) or "нет"
        source_lines = "\n".join(
            f"- [{source['role']}]({source['url']})" for source in item["sources"]
        )
        review.extend(
            [
                f"## #{item['catalogId']} — {title}",
                "",
                f"Изменяемые поля: `{changed}`. Уверенность: `{item['confidence']:.2f}`.",
                "",
                "### Текущая аннотация",
                "",
                catalog[item["catalogId"]]["annotation"],
                "",
                "### Новая аннотация",
                "",
                item["annotation"],
                "",
                "### Новый searchText",
                "",
                item["searchText"],
                "",
                "### Источники",
                "",
                source_lines,
                "",
            ]
        )
    REVIEW_PATH.write_text("\n".join(review), encoding="utf-8")
    print(f"Pilot drafts generated: {len(output)}")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Review: {REVIEW_PATH}")


if __name__ == "__main__":
    main()
