from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


ROOT = Path(__file__).resolve().parent
ASSESSMENT = ROOT / "integration_review_v1" / "new-assessment"
CATALOG = ROOT.parents[2] / "data" / "book_catalog" / "catalog.json"


def main() -> None:
    draft = json.loads((ASSESSMENT / "test_queries.draft.json").read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    families: dict[str, list[dict]] = {}
    for row in draft:
        families.setdefault(row["family_id"], []).append(row)

    book_texts = [
        " ".join([
            book["title"], book["author"], book.get("annotation", ""),
            book.get("searchText", ""), " ".join(book.get("tags", [])),
        ])
        for book in catalog
    ]
    family_ids = list(families)
    family_texts = [" ".join(row["query"] for row in families[family_id]) for family_id in family_ids]
    vectorizer = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True
    )
    matrix = vectorizer.fit_transform([*book_texts, *family_texts])
    book_matrix = matrix[: len(book_texts)]
    query_matrix = matrix[len(book_texts) :]
    similarities = query_matrix @ book_matrix.T

    packet = []
    for family_position, family_id in enumerate(family_ids):
        rows = families[family_id]
        scores = similarities.getrow(family_position).toarray()[0]
        order = np.argsort(-scores)[:12]
        candidates = []
        for position in order:
            book = catalog[int(position)]
            candidates.append({
                "catalog_id": book["id"],
                "title": book["title"],
                "author": book["author"],
                "keyword_score": float(scores[position]),
                "search_text": book.get("searchText", ""),
            })
        packet.append({
            "family_id": family_id,
            "category": rows[0]["category"],
            "queries": [row["query"] for row in rows],
            "candidates": candidates,
            "annotation": {
                "expected_empty": None,
                "intent_criterion": "",
                "judgments": [],
            },
        })
    output = ASSESSMENT / "closed-test-annotation-packet.json"
    output.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"families": len(packet), "queries": len(draft), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
