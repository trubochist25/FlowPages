from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "book_catalog"
DRAFT = DATA / "full-enrichment-draft.json"
VALIDATION = DATA / "full-enrichment-validation.json"
CATALOG = DATA / "catalog.json"


def main() -> None:
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    if validation.get("status") != "passed" or validation.get("errors"):
        raise RuntimeError("Refusing to apply a draft that did not pass validation")

    records = json.loads(DRAFT.read_text(encoding="utf-8"))
    books = [record["book"] for record in records]
    if len(books) != 1000 or len({book["id"] for book in books}) != 1000:
        raise RuntimeError("Draft must contain exactly 1000 unique catalog IDs")

    temporary = CATALOG.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(books, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, CATALOG)
    print(f"Applied {len(books)} books to {CATALOG}")


if __name__ == "__main__":
    main()
