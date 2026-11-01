from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "book_catalog"
V2_DIR = DATA / "search-text-v2"

CATALOG_PATH = DATA / "catalog.json"
WORKS_PATH = DATA / "work-metadata-cache.json"
OPENLIBRARY_RAW_PATH = DATA / "openlibrary-raw.json"
TRANSLATIONS_PATH = DATA / "work-metadata-ru.json"
MANUAL_PATH = DATA / "manual-fallbacks.json"
PILOT_FACTS_PATH = DATA / "pilot" / "book_facts.json"

SOURCE_PACKS_PATH = V2_DIR / "source-packs.jsonl"
SOURCE_REPORT_PATH = V2_DIR / "source-report.json"
SOURCE_AUDIT_PATH = V2_DIR / "source-audit.json"
WIKIPEDIA_RU_PATH = V2_DIR / "wikipedia-ru-cache.json"
WIKIPEDIA_EN_PATH = V2_DIR / "wikipedia-en-cache.json"
GOOGLE_BOOKS_PATH = V2_DIR / "google-books-cache.json"
MANUAL_V2_SOURCES_PATH = V2_DIR / "manual-sources.json"
GENERATION_BATCH_PATH = V2_DIR / "openai-generation-batch.jsonl"
GENERATION_MANIFEST_PATH = V2_DIR / "generation-batch-manifest.json"
GENERATION_RESULTS_PATH = V2_DIR / "generation-results.jsonl"
PILOT_PROFILE_DRAFT_PATH = V2_DIR / "curated-pilot-profiles.jsonl"
MANUAL_PROFILE_DRAFT_PATH = V2_DIR / "curated-manual-profiles.jsonl"
GENERATION_PREVIEW_PATH = V2_DIR / "generation-preview.json"
VERIFICATION_BATCH_PATH = V2_DIR / "openai-verification-batch.jsonl"
VERIFICATION_MANIFEST_PATH = V2_DIR / "verification-batch-manifest.json"
VERIFICATION_RESULTS_PATH = V2_DIR / "verification-results.jsonl"
DRAFT_PATH = V2_DIR / "profiles-draft.json"
DRAFT_CATALOG_PATH = V2_DIR / "catalog-v2-draft.json"
DRAFT_REPORT_PATH = V2_DIR / "draft-report.json"
REVIEW_PATH = V2_DIR / "review.md"

SOURCE_PACK_VERSION = "search-source-pack-v2.0"
PROFILE_VERSION = "search-profile-v2.0"
VERIFICATION_VERSION = "search-profile-verification-v2.0"
PIPELINE_VERSION = "2.0.0"

CONTENT_TYPES = (
    "fiction",
    "nonfiction",
    "biography",
    "poetry",
    "play",
    "collection",
    "children",
)
PACES = ("slow", "medium", "fast", "mixed", "not_applicable")
VERDICTS = (
    "supported",
    "partial",
    "unsupported",
    "contradicted",
    "spoiler",
    "too_generic",
)

CONTENT_LABELS = {
    "fiction": "художественная проза",
    "nonfiction": "нехудожественная литература",
    "biography": "биография или мемуары",
    "poetry": "поэзия",
    "play": "пьеса",
    "collection": "сборник",
    "children": "детская литература",
}
PACE_LABELS = {
    "slow": "медленный",
    "medium": "средний",
    "fast": "быстрый",
    "mixed": "переменный",
    "not_applicable": "не применим",
}

SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
MARKETING_RE = re.compile(
    r"\b(?:бестселлер|шедевр|обязательно\s+прочитать|не\s+оставит\s+равнодуш|"
    r"подойд[её]т\s+читател|читателям\s+понрав|захватывающ(?:ая|ий|ее)\s+книга|"
    r"книга,?\s+которую\s+должен\s+прочитать)\b",
    re.IGNORECASE,
)
SPOILER_RE = re.compile(
    r"\b(?:в\s+(?:самом\s+)?конце|в\s+финале|развязк[ае]|"
    r"убийцей\s+оказывается|оказывается\s+убийцей|"
    r"главн(?:ый|ая)\s+геро(?:й|иня)\s+(?:погибает|умирает)|"
    r"финальн(?:ый|ая|ое)\s+раскрыти|спойлер)\b",
    re.IGNORECASE,
)
GENERIC_DETAIL_RE = re.compile(
    r"^(?:борьба\s+добра\s+и\s+зла|любовь\s+и\s+дружба|жизненные\s+испытания|"
    r"поиск\s+себя|сложные\s+отношения|неожиданные\s+события)[.!]?$",
    re.IGNORECASE,
)
SOURCE_NOISE_RE = re.compile(
    r"\b(?:publish(?:ed|er|ing|ation)?|edition|isbn|award|prize|bestseller|"
    r"перво(?:е|го)\s+издани|издан(?:ие|ия|ию|ием)|опубликован|публикаци|"
    r"преми|наград|бестселлер|источник\s*:|source\s*:)\b",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "")).strip()


def normalize(value: Any) -> str:
    return " ".join(TOKEN_RE.findall(clean(value).casefold().replace("ё", "е")))


def usable_source_words(value: str) -> int:
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", clean(value)) if clean(part)]
    useful = " ".join(part for part in sentences if not SOURCE_NOISE_RE.search(part))
    return len(TOKEN_RE.findall(useful))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_optional_json(path: Path, default: Any) -> Any:
    return read_json(path) if path.exists() else default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: object expected")
        rows.append(value)
    return rows


def read_object_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.casefold() != ".json":
        return read_jsonl(path)
    value = read_json(path)
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{path}: array of objects expected")
    return value


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def add_source(
    sources: list[dict[str, Any]],
    *,
    source_id: str,
    kind: str,
    language: str,
    trust: str,
    text: str,
    url: str = "",
    derived_from: str = "",
) -> None:
    text = clean(text)
    if not text:
        return
    source = {
        "sourceId": source_id,
        "kind": kind,
        "language": language,
        "trust": trust,
        "url": clean(url),
        "text": text[:12000],
    }
    if derived_from:
        source["derivedFrom"] = derived_from
    sources.append(source)


def pilot_text(item: dict[str, Any]) -> str:
    lines = [
        f"Тип произведения: {clean(item.get('workType'))}.",
        f"Завязка: {clean(item.get('premise'))}",
        f"Основной конфликт: {clean(item.get('conflict'))}",
        "Главные действующие лица: " + "; ".join(map(clean, item.get("protagonists", []))) + ".",
        "Место и контекст: " + "; ".join(map(clean, item.get("setting", []))) + ".",
        "Темы: " + "; ".join(map(clean, item.get("themes", []))) + ".",
        "Жанры: " + "; ".join(map(clean, item.get("genres", []))) + ".",
        "Тон: " + "; ".join(map(clean, item.get("moods", []))) + ".",
        f"Темп: {clean(item.get('pace'))}.",
        f"Аудиторная маркировка: {clean(item.get('ageRating'))}.",
    ]
    return clean(" ".join(line for line in lines if clean(line).rstrip(".:") not in {
        "Тип произведения", "Завязка", "Основной конфликт", "Главные действующие лица",
        "Место и контекст", "Темы", "Жанры", "Тон", "Темп", "Аудиторная маркировка",
    }))


def pilot_line(label: str, value: Any) -> str:
    if isinstance(value, list):
        value = "; ".join(map(clean, value))
    return f"{label}: {clean(value)}."


def pilot_content_type(item: dict[str, Any]) -> tuple[str, str]:
    work_type = normalize(item.get("workType"))
    genres = [normalize(value) for value in item.get("genres", [])]
    if any(value == "детская литература" for value in genres):
        return "children", pilot_line("Жанры", item.get("genres", []))
    if work_type in {"биография", "мемуары"}:
        return "biography", pilot_line("Тип произведения", item.get("workType"))
    if work_type in {
        "научно популярная книга",
        "книга о личных финансах",
        "учебное руководство",
    }:
        return "nonfiction", pilot_line("Тип произведения", item.get("workType"))
    return "fiction", pilot_line("Тип произведения", item.get("workType"))


def pilot_detail_text(value: str, *, role: str, content_type: str) -> str:
    value = clean(value)
    return value if len(TOKEN_RE.findall(value)) >= 2 else ""


def pilot_tone(value: str) -> str:
    forms = {
        "академическая": "академический",
        "аналитическая": "аналитический",
        "атмосферная": "атмосферный",
        "вдумчивая": "вдумчивый",
        "волшебная": "волшебный",
        "динамичная": "динамичный",
        "драматичная": "драматичный",
        "загадочная": "загадочный",
        "интеллектуальная": "интеллектуальный",
        "ироничная": "ироничный",
        "искренняя": "искренний",
        "мистическая": "мистический",
        "меланхоличная": "меланхоличный",
        "мотивирующая": "мотивирующий",
        "мрачная": "мрачный",
        "напряжённая": "напряжённый",
        "наблюдательная": "наблюдательный",
        "ностальгическая": "ностальгический",
        "ободряющая": "ободряющий",
        "познавательная": "познавательный",
        "практичная": "практичный",
        "приключенческая": "приключенческий",
        "притчевая": "притчевый",
        "романтичная": "романтичный",
        "сатирическая": "сатирический",
        "созерцательная": "созерцательный",
        "сосредоточенная": "сосредоточенный",
        "тревожная": "тревожный",
        "тяжёлая": "тяжёлый",
        "уютная": "уютный",
        "увлекательная": "увлекательный",
        "циничная": "циничный",
        "эмоциональная": "эмоциональный",
        "эпическая": "эпический",
        "интимная": "интимный",
        "откровенная": "откровенный",
        "бурная": "бурный",
    }
    value = clean(value)
    return {normalize(key): result for key, result in forms.items()}.get(normalize(value), value)


def pilot_profile(item: dict[str, Any]) -> dict[str, Any]:
    catalog_id = int(item["catalogId"])
    content_type, content_type_quote = pilot_content_type(item)
    source_id = "pilot-curated"

    def evidence(quote: str) -> list[dict[str, str]]:
        return [{"sourceId": source_id, "quote": quote}]

    premise = clean(item.get("premise"))
    conflict = clean(item.get("conflict"))
    people = [clean(value) for value in item.get("protagonists", []) if clean(value)]
    settings = [clean(value) for value in item.get("setting", []) if clean(value)]
    people_quote = pilot_line("Главные действующие лица", people)
    setting_quote = pilot_line("Место и контекст", settings)
    details = []
    for value in people[:3]:
        detail_text = pilot_detail_text(value, role="person", content_type=content_type)
        if detail_text:
            details.append({"text": detail_text, "evidence": evidence(people_quote)})
    for value in settings:
        if len(details) >= 6:
            break
        detail_text = pilot_detail_text(value, role="setting", content_type=content_type)
        if detail_text:
            details.append({"text": detail_text, "evidence": evidence(setting_quote)})

    topics_quote = pilot_line("Темы", item.get("themes", []))
    used_theme_indexes: set[int] = set()
    if len(details) < 2:
        for index, value in enumerate(item.get("themes", [])):
            detail_text = clean(value)
            if len(TOKEN_RE.findall(detail_text)) < 2:
                continue
            details.append({"text": detail_text, "evidence": evidence(topics_quote)})
            used_theme_indexes.add(index)
            if len(details) >= 2:
                break
    tone_quote = pilot_line("Тон", item.get("moods", []))
    age = clean(item.get("ageRating"))
    audience = []
    if age:
        audience = [{
            "text": f"читатели от {age.rstrip('+')} лет",
            "evidence": evidence(pilot_line("Аудиторная маркировка", age)),
        }]
    pace_map = {
        "медленный": "slow",
        "средний": "medium",
        "быстрый": "fast",
        "переменный": "mixed",
        "не применим": "not_applicable",
    }
    pace_ru = normalize(item.get("pace"))
    if pace_ru not in pace_map:
        raise ValueError(f"pilot {catalog_id}: unsupported pace {item.get('pace')!r}")
    if len(details) < 2:
        raise ValueError(f"pilot {catalog_id}: fewer than two concrete details")

    return {
        "schemaVersion": PROFILE_VERSION,
        "catalogId": catalog_id,
        "contentType": content_type,
        "contentTypeEvidence": evidence(content_type_quote),
        "summary": {
            "text": f"{premise} {conflict}",
            "evidence": evidence(premise) + evidence(conflict),
        },
        "distinctiveDetails": details,
        "topics": [
            {"text": clean(value), "evidence": evidence(topics_quote)}
            for index, value in enumerate(item.get("themes", []))
            if index not in used_theme_indexes and clean(value)
        ],
        "tone": [
            {"text": pilot_tone(value), "evidence": evidence(tone_quote)}
            for value in item.get("moods", [])[:4]
            if clean(value)
        ],
        "pace": pace_map[pace_ru],
        "paceEvidence": evidence(pilot_line("Темп", item.get("pace"))),
        "audience": audience,
        "confidence": float(item.get("confidence", 0.95)),
        "needsReview": False,
        "reviewReasons": [],
    }


def export_pilot_profiles(args: argparse.Namespace) -> None:
    pilots = read_json(PILOT_FACTS_PATH)
    excluded = set(args.exclude_id or [])
    existing: set[int] = set(excluded)
    if args.missing_only and GENERATION_RESULTS_PATH.exists():
        existing |= {
            int(row["catalogId"])
            for row in read_jsonl(GENERATION_RESULTS_PATH)
            if row.get("hardValidation", {}).get("ok")
        }
    profiles = [
        pilot_profile(item)
        for item in pilots
        if int(item["catalogId"]) not in existing
    ]
    output_path = Path(args.output) if args.output else PILOT_PROFILE_DRAFT_PATH
    write_jsonl(output_path, profiles)
    print(json.dumps({
        "profiles": len(profiles),
        "skippedExistingValid": len(pilots) - len(profiles),
        "explicitlyExcluded": sorted(excluded),
        "output": str(output_path.relative_to(ROOT)).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))


def manual_text(item: dict[str, Any]) -> str:
    return clean(" ".join([
        clean(item.get("description")),
        "Жанры: " + "; ".join(map(clean, item.get("genres", []))) + ".",
        "Темы: " + "; ".join(map(clean, item.get("themes", []))) + ".",
        "Тон: " + "; ".join(map(clean, item.get("mood", []))) + ".",
        f"Темп: {clean(item.get('pace'))}.",
    ]))


MANUAL_PROFILE_SPECS: dict[int, dict[str, Any]] = {
    67: {
        "contentType": "fiction",
        "summary": (0, 2, 3),
        "details": (
            ("Китнисс Эвердин и Пит Мелларк", (0,)),
            ("Дистрикт 12 и Капитолий", (0,)),
            ("Тур победителей и признаки восстания", (1,)),
            ("юбилейная Квартальная бойня", (3,)),
        ),
    },
    174: {
        "contentType": "fiction", "summary": (0, 1), "contentEvidence": 3,
        "details": (
            ("молодой мечтатель и Настенька", (0,)),
            ("летний Петербург и четыре белые ночи", (0, 1)),
            ("ожидание возлюбленного Настеньки", (1,)),
        ),
    },
    306: {
        "contentType": "nonfiction", "summary": (0, 1, 2), "contentEvidence": 3,
        "details": (
            ("явное содержание сна и скрытые мысли", (1,)),
            ("сгущение, смещение и символизация", (1,)),
            ("метод свободных ассоциаций", (2,)),
            ("история психоаналитических идей", (3,)),
        ),
    },
    352: {
        "contentType": "nonfiction", "summary": (0, 1, 2), "contentEvidence": 3,
        "details": (
            ("подготовка материала и развитие памяти", (1,)),
            ("дикция, аргументы и удержание внимания", (1,)),
            ("регулярная практика выступлений", (2,)),
            ("доклады, презентации и переговоры", (3,)),
        ),
    },
    476: {
        "contentType": "nonfiction", "summary": (0, 1, 2), "contentEvidence": 4,
        "details": (
            ("Хафид, бедный погонщик верблюдов", (0,)),
            ("событие в Вифлееме", (1,)),
            ("десять свитков с принципами труда и жизни", (2,)),
            ("самодисциплина и этика продаж", (4,)),
        ),
    },
    516: {
        "contentType": "fiction", "summary": (0, 1, 2), "contentEvidence": 2,
        "details": (
            ("Генри Чинаски на почте Лос-Анджелеса", (0,)),
            ("монотонная работа и бюрократия", (0,)),
            ("алкоголь, скачки и конфликт с начальством", (1,)),
            ("полуавтобиографический роман", (2,)),
        ),
    },
    535: {
        "contentType": "fiction", "summary": (0, 1, 2), "contentEvidence": 3,
        "details": (
            ("планета с цивилизацией разумных обезьян", (0,)),
            ("лишённые речи одичавшие люди", (0,)),
            ("журналист Улисс Меру", (1,)),
            ("учёные-шимпанзе Зира и Корнелиус", (1,)),
        ),
    },
    637: {
        "contentType": "nonfiction", "summary": (0, 1, 2), "contentEvidence": 0,
        "details": (
            ("рисунки Рембрандта из Берлинского гравюрного кабинета", (0,)),
            ("функция, иконография, материалы и стиль", (1,)),
            ("атрибуция работ мастера и его учеников", (2,)),
            ("графический язык Рембрандта", (3,)),
        ),
    },
    665: {
        "contentType": "fiction", "summary": (0, 1), "contentEvidence": 3,
        "details": (
            ("Наталия по прозвищу Коломета", (0,)),
            ("Барселона времён Гражданской войны", (0,)),
            ("дом, заполненный голубями", (1,)),
            ("борьба за детей и собственное существование", (1,)),
        ),
    },
    796: {
        "contentType": "biography", "summary": (0, 1, 2), "contentEvidence": 2,
        "details": (
            ("бедное детство в Южном Лондоне", (0,)),
            ("путь в ранний Голливуд", (0,)),
            ("образ Бродяги", (1,)),
            ("фильмы и собственная студия", (1,)),
            ("мемуары Чарли Чаплина", (0, 2)),
        ),
    },
    821: {
        "contentType": "fiction", "summary": (0, 1, 2), "contentEvidence": 3,
        "details": (
            ("Фил Дик и Конелюб Фэт", (0,)),
            ("луч розового света", (0,)),
            ("философия, гностицизм и психическое расстройство", (1,)),
            ("фильм «ВАЛИС» и ребёнок София", (2,)),
        ),
    },
    836: {
        "contentType": "nonfiction", "summary": (0, 1, 2), "contentEvidence": 0,
        "details": (
            ("чёрные дыры и космические катастрофы", (1,)),
            ("поиск жизни за пределами Земли", (1,)),
            ("мысленные эксперименты и повседневные сравнения", (2,)),
            ("наука, религия и массовая культура", (1,)),
        ),
        "audience": (("любознательные читатели без специальной математической подготовки", 3),),
    },
    838: {
        "contentType": "nonfiction", "summary": (0, 1, 2), "contentEvidence": 0,
        "details": (
            ("лидерство без должности и полномочий", (0, 1)),
            ("работа в периоды перемен", (2,)),
            ("создание сильной команды", (2,)),
            ("самодисциплина и баланс личной жизни", (3,)),
        ),
    },
    860: {
        "contentType": "fiction", "summary": (0, 1, 2), "contentEvidence": 3,
        "details": (
            ("Нью-Йорк 1920-х годов", (0,)),
            ("рассказчик, служба и брак с Мод", (1,)),
            ("танцовщица Мона", (1,)),
            ("богемные знакомства и путь к писательству", (1, 2)),
        ),
        "audience": (("только взрослые читатели", 4),),
    },
    871: {
        "contentType": "fiction", "summary": (0, 1, 2), "contentEvidence": 4,
        "details": (
            ("журналист Джим Квиллеран", (0,)),
            ("критик Джордж Маунтклеменс", (1,)),
            ("сиамский кот Коко", (1,)),
            ("нападение в галерее и испорченные картины", (2,)),
            ("подозрительная смерть", (2,)),
        ),
    },
    883: {
        "contentType": "biography", "summary": (0, 1, 2), "contentEvidence": 3,
        "details": (
            ("экономка Венди Берри в Хайгроуве", (0,)),
            ("принц Чарльз и принцесса Диана", (0,)),
            ("повседневная жизнь загородной резиденции", (0, 1)),
            ("свидетельство участницы событий", (3,)),
        ),
    },
    895: {
        "contentType": "fiction", "summary": (0, 1, 2), "contentEvidence": 3,
        "details": (
            ("комик Тоби Темпл", (0,)),
            ("актриса Джилл Касл", (1,)),
            ("Голливуд и индустрия развлечений", (0, 3)),
            ("опасный союз, любовь и власть", (2,)),
        ),
    },
    950: {
        "contentType": "nonfiction", "summary": (0, 1, 2), "contentEvidence": 0,
        "details": (
            ("разработка программных систем как работа людей", (0,)),
            ("шумный офис и потеря концентрации", (1,)),
            ("текучесть, давление и сверхурочные", (1,)),
            ("сплочённые команды и доверие", (2,)),
            ("роль менеджера и корпоративная культура", (2,)),
        ),
    },
    953: {
        "contentType": "fiction", "summary": (0, 1, 2), "contentEvidence": 4,
        "details": (
            ("судмедэксперт Сара Линтон", (1,)),
            ("начальник полиции Джеффри Толливер", (1,)),
            ("стрельба на катке", (0,)),
            ("похищение ребёнка", (1,)),
            ("детектив Лина Адамс", (2,)),
        ),
    },
    971: {
        "contentType": "nonfiction", "summary": (0, 1, 2), "contentEvidence": 3,
        "details": (
            ("свод еврейского религиозного права", (0,)),
            ("четырнадцать книг", (1,)),
            ("семейные и имущественные отношения", (1,)),
            ("суд, богослужение и этические нормы", (1,)),
            ("систематизация без цепочек толкований", (2,)),
        ),
    },
}


def manual_profile(item: dict[str, Any]) -> dict[str, Any]:
    catalog_id = int(item["catalogId"])
    spec = MANUAL_PROFILE_SPECS.get(catalog_id)
    if not spec:
        raise ValueError(f"manual fallback {catalog_id}: no reviewed extraction spec")
    sentences = [part for part in SENTENCE_RE.split(clean(item.get("description"))) if clean(part)]
    source_id = "manual-fallback"

    def sentence_at(index: int) -> str:
        try:
            return sentences[index]
        except IndexError as exc:
            raise ValueError(f"manual fallback {catalog_id}: missing sentence {index}") from exc

    def evidence(indexes: Iterable[int]) -> list[dict[str, str]]:
        return [{"sourceId": source_id, "quote": sentence_at(index)} for index in indexes]

    summary_indexes = tuple(spec["summary"])
    genre_quote = pilot_line("Жанры", item.get("genres", []))
    content_evidence = [{"sourceId": source_id, "quote": genre_quote}]
    if "contentEvidence" in spec:
        content_evidence.extend(evidence((int(spec["contentEvidence"]),)))
    topics_quote = pilot_line("Темы", item.get("themes", []))
    tone_quote = pilot_line("Тон", item.get("mood", []))
    audience = [
        {"text": text, "evidence": evidence((index,))}
        for text, index in spec.get("audience", ())
    ]
    pace_map = {
        "медленный": "slow",
        "средний": "medium",
        "быстрый": "fast",
        "переменный": "mixed",
        "не применим": "not_applicable",
    }
    pace_ru = normalize(item.get("pace"))
    if pace_ru not in pace_map:
        raise ValueError(f"manual fallback {catalog_id}: unsupported pace {item.get('pace')!r}")
    return {
        "schemaVersion": PROFILE_VERSION,
        "catalogId": catalog_id,
        "contentType": spec["contentType"],
        "contentTypeEvidence": content_evidence,
        "summary": {
            "text": " ".join(sentence_at(index) for index in summary_indexes),
            "evidence": evidence(summary_indexes),
        },
        "distinctiveDetails": [
            {"text": text, "evidence": evidence(indexes)}
            for text, indexes in spec["details"]
        ],
        "topics": [
            {"text": clean(value), "evidence": [{"sourceId": source_id, "quote": topics_quote}]}
            for value in item.get("themes", [])[:8]
            if clean(value)
        ],
        "tone": [
            {"text": pilot_tone(value), "evidence": [{"sourceId": source_id, "quote": tone_quote}]}
            for value in item.get("mood", [])[:4]
            if clean(value)
        ],
        "pace": pace_map[pace_ru],
        "paceEvidence": [{
            "sourceId": source_id,
            "quote": pilot_line("Темп", item.get("pace")),
        }],
        "audience": audience,
        "confidence": 0.97,
        "needsReview": False,
        "reviewReasons": [],
    }


def export_manual_profiles(args: argparse.Namespace) -> None:
    manuals = read_json(MANUAL_PATH)
    excluded = set(args.exclude_id or [])
    existing: set[int] = set(excluded)
    if args.missing_only and GENERATION_RESULTS_PATH.exists():
        existing |= {
            int(row["catalogId"])
            for row in read_jsonl(GENERATION_RESULTS_PATH)
            if row.get("hardValidation", {}).get("ok")
        }
    profiles = [
        manual_profile(item)
        for item in manuals
        if int(item["catalogId"]) not in existing
    ]
    output_path = Path(args.output) if args.output else MANUAL_PROFILE_DRAFT_PATH
    write_jsonl(output_path, profiles)
    print(json.dumps({
        "profiles": len(profiles),
        "skippedExistingValid": len(manuals) - len(profiles),
        "explicitlyExcluded": sorted(excluded),
        "output": str(output_path.relative_to(ROOT)).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))


def build_source_pack(
    book: dict[str, Any],
    works: dict[str, Any],
    translations: dict[str, Any],
    manuals: dict[int, dict[str, Any]],
    pilots: dict[int, dict[str, Any]],
    external_caches: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    source_records: dict[str, dict[str, Any]],
    manual_v2_sources: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    catalog_id = int(book["id"])
    work_key = clean(book.get("workKey"))
    work = works.get(work_key, {})
    translation = translations.get(work_key, {})
    source_record = source_records.get(work_key, {})
    sources: list[dict[str, Any]] = []

    identity_lines = [
        f"Русское название: {clean(book.get('title'))}.",
        f"Оригинальное название: {clean(book.get('sourceTitle'))}.",
        "Авторы: " + "; ".join(map(clean, book.get("authors", []))) + ".",
        "Имена авторов в исходной записи: " + "; ".join(map(clean, source_record.get("author_name", []))) + ".",
        f"Год первой публикации или создания: {book.get('year')}.",
        f"Серия: {clean(book.get('series'))}.",
    ]
    add_source(
        sources,
        source_id="catalog-identity",
        kind="catalog_identity",
        language="ru",
        trust="bibliographic_only",
        text=" ".join(identity_lines),
        url=clean(book.get("coverSource")) or clean(work.get("sourceUrl")),
    )

    pilot = pilots.get(catalog_id)
    if pilot:
        pilot_urls = [clean(source.get("url")) for source in pilot.get("sources", []) if source.get("url")]
        add_source(
            sources,
            source_id="pilot-curated",
            kind="curated_profile",
            language="ru",
            trust="human_curated",
            text=pilot_text(pilot),
            url=pilot_urls[0] if pilot_urls else "",
        )

    manual = manuals.get(catalog_id)
    if manual:
        manual_urls = [clean(url) for url in manual.get("sources", []) if clean(url)]
        add_source(
            sources,
            source_id="manual-fallback",
            kind="curated_summary",
            language="ru",
            trust="human_curated",
            text=manual_text(manual),
            url=manual_urls[0] if manual_urls else "",
        )

    description = clean(work.get("description"))
    if description:
        add_source(
            sources,
            source_id="openlibrary-description-en",
            kind="source_description",
            language="en",
            trust="external_unverified",
            text=description,
            url=clean(work.get("sourceUrl")),
        )
    description_ru = clean(translation.get("descriptionRu"))
    if description_ru:
        add_source(
            sources,
            source_id="openlibrary-description-ru",
            kind="machine_translation",
            language="ru",
            trust="derived_unverified",
            text=description_ru,
            url=clean(translation.get("sourceUrl")) or clean(work.get("sourceUrl")),
            derived_from="openlibrary-description-en" if description else "",
        )

    subject_parts = []
    for label, key in (
        ("Рубрики", "subjects"),
        ("Люди", "subjectPeople"),
        ("Места", "subjectPlaces"),
        ("Эпохи", "subjectTimes"),
    ):
        values = [clean(value) for value in work.get(key, []) if clean(value)]
        if values:
            subject_parts.append(f"{label}: {'; '.join(values)}.")
    if subject_parts:
        add_source(
            sources,
            source_id="openlibrary-subjects",
            kind="subject_headings",
            language="mixed",
            trust="external_unverified",
            text=" ".join(subject_parts),
            url=clean(work.get("sourceUrl")),
        )

    wikipedia_ru, wikipedia_en, google_books = external_caches
    for source_id, kind, language, cached in (
        ("wikipedia-ru", "encyclopedia_extract", "ru", wikipedia_ru.get(work_key, {})),
        ("wikipedia-en", "encyclopedia_extract", "en", wikipedia_en.get(work_key, {})),
        ("google-books", "publisher_description", "mixed", google_books.get(work_key, {})),
    ):
        if cached.get("status") != "ok" or cached.get("matcherVersion") != "2.1":
            continue
        add_source(
            sources,
            source_id=source_id,
            kind=kind,
            language=language,
            trust="external_unverified",
            text=clean(cached.get("extract")) or clean(cached.get("description")),
            url=clean(cached.get("pageUrl")) or clean(cached.get("infoLink")),
        )

    for index, manual_source in enumerate(manual_v2_sources.get(catalog_id, []), 1):
        requested_id = normalize(manual_source.get("sourceId")).replace(" ", "-")
        source_id = requested_id if requested_id.startswith("manual-") else f"manual-v2-{index}"
        if any(source["sourceId"] == source_id for source in sources):
            raise ValueError(f"catalog #{catalog_id}: duplicate sourceId {source_id!r}")
        add_source(
            sources,
            source_id=source_id,
            kind="curated_source",
            language=clean(manual_source.get("language")) or "mixed",
            trust="human_curated",
            text=clean(manual_source.get("text")),
            url=clean(manual_source.get("url")),
        )

    aliases = list(dict.fromkeys(
        clean(value)
        for value in (
            book.get("title"),
            book.get("sourceTitle"),
            *(book.get("searchAliases", []) if isinstance(book.get("searchAliases"), list) else []),
        )
        if clean(value)
    ))
    pack: dict[str, Any] = {
        "schemaVersion": SOURCE_PACK_VERSION,
        "catalogId": catalog_id,
        "workKey": work_key,
        "identity": {
            "title": clean(book.get("title")),
            "sourceTitle": clean(book.get("sourceTitle")),
            "authors": [clean(author) for author in book.get("authors", []) if clean(author)],
            "sourceAuthors": [clean(author) for author in source_record.get("author_name", []) if clean(author)],
            "aliases": aliases,
            "year": book.get("year"),
            "pages": book.get("pages"),
            "series": clean(book.get("series")),
        },
        "legacyHints": {
            "genres": book.get("genres", []),
            "themes": book.get("themes", []),
            "mood": book.get("mood", []),
            "pace": book.get("pace", ""),
            "ageRating": book.get("ageRating", ""),
            "warning": "Unverified legacy values. Compare only; never cite as evidence.",
        },
        "sources": sources,
    }
    pack["inputHash"] = sha256_text(canonical_json({
        "schemaVersion": pack["schemaVersion"],
        "catalogId": pack["catalogId"],
        "workKey": pack["workKey"],
        "identity": pack["identity"],
        "sources": pack["sources"],
    }))
    return pack


def prepare(args: argparse.Namespace) -> None:
    catalog = read_json(CATALOG_PATH)
    works = read_json(WORKS_PATH)
    translations = read_json(TRANSLATIONS_PATH)
    manuals = {int(item["catalogId"]): item for item in read_json(MANUAL_PATH)}
    pilots = {int(item["catalogId"]): item for item in read_json(PILOT_FACTS_PATH)}
    source_records = {clean(item.get("key")): item for item in read_json(OPENLIBRARY_RAW_PATH)}
    manual_v2_rows = read_optional_json(MANUAL_V2_SOURCES_PATH, [])
    manual_v2_sources = {
        int(item["catalogId"]): item.get("sources", []) for item in manual_v2_rows
    }
    external_caches = (
        read_optional_json(WIKIPEDIA_RU_PATH, {}),
        read_optional_json(WIKIPEDIA_EN_PATH, {}),
        read_optional_json(GOOGLE_BOOKS_PATH, {}),
    )
    if args.limit:
        catalog = catalog[: args.limit]

    packs = [
        build_source_pack(
            book, works, translations, manuals, pilots, external_caches,
            source_records, manual_v2_sources,
        )
        for book in catalog
    ]
    write_jsonl(SOURCE_PACKS_PATH, packs)

    kind_counts = Counter(source["kind"] for pack in packs for source in pack["sources"])
    trust_counts = Counter(source["trust"] for pack in packs for source in pack["sources"])
    weak_books = []
    for pack in packs:
        human = any(source["trust"] == "human_curated" for source in pack["sources"])
        independent = {
            source["kind"] for source in pack["sources"]
            if source["kind"] in {"source_description", "encyclopedia_extract", "publisher_description"}
        }
        description_words = max((
            len(TOKEN_RE.findall(source["text"]))
            for source in pack["sources"] if source["kind"] == "source_description"
        ), default=0)
        usable_description_words = max((
            usable_source_words(source["text"])
            for source in pack["sources"] if source["kind"] == "source_description"
        ), default=0)
        reasons = []
        if not human and usable_description_words < 45:
            reasons.append(
                f"source description has only {usable_description_words} usable content words "
                f"({description_words} total)"
            )
        if not human and len(independent) < 2:
            reasons.append("fewer than two independent content sources")
        if reasons:
            weak_books.append({
                "catalogId": pack["catalogId"],
                "workKey": pack["workKey"],
                "title": pack["identity"]["title"],
                "sourceTitle": pack["identity"]["sourceTitle"],
                "descriptionWords": description_words,
                "usableDescriptionWords": usable_description_words,
                "reasons": reasons,
            })

    content_sources = {
        "humanCurated": sum(any(source["trust"] == "human_curated" for source in pack["sources"]) for pack in packs),
        "sourceDescription": sum(any(source["kind"] == "source_description" for source in pack["sources"]) for pack in packs),
        "translation": sum(any(source["kind"] == "machine_translation" for source in pack["sources"]) for pack in packs),
        "subjectsOnly": sum(
            not any(source["kind"] in {"curated_profile", "curated_summary", "source_description", "machine_translation"}
                    for source in pack["sources"])
            and any(source["kind"] == "subject_headings" for source in pack["sources"])
            for pack in packs
        ),
        "noContentEvidence": sum(
            not any(source["kind"] in {"curated_profile", "curated_summary", "source_description", "machine_translation"}
                    for source in pack["sources"])
            for pack in packs
        ),
        "twoIndependentContentSources": sum(
            len({
                source["kind"] for source in pack["sources"]
                if source["kind"] in {"source_description", "encyclopedia_extract", "publisher_description"}
            }) >= 2
            or any(source["trust"] == "human_curated" for source in pack["sources"])
            for pack in packs
        ),
        "thinDescriptionWithoutHumanSource": sum(
            "usable content words" in " ".join(item["reasons"])
            for item in weak_books
        ),
        "weakOrSingleSource": len(weak_books),
    }
    report = {
        "pipelineVersion": PIPELINE_VERSION,
        "schemaVersion": SOURCE_PACK_VERSION,
        "createdAt": now_iso(),
        "catalogSha256": sha256_text(CATALOG_PATH.read_text(encoding="utf-8")),
        "books": len(packs),
        "sourceKinds": dict(sorted(kind_counts.items())),
        "sourceTrust": dict(sorted(trust_counts.items())),
        "coverage": content_sources,
        "output": str(SOURCE_PACKS_PATH.relative_to(ROOT)).replace("\\", "/"),
    }
    write_json(SOURCE_REPORT_PATH, report)
    write_json(SOURCE_AUDIT_PATH, {
        "schemaVersion": SOURCE_PACK_VERSION,
        "createdAt": report["createdAt"],
        "books": weak_books,
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))


EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sourceId", "quote"],
    "properties": {
        "sourceId": {"type": "string", "minLength": 1},
        "quote": {"type": "string", "minLength": 12, "maxLength": 500},
    },
}
CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "evidence"],
    "properties": {
        "text": {"type": "string", "minLength": 2, "maxLength": 900},
        "evidence": {"type": "array", "minItems": 1, "maxItems": 3, "items": EVIDENCE_SCHEMA},
    },
}
PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schemaVersion", "catalogId", "contentType", "contentTypeEvidence", "summary",
        "distinctiveDetails", "topics", "tone", "pace", "paceEvidence", "audience",
        "confidence", "needsReview", "reviewReasons",
    ],
    "properties": {
        "schemaVersion": {"type": "string", "const": PROFILE_VERSION},
        "catalogId": {"type": "integer", "minimum": 1},
        "contentType": {"type": "string", "enum": list(CONTENT_TYPES)},
        "contentTypeEvidence": {"type": "array", "minItems": 1, "maxItems": 3, "items": EVIDENCE_SCHEMA},
        "summary": CLAIM_SCHEMA,
        "distinctiveDetails": {"type": "array", "minItems": 2, "maxItems": 7, "items": CLAIM_SCHEMA},
        "topics": {"type": "array", "minItems": 2, "maxItems": 8, "items": CLAIM_SCHEMA},
        "tone": {"type": "array", "minItems": 1, "maxItems": 4, "items": CLAIM_SCHEMA},
        "pace": {"type": "string", "enum": list(PACES)},
        "paceEvidence": {"type": "array", "minItems": 1, "maxItems": 3, "items": EVIDENCE_SCHEMA},
        "audience": {"type": "array", "maxItems": 4, "items": CLAIM_SCHEMA},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "needsReview": {"type": "boolean"},
        "reviewReasons": {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 2, "maxLength": 300}},
    },
}

GENERATION_INSTRUCTIONS = """You extract a grounded Russian-language search profile for one book.

Rules:
1. Use only SOURCES as evidence. legacyHints are unverified comparison hints and can never support a claim.
2. Every content claim must cite sourceId and a verbatim quote copied from that source's text. A Russian claim may cite an English quote.
3. Do not repair missing facts from memory. If evidence is weak, conflicting, bibliographic-only, or appears to describe an edition/review rather than the work, set needsReview=true and explain why.
4. Write a concrete spoiler-safe premise and distinctive searchable details: protagonists or subject, central situation/conflict, setting, mechanisms, concepts, or named phenomena. Never reveal a resolution, culprit, late twist, death, or final outcome.
5. Remove marketing, awards, sales claims, reviews, edition details, ISBN, page count, publication metadata, and generic praise.
6. Keep topics and tone specific to the evidence. Do not infer fantasy from metaphorical words such as magic, dark, spell, ghost, or wonder without plot evidence.
7. summary: 2-4 Russian sentences, 25-80 words. distinctiveDetails: short concrete phrases/sentences. topics and tone: short noun/adjective phrases.
8. For nonfiction, describe the questions, method, concepts, examples, and practical domain. For fiction, describe premise, conflict, characters, and setting. Adapt similarly for biography, poetry, play, collection, and children.
9. confidence measures source support, not writing fluency. Use <=0.60 when only noisy publisher copy or subject headings are available.
10. Output only the JSON object matching the schema."""


def grounded_pack(pack: dict[str, Any]) -> dict[str, Any]:
    """Return the exact data sent to models, excluding legacy classification hints."""
    return {
        "schemaVersion": pack["schemaVersion"],
        "catalogId": pack["catalogId"],
        "workKey": pack["workKey"],
        "inputHash": pack["inputHash"],
        "identity": pack["identity"],
        "sources": pack["sources"],
    }


def generation_request(pack: dict[str, Any], model: str) -> dict[str, Any]:
    body = {
        "model": model,
        "store": False,
        "instructions": GENERATION_INSTRUCTIONS,
        "input": "SOURCE PACK\n" + json.dumps(grounded_pack(pack), ensure_ascii=False, separators=(",", ":")),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "search_profile_v2",
                "strict": True,
                "schema": PROFILE_SCHEMA,
            },
            "verbosity": "low",
        },
        "reasoning": {"effort": "medium"},
        "max_output_tokens": 3000,
    }
    return {
        "custom_id": f"searchtext-v2-extract-{pack['catalogId']:04d}-{pack['inputHash'][:10]}",
        "method": "POST",
        "url": "/v1/responses",
        "body": body,
    }


def export_generation(args: argparse.Namespace) -> None:
    packs = read_jsonl(SOURCE_PACKS_PATH)
    existing = {}
    if args.missing_only and GENERATION_RESULTS_PATH.exists():
        existing = {
            int(item["catalogId"]): item for item in read_jsonl(GENERATION_RESULTS_PATH)
            if item.get("hardValidation", {}).get("ok")
        }
        packs = [pack for pack in packs if int(pack["catalogId"]) not in existing]
    if args.limit:
        packs = packs[: args.limit]
    requests = [generation_request(pack, args.model) for pack in packs]
    write_jsonl(GENERATION_BATCH_PATH, requests)
    manifest = {
        "pipelineVersion": PIPELINE_VERSION,
        "createdAt": now_iso(),
        "requestCount": len(requests),
        "model": args.model,
        "endpoint": "/v1/responses",
        "promptSha256": sha256_text(GENERATION_INSTRUCTIONS),
        "schemaSha256": sha256_text(canonical_json(PROFILE_SCHEMA)),
        "sourcePackSha256": sha256_text(SOURCE_PACKS_PATH.read_text(encoding="utf-8")),
        "batchFileSha256": sha256_text(GENERATION_BATCH_PATH.read_text(encoding="utf-8")),
        "missingOnly": bool(args.missing_only),
        "preservedValidResults": len(existing),
    }
    write_json(GENERATION_MANIFEST_PATH, manifest)
    report = {
        "requests": len(requests),
        "model": args.model,
        "endpoint": "/v1/responses",
        "batchFile": str(GENERATION_BATCH_PATH.relative_to(ROOT)).replace("\\", "/"),
        "sourcePackSha256": manifest["sourcePackSha256"],
        "promptSha256": manifest["promptSha256"],
        "schemaSha256": manifest["schemaSha256"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def extract_response_payload(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("schemaVersion") == PROFILE_VERSION or row.get("schemaVersion") == VERIFICATION_VERSION:
        return row
    body = row.get("response", {}).get("body", row.get("body", row))
    if isinstance(body, dict) and isinstance(body.get("output_text"), str):
        return json.loads(body["output_text"])
    for output in body.get("output", []) if isinstance(body, dict) else []:
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                return json.loads(content["text"])
    raise ValueError("response has no JSON output_text")


def evidence_errors(
    evidence: Any,
    sources: dict[str, dict[str, Any]],
    path: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(evidence, list) or not evidence:
        return [f"{path}: evidence must be a non-empty array"]
    if len(evidence) > 3:
        errors.append(f"{path}: evidence has {len(evidence)} items; maximum is 3")
    cited_kinds = []
    for index, ref in enumerate(evidence):
        item_path = f"{path}.evidence[{index}]"
        if not isinstance(ref, dict):
            errors.append(f"{item_path}: object expected")
            continue
        unexpected = sorted(set(ref) - {"sourceId", "quote"})
        missing = sorted({"sourceId", "quote"} - set(ref))
        if unexpected:
            errors.append(f"{item_path}: unexpected keys: {', '.join(unexpected)}")
        if missing:
            errors.append(f"{item_path}: missing keys: {', '.join(missing)}")
        source_id = clean(ref.get("sourceId"))
        quote = clean(ref.get("quote"))
        if not source_id:
            errors.append(f"{item_path}: sourceId is empty")
        if len(quote) > 500:
            errors.append(f"{item_path}: quote exceeds 500 characters")
        source = sources.get(source_id)
        if not source:
            errors.append(f"{item_path}: unknown sourceId {source_id!r}")
            continue
        cited_kinds.append(source.get("kind"))
        if source.get("kind") == "machine_translation":
            derived_from = clean(source.get("derivedFrom"))
            if derived_from and derived_from not in sources:
                errors.append(f"{item_path}: translated source has no original {derived_from!r}")
        if source.get("trust") == "bibliographic_only" and not path.startswith("identity"):
            errors.append(f"{item_path}: catalog identity cannot support content claims")
        if len(quote) < 12:
            errors.append(f"{item_path}: quote is shorter than 12 characters")
        elif clean(quote).casefold() not in clean(source.get("text")).casefold():
            errors.append(f"{item_path}: quote is not present verbatim in source {source_id!r}")
    if (path == "summary" or path.startswith("distinctiveDetails")) and cited_kinds:
        if all(kind == "subject_headings" for kind in cited_kinds):
            errors.append(f"{path}: subject headings alone cannot support narrative or content details")
    return errors


def text_errors(text: Any, path: str, *, min_words: int = 1, max_words: int = 100) -> list[str]:
    value = clean(text)
    errors: list[str] = []
    word_count = len(TOKEN_RE.findall(value))
    if not value:
        errors.append(f"{path}: text is empty")
    if word_count < min_words:
        errors.append(f"{path}: only {word_count} words, expected at least {min_words}")
    if word_count > max_words:
        errors.append(f"{path}: {word_count} words, maximum is {max_words}")
    if MARKETING_RE.search(value):
        errors.append(f"{path}: marketing or recommendation language")
    if SPOILER_RE.search(value):
        errors.append(f"{path}: likely spoiler language")
    return errors


def claim_errors(claim: Any, sources: dict[str, dict[str, Any]], path: str, **limits: int) -> list[str]:
    if not isinstance(claim, dict):
        return [f"{path}: object expected"]
    errors = []
    unexpected = sorted(set(claim) - {"text", "evidence"})
    missing = sorted({"text", "evidence"} - set(claim))
    if unexpected:
        errors.append(f"{path}: unexpected keys: {', '.join(unexpected)}")
    if missing:
        errors.append(f"{path}: missing keys: {', '.join(missing)}")
    errors.extend(text_errors(claim.get("text"), path, **limits))
    errors.extend(evidence_errors(claim.get("evidence"), sources, path))
    return errors


def hard_validate_profile(profile: dict[str, Any], pack: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_keys = {
        "schemaVersion", "catalogId", "contentType", "contentTypeEvidence", "summary",
        "distinctiveDetails", "topics", "tone", "pace", "paceEvidence", "audience",
        "confidence", "needsReview", "reviewReasons",
    }
    unexpected = sorted(set(profile) - expected_keys)
    missing = sorted(expected_keys - set(profile))
    if unexpected:
        errors.append("unexpected profile keys: " + ", ".join(unexpected))
    if missing:
        errors.append("missing profile keys: " + ", ".join(missing))
    if profile.get("schemaVersion") != PROFILE_VERSION:
        errors.append(f"schemaVersion must be {PROFILE_VERSION}")
    if profile.get("catalogId") != pack.get("catalogId"):
        errors.append("catalogId does not match source pack")
    if profile.get("contentType") not in CONTENT_TYPES:
        errors.append("contentType is invalid")
    if profile.get("pace") not in PACES:
        errors.append("pace is invalid")
    if isinstance(profile.get("confidence"), bool) or not isinstance(profile.get("confidence"), (int, float)) or not 0 <= profile.get("confidence", -1) <= 1:
        errors.append("confidence must be between 0 and 1")
    if not isinstance(profile.get("needsReview"), bool):
        errors.append("needsReview must be boolean")
    if not isinstance(profile.get("reviewReasons"), list):
        errors.append("reviewReasons must be an array")
    else:
        if len(profile["reviewReasons"]) > 8:
            errors.append("reviewReasons has more than 8 items")
        for index, reason in enumerate(profile["reviewReasons"]):
            if not isinstance(reason, str) or not 2 <= len(clean(reason)) <= 300:
                errors.append(f"reviewReasons[{index}]: expected 2..300 characters")

    sources = {source["sourceId"]: source for source in pack.get("sources", [])}
    errors.extend(evidence_errors(profile.get("contentTypeEvidence"), sources, "contentType"))
    errors.extend(claim_errors(profile.get("summary"), sources, "summary", min_words=25, max_words=80))
    if isinstance(profile.get("summary"), dict):
        summary_sentences = [part for part in SENTENCE_RE.split(clean(profile["summary"].get("text"))) if clean(part)]
        if not 2 <= len(summary_sentences) <= 4:
            errors.append(f"summary: expected 2..4 sentences, got {len(summary_sentences)}")
    errors.extend(evidence_errors(profile.get("paceEvidence"), sources, "pace"))

    fields = (
        ("distinctiveDetails", 2, 7, 2, 24),
        ("topics", 2, 8, 1, 8),
        ("tone", 1, 4, 1, 6),
        ("audience", 0, 4, 1, 10),
    )
    for field, minimum, maximum, min_words, max_words in fields:
        values = profile.get(field)
        if not isinstance(values, list):
            errors.append(f"{field}: array expected")
            continue
        if not minimum <= len(values) <= maximum:
            errors.append(f"{field}: expected {minimum}..{maximum} items, got {len(values)}")
        seen: set[str] = set()
        for index, claim in enumerate(values):
            path = f"{field}[{index}]"
            errors.extend(claim_errors(claim, sources, path, min_words=min_words, max_words=max_words))
            value = normalize(claim.get("text")) if isinstance(claim, dict) else ""
            if value in seen:
                errors.append(f"{path}: duplicate value")
            seen.add(value)
            if field == "distinctiveDetails" and GENERIC_DETAIL_RE.match(clean(claim.get("text"))):
                errors.append(f"{path}: generic detail")

    if profile.get("needsReview") and not profile.get("reviewReasons"):
        errors.append("needsReview=true requires reviewReasons")
    return errors


def custom_id_catalog_id(custom_id: str) -> int | None:
    match = re.search(r"-(\d{4})-[0-9a-f]{10}$", custom_id)
    return int(match.group(1)) if match else None


def import_generation(args: argparse.Namespace) -> None:
    packs = {int(pack["catalogId"]): pack for pack in read_jsonl(SOURCE_PACKS_PATH)}
    output = []
    previous = {}
    if GENERATION_RESULTS_PATH.exists() and args.merge:
        previous = {int(item["catalogId"]): item for item in read_jsonl(GENERATION_RESULTS_PATH)}
    parse_errors = []
    for line_number, row in enumerate(read_object_rows(Path(args.input)), 1):
        catalog_id = custom_id_catalog_id(clean(row.get("custom_id")))
        try:
            profile = extract_response_payload(row)
            catalog_id = int(profile.get("catalogId", catalog_id or 0))
            pack = packs[catalog_id]
            errors = hard_validate_profile(profile, pack)
            custom_id = clean(row.get("custom_id"))
            if custom_id and not custom_id.endswith(pack["inputHash"][:10]):
                errors.append("custom_id input hash does not match current source pack")
            body = row.get("response", {}).get("body", row.get("body", {}))
            output.append({
                "catalogId": catalog_id,
                "inputHash": pack["inputHash"],
                "profile": profile,
                "hardValidation": {"ok": not errors, "errors": errors},
                "generation": {
                    "customId": custom_id,
                    "responseId": clean(body.get("id")) if isinstance(body, dict) else "",
                    "model": clean(body.get("model")) if isinstance(body, dict) else "",
                    "promptSha256": sha256_text(GENERATION_INSTRUCTIONS),
                    "schemaSha256": sha256_text(canonical_json(PROFILE_SCHEMA)),
                },
                "importedAt": now_iso(),
            })
        except Exception as exc:
            parse_errors.append({"line": line_number, "catalogId": catalog_id, "error": str(exc)})
    for item in output:
        previous[int(item["catalogId"])] = item
    output = sorted(previous.values(), key=lambda item: item["catalogId"])
    write_jsonl(GENERATION_RESULTS_PATH, output)
    report = {
        "imported": len(output),
        "hardValid": sum(item["hardValidation"]["ok"] for item in output),
        "hardInvalid": sum(not item["hardValidation"]["ok"] for item in output),
        "parseErrors": parse_errors,
        "output": str(GENERATION_RESULTS_PATH.relative_to(ROOT)).replace("\\", "/"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


VERIFICATION_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path", "verdict", "reason"],
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 100},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string", "minLength": 2, "maxLength": 500},
    },
}
VERIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schemaVersion", "catalogId", "checks", "decision", "reviewReasons"],
    "properties": {
        "schemaVersion": {"type": "string", "const": VERIFICATION_VERSION},
        "catalogId": {"type": "integer", "minimum": 1},
        "checks": {"type": "array", "minItems": 7, "maxItems": 30, "items": VERIFICATION_CHECK_SCHEMA},
        "decision": {"type": "string", "enum": ["accept", "review", "reject"]},
        "reviewReasons": {"type": "array", "maxItems": 12, "items": {"type": "string", "minLength": 2, "maxLength": 300}},
    },
}

VERIFICATION_INSTRUCTIONS = """You are the independent evidence verifier for a Russian book search profile.

Check every listed claim against the supplied source pack and cited quote. Do not use outside knowledge.
Return exactly one check for each required path supplied in REQUIRED PATHS, using that exact path.

Verdicts:
- supported: the source directly supports the whole claim;
- partial: only part of the claim is supported or the wording is stronger than the source;
- unsupported: the source does not support it;
- contradicted: a source conflicts with it;
- spoiler: it reveals a resolution, culprit, late twist, major death, or final outcome;
- too_generic: it is vague boilerplate and adds no book-specific retrieval signal.

Check content type, premise, each detail, topics, tone, pace, and audience independently. Metaphorical words do not prove a fantasy genre or supernatural plot. Publisher adjectives do not prove tone. Subject headings can support topics but usually cannot support a detailed premise. Machine translation must remain consistent with its original when both exist.

decision=accept only when every path is supported and there is no unresolved source conflict. Use review for plausible but partial/ambiguous cases and reject for unsupported, contradicted, or spoiler content. Output only JSON matching the schema."""


def claim_paths(profile: dict[str, Any]) -> list[str]:
    paths = ["contentType", "summary"]
    for field in ("distinctiveDetails", "topics", "tone"):
        paths.extend(f"{field}[{index}]" for index, _ in enumerate(profile.get(field, [])))
    paths.append("pace")
    paths.extend(f"audience[{index}]" for index, _ in enumerate(profile.get("audience", [])))
    return paths


def verification_request(
    result: dict[str, Any], pack: dict[str, Any], model: str,
) -> dict[str, Any]:
    profile = result["profile"]
    payload = {
        "requiredPaths": claim_paths(profile),
        "profile": profile,
        "sourcePack": grounded_pack(pack),
    }
    body = {
        "model": model,
        "store": False,
        "instructions": VERIFICATION_INSTRUCTIONS,
        "input": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "search_profile_verification_v2",
                "strict": True,
                "schema": VERIFICATION_SCHEMA,
            },
            "verbosity": "low",
        },
        "reasoning": {"effort": "high"},
        "max_output_tokens": 3500,
    }
    return {
        "custom_id": f"searchtext-v2-verify-{pack['catalogId']:04d}-{pack['inputHash'][:10]}",
        "method": "POST",
        "url": "/v1/responses",
        "body": body,
    }


def export_verification(args: argparse.Namespace) -> None:
    packs = {int(pack["catalogId"]): pack for pack in read_jsonl(SOURCE_PACKS_PATH)}
    results = read_jsonl(GENERATION_RESULTS_PATH)
    valid = [item for item in results if item.get("hardValidation", {}).get("ok")]
    existing = {}
    if args.missing_only and VERIFICATION_RESULTS_PATH.exists():
        existing = {
            int(item["catalogId"]): item for item in read_jsonl(VERIFICATION_RESULTS_PATH)
            if item.get("hardValidation", {}).get("ok")
        }
        valid = [item for item in valid if int(item["catalogId"]) not in existing]
    if args.limit:
        valid = valid[: args.limit]
    requests = [verification_request(item, packs[int(item["catalogId"])], args.model) for item in valid]
    write_jsonl(VERIFICATION_BATCH_PATH, requests)
    manifest = {
        "pipelineVersion": PIPELINE_VERSION,
        "createdAt": now_iso(),
        "requestCount": len(requests),
        "model": args.model,
        "endpoint": "/v1/responses",
        "promptSha256": sha256_text(VERIFICATION_INSTRUCTIONS),
        "schemaSha256": sha256_text(canonical_json(VERIFICATION_SCHEMA)),
        "generationResultsSha256": sha256_text(GENERATION_RESULTS_PATH.read_text(encoding="utf-8")),
        "batchFileSha256": sha256_text(VERIFICATION_BATCH_PATH.read_text(encoding="utf-8")),
        "missingOnly": bool(args.missing_only),
        "preservedValidResults": len(existing),
    }
    write_json(VERIFICATION_MANIFEST_PATH, manifest)
    print(json.dumps({
        "requests": len(requests),
        "skippedHardInvalid": len(results) - len(valid),
        "model": args.model,
        "batchFile": str(VERIFICATION_BATCH_PATH.relative_to(ROOT)).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))


def validate_verification(
    verification: dict[str, Any], result: dict[str, Any], pack: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    expected_keys = {"schemaVersion", "catalogId", "checks", "decision", "reviewReasons"}
    unexpected_keys = sorted(set(verification) - expected_keys)
    missing_keys = sorted(expected_keys - set(verification))
    if unexpected_keys:
        errors.append("unexpected verification keys: " + ", ".join(unexpected_keys))
    if missing_keys:
        errors.append("missing verification keys: " + ", ".join(missing_keys))
    if verification.get("schemaVersion") != VERIFICATION_VERSION:
        errors.append(f"schemaVersion must be {VERIFICATION_VERSION}")
    if verification.get("catalogId") != pack.get("catalogId"):
        errors.append("catalogId does not match")
    if verification.get("decision") not in {"accept", "review", "reject"}:
        errors.append("invalid decision")
    checks = verification.get("checks")
    if not isinstance(checks, list):
        return errors + ["checks must be an array"]
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(f"checks[{index}]: object expected")
            continue
        unexpected = sorted(set(check) - {"path", "verdict", "reason"})
        missing = sorted({"path", "verdict", "reason"} - set(check))
        if unexpected:
            errors.append(f"checks[{index}]: unexpected keys: {', '.join(unexpected)}")
        if missing:
            errors.append(f"checks[{index}]: missing keys: {', '.join(missing)}")
        if not clean(check.get("reason")):
            errors.append(f"checks[{index}]: reason is empty")
    expected = claim_paths(result["profile"])
    actual = [check.get("path") for check in checks if isinstance(check, dict)]
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    duplicates = sorted(path for path, count in Counter(actual).items() if count > 1)
    if missing:
        errors.append("missing checks: " + ", ".join(missing))
    if unexpected:
        errors.append("unexpected checks: " + ", ".join(unexpected))
    if duplicates:
        errors.append("duplicate checks: " + ", ".join(duplicates))
    invalid_verdicts = [check.get("verdict") for check in checks if check.get("verdict") not in VERDICTS]
    if invalid_verdicts:
        errors.append("invalid verdicts")
    verdicts = [check.get("verdict") for check in checks]
    if verification.get("decision") == "accept" and any(verdict != "supported" for verdict in verdicts):
        errors.append("decision=accept requires every check to be supported")
    if verification.get("decision") in {"review", "reject"} and not verification.get("reviewReasons"):
        errors.append("review or reject decision requires reviewReasons")
    if result["profile"].get("needsReview") and verification.get("decision") == "accept":
        errors.append("generator requested review")
    return errors


def import_verification(args: argparse.Namespace) -> None:
    packs = {int(pack["catalogId"]): pack for pack in read_jsonl(SOURCE_PACKS_PATH)}
    generations = {int(item["catalogId"]): item for item in read_jsonl(GENERATION_RESULTS_PATH)}
    output = []
    previous = {}
    if VERIFICATION_RESULTS_PATH.exists() and args.merge:
        previous = {int(item["catalogId"]): item for item in read_jsonl(VERIFICATION_RESULTS_PATH)}
    parse_errors = []
    for line_number, row in enumerate(read_object_rows(Path(args.input)), 1):
        catalog_id = custom_id_catalog_id(clean(row.get("custom_id")))
        try:
            verification = extract_response_payload(row)
            catalog_id = int(verification.get("catalogId", catalog_id or 0))
            result = generations[catalog_id]
            pack = packs[catalog_id]
            errors = validate_verification(verification, result, pack)
            custom_id = clean(row.get("custom_id"))
            if custom_id and not custom_id.endswith(pack["inputHash"][:10]):
                errors.append("custom_id input hash does not match current source pack")
            body = row.get("response", {}).get("body", row.get("body", {}))
            output.append({
                "catalogId": catalog_id,
                "inputHash": pack["inputHash"],
                "verification": verification,
                "hardValidation": {"ok": not errors, "errors": errors},
                "verificationRun": {
                    "customId": custom_id,
                    "responseId": clean(body.get("id")) if isinstance(body, dict) else "",
                    "model": clean(body.get("model")) if isinstance(body, dict) else "",
                    "promptSha256": sha256_text(VERIFICATION_INSTRUCTIONS),
                    "schemaSha256": sha256_text(canonical_json(VERIFICATION_SCHEMA)),
                },
                "importedAt": now_iso(),
            })
        except Exception as exc:
            parse_errors.append({"line": line_number, "catalogId": catalog_id, "error": str(exc)})
    for item in output:
        previous[int(item["catalogId"])] = item
    output = sorted(previous.values(), key=lambda item: item["catalogId"])
    write_jsonl(VERIFICATION_RESULTS_PATH, output)
    print(json.dumps({
        "imported": len(output),
        "hardValid": sum(item["hardValidation"]["ok"] for item in output),
        "accepted": sum(
            item["hardValidation"]["ok"] and item["verification"].get("decision") == "accept"
            for item in output
        ),
        "parseErrors": parse_errors,
        "output": str(VERIFICATION_RESULTS_PATH.relative_to(ROOT)).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))


def sentence(value: str) -> str:
    value = clean(value)
    if not value or value[-1] in ".!?":
        return value
    return value + "."


def claim_texts(profile: dict[str, Any], field: str) -> list[str]:
    return [clean(item.get("text")) for item in profile.get(field, []) if clean(item.get("text"))]


def render_search_text(pack: dict[str, Any], profile: dict[str, Any]) -> str:
    identity = pack["identity"]
    title = clean(identity["title"])
    source_title = clean(identity.get("sourceTitle"))
    author = ", ".join(identity.get("authors", []))
    original = f" ({source_title})" if source_title and normalize(source_title) != normalize(title) else ""
    parts = [sentence(f"«{title}»{original} — {CONTENT_LABELS[profile['contentType']]}; автор: {author}")]
    alternate_titles = [
        clean(value)
        for value in identity.get("aliases", [])
        if clean(value)
        and normalize(value) not in {normalize(title), normalize(source_title)}
    ]
    if alternate_titles:
        parts.append(sentence("Другие названия: " + "; ".join(alternate_titles)))
    parts.append(sentence(profile["summary"]["text"]))
    details = claim_texts(profile, "distinctiveDetails")
    if details:
        parts.append(sentence("Характерные детали: " + "; ".join(details)))
    topics = claim_texts(profile, "topics")
    if topics:
        parts.append(sentence("Темы: " + "; ".join(topics)))
    tones = claim_texts(profile, "tone")
    if tones:
        parts.append(sentence("Тон: " + "; ".join(tones)))
    parts.append(sentence("Темп: " + PACE_LABELS[profile["pace"]]))
    audience = claim_texts(profile, "audience")
    if audience:
        parts.append(sentence("Аудитория: " + "; ".join(audience)))
    return clean(" ".join(parts))


def preview_generation(args: argparse.Namespace) -> None:
    packs = {int(pack["catalogId"]): pack for pack in read_jsonl(SOURCE_PACKS_PATH)}
    generations = read_jsonl(GENERATION_RESULTS_PATH)
    entries = []
    for generation in generations:
        catalog_id = int(generation["catalogId"])
        pack = packs[catalog_id]
        profile = generation["profile"]
        errors = hard_validate_profile(profile, pack)
        search_text = render_search_text(pack, profile)
        words = len(TOKEN_RE.findall(search_text))
        lower, upper = (
            (60, 110)
            if profile["contentType"] in {"fiction", "children", "play", "collection"}
            else (70, 130)
        )
        if not lower <= words <= upper:
            errors.append(f"rendered searchText has {words} words; expected {lower}..{upper}")
        token_count, token_source = e5_token_count(search_text)
        if token_count is None:
            errors.append("could not verify E5 token count: " + token_source)
        elif token_count > 480:
            errors.append(f"rendered searchText has {token_count} E5 tokens; maximum is 480")
        entries.append({
            "catalogId": catalog_id,
            "title": pack["identity"]["title"],
            "contentType": profile["contentType"],
            "searchText": search_text,
            "wordCount": words,
            "e5TokenCount": token_count,
            "e5Tokenizer": token_source,
            "ok": not errors,
            "errors": errors,
        })
    output_path = Path(args.output) if args.output else GENERATION_PREVIEW_PATH
    payload = {
        "createdAt": now_iso(),
        "profiles": len(entries),
        "valid": sum(entry["ok"] for entry in entries),
        "invalid": sum(not entry["ok"] for entry in entries),
        "entries": entries,
    }
    write_json(output_path, payload)
    print(json.dumps({
        "profiles": payload["profiles"],
        "valid": payload["valid"],
        "invalid": payload["invalid"],
        "output": str(output_path.relative_to(ROOT)).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))


@lru_cache(maxsize=1)
def load_e5_tokenizer() -> tuple[Any | None, str]:
    candidates = [ROOT / "data" / "ml_search" / "local-model"]
    try:
        from transformers import AutoTokenizer
    except Exception as exc:
        return None, f"transformers unavailable: {exc}"
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            tokenizer = AutoTokenizer.from_pretrained(str(candidate), local_files_only=True)
            return tokenizer, str(candidate)
        except Exception:
            continue
    return None, "no local E5 tokenizer found"


def e5_token_count(value: str) -> tuple[int | None, str]:
    tokenizer, source = load_e5_tokenizer()
    if tokenizer is None:
        return None, source
    return len(tokenizer.encode("passage: " + value, add_special_tokens=True, truncation=False)), source


def normalized_sentences(value: str) -> list[str]:
    return [normalize(part) for part in SENTENCE_RE.split(value) if len(TOKEN_RE.findall(part)) >= 5]


def assemble(args: argparse.Namespace) -> None:
    catalog = read_json(CATALOG_PATH)
    catalog_by_id = {int(book["id"]): book for book in catalog}
    packs = {int(pack["catalogId"]): pack for pack in read_jsonl(SOURCE_PACKS_PATH)}
    generations = {int(item["catalogId"]): item for item in read_jsonl(GENERATION_RESULTS_PATH)}
    verifications = {int(item["catalogId"]): item for item in read_jsonl(VERIFICATION_RESULTS_PATH)}

    entries = []
    sentence_counts: Counter[str] = Counter()
    search_text_counts: Counter[str] = Counter()
    for catalog_id in sorted(catalog_by_id):
        book = catalog_by_id[catalog_id]
        pack = packs.get(catalog_id)
        generation = generations.get(catalog_id)
        verification = verifications.get(catalog_id)
        errors: list[str] = []
        status = "accepted"
        if not pack:
            errors.append("missing source pack")
        if not generation:
            errors.append("missing generation")
        elif not generation.get("hardValidation", {}).get("ok"):
            errors.extend(generation["hardValidation"].get("errors", []))
        if not verification:
            errors.append("missing verification")
        elif not verification.get("hardValidation", {}).get("ok"):
            errors.extend(verification["hardValidation"].get("errors", []))
        elif verification["verification"].get("decision") != "accept":
            errors.append("verifier decision: " + clean(verification["verification"].get("decision")))
            errors.extend(verification["verification"].get("reviewReasons", []))
        if errors:
            status = "review"

        search_text = ""
        profile = generation.get("profile") if generation else None
        token_count = None
        token_source = ""
        if status == "accepted" and pack and profile:
            search_text = render_search_text(pack, profile)
            words = len(TOKEN_RE.findall(search_text))
            lower, upper = (60, 110) if profile["contentType"] in {"fiction", "children", "play", "collection"} else (70, 130)
            if not lower <= words <= upper:
                errors.append(f"rendered searchText has {words} words; expected {lower}..{upper}")
            if MARKETING_RE.search(search_text):
                errors.append("rendered searchText contains marketing language")
            if SPOILER_RE.search(search_text):
                errors.append("rendered searchText contains likely spoiler language")
            token_count, token_source = e5_token_count(search_text)
            if token_count is None:
                errors.append("could not verify E5 token count: " + token_source)
            elif token_count > 480:
                errors.append(f"rendered searchText has {token_count} E5 tokens; maximum is 480")
            if errors:
                status = "review"
            search_text_counts[normalize(search_text)] += 1
            sentence_counts.update(normalized_sentences(search_text))

        entries.append({
            "catalogId": catalog_id,
            "workKey": clean(book.get("workKey")),
            "status": status,
            "inputHash": pack.get("inputHash") if pack else None,
            "profileVersion": PROFILE_VERSION,
            "aliases": pack.get("identity", {}).get("aliases", []) if pack else [],
            "profile": profile,
            "searchText": search_text,
            "searchTextSha256": sha256_text(search_text) if search_text else None,
            "wordCount": len(TOKEN_RE.findall(search_text)) if search_text else None,
            "e5TokenCount": token_count,
            "e5Tokenizer": token_source,
            "errors": errors,
        })

    duplicate_texts = {text for text, count in search_text_counts.items() if text and count > 1}
    boilerplate_sentences = {text: count for text, count in sentence_counts.items() if count >= max(10, len(catalog) // 20)}
    for entry in entries:
        if entry["status"] != "accepted":
            continue
        normalized_text = normalize(entry["searchText"])
        if normalized_text in duplicate_texts:
            entry["status"] = "review"
            entry["errors"].append("duplicate rendered searchText")
        repeated = [part for part in normalized_sentences(entry["searchText"]) if part in boilerplate_sentences]
        if repeated:
            entry["status"] = "review"
            entry["errors"].append("cross-book boilerplate sentence: " + repeated[0])

    accepted = [entry for entry in entries if entry["status"] == "accepted"]
    review = [entry for entry in entries if entry["status"] != "accepted"]
    write_json(DRAFT_PATH, entries)

    draft_catalog = []
    if not review:
        for entry in entries:
            book = copy.deepcopy(catalog_by_id[entry["catalogId"]])
            book["searchText"] = entry["searchText"]
            book["searchProfileVersion"] = PROFILE_VERSION
            book["searchProfileHash"] = entry["searchTextSha256"]
            draft_catalog.append(book)
        write_json(DRAFT_CATALOG_PATH, draft_catalog)
    elif DRAFT_CATALOG_PATH.exists():
        DRAFT_CATALOG_PATH.unlink()

    report = {
        "pipelineVersion": PIPELINE_VERSION,
        "createdAt": now_iso(),
        "catalogBooks": len(catalog),
        "accepted": len(accepted),
        "review": len(review),
        "complete": not review,
        "duplicateSearchTexts": len(duplicate_texts),
        "boilerplateSentences": boilerplate_sentences,
        "profileDraft": str(DRAFT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "catalogDraft": str(DRAFT_CATALOG_PATH.relative_to(ROOT)).replace("\\", "/") if not review else None,
        "catalogUntouched": True,
    }
    write_json(DRAFT_REPORT_PATH, report)

    lines = ["# Проверка searchText v2", "", f"Принято: {len(accepted)} из {len(entries)}.", ""]
    for entry in review:
        book = catalog_by_id[entry["catalogId"]]
        lines.extend([
            f"## {entry['catalogId']}. {book['title']}", "",
            *[f"- {error}" for error in entry["errors"]], "",
        ])
    REVIEW_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Grounded searchText v2 pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="build versioned source packs")
    prepare_parser.add_argument("--limit", type=int, default=0)
    prepare_parser.set_defaults(func=prepare)

    generation_parser = subparsers.add_parser("export-generation", help="write OpenAI Batch extraction requests")
    generation_parser.add_argument("--model", default="gpt-5.5")
    generation_parser.add_argument("--limit", type=int, default=0)
    generation_parser.add_argument("--missing-only", action="store_true")
    generation_parser.set_defaults(func=export_generation)

    pilot_parser = subparsers.add_parser(
        "export-pilot-profiles",
        help="convert human-curated pilot facts into grounded v2 profiles",
    )
    pilot_parser.add_argument("--output", default="")
    pilot_parser.add_argument("--missing-only", action="store_true")
    pilot_parser.add_argument("--exclude-id", type=int, action="append", default=[])
    pilot_parser.set_defaults(func=export_pilot_profiles)

    manual_parser = subparsers.add_parser(
        "export-manual-profiles",
        help="convert reviewed manual fallback descriptions into grounded v2 profiles",
    )
    manual_parser.add_argument("--output", default="")
    manual_parser.add_argument("--missing-only", action="store_true")
    manual_parser.add_argument("--exclude-id", type=int, action="append", default=[])
    manual_parser.set_defaults(func=export_manual_profiles)

    import_generation_parser = subparsers.add_parser("import-generation", help="import extraction JSONL")
    import_generation_parser.add_argument("input")
    import_generation_parser.add_argument("--merge", action="store_true")
    import_generation_parser.set_defaults(func=import_generation)

    preview_parser = subparsers.add_parser(
        "preview-generation",
        help="render and validate every currently generated profile without verification",
    )
    preview_parser.add_argument("--output", default="")
    preview_parser.set_defaults(func=preview_generation)

    verification_parser = subparsers.add_parser("export-verification", help="write independent verification batch")
    verification_parser.add_argument("--model", default="gpt-5.5")
    verification_parser.add_argument("--limit", type=int, default=0)
    verification_parser.add_argument("--missing-only", action="store_true")
    verification_parser.set_defaults(func=export_verification)

    import_verification_parser = subparsers.add_parser("import-verification", help="import verification JSONL")
    import_verification_parser.add_argument("input")
    import_verification_parser.add_argument("--merge", action="store_true")
    import_verification_parser.set_defaults(func=import_verification)

    assemble_parser = subparsers.add_parser("assemble", help="render and validate parallel v2 draft")
    assemble_parser.set_defaults(func=assemble)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
