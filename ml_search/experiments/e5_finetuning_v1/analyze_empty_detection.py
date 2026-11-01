from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.schemas import SearchRequest
from ml_search.search import SearchEngine


ROOT = Path(__file__).resolve().parent
ASSESSMENT = ROOT / "integration_review_v1" / "new-assessment"
OUTPUT = ASSESSMENT / "empty-detection-signals.json"


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"Output already exists: {OUTPUT}")
    os.environ.update(
        {
            "ML_SEARCH_OFFLINE": "1",
            "ML_SEARCH_MODEL_NAME": "multilingual-e5-small-finetuned-lr1e-5-epoch3",
            "ML_SEARCH_LOCAL_MODEL": str(ROOT / "limited_experiment" / "selected-model"),
            "ML_SEARCH_INDEX": str(ROOT / "comparison" / "index" / "book-index.npz"),
            "ML_SEARCH_MANIFEST": str(ROOT / "comparison" / "index" / "manifest.json"),
            "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
        }
    )
    settings = Settings.from_env("small")
    embedder = E5Embedder(
        settings.model_name,
        settings.model_cache_dir,
        settings.batch_size,
        settings.local_model_path,
        settings.model_dimension,
    )
    engine = SearchEngine.from_settings(settings, embedder)
    cases = json.loads(
        (ASSESSMENT / "dev_queries.annotated.json").read_text(encoding="utf-8")
    )
    product_to_catalog = {book.product_id: book.catalog_id for book in engine.books}
    catalog_to_position = {
        book.catalog_id: position for position, book in enumerate(engine.books)
    }
    rows = []
    for case in cases:
        vector = embedder.encode_queries([case["query"]])[0]
        raw = engine.vector_index.similarities(vector)
        ordered = np.argsort(-raw)
        response = engine.search(
            SearchRequest(query=case["query"], limit=10, include_debug=True)
        )
        grades = {item["catalog_id"]: item["grade"] for item in case["judgments"]}
        relevant_positions = [
            catalog_to_position[catalog_id]
            for catalog_id, grade in grades.items()
            if grade == 2
        ]
        top = response.results[0] if response.results else None
        rows.append(
            {
                "query_id": case["query_id"],
                "family_id": case["family_id"],
                "expected_empty": case["expected_empty"],
                "raw_top1": float(raw[ordered[0]]),
                "raw_top2": float(raw[ordered[1]]),
                "raw_gap": float(raw[ordered[0]] - raw[ordered[1]]),
                "best_grade2_raw": (
                    max(float(raw[position]) for position in relevant_positions)
                    if relevant_positions
                    else None
                ),
                "best_grade2_semantic_rank": (
                    min(int(np.flatnonzero(ordered == position)[0]) + 1 for position in relevant_positions)
                    if relevant_positions
                    else None
                ),
                "top_catalog_id": product_to_catalog[top.product_id] if top else None,
                "top_title": top.title if top else None,
                "top_total": top.score if top else None,
                "top_relevance": top.relevance_score if top else None,
                "top_breakdown": (
                    top.score_breakdown.model_dump() if top and top.score_breakdown else None
                ),
            }
        )

    empties = [row for row in rows if row["expected_empty"]]
    positives = [row for row in rows if not row["expected_empty"]]
    candidates = sorted({row["raw_top1"] for row in rows})
    threshold_trials = []
    for threshold in candidates:
        empty_recall = sum(row["raw_top1"] < threshold for row in empties) / len(empties)
        positive_recall = sum(row["raw_top1"] >= threshold for row in positives) / len(positives)
        threshold_trials.append(
            {
                "threshold": threshold,
                "empty_recall": empty_recall,
                "positive_recall": positive_recall,
                "balanced_accuracy": (empty_recall + positive_recall) / 2,
            }
        )
    best = max(
        threshold_trials,
        key=lambda row: (row["balanced_accuracy"], row["positive_recall"]),
    )
    result = {
        "rows": rows,
        "raw_top1_ranges": {
            "empty": {
                "min": min(row["raw_top1"] for row in empties),
                "max": max(row["raw_top1"] for row in empties),
            },
            "nonempty": {
                "min": min(row["raw_top1"] for row in positives),
                "max": max(row["raw_top1"] for row in positives),
            },
        },
        "best_single_threshold_diagnostic": best,
        "decision": (
            "candidate_only" if best["positive_recall"] >= 0.95 and best["empty_recall"] >= 0.75
            else "do_not_integrate_single_threshold"
        ),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("raw_top1_ranges", "best_single_threshold_diagnostic", "decision")}))


if __name__ == "__main__":
    main()
