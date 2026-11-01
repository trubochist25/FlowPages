from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "data" / "book_catalog" / "catalog.json"
OUTPUT = ROOT / "data" / "experiments" / "defense-search-moderate.cases.json"


SPECS = [
    ("M01", "уютная книга о семье", {"mood": ["уютная"], "themes": ["семья и поколения"]}),
    ("M02", "мрачная история о власти", {"mood": ["мрачная"], "themes": ["власть и общество"]}),
    ("M03", "лёгкая книга о дружбе", {"mood": ["лёгкая"], "themes": ["дружба и взаимопомощь"]}),
    ("M04", "напряжённая история о выживании", {"mood": ["напряжённая"], "themes": ["выживание и испытания"]}),
    ("M05", "романтичная история о путешествии", {"mood": ["романтичная"], "themes": ["путешествия и приключения"]}),
    ("M06", "вдумчивая книга о смысле жизни", {"mood": ["вдумчивая"], "themes": ["смысл жизни и выбор"]}),
    ("M07", "загадочная история о тайнах", {"mood": ["загадочная"], "themes": ["расследование и тайны"]}),
    ("M08", "познавательная книга о науке", {"mood": ["познавательная"], "themes": ["наука и устройство мира"]}),
    ("M09", "динамичная книга о приключениях", {"mood": ["динамичная"], "themes": ["путешествия и приключения"]}),
    ("M10", "страшная история о неизвестном", {"mood": ["страшная"], "themes": ["страх и неизвестность"]}),
    ("G01", "мрачный детектив", {"genres": ["Детективы"], "mood": ["мрачная"]}),
    ("G02", "динамичная фантастика", {"genres": ["Фантастика"], "mood": ["динамичная"]}),
    ("G03", "уютное фэнтези", {"genres": ["Фэнтези"], "mood": ["уютная"]}),
    ("G04", "напряжённый триллер", {"genres": ["Триллеры"], "mood": ["напряжённая"]}),
    ("G05", "лёгкая романтическая книга", {"genres": ["Романтика"], "mood": ["лёгкая"]}),
    ("G06", "страшная книга ужасов", {"genres": ["Ужасы"], "mood": ["страшная"]}),
    ("G07", "приключенческая классика", {"genres": ["Классическая литература"], "mood": ["приключенческая"]}),
    ("G08", "вдумчивая современная проза", {"genres": ["Современная проза"], "mood": ["вдумчивая"]}),
    ("G09", "познавательная биография", {"genres": ["Биографии и мемуары"], "mood": ["познавательная"]}),
    ("G10", "интеллектуальная философская книга", {"genres": ["Философия"], "mood": ["интеллектуальная"]}),
    ("T01", "фантастика про космос", {"genres": ["Фантастика"], "themes": ["космос и открытия"]}),
    ("T02", "детектив про расследование тайны", {"genres": ["Детективы"], "themes": ["расследование и тайны"]}),
    ("T03", "фэнтези про магию", {"genres": ["Фэнтези"], "themes": ["магия и сверхъестественное"]}),
    ("T04", "исторический роман о войне", {"genres": ["Историческая проза"], "themes": ["война и её последствия"]}),
    ("T05", "классика о любви", {"genres": ["Классическая литература"], "themes": ["любовь и отношения"]}),
    ("T06", "приключения о выживании", {"genres": ["Приключения"], "themes": ["выживание и испытания"]}),
    ("T07", "психология о человеческом поведении", {"genres": ["Психология"], "themes": ["мышление и поведение"]}),
    ("T08", "саморазвитие про полезные привычки", {"genres": ["Саморазвитие"], "themes": ["привычки и личный рост"]}),
    ("T09", "научно-популярная книга об устройстве мира", {"genres": ["Научно-популярная литература"], "themes": ["наука и устройство мира"]}),
    ("T10", "фантастика о власти и обществе", {"genres": ["Фантастика"], "themes": ["власть и общество"]}),
    ("C01", "короткий динамичный детектив", {"genres": ["Детективы"], "pace": "быстрый", "pages_max": 300}),
    ("C02", "длинное медленное фэнтези", {"genres": ["Фэнтези"], "pace": "медленный", "pages_min": 400}),
    ("C03", "короткая лёгкая классика", {"genres": ["Классическая литература"], "mood": ["лёгкая"], "pages_max": 300}),
    ("C04", "быстрая фантастика до 350 страниц", {"genres": ["Фантастика"], "pace": "быстрый", "pages_max": 350}),
    ("C05", "небольшой роман о любви", {"genres": ["Романтика"], "themes": ["любовь и отношения"], "pages_max": 350}),
    ("C06", "детское приключение для младших читателей", {"genres": ["Детская литература", "Приключения"], "age": ["6+"]}),
    ("C07", "подростковая фантастика", {"genres": ["Подростковая литература", "Фантастика"]}),
    ("C08", "уютное детское фэнтези", {"genres": ["Детская литература", "Фэнтези"], "mood": ["уютная"]}),
    ("C09", "семейная история для подростка", {"themes": ["семья и поколения"], "age": ["12+"]}),
    ("C10", "мрачный детектив для взрослых", {"genres": ["Детективы"], "mood": ["мрачная"], "age": ["16+", "18+"]}),
]


def matches(book: dict, criteria: dict) -> bool:
    for field in ("genres", "themes", "mood"):
        required = criteria.get(field, [])
        actual = set(book.get(field, []))
        if required and not all(value in actual for value in required):
            return False
    if criteria.get("pace") and book.get("pace") != criteria["pace"]:
        return False
    if criteria.get("age") and book.get("ageRating") not in criteria["age"]:
        return False
    if criteria.get("pages_min") is not None and int(book["pages"]) < criteria["pages_min"]:
        return False
    if criteria.get("pages_max") is not None and int(book["pages"]) > criteria["pages_max"]:
        return False
    return True


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    cases = []
    for query_id, query, criteria in SPECS:
        expected = [book for book in catalog if matches(book, criteria)]
        if not expected:
            raise RuntimeError(f"No relevant books for {query_id}: {query}")
        cases.append(
            {
                "query_id": query_id,
                "category": query_id[0],
                "query": query,
                "criteria": criteria,
                "expected_catalog_ids": [int(book["id"]) for book in expected],
                "expected_titles": [book["title"] for book in expected],
            }
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"cases={len(cases)}")
    for case in cases:
        print(f"{case['query_id']}\t{len(case['expected_catalog_ids'])}\t{case['query']}")
    print("sha256=" + hashlib.sha256(OUTPUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
