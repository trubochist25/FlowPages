from __future__ import annotations

import argparse
import gc
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from .cli import make_embedder
from .config import Settings
from .schemas import SearchRequest
from .search import SearchEngine


DEFAULT_QUERIES = Path(__file__).with_name("evaluation_queries.json")


def ndcg_at_10(row: dict) -> float:
    expected = set(row["expected_titles"])
    gains = [1.0 if title in expected else 0.0 for title in row["top_titles"][:10]]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_hits = min(len(expected), 10)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal if ideal else 0.0


def rank_metrics(rows: list[dict]) -> dict:
    ranks = [row["rank"] for row in rows]
    result = {
        "queries": len(rows),
        "hit_at_1": round(sum(rank == 1 for rank in ranks) / len(rows), 4),
        "hit_at_3": round(
            sum(rank is not None and rank <= 3 for rank in ranks) / len(rows), 4
        ),
        "hit_at_5": round(
            sum(rank is not None and rank <= 5 for rank in ranks) / len(rows), 4
        ),
        "hit_at_10": round(
            sum(rank is not None and rank <= 10 for rank in ranks) / len(rows), 4
        ),
        "mrr_at_10": round(
            sum(1.0 / rank for rank in ranks if rank is not None and rank <= 10)
            / len(rows),
            4,
        ),
        "ndcg_at_10": round(statistics.fmean(ndcg_at_10(row) for row in rows), 4),
    }
    guard_rows = [row for row in rows if row.get("forbidden_titles")]
    if guard_rows:
        result["guard_queries"] = len(guard_rows)
        for cutoff in (1, 3, 10):
            result[f"forbidden_hit_at_{cutoff}"] = round(
                sum(
                    any(
                        rank is not None and rank <= cutoff
                        for rank in row.get("forbidden_ranks", {}).values()
                    )
                    for row in guard_rows
                )
                / len(guard_rows),
                4,
            )
    return result


def metrics(rows: list[dict]) -> dict:
    latencies = [row["processing_ms"] for row in rows]
    return {
        **rank_metrics(rows),
        "mean_processing_ms": round(statistics.fmean(latencies), 3),
        "median_processing_ms": round(statistics.median(latencies), 3),
    }


def evaluate(cases: list[dict]) -> dict:
    settings = Settings.from_env("small")
    started = time.perf_counter()
    embedder = make_embedder(settings, "e5")
    engine = SearchEngine.from_settings(settings, embedder)
    load_ms = round((time.perf_counter() - started) * 1000, 3)
    rows = []

    for case in cases:
        response = engine.search(SearchRequest(query=case["query"], limit=10))
        titles = [item.title for item in response.results]
        expected = set(case["expected_titles"])
        rank = next(
            (position for position, title in enumerate(titles, start=1) if title in expected),
            None,
        )
        forbidden = set(case.get("forbidden_titles", []))
        forbidden_ranks = {
            title: next(
                (position for position, result_title in enumerate(titles, start=1) if result_title == title),
                None,
            )
            for title in sorted(forbidden)
        }
        rows.append(
            {
                **case,
                "rank": rank,
                "forbidden_ranks": forbidden_ranks,
                "processing_ms": response.processing_ms,
                "top_titles": titles,
            }
        )

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)

    vector_cases = [
        case for case in cases if case["category"] in {"semantic", "theme_mood"}
    ]
    vector_started = time.perf_counter()
    query_vectors = embedder.encode_queries([case["query"] for case in vector_cases])
    vector_encoding_ms = round((time.perf_counter() - vector_started) * 1000, 3)
    vector_rows = []
    titles = np.asarray([book.title for book in engine.books], dtype=object)
    for case, query_vector in zip(vector_cases, query_vectors):
        order = np.argsort(-engine.vector_index.similarities(query_vector))
        expected = set(case["expected_titles"])
        rank = next(
            position
            for position, book_index in enumerate(order, start=1)
            if titles[book_index] in expected
        )
        vector_rows.append(
            {
                **case,
                "rank": rank,
                "top_titles": titles[order[:10]].tolist(),
            }
        )

    grouped_vectors = defaultdict(list)
    for row in vector_rows:
        grouped_vectors[row["category"]].append(row)

    result = {
        "model": "small",
        "model_name": settings.model_name,
        "dimension": embedder.dimension,
        "load_ms": load_ms,
        "metrics": {
            "all": metrics(rows),
            **{category: metrics(items) for category, items in grouped.items()},
        },
        "vector_only": {
            "encoding_ms": vector_encoding_ms,
            "metrics": {
                "all": rank_metrics(vector_rows),
                **{
                    category: rank_metrics(items)
                    for category, items in grouped_vectors.items()
                },
            },
            "results": vector_rows,
        },
        "results": rows,
    }
    del engine, embedder
    gc.collect()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate FlowPages ML search")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.queries.read_text(encoding="utf-8"))
    report = evaluate(cases)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        summary = {
            "model_name": report["model_name"],
            "dimension": report["dimension"],
            "load_ms": report["load_ms"],
            "metrics": report["metrics"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
