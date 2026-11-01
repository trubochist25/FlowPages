from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.schemas import (
    AlchemyAnalyzeRequest,
    AlchemyRecommendRequest,
    RecommendationRequest,
    SearchFilters,
    SearchRequest,
)
from ml_search.search import SearchEngine
from ml_search.text import normalize_text


ROOT = Path(__file__).resolve().parent
ASSESSMENT = ROOT / "integration_review_v1" / "new-assessment"
QRELS = ASSESSMENT / "test_queries.annotated.json"
FREEZE = ASSESSMENT / "closed-test-freeze-manifest.json"
OUTPUT = ROOT / "closed_test_final_v1"
ENV_KEYS = (
    "ML_SEARCH_MODEL_NAME", "ML_SEARCH_LOCAL_MODEL", "ML_SEARCH_INDEX",
    "ML_SEARCH_MANIFEST", "ML_SEARCH_FUZZY_TITLE_RESOLVER",
    "ML_SEARCH_MULTI_VECTOR_RERANKER", "ML_SEARCH_MULTI_VECTOR_INDEX",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ndcg(ids: list[int], grades: dict[int, int]) -> float:
    dcg = sum((2 ** grades.get(cid, 0) - 1) / math.log2(rank + 2) for rank, cid in enumerate(ids[:10]))
    ideal = sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(sorted(grades.values(), reverse=True)[:10]))
    return dcg / ideal if ideal else 0.0


def settings_for(mode: str) -> Settings:
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["ML_SEARCH_OFFLINE"] = "1"
    if mode == "selected_multivector":
        os.environ.update({
            "ML_SEARCH_MODEL_NAME": "multilingual-e5-small-finetuned-lr1e-5-epoch3",
            "ML_SEARCH_LOCAL_MODEL": str(ROOT / "limited_experiment" / "selected-model"),
            "ML_SEARCH_INDEX": str(ROOT / "comparison" / "index" / "book-index.npz"),
            "ML_SEARCH_MANIFEST": str(ROOT / "comparison" / "index" / "manifest.json"),
            "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
            "ML_SEARCH_MULTI_VECTOR_RERANKER": "1",
            "ML_SEARCH_MULTI_VECTOR_INDEX": str(ROOT / "reranking_v1" / "field-vectors.npz"),
        })
    return Settings.from_env("small")


def aggregate(rows: list[dict]) -> dict:
    judged = [row for row in rows if not row["expected_empty"]]
    grade2 = [row for row in judged if row["has_grade2"]]
    families: dict[str, list[dict]] = defaultdict(list)
    for row in judged:
        families[row["family_id"]].append(row)
    grade2_families = {family: group for family, group in families.items() if any(item["has_grade2"] for item in group)}
    empty = [row for row in rows if row["expected_empty"]]
    return {
        "queries": len(rows),
        "judged_queries": len(judged),
        "grade2_queries": len(grade2),
        "expected_empty_queries": len(empty),
        "family_macro_ndcg10": (
            float(np.mean([np.mean([item["ndcg10"] for item in group]) for group in families.values()]))
            if families else None
        ),
        "family_macro_hit3": (
            float(np.mean([np.mean([item["hit3"] for item in group]) for group in grade2_families.values()]))
            if grade2_families else None
        ),
        "family_macro_hit10": (
            float(np.mean([np.mean([item["hit10"] for item in group]) for group in grade2_families.values()]))
            if grade2_families else None
        ),
        "empty_state_accuracy": float(np.mean([item["state"] == "no_matches" for item in empty])) if empty else None,
    }


def evaluate(mode: str, cases: list[dict], training_ids: set[int]) -> dict:
    settings = settings_for(mode)
    embedder = E5Embedder(settings.model_name, settings.model_cache_dir, settings.batch_size, settings.local_model_path, settings.model_dimension)
    engine = SearchEngine.from_settings(settings, embedder)
    catalog_by_product = {book.product_id: book.catalog_id for book in engine.books}
    rows, durations = [], []
    for case in cases:
        started = time.perf_counter()
        response = engine.search(SearchRequest(query=case["query"], limit=10))
        elapsed = (time.perf_counter() - started) * 1000
        durations.append(elapsed)
        ids = [catalog_by_product[result.product_id] for result in response.results]
        grades = {item["catalog_id"]: item["grade"] for item in case["judgments"]}
        good = {cid for cid, grade in grades.items() if grade == 2}
        rank = next((rank + 1 for rank, cid in enumerate(ids) if cid in good), None)
        relevant = {cid for cid, grade in grades.items() if grade > 0}
        rows.append({
            "query_id": case["query_id"], "family_id": case["family_id"], "category": case["category"],
            "expected_empty": case["expected_empty"], "has_grade2": bool(good),
            "all_relevant_books_outside_training": bool(relevant) and relevant.isdisjoint(training_ids),
            "ndcg10": ndcg(ids, grades) if grades else None,
            "hit3": bool(rank and rank <= 3), "hit10": bool(rank and rank <= 10), "rank": rank,
            "state": response.state, "elapsed_ms": elapsed, "top_ids": ids,
        })

    categories = {}
    for category in sorted({row["category"] for row in rows}):
        category_rows = [row for row in rows if row["category"] == category]
        categories[category] = {**aggregate(category_rows),
            "latency_p95_ms": float(np.percentile([row["elapsed_ms"] for row in category_rows], 95))}
    unseen = [row for row in rows if row["all_relevant_books_outside_training"]]

    title = engine.search(SearchRequest(query="Дюна Фрэнк Герберт", limit=5))
    author = engine.search(SearchRequest(query="Фёдор Достоевский", limit=5))
    typo = engine.search(SearchRequest(query="гарри потр философкий камин", limit=5))
    filtered = engine.search(SearchRequest(query="детектив", filters=SearchFilters(pages_max=250, price_max=700, genres=["Детективы"]), limit=50))
    books = {book.product_id: book for book in engine.books}
    blank = engine.search(SearchRequest(query="", limit=10))
    alchemy_analysis = engine.analyze_alchemy(AlchemyAnalyzeRequest(query="уютная загадочная книга без мистики"))
    alchemy_results = engine.recommend_alchemy(AlchemyRecommendRequest(query="уютная загадочная книга", limit=6, random_seed=7))
    recommendations = engine.recommend(RecommendationRequest(limit=5, random_seed=7))
    checks = {
        "title_top1": bool(title.results and title.results[0].title == "Дюна"),
        "author_top1": bool(author.results and normalize_text(author.results[0].author) == normalize_text("Фёдор Достоевский")),
        "typo_top1": bool(typo.results and typo.results[0].title == "Гарри Поттер и философский камень"),
        "strict_filters": bool(filtered.results) and all(books[item.product_id].pages <= 250 and books[item.product_id].price <= 700 and "Детективы" in books[item.product_id].genres for item in filtered.results),
        "blank_query_stable": blank.state in {"results", "partial"} and bool(blank.results),
        "alchemy_analysis": bool(alchemy_analysis.positive or alchemy_analysis.negative),
        "alchemy_recommendations": len(alchemy_results.results) == 6,
        "recommendations": len(recommendations.results) == 5,
    }
    result = {
        "mode": mode, "model": settings.model_name, "summary": aggregate(rows), "by_category": categories,
        "outside_training": aggregate(unseen) if unseen else None,
        "outside_training_queries": len(unseen),
        "latency_ms": {"mean": statistics.fmean(durations), "p95": float(np.percentile(durations, 95)), "max": max(durations)},
        "mandatory_checks": {"all_passed": all(checks.values()), **checks}, "rows": rows,
    }
    del engine, embedder
    gc.collect()
    return result


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError("Closed test has already been run")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if digest(QRELS) != freeze["annotated_sha256"]:
        raise RuntimeError("Closed-test qrels changed after freeze")
    cases = json.loads(QRELS.read_text(encoding="utf-8"))
    training = [json.loads(line) for line in (ROOT / "training" / "train_triplets.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    training_ids = {item[key] for item in training for key in ("positive_catalog_id", "negative_catalog_id")}
    for item in training:
        training_ids.update(extra["catalog_id"] for extra in item.get("additional_compatible_positives", []))
    OUTPUT.mkdir()
    started = datetime.now(timezone.utc).isoformat()
    baseline = evaluate("production_baseline", cases, training_ids)
    selected = evaluate("selected_multivector", cases, training_ids)
    result = {
        "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "One-time frozen 99-query closed test. Production baseline compared with the frozen selected model plus multi-vector index. No tuning after opening.",
        "qrels_sha256": digest(QRELS), "training_book_ids": sorted(training_ids),
        "production_baseline": baseline, "selected_multivector": selected,
        "delta": {key: selected["summary"][key] - baseline["summary"][key] for key in ("family_macro_ndcg10", "family_macro_hit3", "family_macro_hit10")},
        "p95_ratio": selected["latency_ms"]["p95"] / baseline["latency_ms"]["p95"],
        "limitations": freeze["limitations"],
    }
    (OUTPUT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"production_baseline": {"summary": baseline["summary"], "latency_ms": baseline["latency_ms"]},
                      "selected_multivector": {"summary": selected["summary"], "outside_training": selected["outside_training"], "latency_ms": selected["latency_ms"], "mandatory_checks": selected["mandatory_checks"]},
                      "delta": result["delta"], "p95_ratio": result["p95_ratio"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
