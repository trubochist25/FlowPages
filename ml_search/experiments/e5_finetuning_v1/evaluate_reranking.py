from __future__ import annotations

import json
import hashlib
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .tune_signal_weights import cases, collect, load_engine, ndcg, ranked_ids


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "reranking_v1"


def split_profile(text: str) -> tuple[str, str]:
    marker = "Характерные детали:"
    if marker not in text:
        return text, text
    plot, structured = text.split(marker, 1)
    return plot.strip(), structured.strip()


def field_texts(engine) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = defaultdict(list)
    for book in engine.books:
        plot, structured = split_profile(book.search_text)
        fields["plot"].append(plot)
        fields["structured"].append(structured)
        fields["annotation"].append(book.annotation or plot)
        fields["taxonomy"].append(
            "; ".join(
                part
                for part in (
                    f"Жанры: {', '.join(book.genres)}" if book.genres else "",
                    f"Темы: {', '.join(book.themes)}" if book.themes else "",
                    f"Настроение: {', '.join(book.moods)}" if book.moods else "",
                    f"Темп: {book.pace}" if book.pace else "",
                )
                if part
            )
        )
    return fields


def encode_fields(engine, fields: dict[str, list[str]]) -> dict[str, np.ndarray]:
    cache_path = OUTPUT / "field-vectors.npz"
    if cache_path.exists():
        write_field_manifest(cache_path, engine)
        with np.load(cache_path) as data:
            return {name: data[name] for name in data.files}
    encoded = {
        name: engine.embedder.encode_passages(texts) for name, texts in fields.items()
    }
    np.savez_compressed(cache_path, **encoded)
    write_field_manifest(cache_path, engine)
    return encoded


def write_field_manifest(path: Path, engine) -> None:
    primary = json.loads((ROOT / "comparison" / "index" / "manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "format": "flowpages-multi-vector-fields-v1",
        "model_name": engine.embedder.model_name,
        "catalog_sha256": primary["catalog_sha256"],
        "books": len(engine.books),
        "dimension": engine.embedder.dimension,
        "fields": ["plot", "annotation", "structured", "taxonomy"],
        "index_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    path.with_name(f"{path.stem}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def family_metrics(rows: list[dict]) -> dict[str, float]:
    nonempty = [row for row in rows if not row["expected_empty"]]
    families: dict[str, list[dict]] = defaultdict(list)
    for row in nonempty:
        families[row["family_id"]].append(row)
    return {
        "ndcg10": float(
            np.mean([np.mean([item["ndcg10"] for item in group]) for group in families.values()])
        ),
        "hit3": float(
            np.mean([np.mean([item["hit3"] for item in group]) for group in families.values()])
        ),
        "hit10": float(
            np.mean([np.mean([item["hit10"] for item in group]) for group in families.values()])
        ),
    }


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    engine = load_engine()
    dev_cases, regression_cases = cases()
    title_ids: dict[str, list[int]] = defaultdict(list)
    for book in engine.books:
        title_ids[book.title].append(book.catalog_id)
    all_cases = [*dev_cases, *regression_cases]
    signals = collect(engine, all_cases, title_ids)
    fields = field_texts(engine)
    vectors = encode_fields(engine, fields)
    queries = engine.embedder.encode_queries(
        [engine.analyze(case["query"]).corrected_query for case in all_cases]
    )
    field_scores = {
        name: np.matmul(queries, matrix.T) for name, matrix in vectors.items()
    }

    base_orders: list[list[int]] = []
    base_scores: list[np.ndarray] = []
    for row in signals:
        _, ordered_scores = ranked_ids(engine, row, 0.70, 0.70, 0.23)
        if row["has_metadata"]:
            score = (
                0.70 * row["semantic"]
                + 0.23 * row["lexical"]
                + 0.02 * row["metadata"]
                + 0.03 * row["popularity"]
                + 0.02 * row["rating"]
            )
        else:
            score = (
                0.70 * row["semantic"]
                + 0.25 * row["lexical"]
                + 0.03 * row["popularity"]
                + 0.02 * row["rating"]
            )
        score = np.asarray(score, dtype=np.float32)
        # Navigation queries stay protected exactly as in the current ranker.
        floors = {
            "exact_title": 0.99, "title": 0.96, "fuzzy_title": 0.94,
            "exact_author": 0.98, "author": 0.95, "fuzzy_author": 0.93,
        }
        for pos, entity in enumerate(row["entity_kind"]):
            if entity:
                entity_score = (
                    0.25 * row["semantic"][pos]
                    + 0.60 * row["lexical"][pos]
                    + 0.10 * row["metadata"][pos]
                    + 0.03 * row["popularity"][pos]
                    + 0.02 * row["rating"][pos]
                )
                score[pos] = max(entity_score, floors.get(entity, 0.93))
        base_orders.append(list(np.argsort(-score)))
        base_scores.append(score)

    def evaluate(indices: list[int], config: dict) -> tuple[dict, list[dict]]:
        output_rows = []
        k = config["candidate_k"]
        alpha = config["alpha"]
        component = config["component"]
        for qi in indices:
            row = signals[qi]
            candidates = np.asarray(base_orders[qi][:k], dtype=np.int32)
            base = base_scores[qi][candidates]
            # Candidate-local scaling makes the blend comparable across query types.
            base_scaled = (base - base.min()) / max(float(base.max() - base.min()), 1e-6)
            if component == "max_fields":
                rerank_raw = np.maximum.reduce(
                    [field_scores[name][qi, candidates] for name in ("plot", "annotation", "structured", "taxonomy")]
                )
            elif component == "plot_structured":
                rerank_raw = 0.65 * field_scores["plot"][qi, candidates] + 0.35 * field_scores["structured"][qi, candidates]
            else:
                rerank_raw = field_scores[component][qi, candidates]
            rerank_scaled = (rerank_raw - rerank_raw.min()) / max(
                float(rerank_raw.max() - rerank_raw.min()), 1e-6
            )
            combined = (1.0 - alpha) * base_scaled + alpha * rerank_scaled
            # Never disturb a recognized title/author candidate.
            entity_mask = np.asarray([row["entity_kind"][p] is not None for p in candidates])
            combined[entity_mask] += 2.0
            order = candidates[np.argsort(-combined)]
            ids = [engine.books[p].catalog_id for p in order[:10]]
            good = {cid for cid, grade in row["grades"].items() if grade == 2}
            rank = next((rank + 1 for rank, cid in enumerate(ids) if cid in good), None)
            output_rows.append({
                "query_id": row["query_id"],
                "family_id": row["family_id"],
                "category": row["category"],
                "expected_empty": row["expected_empty"],
                "ndcg10": ndcg(ids, row["grades"]) if row["grades"] else None,
                "hit3": bool(rank and rank <= 3),
                "hit10": bool(rank and rank <= 10),
                "rank": rank,
                "top_ids": ids,
            })
        return family_metrics(output_rows), output_rows

    dev_idx = list(range(len(dev_cases)))
    reg_idx = list(range(len(dev_cases), len(all_cases)))
    baseline = {"candidate_k": 10, "alpha": 0.0, "component": "plot"}
    default_dev, default_dev_rows = evaluate(dev_idx, baseline)
    default_reg, default_reg_rows = evaluate(reg_idx, baseline)

    recall = {}
    for k in (10, 20, 30, 50, 100, 200, 1000):
        hits = []
        for qi in dev_idx:
            row = signals[qi]
            if row["expected_empty"]:
                continue
            good = {cid for cid, grade in row["grades"].items() if grade == 2}
            ids = {engine.books[p].catalog_id for p in base_orders[qi][:k]}
            hits.append(bool(good & ids))
        recall[str(k)] = float(np.mean(hits))

    candidates = []
    for k in (10, 20, 30, 50, 100, 200, 1000):
        for component in ("plot", "annotation", "structured", "taxonomy", "max_fields", "plot_structured"):
            for alpha in (0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
                config = {"candidate_k": k, "component": component, "alpha": alpha}
                dev_metric, _ = evaluate(dev_idx, config)
                reg_metric, _ = evaluate(reg_idx, config)
                candidates.append({"config": config, "dev": dev_metric, "regression77": reg_metric})
    eligible = [
        item for item in candidates
        if item["regression77"]["hit3"] >= default_reg["hit3"] - 1 / 77
        and item["regression77"]["hit10"] >= default_reg["hit10"] - 1 / 77
    ]
    eligible.sort(key=lambda item: (item["dev"]["ndcg10"], item["dev"]["hit3"], item["dev"]["hit10"]), reverse=True)
    selected = eligible[0]
    selected_dev, selected_dev_rows = evaluate(dev_idx, selected["config"])
    selected_reg, selected_reg_rows = evaluate(reg_idx, selected["config"])

    # Family holdout: select using the other families and score the excluded family.
    families = sorted({signals[i]["family_id"] for i in dev_idx if not signals[i]["expected_empty"]})
    cv_rows = []
    for family in families:
        train = [i for i in dev_idx if signals[i]["family_id"] != family]
        test = [i for i in dev_idx if signals[i]["family_id"] == family]
        ranked_configs = []
        for item in eligible:
            train_metric, _ = evaluate(train, item["config"])
            ranked_configs.append((train_metric["ndcg10"], train_metric["hit3"], item["config"]))
        config = max(ranked_configs, key=lambda x: (x[0], x[1]))[2]
        _, rows = evaluate(test, config)
        cv_rows.extend(rows)
    cv_metric = family_metrics(cv_rows)

    result = {
        "protocol": "Rerank only current top-K; select on 51-query dev with 77-query guardrails; validate selection by leave-one-family-out; 99-query closed test unopened.",
        "candidate_recall_dev": recall,
        "baseline": {"dev": default_dev, "regression77": default_reg},
        "searched_variants": len(candidates),
        "eligible_variants": len(eligible),
        "selected": selected,
        "selected_delta": {key: selected_dev[key] - default_dev[key] for key in default_dev},
        "selected_rows": {"dev": selected_dev_rows, "regression77": selected_reg_rows},
        "leave_one_family_out": {
            "adaptive": cv_metric,
            "baseline": default_dev,
            "delta": {key: cv_metric[key] - default_dev[key] for key in default_dev},
        },
        "top20": eligible[:20],
        "limitations": [
            "The dev judgments are sparse and agent-authored; unjudged books remain unknown.",
            "This tests a bi-encoder field reranker, not a true cross-encoder with joint token attention.",
        ],
    }
    (OUTPUT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("candidate_recall_dev", "baseline", "selected", "selected_delta", "leave_one_family_out")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
