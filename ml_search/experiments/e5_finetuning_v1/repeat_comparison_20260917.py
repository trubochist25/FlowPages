from __future__ import annotations

import gc
import json
import math
import os
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.schemas import SearchRequest
from ml_search.search import SearchEngine


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "comparison_repeat_20260917"
ENV_KEYS = (
    "ML_SEARCH_MODEL_NAME",
    "ML_SEARCH_LOCAL_MODEL",
    "ML_SEARCH_INDEX",
    "ML_SEARCH_MANIFEST",
    "ML_SEARCH_FUZZY_TITLE_RESOLVER",
    "ML_SEARCH_MULTI_VECTOR_RERANKER",
    "ML_SEARCH_MULTI_VECTOR_INDEX",
)


def settings_for(mode: str) -> Settings:
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["ML_SEARCH_OFFLINE"] = "1"
    if mode == "new":
        os.environ.update(
            {
                "ML_SEARCH_MODEL_NAME": "multilingual-e5-small-finetuned-lr1e-5-epoch3",
                "ML_SEARCH_LOCAL_MODEL": str(ROOT / "limited_experiment" / "selected-model"),
                "ML_SEARCH_INDEX": str(ROOT / "comparison" / "index" / "book-index.npz"),
                "ML_SEARCH_MANIFEST": str(ROOT / "comparison" / "index" / "manifest.json"),
                "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
                "ML_SEARCH_MULTI_VECTOR_RERANKER": "1",
                "ML_SEARCH_MULTI_VECTOR_INDEX": str(ROOT / "reranking_v1" / "field-vectors.npz"),
            }
        )
    return Settings.from_env("small")


def ndcg(ids: list[int], grades: dict[int, int]) -> float:
    dcg = sum(
        (2 ** grades.get(cid, 0) - 1) / math.log2(rank + 2)
        for rank, cid in enumerate(ids[:10])
    )
    ideal = sum(
        (2**grade - 1) / math.log2(rank + 2)
        for rank, grade in enumerate(sorted(grades.values(), reverse=True)[:10])
    )
    return dcg / ideal if ideal else 0.0


def score(case: dict, ids: list[int], elapsed_ms: float, state: str) -> dict:
    grades = {item["catalog_id"]: item["grade"] for item in case["judgments"]}
    good = {cid for cid, grade in grades.items() if grade == 2}
    rank = next((rank for rank, cid in enumerate(ids, 1) if cid in good), None)
    return {
        "query_id": case["query_id"],
        "group_id": case["group_id"],
        "category": case["category"],
        "expected_empty": case["expected_empty"],
        "has_grade2": bool(good),
        "ndcg10": ndcg(ids, grades) if grades else None,
        "hit3": bool(rank and rank <= 3),
        "hit10": bool(rank and rank <= 10),
        "rank": rank,
        "state": state,
        "elapsed_ms": elapsed_ms,
        "top_ids": ids,
    }


def aggregate(rows: list[dict]) -> dict:
    judged = [row for row in rows if not row["expected_empty"]]
    families: dict[str, list[dict]] = defaultdict(list)
    for row in judged:
        families[row["group_id"]].append(row)
    grade2_families = {
        family: group
        for family, group in families.items()
        if any(item["has_grade2"] for item in group)
    }
    empty = [row for row in rows if row["expected_empty"]]
    return {
        "queries": len(rows),
        "families": len({row["group_id"] for row in rows}),
        "judged_queries": len(judged),
        "expected_empty_queries": len(empty),
        "family_macro_ndcg10": float(
            np.mean([np.mean([item["ndcg10"] for item in group]) for group in families.values()])
        ) if families else None,
        "family_macro_hit3": float(
            np.mean([np.mean([item["hit3"] for item in group]) for group in grade2_families.values()])
        ) if grade2_families else None,
        "family_macro_hit10": float(
            np.mean([np.mean([item["hit10"] for item in group]) for group in grade2_families.values()])
        ) if grade2_families else None,
        "empty_state_accuracy": float(
            np.mean([item["state"] == "no_matches" for item in empty])
        ) if empty else None,
        "latency_mean_ms": statistics.fmean(row["elapsed_ms"] for row in rows),
        "latency_p95_ms": float(np.percentile([row["elapsed_ms"] for row in rows], 95)),
    }


def evaluate_dev(engine: SearchEngine, cases: list[dict]) -> dict:
    catalog_by_product = {book.product_id: book.catalog_id for book in engine.books}
    modes: dict[str, list[dict]] = {"semantic": [], "full": []}
    for position, case in enumerate(cases, 1):
        started = time.perf_counter()
        vector = engine.embedder.encode_queries([case["query"]])[0]
        indices = np.argsort(-engine.vector_index.similarities(vector), kind="stable")[:10]
        ids = [engine.books[index].catalog_id for index in indices]
        modes["semantic"].append(
            score(case, ids, (time.perf_counter() - started) * 1000, "always_returns_top10")
        )

        started = time.perf_counter()
        response = engine.search(SearchRequest(query=case["query"], limit=10))
        ids = [catalog_by_product[item.product_id] for item in response.results]
        modes["full"].append(
            score(case, ids, (time.perf_counter() - started) * 1000, response.state)
        )
        if position % 10 == 0:
            print(json.dumps({"event": "dev_progress", "done": position}), flush=True)

    result = {}
    for mode, rows in modes.items():
        categories = {
            category: aggregate([row for row in rows if row["category"] == category])
            for category in sorted({row["category"] for row in rows})
        }
        result[mode] = {"summary": aggregate(rows), "by_category": categories, "rows": rows}
    return result


def evaluate_regression(engine: SearchEngine, cases: list[dict]) -> dict:
    rows = []
    for position, case in enumerate(cases, 1):
        response = engine.search(SearchRequest(query=case["query"], limit=10))
        titles = [item.title for item in response.results]
        rank = next(
            (rank for rank, title in enumerate(titles, 1) if title in case["expected_titles"]),
            None,
        )
        rows.append({
            "query": case["query"], "category": case["category"], "rank": rank,
            "top_titles": titles, "processing_ms": response.processing_ms,
        })
        if position % 20 == 0:
            print(json.dumps({"event": "regression_progress", "done": position}), flush=True)

    def metrics(items: list[dict]) -> dict:
        return {
            "queries": len(items),
            "hit1": float(np.mean([bool(row["rank"] and row["rank"] <= 1) for row in items])),
            "hit3": float(np.mean([bool(row["rank"] and row["rank"] <= 3) for row in items])),
            "hit10": float(np.mean([bool(row["rank"] and row["rank"] <= 10) for row in items])),
            "mrr": float(np.mean([1 / row["rank"] if row["rank"] else 0 for row in items])),
            "latency_p95_ms": float(np.percentile([row["processing_ms"] for row in items], 95)),
        }

    return {
        "summary": metrics(rows),
        "by_category": {
            category: metrics([row for row in rows if row["category"] == category])
            for category in sorted({row["category"] for row in rows})
        },
        "rows": rows,
    }


def evaluate_mode(mode: str, dev: list[dict], regression: list[dict]) -> dict:
    settings = settings_for(mode)
    embedder = E5Embedder(
        settings.model_name,
        settings.model_cache_dir,
        settings.batch_size,
        settings.local_model_path,
        settings.model_dimension,
    )
    engine = SearchEngine.from_settings(settings, embedder)
    for query in ("книга о дружбе", "уютная история", "Дюна Фрэнк Герберт"):
        engine.search(SearchRequest(query=query, limit=10))
    result = {
        "model": settings.model_name,
        "configuration": {
            "multi_vector_reranker": settings.multi_vector_reranker,
            "fuzzy_title_resolver": settings.fuzzy_title_resolver,
        },
        "development": evaluate_dev(engine, dev),
        "regression77": evaluate_regression(engine, regression),
    }
    del engine, embedder
    gc.collect()
    return result


def main() -> None:
    OUT.mkdir(exist_ok=True)
    dev = json.loads((ROOT / "dev_queries.json").read_text(encoding="utf-8"))
    regression = json.loads((ROOT.parents[2] / "ml_search" / "evaluation_queries.json").read_text(encoding="utf-8"))
    result = {
        "protocol": {
            "date": "2026-09-17",
            "closed_test_rerun": False,
            "development_queries": len(dev),
            "development_families": len({row["group_id"] for row in dev}),
            "development_categories": dict(Counter(row["category"] for row in dev)),
            "regression_queries": len(regression),
            "regression_categories": dict(Counter(row["category"] for row in regression)),
            "note": "Development labels are synthetic and were authored from catalog descriptions.",
        },
        "old": evaluate_mode("old", dev, regression),
        "new": evaluate_mode("new", dev, regression),
    }
    (OUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    printable = {
        mode: {
            "semantic": data["development"]["semantic"]["summary"],
            "full": data["development"]["full"]["summary"],
            "regression77": data["regression77"]["summary"],
        }
        for mode, data in result.items() if mode in {"old", "new"}
    }
    print(json.dumps(printable, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
