from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import Book
from .text import normalize_text


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_catalog(catalog_path: Path, import_report_path: Path) -> list[Book]:
    raw_books = json.loads(catalog_path.read_text(encoding="utf-8"))
    report = json.loads(import_report_path.read_text(encoding="utf-8"))
    first_product_id = int(report["firstProductId"])
    last_product_id = int(report["lastProductId"])

    if len(raw_books) != int(report["products"]):
        raise RuntimeError("Catalog and OpenCart import report contain different counts")
    if last_product_id - first_product_id + 1 != len(raw_books):
        raise RuntimeError("Product IDs are not contiguous; rebuild the product mapping")

    books: list[Book] = []
    for index, raw in enumerate(raw_books):
        catalog_id = int(raw["id"])
        product_id = first_product_id + index
        if catalog_id != index + 1:
            raise RuntimeError("Catalog IDs must be sequential and start at 1")

        title = str(raw["title"])
        source_title = str(raw.get("sourceTitle", ""))
        author = str(raw["author"])
        genres = tuple(str(item) for item in raw.get("genres", []))
        themes = tuple(str(item) for item in raw.get("themes", []))
        moods = tuple(str(item) for item in raw.get("mood", []))
        search_text = str(raw.get("searchText", ""))
        annotation = str(raw.get("annotation", ""))
        search_aliases = tuple(str(item) for item in raw.get("searchAliases", []))
        searchable = " ".join(
            [
                title,
                " ".join(search_aliases),
                author,
                " ".join(genres),
                " ".join(themes),
                " ".join(moods),
                str(raw.get("pace", "")),
                annotation,
                search_text,
            ]
        )
        books.append(
            Book(
                product_id=product_id,
                catalog_id=catalog_id,
                title=title,
                source_title=source_title,
                author=author,
                authors=tuple(str(item) for item in raw.get("authors", [author])),
                year=int(raw["year"]),
                pages=int(raw["pages"]),
                genres=genres,
                themes=themes,
                moods=moods,
                pace=str(raw["pace"]),
                age_rating=str(raw["ageRating"]),
                language=str(raw["language"]),
                series=str(raw.get("series", "")),
                price=float(raw["price"]),
                quantity=int(raw.get("quantity", 0)),
                popularity=int(raw.get("popularity", 0)),
                rating=float(raw.get("rating", 0)),
                rating_count=int(raw.get("ratingCount", 0)),
                annotation=annotation,
                search_text=search_text,
                image=f"catalog/books/book-{catalog_id:04d}.jpg",
                title_norm=normalize_text(title),
                source_title_norm=normalize_text(source_title),
                author_norm=normalize_text(author),
                searchable_norm=normalize_text(searchable),
            )
        )
    return books


def passage_for_embedding(book: Book) -> str:
    # search_text starts with the title and author and already contains the
    # structured semantic profile. Avoid duplicating those fields here: E5 has
    # a 512-token window and repeated metadata would push the useful tail out.
    return book.search_text
