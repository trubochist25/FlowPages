import json
import random
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "data" / "book_catalog" / "full-enrichment-draft.json"

JUNK = re.compile(
    r"краткое описание|дата публикации|описание на|см\. также|также содержится|"
    r"ваш вердикт|-{3,}|предшественник|реклама издателя|он использовал его|"
    r"это невероятно|не похож на|пожалуйста|перед вами|задняя крышка|netflix|"
    r"new york times|isbn|https?://",
    re.IGNORECASE,
)


def main() -> None:
    records = json.loads(DRAFT.read_text(encoding="utf-8"))
    hits = []
    for record in records:
        book = record["book"]
        match = JUNK.search(f'{book["annotation"]} {book["searchText"]}')
        if match:
            hits.append((book["id"], book["title"], match.group(0)))

    print(f"JUNK_HITS {len(hits)}")
    for hit in hits[:30]:
        print(hit)

    random.seed(904)
    print("\nRANDOM_SAMPLE")
    for record in random.sample(records, 20):
        book = record["book"]
        print(f'\n#{book["id"]} {book["title"]} — {book["author"]}')
        print(book["annotation"])
        print("SEARCH:", book["searchText"])


if __name__ == "__main__":
    main()
