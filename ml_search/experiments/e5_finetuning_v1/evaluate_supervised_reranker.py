from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml_search.text import token_overlap

from .evaluate_reranking import family_metrics, field_texts
from .tune_signal_weights import cases, collect, load_engine, ndcg


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "supervised_reranking_v1"
FIELD_CACHE = ROOT / "reranking_v1" / "field-vectors.npz"
TRAINING = ROOT / "training" / "train_triplets.jsonl"


def load_training() -> list[dict]:
    return [json.loads(line) for line in TRAINING.read_text(encoding="utf-8").splitlines() if line.strip()]


def base_score(row: dict) -> np.ndarray:
    if row["has_metadata"]:
        score = 0.70 * row["semantic"] + 0.23 * row["lexical"] + 0.02 * row["metadata"]
    else:
        score = 0.70 * row["semantic"] + 0.25 * row["lexical"]
    score = np.asarray(score + 0.03 * row["popularity"] + 0.02 * row["rating"], dtype=np.float32)
    floors = {"exact_title": 0.99, "title": 0.96, "fuzzy_title": 0.94,
              "exact_author": 0.98, "author": 0.95, "fuzzy_author": 0.93}
    for pos, entity in enumerate(row["entity_kind"]):
        if entity:
            entity_score = (0.25 * row["semantic"][pos] + 0.60 * row["lexical"][pos]
                            + 0.10 * row["metadata"][pos] + 0.03 * row["popularity"][pos]
                            + 0.02 * row["rating"][pos])
            score[pos] = max(entity_score, floors.get(entity, 0.93))
    return score


def features(
    query: str,
    qi: int,
    positions: np.ndarray,
    row: dict,
    field_scores: dict[str, np.ndarray],
    fields: dict[str, list[str]],
) -> np.ndarray:
    values = []
    base_values = base_score(row)
    for pos in positions:
        values.append([
            float(base_values[pos]),
            float(row["semantic_raw"][pos]),
            float(field_scores["plot"][qi, pos]),
            float(field_scores["annotation"][qi, pos]),
            float(field_scores["structured"][qi, pos]),
            float(field_scores["taxonomy"][qi, pos]),
            float(row["lexical"][pos]),
            float(row["metadata"][pos]),
            token_overlap(query, fields["plot"][pos]),
            token_overlap(query, fields["structured"][pos]),
        ])
    return np.asarray(values, dtype=np.float32)


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    engine = load_engine()
    fields = field_texts(engine)
    with np.load(FIELD_CACHE) as data:
        field_vectors = {name: data[name] for name in data.files}

    training = load_training()
    dev_cases, regression_cases = cases()
    train_cases = [
        {"query_id": item["example_id"], "family_id": item["group_id"], "category": "training", "query": item["query"], "expected_empty": False,
         "judgments": [{"catalog_id": item["positive_catalog_id"], "grade": 2}]}
        for item in training
    ]
    all_cases = [*train_cases, *dev_cases, *regression_cases]
    title_ids: dict[str, list[int]] = defaultdict(list)
    for book in engine.books:
        title_ids[book.title].append(book.catalog_id)
    rows = collect(engine, all_cases, title_ids)
    query_texts = [engine.analyze(case["query"]).corrected_query for case in all_cases]
    query_vectors = engine.embedder.encode_queries(query_texts)
    field_scores = {name: query_vectors @ matrix.T for name, matrix in field_vectors.items()}
    position_by_id = {book.catalog_id: pos for pos, book in enumerate(engine.books)}

    pair_x = []
    for qi, item in enumerate(training):
        pos = position_by_id[item["positive_catalog_id"]]
        neg = position_by_id[item["negative_catalog_id"]]
        pair_features = features(query_texts[qi], qi, np.asarray([pos, neg]), rows[qi], field_scores, fields)
        diff = pair_features[0] - pair_features[1]
        pair_x.extend([diff, -diff])
    pair_y = np.asarray([label for _ in training for label in (1, 0)])
    model = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000, random_state=17))
    model.fit(np.asarray(pair_x), pair_y)

    cached_base: list[np.ndarray] = []
    cached_order: list[np.ndarray] = []
    cached_learned: list[np.ndarray] = []
    for qi, row in enumerate(rows):
        base = base_score(row)
        order = np.argsort(-base)[:50]
        x = features(query_texts[qi], qi, order, row, field_scores, fields)
        cached_base.append(base)
        cached_order.append(order)
        cached_learned.append(np.asarray(model.decision_function(x), dtype=np.float32))

    def evaluate(indices: list[int], config: dict) -> tuple[dict, list[dict]]:
        output = []
        for qi in indices:
            row = rows[qi]
            base = cached_base[qi]
            candidates = cached_order[qi][: config["candidate_k"]]
            learned = cached_learned[qi][: config["candidate_k"]]
            base_local = base[candidates]
            base_local = (base_local - base_local.min()) / max(float(np.ptp(base_local)), 1e-6)
            learned = (learned - learned.min()) / max(float(np.ptp(learned)), 1e-6)
            combined = (1 - config["alpha"]) * base_local + config["alpha"] * learned
            entities = np.asarray([row["entity_kind"][pos] is not None for pos in candidates])
            combined[entities] += 2.0
            order = candidates[np.argsort(-combined)]
            ids = [engine.books[pos].catalog_id for pos in order[:10]]
            good = {cid for cid, grade in row["grades"].items() if grade == 2}
            rank = next((rank + 1 for rank, cid in enumerate(ids) if cid in good), None)
            output.append({"query_id": row["query_id"], "family_id": row["family_id"], "category": row["category"],
                           "expected_empty": row["expected_empty"], "ndcg10": ndcg(ids, row["grades"]) if row["grades"] else None,
                           "hit3": bool(rank and rank <= 3), "hit10": bool(rank and rank <= 10), "rank": rank, "top_ids": ids})
        return family_metrics(output), output

    train_n = len(train_cases)
    dev_idx = list(range(train_n, train_n + len(dev_cases)))
    reg_idx = list(range(train_n + len(dev_cases), len(all_cases)))
    baseline_config = {"candidate_k": 10, "alpha": 0.0}
    baseline_dev, _ = evaluate(dev_idx, baseline_config)
    baseline_reg, _ = evaluate(reg_idx, baseline_config)
    variants = []
    for k in (10, 20, 30, 50):
        for alpha in (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80):
            config = {"candidate_k": k, "alpha": alpha}
            dev, _ = evaluate(dev_idx, config)
            reg, _ = evaluate(reg_idx, config)
            variants.append({"config": config, "dev": dev, "regression77": reg})
    eligible = [item for item in variants if item["regression77"]["hit3"] >= baseline_reg["hit3"] - 1 / 77 and item["regression77"]["hit10"] >= baseline_reg["hit10"] - 1 / 77]
    eligible.sort(key=lambda item: (item["dev"]["ndcg10"], item["dev"]["hit3"], item["dev"]["hit10"]), reverse=True)
    selected = eligible[0]
    _, selected_rows = evaluate(dev_idx, selected["config"])

    families = sorted({rows[i]["family_id"] for i in dev_idx if not rows[i]["expected_empty"]})
    cv_rows = []
    for family in families:
        tune = [i for i in dev_idx if rows[i]["family_id"] != family]
        held = [i for i in dev_idx if rows[i]["family_id"] == family]
        best = max(eligible, key=lambda item: (evaluate(tune, item["config"])[0]["ndcg10"], evaluate(tune, item["config"])[0]["hit3"]))
        cv_rows.extend(evaluate(held, best["config"])[1])
    cv = family_metrics(cv_rows)

    feature_names = ["base", "whole_profile", "plot", "annotation", "structured", "taxonomy", "lexical", "metadata", "plot_overlap", "structured_overlap"]
    classifier = model.named_steps["logisticregression"]
    scaler = model.named_steps["standardscaler"]
    effective = classifier.coef_[0] / scaler.scale_
    result = {
        "protocol": "Pairwise logistic reranker trained only on 34 reviewed training triplets; hyperparameters selected on dev with regression guardrails; 99-query closed test unopened.",
        "training_pairs": len(training),
        "feature_weights": dict(zip(feature_names, map(float, effective))),
        "baseline": {"dev": baseline_dev, "regression77": baseline_reg},
        "selected": selected,
        "selected_delta": {key: selected["dev"][key] - baseline_dev[key] for key in baseline_dev},
        "leave_one_family_out": {"adaptive": cv, "baseline": baseline_dev, "delta": {key: cv[key] - baseline_dev[key] for key in baseline_dev}},
        "selected_rows": selected_rows,
        "top_variants": eligible[:20],
        "limitations": ["Only 34 reviewed pairwise examples are available.", "This is a supervised feature reranker, not a transformer cross-encoder."],
    }
    (OUTPUT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("training_pairs", "feature_weights", "baseline", "selected", "selected_delta", "leave_one_family_out")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
