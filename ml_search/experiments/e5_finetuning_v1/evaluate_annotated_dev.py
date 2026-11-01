from __future__ import annotations

import gc
import json
import math
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.schemas import SearchRequest
from ml_search.search import SearchEngine


ROOT = Path(__file__).resolve().parent
ASSESSMENT = ROOT / "integration_review_v1" / "new-assessment"
OUTPUT = ASSESSMENT / "dev-evaluation.json"
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
    if mode in {"experimental", "description_overlay"}:
        os.environ.update(
            {
                "ML_SEARCH_MODEL_NAME": "multilingual-e5-small-finetuned-lr1e-5-epoch3",
                "ML_SEARCH_LOCAL_MODEL": str(ROOT / "limited_experiment" / "selected-model"),
                "ML_SEARCH_INDEX": str(ROOT / "comparison" / "index" / "book-index.npz"),
                "ML_SEARCH_MANIFEST": str(ROOT / "comparison" / "index" / "manifest.json"),
                "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
            }
        )
        if mode == "description_overlay":
            overlay = ROOT / "integration_review_v1" / "description_overlay_v1"
            os.environ["ML_SEARCH_INDEX"] = str(overlay / "book-index.npz")
            os.environ["ML_SEARCH_MANIFEST"] = str(overlay / "manifest.json")
    return Settings.from_env("small")


def ndcg(ids: list[int], grades: dict[int, int]) -> float:
    dcg = sum(
        (2 ** grades.get(catalog_id, 0) - 1) / math.log2(rank + 1)
        for rank, catalog_id in enumerate(ids, start=1)
    )
    ideal_grades = sorted(grades.values(), reverse=True)[:10]
    ideal = sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(ideal_grades, start=1)
    )
    return dcg / ideal if ideal else 0.0


def evaluate(mode: str, cases: list[dict]) -> dict:
    settings = settings_for(mode)
    embedder = E5Embedder(
        settings.model_name,
        settings.model_cache_dir,
        settings.batch_size,
        settings.local_model_path,
        settings.model_dimension,
    )
    engine = SearchEngine.from_settings(settings, embedder)
    product_to_catalog = {book.product_id: book.catalog_id for book in engine.books}
    rows = []
    for case in cases:
        started = time.perf_counter()
        response = engine.search(SearchRequest(query=case["query"], limit=10))
        elapsed_ms = (time.perf_counter() - started) * 1000
        ids = [product_to_catalog[item.product_id] for item in response.results]
        grades = {item["catalog_id"]: item["grade"] for item in case["judgments"]}
        good = {catalog_id for catalog_id, grade in grades.items() if grade == 2}
        rank = next(
            (position for position, catalog_id in enumerate(ids, start=1) if catalog_id in good),
            None,
        )
        rows.append(
            {
                "query_id": case["query_id"],
                "family_id": case["family_id"],
                "category": case["category"],
                "query": case["query"],
                "expected_empty": case["expected_empty"],
                "rank": rank,
                "ndcg10": ndcg(ids, grades) if grades else None,
                "empty_success": not response.results if case["expected_empty"] else None,
                "returned": len(response.results),
                "top_ids": ids,
                "top_titles": [item.title for item in response.results],
                "elapsed_ms": elapsed_ms,
            }
        )

    nonempty = [row for row in rows if not row["expected_empty"]]
    empty = [row for row in rows if row["expected_empty"]]
    by_family: dict[str, list[dict]] = defaultdict(list)
    for row in nonempty:
        by_family[row["family_id"]].append(row)
    family_metrics = []
    for family_id, family_rows in by_family.items():
        family_metrics.append(
            {
                "family_id": family_id,
                "ndcg10": statistics.fmean(row["ndcg10"] for row in family_rows),
                "hit3": statistics.fmean(
                    row["rank"] is not None and row["rank"] <= 3
                    for row in family_rows
                ),
                "hit10": statistics.fmean(
                    row["rank"] is not None and row["rank"] <= 10
                    for row in family_rows
                ),
            }
        )
    durations = [row["elapsed_ms"] for row in rows]
    result = {
        "model_name": settings.model_name,
        "fuzzy_title_resolver": settings.fuzzy_title_resolver,
        "metrics_family_macro": {
            key: statistics.fmean(item[key] for item in family_metrics)
            for key in ("ndcg10", "hit3", "hit10")
        },
        "expected_empty_accuracy": statistics.fmean(
            row["empty_success"] for row in empty
        ),
        "latency_ms": {
            "mean": statistics.fmean(durations),
            "p95": sorted(durations)[int(0.95 * (len(durations) - 1))],
        },
        "families": family_metrics,
        "rows": rows,
    }
    del engine, embedder
    gc.collect()
    return result


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"Output already exists: {OUTPUT}")
    cases = json.loads(
        (ASSESSMENT / "dev_queries.annotated.json").read_text(encoding="utf-8")
    )
    baseline = evaluate("baseline", cases)
    experimental = evaluate("experimental", cases)
    delta = {
        key: experimental["metrics_family_macro"][key]
        - baseline["metrics_family_macro"][key]
        for key in ("ndcg10", "hit3", "hit10")
    }
    result = {
        "protocol": (
            "Agent-editorial dev qrels frozen before retrieval; family-macro metrics; "
            "99-query new test remains unopened"
        ),
        "baseline": baseline,
        "experimental": experimental,
        "delta": delta,
        "latency_p95_ratio": (
            experimental["latency_ms"]["p95"] / baseline["latency_ms"]["p95"]
        ),
    }
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "baseline": baseline["metrics_family_macro"],
                "experimental": experimental["metrics_family_macro"],
                "delta": delta,
                "baseline_empty_accuracy": baseline["expected_empty_accuracy"],
                "experimental_empty_accuracy": experimental["expected_empty_accuracy"],
                "latency_p95_ratio": result["latency_p95_ratio"],
            }
        )
    )


if __name__ == "__main__":
    main()
