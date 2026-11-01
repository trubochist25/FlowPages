from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from itertools import product
from pathlib import Path

import numpy as np

from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.schemas import SearchFilters
from ml_search.search import SearchEngine


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
ASSESSMENT = ROOT / "integration_review_v1" / "new-assessment"
OUTPUT = ROOT / "signal_tuning_v1"
MODEL_NAME = "multilingual-e5-small-finetuned-lr1e-5-epoch3"


def ndcg(ids: list[int], grades: dict[int, int]) -> float:
    dcg = sum(
        (2 ** grades.get(catalog_id, 0) - 1) / math.log2(rank + 2)
        for rank, catalog_id in enumerate(ids[:10])
    )
    ideal = sum(
        (2**grade - 1) / math.log2(rank + 2)
        for rank, grade in enumerate(sorted(grades.values(), reverse=True)[:10])
    )
    return dcg / ideal if ideal else 0.0


def load_engine() -> SearchEngine:
    os.environ.update(
        {
            "ML_SEARCH_OFFLINE": "1",
            "ML_SEARCH_MODEL_NAME": MODEL_NAME,
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
    return SearchEngine.from_settings(settings, embedder)


def cases() -> tuple[list[dict], list[dict]]:
    dev = json.loads(
        (ASSESSMENT / "dev_queries.annotated.json").read_text(encoding="utf-8")
    )
    regression = json.loads(
        (PROJECT / "ml_search" / "evaluation_queries.json").read_text(
            encoding="utf-8"
        )
    )
    for index, case in enumerate(regression):
        case["query_id"] = f"REG-{index + 1:03d}"
        case["family_id"] = case["query_id"]
        case["expected_empty"] = False
    return dev, regression


def collect(engine: SearchEngine, all_cases: list[dict], title_ids: dict[str, list[int]]) -> list[dict]:
    rows = []
    filters = SearchFilters()
    for case in all_cases:
        intent = engine.analyze(case["query"])
        vector = engine.embedder.encode_queries([intent.corrected_query])[0]
        semantic_raw = engine.vector_index.similarities(vector)
        semantic = np.clip((semantic_raw + 1.0) / 2.0, 0.0, 1.0)
        lexical = np.zeros(len(engine.books), dtype=np.float32)
        metadata = np.zeros(len(engine.books), dtype=np.float32)
        popularity = np.zeros(len(engine.books), dtype=np.float32)
        rating = np.zeros(len(engine.books), dtype=np.float32)
        entity_kind: list[str | None] = []
        for position, book in enumerate(engine.books):
            lexical[position], entity = engine._lexical_score(book, intent)
            entity_kind.append(entity)
            metadata[position] = engine._metadata_score(book, intent)[0]
            popularity[position] = math.log1p(book.popularity) / math.log1p(
                engine._max_popularity
            )
            rating[position] = engine._rating_score(book, None)
        if "judgments" in case:
            grades = {
                item["catalog_id"]: item["grade"] for item in case["judgments"]
            }
        else:
            grades = {
                catalog_id: 2
                for title in case["expected_titles"]
                for catalog_id in title_ids.get(title, [])
            }
        rows.append(
            {
                "query_id": case["query_id"],
                "family_id": case["family_id"],
                "category": case["category"],
                "query": case["query"],
                "expected_empty": case.get("expected_empty", False),
                "has_metadata": engine._has_metadata_preferences(intent),
                "grades": grades,
                "semantic": semantic,
                "semantic_raw": semantic_raw,
                "lexical": lexical,
                "metadata": metadata,
                "popularity": popularity,
                "rating": rating,
                "entity_kind": entity_kind,
            }
        )
    return rows


ENTITY_FLOORS = {
    "exact_title": 0.99,
    "title": 0.96,
    "fuzzy_title": 0.94,
    "exact_author": 0.98,
    "author": 0.95,
    "fuzzy_author": 0.93,
}


def ranked_ids(
    engine: SearchEngine,
    row: dict,
    plain_semantic: float,
    metadata_semantic: float,
    metadata_lexical: float,
) -> tuple[list[int], np.ndarray]:
    if row["has_metadata"]:
        metadata_weight = 0.95 - metadata_semantic - metadata_lexical
        score = (
            metadata_semantic * row["semantic"]
            + metadata_lexical * row["lexical"]
            + metadata_weight * row["metadata"]
            + 0.03 * row["popularity"]
            + 0.02 * row["rating"]
        )
    else:
        score = (
            plain_semantic * row["semantic"]
            + (0.95 - plain_semantic) * row["lexical"]
            + 0.03 * row["popularity"]
            + 0.02 * row["rating"]
        )
    score = np.asarray(score, dtype=np.float32)
    for position, entity in enumerate(row["entity_kind"]):
        if entity:
            entity_score = (
                0.25 * row["semantic"][position]
                + 0.60 * row["lexical"][position]
                + 0.10 * row["metadata"][position]
                + 0.03 * row["popularity"][position]
                + 0.02 * row["rating"][position]
            )
            score[position] = max(entity_score, ENTITY_FLOORS.get(entity, 0.93))
    order = np.argsort(-score)
    ids = [engine.books[position].catalog_id for position in order[:10]]
    return ids, score[order]


def metrics(engine: SearchEngine, rows: list[dict], weights: tuple[float, float, float]) -> dict:
    plain_semantic, metadata_semantic, metadata_lexical = weights
    query_rows = []
    for row in rows:
        ids, scores = ranked_ids(
            engine, row, plain_semantic, metadata_semantic, metadata_lexical
        )
        good = {catalog_id for catalog_id, grade in row["grades"].items() if grade == 2}
        rank = next(
            (index + 1 for index, catalog_id in enumerate(ids) if catalog_id in good),
            None,
        )
        query_rows.append(
            {
                "family_id": row["family_id"],
                "expected_empty": row["expected_empty"],
                "ndcg10": ndcg(ids, row["grades"]) if row["grades"] else None,
                "hit3": bool(rank and rank <= 3),
                "hit10": bool(rank and rank <= 10),
                "rank": rank,
                "top_score": float(scores[0]),
                "score_gap": float(scores[0] - scores[1]),
                "top_ids": ids,
            }
        )
    nonempty = [row for row in query_rows if not row["expected_empty"]]
    families: dict[str, list[dict]] = defaultdict(list)
    for row in nonempty:
        families[row["family_id"]].append(row)
    return {
        "ndcg10": float(
            np.mean([np.mean([row["ndcg10"] for row in group]) for group in families.values()])
        ),
        "hit3": float(
            np.mean([np.mean([row["hit3"] for row in group]) for group in families.values()])
        ),
        "hit10": float(
            np.mean([np.mean([row["hit10"] for row in group]) for group in families.values()])
        ),
        "rows": query_rows,
    }


def serializable_signal_cache(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        compact = {
            key: value
            for key, value in row.items()
            if key not in {
                "semantic",
                "semantic_raw",
                "lexical",
                "metadata",
                "popularity",
                "rating",
                "entity_kind",
            }
        }
        compact["raw_semantic_summary"] = {
            "max": float(np.max(row["semantic_raw"])),
            "mean": float(np.mean(row["semantic_raw"])),
            "std": float(np.std(row["semantic_raw"])),
            "top10_mean": float(np.mean(np.sort(row["semantic_raw"])[-10:])),
        }
        result.append(compact)
    return result


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"Output already exists: {OUTPUT}")
    OUTPUT.mkdir()
    engine = load_engine()
    dev_cases, regression_cases = cases()
    title_ids: dict[str, list[int]] = defaultdict(list)
    for book in engine.books:
        title_ids[book.title].append(book.catalog_id)
    rows = collect(engine, [*dev_cases, *regression_cases], title_ids)
    dev_rows = rows[: len(dev_cases)]
    regression_rows = rows[len(dev_cases) :]
    default = (0.70, 0.70, 0.23)
    default_dev = metrics(engine, dev_rows, default)
    default_regression = metrics(engine, regression_rows, default)

    candidates = []
    plain_values = np.arange(0.45, 0.86, 0.05)
    metadata_semantic_values = np.arange(0.40, 0.81, 0.05)
    metadata_lexical_values = np.arange(0.05, 0.41, 0.05)
    for plain, meta_sem, meta_lex in product(
        plain_values, metadata_semantic_values, metadata_lexical_values
    ):
        if meta_sem + meta_lex > 0.90:
            continue
        weights = (round(float(plain), 2), round(float(meta_sem), 2), round(float(meta_lex), 2))
        dev_metric = metrics(engine, dev_rows, weights)
        reg_metric = metrics(engine, regression_rows, weights)
        if (
            reg_metric["hit3"] >= default_regression["hit3"] - (1 / 77)
            and reg_metric["hit10"] >= default_regression["hit10"] - (1 / 77)
        ):
            candidates.append(
                {
                    "weights": {
                        "plain_semantic": weights[0],
                        "plain_lexical": round(0.95 - weights[0], 2),
                        "metadata_semantic": weights[1],
                        "metadata_lexical": weights[2],
                        "metadata_preference": round(0.95 - weights[1] - weights[2], 2),
                        "popularity": 0.03,
                        "rating": 0.02,
                    },
                    "dev": {key: dev_metric[key] for key in ("ndcg10", "hit3", "hit10")},
                    "regression77": {
                        key: reg_metric[key] for key in ("ndcg10", "hit3", "hit10")
                    },
                }
            )
    candidates.sort(
        key=lambda item: (
            item["dev"]["ndcg10"],
            item["dev"]["hit3"],
            item["regression77"]["hit3"],
        ),
        reverse=True,
    )
    selected = candidates[0]
    selected_tuple = (
        selected["weights"]["plain_semantic"],
        selected["weights"]["metadata_semantic"],
        selected["weights"]["metadata_lexical"],
    )
    selected_dev = metrics(engine, dev_rows, selected_tuple)
    selected_regression = metrics(engine, regression_rows, selected_tuple)
    result = {
        "protocol": (
            "Grid selected on 51-query family-macro dev NDCG; 77-query Hit@3 and "
            "Hit@10 may each lose at most one query; entity floors unchanged; 99-query test unopened"
        ),
        "grid_candidates": len(candidates),
        "default": {
            "weights": {
                "plain_semantic": 0.70,
                "plain_lexical": 0.25,
                "metadata_semantic": 0.70,
                "metadata_lexical": 0.23,
                "metadata_preference": 0.02,
                "popularity": 0.03,
                "rating": 0.02,
            },
            "dev": {key: default_dev[key] for key in ("ndcg10", "hit3", "hit10")},
            "regression77": {
                key: default_regression[key] for key in ("ndcg10", "hit3", "hit10")
            },
        },
        "selected": selected,
        "delta": {
            key: selected["dev"][key] - default_dev[key]
            for key in ("ndcg10", "hit3", "hit10")
        },
        "selected_rows": {
            "dev": selected_dev["rows"],
            "regression77": selected_regression["rows"],
        },
        "top20": candidates[:20],
        "limitations": [
            "Dev qrels are agent-authored and sparse; unjudged books are unknown, not negative.",
            "The grid tunes relative ranking only and cannot by itself identify no-match queries.",
        ],
    }
    (OUTPUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT / "signal-summary.json").write_text(
        json.dumps(serializable_signal_cache(rows), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "default": result["default"],
                "selected": selected,
                "delta": result["delta"],
                "candidates": len(candidates),
            }
        )
    )


if __name__ == "__main__":
    main()
