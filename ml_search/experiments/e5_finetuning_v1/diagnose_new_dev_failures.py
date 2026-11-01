from __future__ import annotations

import gc
import json
import os
from pathlib import Path

import numpy as np

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.schemas import SearchRequest
from ml_search.search import SearchEngine


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "integration_review_v1" / "new-assessment" / "failure-signals.json"
CASES = (
    ("NEW-F06", "Ищу грустную, но поддерживающую историю о том, как начать жить после потери работы", 743),
    ("NEW-F12", "Хочу роман, в котором летняя жара и городская теснота усиливают напряжение", 38),
    ("NEW-F39", "Ищу семейный роман, где основной конфликт не сводится к наследству", 46),
    ("NEW-F07", "Хочу напряжённую книгу о недоверии между близкими друзьями: вроде никто не враг, а спокойно быть нельзя", 76),
)
KEYS = (
    "ML_SEARCH_MODEL_NAME",
    "ML_SEARCH_LOCAL_MODEL",
    "ML_SEARCH_INDEX",
    "ML_SEARCH_MANIFEST",
    "ML_SEARCH_FUZZY_TITLE_RESOLVER",
)


def settings(mode: str) -> Settings:
    for key in KEYS:
        os.environ.pop(key, None)
    os.environ["ML_SEARCH_OFFLINE"] = "1"
    if mode == "experimental":
        os.environ.update(
            {
                "ML_SEARCH_MODEL_NAME": "multilingual-e5-small-finetuned-lr1e-5-epoch3",
                "ML_SEARCH_LOCAL_MODEL": str(ROOT / "limited_experiment" / "selected-model"),
                "ML_SEARCH_INDEX": str(ROOT / "comparison" / "index" / "book-index.npz"),
                "ML_SEARCH_MANIFEST": str(ROOT / "comparison" / "index" / "manifest.json"),
                "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
            }
        )
    return Settings.from_env("small")


def run(mode: str) -> list[dict]:
    current = settings(mode)
    embedder = E5Embedder(
        current.model_name,
        current.model_cache_dir,
        current.batch_size,
        current.local_model_path,
        current.model_dimension,
    )
    engine = SearchEngine.from_settings(current, embedder)
    catalog_to_position = {
        book.catalog_id: position for position, book in enumerate(engine.books)
    }
    product_to_catalog = {book.product_id: book.catalog_id for book in engine.books}
    rows = []
    for family, query, target_id in CASES:
        vector = embedder.encode_queries([query])[0]
        similarities = engine.vector_index.similarities(vector)
        order = np.argsort(-similarities)
        position = catalog_to_position[target_id]
        semantic_rank = int(np.flatnonzero(order == position)[0]) + 1
        response = engine.search(
            SearchRequest(query=query, limit=50, include_debug=True)
        )
        ids = [product_to_catalog[item.product_id] for item in response.results]
        full_rank = ids.index(target_id) + 1 if target_id in ids else None
        target = next(
            (item for item in response.results if product_to_catalog[item.product_id] == target_id),
            None,
        )
        rows.append(
            {
                "family_id": family,
                "query": query,
                "target_id": target_id,
                "target_title": engine.books[position].title,
                "semantic_rank": semantic_rank,
                "cosine": float(similarities[position]),
                "full_rank": full_rank,
                "full_score": target.score if target else None,
                "score_breakdown": (
                    target.score_breakdown.model_dump() if target and target.score_breakdown else None
                ),
                "top_titles": [item.title for item in response.results[:5]],
            }
        )
    del engine, embedder
    gc.collect()
    return rows


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"Output already exists: {OUTPUT}")
    result = {"baseline": run("baseline"), "experimental": run("experimental")}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
