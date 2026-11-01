from __future__ import annotations

import json
import math
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.reranking import MultiVectorReranker
from ml_search.schemas import SearchRequest
from ml_search.search import SearchEngine


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "multivector_integration_v1"
DEV_PATH = ROOT / "integration_review_v1" / "new-assessment" / "dev_queries.annotated.json"


def ndcg(ids: list[int], grades: dict[int, int]) -> float:
    dcg = sum((2 ** grades.get(cid, 0) - 1) / math.log2(rank + 2) for rank, cid in enumerate(ids[:10]))
    ideal = sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(sorted(grades.values(), reverse=True)[:10]))
    return dcg / ideal if ideal else 0.0


def summarize(rows: list[dict], family_macro: bool) -> dict:
    if family_macro:
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            if not row["expected_empty"]:
                groups[row["family_id"]].append(row)
        return {key: float(np.mean([np.mean([item[key] for item in group]) for group in groups.values()])) for key in ("ndcg10", "hit3", "hit10")}
    return {key: float(np.mean([row[key] for row in rows])) for key in ("ndcg10", "hit3", "hit10")}


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    os.environ.update({
        "ML_SEARCH_OFFLINE": "1",
        "ML_SEARCH_MODEL_NAME": "multilingual-e5-small-finetuned-lr1e-5-epoch3",
        "ML_SEARCH_LOCAL_MODEL": str(ROOT / "limited_experiment" / "selected-model"),
        "ML_SEARCH_INDEX": str(ROOT / "comparison" / "index" / "book-index.npz"),
        "ML_SEARCH_MANIFEST": str(ROOT / "comparison" / "index" / "manifest.json"),
        "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
    })
    os.environ.pop("ML_SEARCH_MULTI_VECTOR_RERANKER", None)
    settings = Settings.from_env("small")
    embedder = E5Embedder(settings.model_name, settings.model_cache_dir, settings.batch_size, settings.local_model_path, settings.model_dimension)
    engine = SearchEngine.from_settings(settings, embedder)
    reranker = MultiVectorReranker.load(ROOT / "reranking_v1" / "field-vectors.npz", len(engine.books), embedder.dimension)
    catalog_by_product = {book.product_id: book.catalog_id for book in engine.books}
    title_ids: dict[str, list[int]] = defaultdict(list)
    for book in engine.books:
        title_ids[book.title].append(book.catalog_id)
    dev = json.loads(DEV_PATH.read_text(encoding="utf-8"))
    regression = json.loads((ROOT.parents[2] / "ml_search" / "evaluation_queries.json").read_text(encoding="utf-8"))

    def run(cases: list[dict], enabled: bool, is_dev: bool) -> tuple[list[dict], list[float]]:
        engine.multi_vector_reranker = reranker if enabled else None
        rows, durations = [], []
        for index, case in enumerate(cases):
            started = time.perf_counter()
            response = engine.search(SearchRequest(query=case["query"], limit=10))
            durations.append((time.perf_counter() - started) * 1000)
            ids = [catalog_by_product[item.product_id] for item in response.results]
            grades = ({item["catalog_id"]: item["grade"] for item in case["judgments"]} if is_dev else
                      {cid: 2 for title in case["expected_titles"] for cid in title_ids.get(title, [])})
            good = {cid for cid, grade in grades.items() if grade == 2}
            rank = next((rank + 1 for rank, cid in enumerate(ids) if cid in good), None)
            rows.append({"query_id": case.get("query_id", f"REG-{index+1:03d}"), "family_id": case.get("family_id", f"REG-{index+1:03d}"),
                         "expected_empty": case.get("expected_empty", False), "ndcg10": ndcg(ids, grades),
                         "hit3": bool(rank and rank <= 3), "hit10": bool(rank and rank <= 10), "rank": rank,
                         "top_ids": ids, "state": response.state})
        return rows, durations

    engine.search(SearchRequest(query="атмосферная книга", limit=10))
    base_dev, base_dev_time = run(dev, False, True)
    new_dev, new_dev_time = run(dev, True, True)
    base_reg, base_reg_time = run(regression, False, False)
    new_reg, new_reg_time = run(regression, True, False)
    metrics = {
        "baseline": {"dev": summarize(base_dev, True), "regression77": summarize(base_reg, False)},
        "multivector": {"dev": summarize(new_dev, True), "regression77": summarize(new_reg, False)},
    }
    result = {
        "protocol": "Real SearchEngine with selected E5 model, matching index, unchanged weights and optional multi-vector field index; 99-query closed test unopened.",
        **metrics,
        "delta": {scope: {key: metrics["multivector"][scope][key] - metrics["baseline"][scope][key] for key in ("ndcg10", "hit3", "hit10")} for scope in ("dev", "regression77")},
        "latency_ms": {
            "baseline_p95": float(np.percentile(base_dev_time + base_reg_time, 95)),
            "multivector_p95": float(np.percentile(new_dev_time + new_reg_time, 95)),
            "baseline_mean": statistics.fmean(base_dev_time + base_reg_time),
            "multivector_mean": statistics.fmean(new_dev_time + new_reg_time),
        },
        "rows": {"baseline_dev": base_dev, "multivector_dev": new_dev, "baseline_regression": base_reg, "multivector_regression": new_reg},
    }
    result["latency_ms"]["p95_ratio"] = result["latency_ms"]["multivector_p95"] / result["latency_ms"]["baseline_p95"]
    (OUTPUT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("baseline", "multivector", "delta", "latency_ms")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
