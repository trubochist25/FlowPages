from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from ml_search.text import tokenize
from ml_search.experiments.e5_finetuning_v1.tune_signal_weights import (
    ASSESSMENT,
    OUTPUT as TUNING_OUTPUT,
    cases,
    collect,
    load_engine,
    metrics,
    ranked_ids,
)


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "signal_validation_v1"


def tuple_from(candidate: dict) -> tuple[float, float, float]:
    weights = candidate["weights"]
    return (
        weights["plain_semantic"],
        weights["metadata_semantic"],
        weights["metadata_lexical"],
    )


def family_ndcg(engine, rows: list[dict], weights: tuple[float, float, float]) -> dict[str, float]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    result = metrics(engine, rows, weights)["rows"]
    for row in result:
        if not row["expected_empty"]:
            grouped[row["family_id"]].append(row)
    return {
        family: float(np.mean([row["ndcg10"] for row in family_rows]))
        for family, family_rows in grouped.items()
    }


def default_scores(engine, row: dict) -> tuple[list[int], np.ndarray]:
    return ranked_ids(engine, row, 0.70, 0.70, 0.23)


def confidence_features(engine, row: dict) -> list[float]:
    raw = row["semantic_raw"]
    semantic_order = np.argsort(-raw)
    lexical_order = np.argsort(-row["lexical"])
    _, scores = default_scores(engine, row)
    query_tokens = [token for token in tokenize(row["query"]) if len(token) >= 3]
    known_fraction = (
        np.mean([engine._profile_token_frequency[token] > 0 for token in query_tokens])
        if query_tokens
        else 0.0
    )
    top5_overlap = len(set(semantic_order[:5]).intersection(lexical_order[:5])) / 5
    raw_std = float(np.std(raw)) or 1.0
    return [
        float(raw[semantic_order[0]]),
        float((raw[semantic_order[0]] - np.mean(raw)) / raw_std),
        float(raw[semantic_order[0]] - raw[semantic_order[1]]),
        float(raw[semantic_order[0]] - np.mean(raw[semantic_order[:10]])),
        float(np.max(row["lexical"])),
        float(row["lexical"][lexical_order[0]] - row["lexical"][lexical_order[1]]),
        float(scores[0]),
        float(scores[0] - scores[1]),
        float(top5_overlap),
        float(known_fraction),
    ]


def fit_logistic(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    design = np.column_stack([np.ones(len(z)), z])
    weights = np.zeros(design.shape[1], dtype=np.float64)
    class_weight = np.where(
        y == 1,
        len(y) / (2 * max(1, np.sum(y == 1))),
        len(y) / (2 * max(1, np.sum(y == 0))),
    )
    for _ in range(2500):
        logits = np.clip(design @ weights, -30, 30)
        probability = 1.0 / (1.0 + np.exp(-logits))
        gradient = design.T @ ((probability - y) * class_weight) / len(y)
        gradient[1:] += 0.03 * weights[1:]
        weights -= 0.05 * gradient
    return weights, mean, scale


def predict_logistic(
    x: np.ndarray, weights: np.ndarray, mean: np.ndarray, scale: np.ndarray
) -> np.ndarray:
    design = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    return 1.0 / (1.0 + np.exp(-np.clip(design @ weights, -30, 30)))


def best_threshold(probability: np.ndarray, y: np.ndarray) -> float:
    choices = sorted({0.0, 1.0, *probability.tolist()})
    best = (0.5, -1.0, -1.0)
    for threshold in choices:
        predicted = probability >= threshold
        positive_recall = np.mean(predicted[y == 1]) if np.any(y == 1) else 0.0
        empty_recall = np.mean(~predicted[y == 0]) if np.any(y == 0) else 0.0
        balanced = (positive_recall + empty_recall) / 2
        if (balanced, positive_recall) > (best[1], best[2]):
            best = (threshold, balanced, positive_recall)
    return float(best[0])


def grouped_confidence_validation(engine, rows: list[dict]) -> dict:
    x = np.asarray([confidence_features(engine, row) for row in rows])
    y = np.asarray([not row["expected_empty"] for row in rows], dtype=np.float64)
    families = np.asarray([row["family_id"] for row in rows])
    probabilities = np.zeros(len(rows), dtype=np.float64)
    predictions = np.zeros(len(rows), dtype=bool)
    thresholds = []
    for family in sorted(set(families)):
        train = families != family
        test = ~train
        weights, mean, scale = fit_logistic(x[train], y[train])
        train_probability = predict_logistic(x[train], weights, mean, scale)
        threshold = best_threshold(train_probability, y[train])
        test_probability = predict_logistic(x[test], weights, mean, scale)
        probabilities[test] = test_probability
        predictions[test] = test_probability >= threshold
        thresholds.append(threshold)
    positive = y == 1
    empty = y == 0
    positive_recall = float(np.mean(predictions[positive]))
    empty_recall = float(np.mean(~predictions[empty]))
    false_empty = [
        rows[index]["query_id"]
        for index in range(len(rows))
        if positive[index] and not predictions[index]
    ]
    missed_empty = [
        rows[index]["query_id"]
        for index in range(len(rows))
        if empty[index] and predictions[index]
    ]
    return {
        "protocol": "leave-one-family-out logistic regression with per-fold threshold selection",
        "features": [
            "raw_top1",
            "raw_top1_zscore",
            "raw_top1_gap",
            "raw_top1_minus_top10_mean",
            "lexical_top1",
            "lexical_gap",
            "ranking_top_score",
            "ranking_gap",
            "semantic_lexical_top5_overlap",
            "known_query_token_fraction",
        ],
        "positive_recall": positive_recall,
        "empty_recall": empty_recall,
        "balanced_accuracy": (positive_recall + empty_recall) / 2,
        "false_empty_query_ids": false_empty,
        "missed_empty_query_ids": missed_empty,
        "median_threshold": float(np.median(thresholds)),
        "probabilities": [
            {
                "query_id": row["query_id"],
                "family_id": row["family_id"],
                "expected_empty": row["expected_empty"],
                "probability_has_match": float(probabilities[index]),
                "predicted_has_match": bool(predictions[index]),
            }
            for index, row in enumerate(rows)
        ],
    }


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"Output already exists: {OUTPUT}")
    OUTPUT.mkdir()
    tuning = json.loads((TUNING_OUTPUT / "results.json").read_text(encoding="utf-8"))
    engine = load_engine()
    dev_cases, regression_cases = cases()
    title_ids: dict[str, list[int]] = defaultdict(list)
    for book in engine.books:
        title_ids[book.title].append(book.catalog_id)
    rows = collect(engine, [*dev_cases, *regression_cases], title_ids)
    dev_rows = rows[: len(dev_cases)]

    candidate_records = [
        {"name": "default", "weights": tuning["default"]["weights"]},
        *[
            {"name": f"grid_{index + 1}", "weights": item["weights"]}
            for index, item in enumerate(tuning["top20"])
        ],
    ]
    for item in candidate_records:
        item["tuple"] = tuple_from(item)
        item["families"] = family_ndcg(engine, dev_rows, item["tuple"])
    families = sorted(candidate_records[0]["families"])
    selected_counts: Counter[str] = Counter()
    heldout_scores = []
    default_scores_cv = []
    fold_choices = []
    for heldout in families:
        training_families = [family for family in families if family != heldout]
        chosen = max(
            candidate_records,
            key=lambda item: np.mean(
                [item["families"][family] for family in training_families]
            ),
        )
        selected_counts[chosen["name"]] += 1
        heldout_scores.append(chosen["families"][heldout])
        default_scores_cv.append(candidate_records[0]["families"][heldout])
        fold_choices.append(
            {
                "heldout_family": heldout,
                "selected": chosen["name"],
                "selected_heldout_ndcg": chosen["families"][heldout],
                "default_heldout_ndcg": candidate_records[0]["families"][heldout],
            }
        )
    weight_stability = {
        "protocol": "leave-one-family-out selection among default and grid top20",
        "selected_frequency": dict(selected_counts),
        "adaptive_cv_ndcg": float(np.mean(heldout_scores)),
        "default_cv_ndcg": float(np.mean(default_scores_cv)),
        "delta": float(np.mean(heldout_scores) - np.mean(default_scores_cv)),
        "folds": fold_choices,
    }
    confidence = grouped_confidence_validation(engine, dev_rows)
    recommendation = {
        "weights": (
            "keep_default"
            if weight_stability["delta"] < 0.01
            else "candidate_requires_closed_test"
        ),
        "empty_detection": (
            "candidate_requires_more_independent_empty_families"
            if confidence["positive_recall"] >= 0.90
            and confidence["empty_recall"] >= 0.75
            else "do_not_integrate"
        ),
    }
    result = {
        "weight_stability": weight_stability,
        "empty_detection": confidence,
        "recommendation": recommendation,
        "limitations": [
            "Only four empty-intent families are available; three paraphrases per family are correlated.",
            "All development judgments were made by the same agent that authored the queries.",
        ],
    }
    (OUTPUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "weight_stability": {
                    key: weight_stability[key]
                    for key in ("selected_frequency", "adaptive_cv_ndcg", "default_cv_ndcg", "delta")
                },
                "empty_detection": {
                    key: confidence[key]
                    for key in ("positive_recall", "empty_recall", "balanced_accuracy")
                },
                "recommendation": recommendation,
            }
        )
    )


if __name__ == "__main__":
    main()
