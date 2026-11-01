from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "book_catalog"
DRAFT = DATA / "full-enrichment-draft.json"
REPORT = DATA / "full-enrichment-validation.json"
REVIEW = DATA / "full-enrichment-review.md"

ALLOWED_GENRES = {
    "Психология", "Саморазвитие", "Бизнес и экономика", "История",
    "Биографии и мемуары", "Научно-популярная литература", "Философия",
    "Искусство и культура", "Здоровье", "Родительство",
    "Компьютеры и технологии", "Религия", "Ужасы", "Триллеры",
    "Детективы", "Фантастика", "Фэнтези", "Романтика", "Приключения",
    "Историческая проза", "Юмор", "Поэзия", "Подростковая литература",
    "Детская литература", "Комиксы и манга", "Классическая литература",
    "Современная проза",
}
ALLOWED_PACE = {"быстрый", "средний", "медленный"}
ALLOWED_AGE = {"0+", "6+", "12+", "16+", "18+"}
FATAL_TEXT = re.compile(
    r"https?://|\[\s*(?:источник|source)\s*\]|\[[^]]+\]\[\d+\]|"
    r"\bISBN\b|new york times|\bбестселлер\b|\bцена\s*:",
    re.I,
)
SUSPICIOUS_AUTHOR = re.compile(
    r"редакцион|переводчик|издатель|simon\s*&\s*schuster|\binc\.?$|/",
    re.I,
)
SUSPICIOUS_TITLE = re.compile(
    r"\[(?:\s*id\d+|collection|set|\d+ (?:истори|рассказ))|"
    r"russian edition|gift set|sound library|centennial ed|\bhc\b",
    re.I,
)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def word_count(value: str) -> int:
    return len(re.findall(r"[\wЁё–—-]+", value, re.UNICODE))


def normalized_sentences(value: str) -> list[str]:
    result = []
    for sentence in re.split(r"(?<=[.!?])\s+", value):
        normalized = re.sub(r"[^\w]+", " ", sentence.casefold()).strip()
        if len(normalized.split()) >= 5:
            result.append(normalized)
    return result


def normalize(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold()).replace("ё", "е").strip()


def main() -> None:
    data = read(DRAFT)
    errors: list[str] = []
    warnings: list[str] = []
    measurements = []
    ids = [item.get("catalogId") for item in data]
    work_keys = [item.get("workKey") for item in data]

    if len(data) != 1000:
        errors.append(f"Ожидалось 1000 книг, получено {len(data)}")
    if ids != list(range(1, len(data) + 1)):
        errors.append("catalogId должны быть последовательными от 1 до 1000")
    if len(set(work_keys)) != len(work_keys):
        errors.append("Обнаружены повторяющиеся workKey")

    try:
        from transformers import AutoTokenizer

        model_path = ROOT / "data" / "ml_search" / "local-model"
        tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    except Exception as exc:
        tokenizer = None
        warnings.append(f"Токенизатор E5 не загружен: {exc}")

    annotation_hashes = Counter()
    for item in data:
        cid = item.get("catalogId")
        book = item.get("book", {})
        title = str(book.get("title", "")).strip()
        author = str(book.get("author", "")).strip()
        annotation = str(book.get("annotation", "")).strip()
        search_text = str(book.get("searchText", "")).strip()
        annotation_words = word_count(annotation)
        search_words = word_count(search_text)
        token_count = len(tokenizer.encode(f"passage: {search_text}", add_special_tokens=True)) if tokenizer else None

        required = ("title", "author", "authors", "year", "pages", "genres", "themes", "mood", "pace", "ageRating", "price", "annotation", "searchText")
        missing = [key for key in required if key not in book or book[key] in (None, "", [])]
        if missing:
            errors.append(f"#{cid}: отсутствуют обязательные поля: {', '.join(missing)}")
        if not 80 <= annotation_words <= 110:
            errors.append(f"#{cid}: аннотация содержит {annotation_words} слов")
        if not 110 <= search_words <= 175:
            errors.append(f"#{cid}: searchText содержит {search_words} слов")
        if token_count is not None and token_count > 512:
            errors.append(f"#{cid}: searchText содержит {token_count} токенов E5")
        if FATAL_TEXT.search(annotation) or FATAL_TEXT.search(search_text):
            errors.append(f"#{cid}: в тексте осталась ссылка, разметка или рекламный маркер")
        if normalize(title) not in normalize(search_text):
            errors.append(f"#{cid}: название отсутствует в searchText")
        if author.casefold() not in search_text.casefold():
            errors.append(f"#{cid}: автор отсутствует в searchText")

        authors = [str(value).strip() for value in book.get("authors", [])]
        if author != ", ".join(authors):
            errors.append(f"#{cid}: author не совпадает с authors")
        if len({value.casefold() for value in authors}) != len(authors):
            errors.append(f"#{cid}: автор указан повторно")
        if any(SUSPICIOUS_AUTHOR.search(value) for value in authors):
            warnings.append(f"#{cid}: подозрительная запись автора: {author}")

        genres = book.get("genres", [])
        unknown = sorted(set(genres) - ALLOWED_GENRES)
        if unknown or not 1 <= len(genres) <= 3:
            errors.append(f"#{cid}: некорректные жанры: {genres}")
        if not 2 <= len(book.get("themes", [])) <= 8:
            errors.append(f"#{cid}: ожидается 2–8 тем")
        if not 1 <= len(book.get("mood", [])) <= 3:
            errors.append(f"#{cid}: ожидается 1–3 настроения")
        if book.get("pace") not in ALLOWED_PACE:
            errors.append(f"#{cid}: неизвестный темп {book.get('pace')!r}")
        if book.get("ageRating") not in ALLOWED_AGE:
            errors.append(f"#{cid}: неизвестный возраст {book.get('ageRating')!r}")
        # Отрицательный год — общепринятое машинное представление дат до н. э.
        if not -1000 <= int(book.get("year", 0)) <= 2026 or int(book.get("year", 0)) == 0:
            errors.append(f"#{cid}: некорректный год {book.get('year')!r}")
        if not 10 <= int(book.get("pages", 0)) <= 5000:
            errors.append(f"#{cid}: некорректный объём {book.get('pages')!r}")
        if float(book.get("price", 0)) <= 0:
            errors.append(f"#{cid}: некорректная цена")
        if SUSPICIOUS_TITLE.search(title):
            warnings.append(f"#{cid}: в названии возможна пометка издания: {title}")
        if re.search(r"[ІіЇїЄєЎў]", title):
            errors.append(f"#{cid}: название содержит нерусские кириллические буквы: {title}")

        sentence_counts = Counter(normalized_sentences(annotation))
        repeated = [sentence for sentence, count in sentence_counts.items() if count > 1]
        if repeated:
            errors.append(f"#{cid}: в аннотации повторяется предложение")
        annotation_hashes[hashlib.sha1(annotation.casefold().encode()).hexdigest()] += 1

        sources = item.get("sources", [])
        if not sources or any(not str(source.get("url", "")).startswith("https://") for source in sources):
            errors.append(f"#{cid}: нет проверяемого HTTPS-источника")
        measurements.append({
            "catalogId": cid,
            "title": title,
            "provenance": item.get("provenance"),
            "annotationWords": annotation_words,
            "searchTextWords": search_words,
            "searchTextTokens": token_count,
        })

    duplicate_annotations = sum(count - 1 for count in annotation_hashes.values() if count > 1)
    if duplicate_annotations:
        errors.append(f"Полностью совпадающих аннотаций: {duplicate_annotations}")

    provenance = Counter(item.get("provenance") for item in data)
    summary = {
        "books": len(data),
        "provenance": dict(provenance),
        "annotationWordsMin": min(x["annotationWords"] for x in measurements),
        "annotationWordsMax": max(x["annotationWords"] for x in measurements),
        "searchTextWordsMin": min(x["searchTextWords"] for x in measurements),
        "searchTextWordsMax": max(x["searchTextWords"] for x in measurements),
        "searchTextTokensMax": max((x["searchTextTokens"] or 0) for x in measurements),
        "warnings": len(warnings),
    }
    report = {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "measurements": measurements,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    review_ids = set(range(1, 1001, 17))
    review_ids.update(item["catalogId"] for item in data if item.get("provenance") != "openlibrary-description")
    lines = ["# Рецензирование полного каталога", "", f"Статус автоматики: **{report['status']}**", "", f"Выборка: {len(review_ids)} карточек из 1000.", ""]
    for item in data:
        if item["catalogId"] not in review_ids:
            continue
        book = item["book"]
        lines.extend([
            f"## {item['catalogId']}. {book['title']}", "",
            f"- Автор: {book['author']}",
            f"- Жанры: {', '.join(book['genres'])}",
            f"- Темы: {', '.join(book['themes'])}",
            f"- Настроение / темп: {', '.join(book['mood'])} / {book['pace']}",
            f"- Происхождение: {item['provenance']}", "",
            book["annotation"], "",
            f"`searchText`: {book['searchText']}", "",
        ])
    REVIEW.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "errors": len(errors), "warnings": len(warnings), "summary": summary}, ensure_ascii=False, indent=2))
    if errors:
        print("\n".join(errors[:50]))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
