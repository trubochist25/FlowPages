from __future__ import annotations

import json
import os
from pathlib import Path

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.schemas import RecommendationRequest, SearchFilters, SearchRequest
from ml_search.search import SearchEngine
from ml_search.text import normalize_text


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "multivector_integration_v1" / "mandatory-checks.json"


def main() -> None:
    os.environ.update({
        "ML_SEARCH_OFFLINE": "1",
        "ML_SEARCH_MODEL_NAME": "multilingual-e5-small-finetuned-lr1e-5-epoch3",
        "ML_SEARCH_LOCAL_MODEL": str(ROOT / "limited_experiment" / "selected-model"),
        "ML_SEARCH_INDEX": str(ROOT / "comparison" / "index" / "book-index.npz"),
        "ML_SEARCH_MANIFEST": str(ROOT / "comparison" / "index" / "manifest.json"),
        "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
        "ML_SEARCH_MULTI_VECTOR_RERANKER": "1",
        "ML_SEARCH_MULTI_VECTOR_INDEX": str(ROOT / "reranking_v1" / "field-vectors.npz"),
    })
    settings = Settings.from_env("small")
    embedder = E5Embedder(settings.model_name, settings.model_cache_dir, settings.batch_size, settings.local_model_path, settings.model_dimension)
    engine = SearchEngine.from_settings(settings, embedder)
    books = {book.product_id: book for book in engine.books}

    title = engine.search(SearchRequest(query="Дюна Фрэнк Герберт", limit=5))
    typo = engine.search(SearchRequest(query="гарри потр философкий камин", limit=5))
    author = engine.search(SearchRequest(query="Фёдор Достоевский", limit=5))
    filters = SearchFilters(pages_max=250, price_max=700, genres=["Детективы"])
    filtered = engine.search(SearchRequest(query="детектив", filters=filters, limit=50))
    no_matches = engine.search(SearchRequest(query="книга", filters=SearchFilters(price_max=1), limit=10))
    invalid = engine.search(SearchRequest(query="!!! …", limit=10))
    uncertain = engine.search(SearchRequest(query="ремонт настольной игры с дополненной реальностью", limit=10))
    recommendation = engine.recommend(RecommendationRequest(limit=5, random_seed=7))
    checks = {
        "title_top1": bool(title.results and title.results[0].title == "Дюна"),
        "fuzzy_title_top1": bool(typo.results and typo.results[0].title == "Гарри Поттер и философский камень"),
        "author_top1": bool(
            author.results
            and normalize_text(author.results[0].author)
            == normalize_text("Фёдор Достоевский")
        ),
        "strict_filters": bool(filtered.results) and all(
            books[item.product_id].pages <= 250
            and books[item.product_id].price <= 700
            and "Детективы" in books[item.product_id].genres
            for item in filtered.results
        ),
        "no_matches_after_strict_filter": no_matches.state == "no_matches" and not no_matches.results,
        "invalid_query": invalid.state == "invalid_query" and not invalid.results,
        "semantic_uncertainty_returns_candidates": uncertain.state in {"results", "partial"} and bool(uncertain.results),
        "recommendations": len(recommendation.results) == 5,
    }
    result = {"all_passed": all(checks.values()), "checks": checks}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
