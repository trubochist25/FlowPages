from __future__ import annotations

import gc
import json
import os
import statistics
import time
from pathlib import Path

from ml_search.catalog import load_catalog
from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.schemas import RecommendationRequest, SearchFilters, SearchRequest
from ml_search.search import SearchEngine


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
OUTPUT_DIR = ROOT / "integrated_validation_v1"
EXPERIMENT_KEYS = (
    "ML_SEARCH_MODEL_NAME",
    "ML_SEARCH_LOCAL_MODEL",
    "ML_SEARCH_INDEX",
    "ML_SEARCH_MANIFEST",
    "ML_SEARCH_FUZZY_TITLE_RESOLVER",
)


def settings_for(mode: str) -> Settings:
    for key in EXPERIMENT_KEYS:
        os.environ.pop(key, None)
    os.environ["ML_SEARCH_OFFLINE"] = "1"
    if mode == "experimental":
        os.environ.update(
            {
                "ML_SEARCH_MODEL_NAME": (
                    "multilingual-e5-small-finetuned-lr1e-5-epoch3"
                ),
                "ML_SEARCH_LOCAL_MODEL": str(
                    ROOT / "limited_experiment" / "selected-model"
                ),
                "ML_SEARCH_INDEX": str(
                    ROOT / "comparison" / "index" / "book-index.npz"
                ),
                "ML_SEARCH_MANIFEST": str(
                    ROOT / "comparison" / "index" / "manifest.json"
                ),
                "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
            }
        )
    return Settings.from_env("small")


def expected_rank(titles: list[str], expected: list[str]) -> int | None:
    expected_set = set(expected)
    return next(
        (position for position, title in enumerate(titles, start=1) if title in expected_set),
        None,
    )


def validate_mode(mode: str) -> dict:
    settings = settings_for(mode)
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    embedder = E5Embedder(
        settings.model_name,
        settings.model_cache_dir,
        settings.batch_size,
        settings.local_model_path,
        settings.model_dimension,
    )
    engine = SearchEngine.from_settings(settings, embedder)
    cases = json.loads(
        (PROJECT_ROOT / "ml_search" / "evaluation_queries.json").read_text(
            encoding="utf-8"
        )
    )

    rows = []
    durations = []
    for case in cases:
        started = time.perf_counter()
        response = engine.search(SearchRequest(query=case["query"], limit=10))
        elapsed_ms = (time.perf_counter() - started) * 1000
        durations.append(elapsed_ms)
        titles = [item.title for item in response.results]
        rows.append(
            {
                "category": case["category"],
                "query": case["query"],
                "expected_titles": case["expected_titles"],
                "rank": expected_rank(titles, case["expected_titles"]),
                "top_titles": titles,
                "elapsed_ms": elapsed_ms,
            }
        )

    filters = SearchFilters(
        pages_max=250,
        price_max=700,
        genres=["Детективы"],
    )
    filtered = engine.search(
        SearchRequest(query="детектив", filters=filters, limit=50)
    )
    books_by_product = {book.product_id: book for book in engine.books}
    filters_strict = bool(filtered.results) and all(
        books_by_product[item.product_id].pages <= 250
        and books_by_product[item.product_id].price <= 700
        and "Детективы" in books_by_product[item.product_id].genres
        for item in filtered.results
    )

    author_results = engine.search(
        SearchRequest(query="Фёдор Достоевский", limit=5)
    ).results
    invalid = engine.search(SearchRequest(query="!!! …", limit=10))
    recommendation = engine.recommend(RecommendationRequest(limit=5, random_seed=7))
    target_checks = {}
    for query, expected in (
        ("гарри потр философкий камин", "Гарри Поттер и философский камень"),
        ("татуировка дракона", "Девушка с татуировкой дракона"),
    ):
        response = engine.search(SearchRequest(query=query, limit=10))
        titles = [item.title for item in response.results]
        target_checks[query] = {
            "expected": expected,
            "rank": expected_rank(titles, [expected]),
            "matched_titles": engine.analyze(query).matched_titles,
        }

    ranks = [row["rank"] for row in rows]
    result = {
        "mode": mode,
        "model_name": settings.model_name,
        "model_path": str(settings.local_model_path),
        "index_path": str(settings.index_path),
        "manifest_model_name": manifest["model_name"],
        "fuzzy_title_resolver": settings.fuzzy_title_resolver,
        "queries": len(rows),
        "hit1": sum(rank is not None and rank <= 1 for rank in ranks) / len(ranks),
        "hit3": sum(rank is not None and rank <= 3 for rank in ranks) / len(ranks),
        "hit10": sum(rank is not None and rank <= 10 for rank in ranks) / len(ranks),
        "latency_ms": {
            "mean": statistics.fmean(durations),
            "p95": sorted(durations)[int(0.95 * (len(durations) - 1))],
            "max": max(durations),
        },
        "checks": {
            "strict_filters": filters_strict,
            "author_results": [
                {"title": item.title, "author": item.author} for item in author_results
            ],
            "invalid_query_state": invalid.state,
            "invalid_query_empty": not invalid.results,
            "recommendation_count": len(recommendation.results),
            "target_queries": target_checks,
        },
        "rows": rows,
    }
    del engine, embedder
    gc.collect()
    return result


def main() -> None:
    if OUTPUT_DIR.exists():
        raise RuntimeError(f"Output directory already exists: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir()
    baseline = validate_mode("baseline")
    experimental = validate_mode("experimental")
    result = {
        "protocol": (
            "Real SearchEngine, unchanged catalogue/ranking weights, 77 regression "
            "queries, baseline then experimental model+index+title resolver"
        ),
        "baseline": baseline,
        "experimental": experimental,
        "delta": {
            key: experimental[key] - baseline[key]
            for key in ("hit1", "hit3", "hit10")
        },
        "latency_p95_ratio": (
            experimental["latency_ms"]["p95"]
            / baseline["latency_ms"]["p95"]
        ),
    }
    (OUTPUT_DIR / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "baseline": {
                    key: baseline[key] for key in ("hit1", "hit3", "hit10")
                },
                "experimental": {
                    key: experimental[key]
                    for key in ("hit1", "hit3", "hit10")
                },
                "delta": result["delta"],
                "latency_p95_ratio": result["latency_p95_ratio"],
                "checks": experimental["checks"],
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
