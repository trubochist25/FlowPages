from __future__ import annotations

import argparse
import functools
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .calibration import (
    ALCHEMY_ANCHOR_CALIBRATION,
    ALCHEMY_QUERY_CALIBRATION,
)
from .cli import make_embedder
from .config import Settings
from .evaluate_alchemy import (
    _anchor_related,
    _supports,
    build_meaningful_cases,
)
from .embeddings import Embedder
from .schemas import (
    AlchemyAnalyzeRequest,
    AlchemyAnchor,
    AlchemyIngredient,
    AlchemyNegativeIngredient,
    AlchemyRecommendRequest,
    SearchRequest,
)
from .search import SearchEngine


ROOT = Path(__file__).resolve().parents[1]
POSITIVE_QUERIES = Path(__file__).with_name("evaluation_queries.json")
NEGATIVE_QUERIES = Path(__file__).with_name("relevance_negative_queries.json")
DEFAULT_OUTPUT = ROOT / "data" / "ml_search" / "relevance-calibration-report.json"
TARGET_RECALL = 0.90
TARGET_REJECTION = 0.90
CONTRAST_PERCENTILES = (50, 75, 90)
NAVIGATIONAL_CATEGORIES = {
    "navigational",
    "typo",
    "one_word_guard",
    "one_word_positive",
    "partial_title",
    "author_only",
}


def _has_meaningful_text(value: str) -> bool:
    return any(character.isalnum() for character in value)


class CachedQueryEmbedder:
    """Batch-preload query vectors so a full calibration run stays practical."""

    def __init__(self, backend: Embedder) -> None:
        self.backend = backend
        self.model_name = backend.model_name
        self.dimension = backend.dimension
        self.cache: dict[str, np.ndarray] = {}

    def preload(self, texts: Iterable[str]) -> None:
        self.encode_queries(list(dict.fromkeys(text for text in texts if text)))

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        missing = list(dict.fromkeys(text for text in texts if text not in self.cache))
        if missing:
            vectors = self.backend.encode_queries(missing)
            for text, vector in zip(missing, vectors):
                self.cache[text] = np.asarray(vector, dtype=np.float32)
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        return np.stack([self.cache[text] for text in texts]).astype(
            np.float32,
            copy=False,
        )

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self.backend.encode_passages(texts)


def _quantiles(values: Iterable[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {}

    def at(fraction: float) -> float:
        index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
        return round(ordered[index], 6)

    return {
        "min": round(ordered[0], 6),
        "p10": at(0.10),
        "p25": at(0.25),
        "median": round(statistics.median(ordered), 6),
        "p75": at(0.75),
        "p90": at(0.90),
        "max": round(ordered[-1], 6),
    }


def _rates(threshold: float, positives: list[float], negatives: list[float]) -> dict:
    recall = (
        sum(score >= threshold for score in positives) / len(positives)
        if positives
        else 0.0
    )
    rejection = (
        sum(score < threshold for score in negatives) / len(negatives)
        if negatives
        else 0.0
    )
    return {
        "positive_recall": recall,
        "negative_rejection": rejection,
        "balanced_accuracy": (recall + rejection) / 2.0,
    }


def _select_threshold(positives: list[float], negatives: list[float]) -> dict:
    if not positives:
        return {
            "threshold": None,
            "reason": "no_positive_samples",
            "positive_samples": 0,
            "negative_samples": len(negatives),
        }

    points = {0.0, 1.0}
    for score in [*positives, *negatives]:
        bounded = max(0.0, min(1.0, float(score)))
        points.add(bounded)
        points.add(math.nextafter(bounded, 1.0))
    candidates = sorted(points)
    evaluated = [(threshold, _rates(threshold, positives, negatives)) for threshold in candidates]
    recall_safe = [item for item in evaluated if item[1]["positive_recall"] >= TARGET_RECALL]
    if negatives and recall_safe:
        selected = max(
            recall_safe,
            key=lambda item: (
                item[1]["negative_rejection"],
                item[1]["positive_recall"],
                item[0],
            ),
        )
        reason = "best_rejection_with_recall_at_least_90_percent"
    elif recall_safe:
        selected = max(recall_safe, key=lambda item: item[0])
        reason = "highest_threshold_with_recall_at_least_90_percent"
    else:
        selected = max(
            evaluated,
            key=lambda item: (item[1]["balanced_accuracy"], -item[0]),
        )
        reason = "best_balanced_accuracy_no_90_percent_recall_solution"

    threshold, rates = selected
    return {
        "threshold": round(threshold, 6),
        "reason": reason,
        "positive_samples": len(positives),
        "negative_samples": len(negatives),
        "positive_recall": round(rates["positive_recall"], 4),
        "negative_rejection": round(rates["negative_rejection"], 4),
        "balanced_accuracy": round(rates["balanced_accuracy"], 4),
        "meets_targets": (
            rates["positive_recall"] >= TARGET_RECALL
            and (not negatives or rates["negative_rejection"] >= TARGET_REJECTION)
        ),
        "positive_distribution": _quantiles(positives),
        "negative_distribution": _quantiles(negatives),
    }


def _contrast_scores(results: Sequence, percentile: int) -> dict[int, float]:
    """Score how far each visible candidate stands above the query background."""
    if not results:
        return {}
    absolute = np.asarray(
        [item.relevance_score for item in results],
        dtype=np.float32,
    )
    background = float(np.percentile(absolute, percentile))
    adjusted: dict[int, float] = {}
    for item in results:
        score = float(item.relevance_score)
        breakdown = getattr(item, "score_breakdown", None)
        entity_match = getattr(breakdown, "entity_match", None)
        if entity_match:
            adjusted[item.product_id] = score
            continue
        adjusted[item.product_id] = score * max(0.0, score - background)
    return adjusted


def _contrast_report(samples: dict) -> dict:
    return {
        str(percentile): {
            mode: _select_threshold(values["positive"], values["negative"])
            for mode, values in sorted(modes.items())
        }
        for percentile, modes in sorted(samples.items())
    }


def _search_mode(case: dict, intent: dict) -> str:
    if (
        case.get("category") in NAVIGATIONAL_CATEGORIES
        or intent.get("matched_titles")
        or intent.get("matched_authors")
    ):
        return "navigational"
    return "semantic"


def _alchemy_request(analysis, *, seed: int) -> AlchemyRecommendRequest:
    return AlchemyRecommendRequest(
        query=analysis.normalized_query,
        residual_query=analysis.residual_query,
        anchors=[
            AlchemyAnchor(
                product_id=item.product_id,
                weight=item.weight,
                aspects=item.aspects,
            )
            for item in analysis.anchors
        ],
        positive=[
            AlchemyIngredient(kind=item.kind, value=item.value, weight=item.weight)
            for item in analysis.positive
        ],
        negative=[
            AlchemyNegativeIngredient(
                kind=item.kind,
                value=item.value,
                weight=item.weight,
                mode=item.mode,
            )
            for item in analysis.negative
        ],
        filters=analysis.filters,
        surprise=0.35,
        random_seed=seed,
        include_debug=True,
        limit=12,
    )


def _alchemy_mode(request: AlchemyRecommendRequest) -> str:
    structured = bool(request.anchors or request.positive or request.negative)
    freeform = bool(
        request.residual_query
        if request.residual_query is not None
        else request.query
    )
    if request.anchors and freeform:
        return "hybrid"
    if request.anchors:
        return "anchor"
    if structured and freeform:
        return "hybrid"
    if structured:
        return "structured"
    return "freeform"


def _query_texts_for_alchemy(engine: SearchEngine, request: AlchemyRecommendRequest) -> list[str]:
    ranker = engine.alchemy_service.ranker
    values = [ranker._semantic_query_text(request)]
    values.extend(item.value for item in request.positive)
    values.extend(item.value for item in request.negative)
    values.extend("; ".join(anchor.aspects) for anchor in request.anchors if anchor.aspects)
    return [value for value in values if value]


def _preload_queries(
    engine: SearchEngine,
    embedder: CachedQueryEmbedder,
    positives: list[dict],
    negatives: list[dict],
) -> None:
    texts: list[str] = []
    all_cases = [*positives, *negatives]
    for case in all_cases:
        intent = engine.analyze(case["query"])
        texts.extend(
            value
            for value in (intent.corrected_query, intent.residual_query)
            if value
        )
        if not _has_meaningful_text(case["query"]):
            continue
        analysis = engine.analyze_alchemy(AlchemyAnalyzeRequest(query=case["query"]))
        if analysis.normalized_query or analysis.anchors or analysis.positive:
            request = _alchemy_request(analysis, seed=1)
            texts.extend(_query_texts_for_alchemy(engine, request))
    for case in build_meaningful_cases(list(engine.books)):
        texts.extend(_query_texts_for_alchemy(engine, case.request))
    embedder.preload(texts)


def _install_analysis_cache(engine: SearchEngine) -> None:
    original_analyze = engine.analyze
    original_alchemy = engine.analyze_alchemy

    @functools.lru_cache(maxsize=None)
    def cached_analyze(query: str):
        return original_analyze(query)

    @functools.lru_cache(maxsize=None)
    def cached_alchemy(query: str, locale: str):
        return original_alchemy(AlchemyAnalyzeRequest(query=query, locale=locale))

    engine.analyze = cached_analyze  # type: ignore[method-assign]
    engine.analyze_alchemy = (  # type: ignore[method-assign]
        lambda request: cached_alchemy(request.query, request.locale)
    )


def _retrieval_summary(rows: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["label"] == "positive":
            grouped[row["mode"]].append(row)
    return {
        mode: {
            "positive_cases": len(values),
            "matched_cases": sum(row["matched"] for row in values),
            "coverage": round(
                sum(row["matched"] for row in values) / len(values),
                4,
            ),
        }
        for mode, values in sorted(grouped.items())
    }


def _evaluate_search(engine: SearchEngine, positives: list[dict], negatives: list[dict]) -> dict:
    samples: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"positive": [], "negative": []}
    )
    contrast_samples: dict[int, dict] = {
        percentile: defaultdict(lambda: {"positive": [], "negative": []})
        for percentile in CONTRAST_PERCENTILES
    }
    rows = []
    for case in positives:
        response = engine.search(
            SearchRequest(query=case["query"], limit=100, include_debug=True)
        )
        expected = set(case["expected_titles"])
        matching = [item for item in response.results if item.title in expected]
        score = max((item.relevance_score for item in matching), default=0.0)
        mode = _search_mode(case, response.intent)
        if matching:
            samples[mode]["positive"].append(score)
            for percentile in CONTRAST_PERCENTILES:
                adjusted = _contrast_scores(response.results, percentile)
                contrast_samples[percentile][mode]["positive"].append(
                    max(adjusted[item.product_id] for item in matching)
                )
        rows.append(
            {
                "id": case.get("query"),
                "label": "positive",
                "mode": mode,
                "score": round(score, 6),
                "matched": bool(matching),
            }
        )
        forbidden = set(case.get("forbidden_titles", []))
        forbidden_scores = [
            item.relevance_score for item in response.results if item.title in forbidden
        ]
        samples[mode]["negative"].extend(forbidden_scores)
        for percentile in CONTRAST_PERCENTILES:
            adjusted = _contrast_scores(response.results, percentile)
            contrast_samples[percentile][mode]["negative"].extend(
                adjusted[item.product_id]
                for item in response.results
                if item.title in forbidden
            )

    for case in negatives:
        if "search" not in case["targets"]:
            continue
        response = engine.search(
            SearchRequest(query=case["query"], limit=20, include_debug=True)
        )
        score = max((item.relevance_score for item in response.results), default=0.0)
        mode = _search_mode(case, response.intent)
        samples[mode]["negative"].append(score)
        for percentile in CONTRAST_PERCENTILES:
            adjusted = _contrast_scores(response.results, percentile)
            contrast_samples[percentile][mode]["negative"].append(
                max(adjusted.values(), default=0.0)
            )
        rows.append(
            {
                "id": case["id"],
                "label": case["expected_action"],
                "mode": mode,
                "score": round(score, 6),
                "matched": False,
            }
        )
    return {
        "thresholds": {
            mode: _select_threshold(values["positive"], values["negative"])
            for mode, values in sorted(samples.items())
        },
        "retrieval": _retrieval_summary(rows),
        "contrast_experiment": _contrast_report(contrast_samples),
        "samples": rows,
    }


def _evaluate_alchemy(engine: SearchEngine, positives: list[dict], negatives: list[dict]) -> dict:
    books_by_id = {book.product_id: book for book in engine.books}
    samples: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"positive": [], "negative": []}
    )
    contrast_samples: dict[int, dict] = {
        percentile: defaultdict(lambda: {"positive": [], "negative": []})
        for percentile in CONTRAST_PERCENTILES
    }
    rows = []

    for case in build_meaningful_cases(list(engine.books)):
        response = engine.recommend_alchemy(case.request)
        mode = _alchemy_mode(case.request)
        supported_scores = []
        unsupported_scores = []
        for item in response.results:
            book = books_by_id[item.product_id]
            supported = (
                _anchor_related(book, books_by_id[case.anchor_id])
                if case.anchor_id
                else _supports(book, case.focus_kind, case.focus_value)
            )
            (supported_scores if supported else unsupported_scores).append(
                item.relevance_score
            )
        case_score = max(supported_scores, default=0.0)
        if supported_scores:
            samples[mode]["positive"].append(case_score)
        samples[mode]["negative"].extend(unsupported_scores)
        for percentile in CONTRAST_PERCENTILES:
            adjusted = _contrast_scores(response.results, percentile)
            adjusted_supported = []
            adjusted_unsupported = []
            for item in response.results:
                book = books_by_id[item.product_id]
                supported = (
                    _anchor_related(book, books_by_id[case.anchor_id])
                    if case.anchor_id
                    else _supports(book, case.focus_kind, case.focus_value)
                )
                target = adjusted_supported if supported else adjusted_unsupported
                target.append(adjusted[item.product_id])
            if adjusted_supported:
                contrast_samples[percentile][mode]["positive"].append(
                    max(adjusted_supported)
                )
            contrast_samples[percentile][mode]["negative"].extend(
                adjusted_unsupported
            )
        rows.append(
            {
                "id": case.name,
                "label": "positive",
                "mode": mode,
                "score": round(case_score, 6),
                "matched": bool(supported_scores),
            }
        )

    for index, case in enumerate(positives):
        analysis = engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query=case["query"])
        )
        request = _alchemy_request(analysis, seed=3001 + index)
        response = engine.recommend_alchemy(request)
        expected = set(case["expected_titles"])
        matching = [
            item
            for item in response.results
            if books_by_id[item.product_id].title in expected
        ]
        score = max((item.relevance_score for item in matching), default=0.0)
        mode = _alchemy_mode(request)
        if matching:
            samples[mode]["positive"].append(score)
            for percentile in CONTRAST_PERCENTILES:
                adjusted = _contrast_scores(response.results, percentile)
                contrast_samples[percentile][mode]["positive"].append(
                    max(adjusted[item.product_id] for item in matching)
                )
        rows.append(
            {
                "id": case["query"],
                "label": "positive",
                "mode": mode,
                "score": round(score, 6),
                "matched": bool(matching),
            }
        )

    for index, case in enumerate(negatives):
        if "alchemy" not in case["targets"]:
            continue
        if not _has_meaningful_text(case["query"]):
            samples["freeform"]["negative"].append(0.0)
            for percentile in CONTRAST_PERCENTILES:
                contrast_samples[percentile]["freeform"]["negative"].append(0.0)
            rows.append(
                {
                    "id": case["id"],
                    "label": case["expected_action"],
                    "mode": "freeform",
                    "score": 0.0,
                    "matched": False,
                }
            )
            continue
        analysis = engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query=case["query"])
        )
        if not analysis.normalized_query and not analysis.anchors and not analysis.positive:
            samples["freeform"]["negative"].append(0.0)
            for percentile in CONTRAST_PERCENTILES:
                contrast_samples[percentile]["freeform"]["negative"].append(0.0)
            rows.append(
                {
                    "id": case["id"],
                    "label": case["expected_action"],
                    "mode": "freeform",
                    "score": 0.0,
                    "matched": False,
                }
            )
            continue
        request = _alchemy_request(analysis, seed=6001 + index)
        response = engine.recommend_alchemy(request)
        score = max((item.relevance_score for item in response.results), default=0.0)
        mode = _alchemy_mode(request)
        samples[mode]["negative"].append(score)
        for percentile in CONTRAST_PERCENTILES:
            adjusted = _contrast_scores(response.results, percentile)
            contrast_samples[percentile][mode]["negative"].append(
                max(adjusted.values(), default=0.0)
            )
        rows.append(
            {
                "id": case["id"],
                "label": case["expected_action"],
                "mode": mode,
                "score": round(score, 6),
                "matched": False,
            }
        )

    return {
        "thresholds": {
            mode: _select_threshold(values["positive"], values["negative"])
            for mode, values in sorted(samples.items())
        },
        "retrieval": _retrieval_summary(rows),
        "contrast_experiment": _contrast_report(contrast_samples),
        "samples": rows,
    }


def evaluate(model: str = "small") -> dict:
    started = time.perf_counter()
    settings = Settings.from_env(model)
    embedder = CachedQueryEmbedder(make_embedder(settings, "e5"))
    engine = SearchEngine.from_settings(settings, embedder)
    _install_analysis_cache(engine)
    positives = json.loads(POSITIVE_QUERIES.read_text(encoding="utf-8"))
    negatives = json.loads(NEGATIVE_QUERIES.read_text(encoding="utf-8"))["cases"]
    _preload_queries(engine, embedder, positives, negatives)
    search = _evaluate_search(engine, positives, negatives)
    alchemy = _evaluate_alchemy(engine, positives, negatives)
    thresholds = {
        **{f"search.{key}": value for key, value in search["thresholds"].items()},
        **{f"alchemy.{key}": value for key, value in alchemy["thresholds"].items()},
    }
    return {
        "model": settings.model_name,
        "catalog_books": len(engine.books),
        "positive_queries": len(positives),
        "negative_queries": len(negatives),
        "targets": {
            "minimum_positive_recall": TARGET_RECALL,
            "minimum_negative_rejection": TARGET_REJECTION,
        },
        "alchemy_similarity_calibration": {
            "query": ALCHEMY_QUERY_CALIBRATION.as_dict(),
            "anchor": ALCHEMY_ANCHOR_CALIBRATION.as_dict(),
        },
        "recommended_thresholds": thresholds,
        "all_thresholds_meet_targets": all(
            value.get("meets_targets", False)
            for value in thresholds.values()
            if value.get("positive_samples", 0) and value.get("negative_samples", 0)
        ),
        "processing_ms": round((time.perf_counter() - started) * 1000, 3),
        "search": search,
        "alchemy": alchemy,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate independent relevance thresholds for FlowPages"
    )
    parser.add_argument("--model", default="small")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate(args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {
        "model": report["model"],
        "positive_queries": report["positive_queries"],
        "negative_queries": report["negative_queries"],
        "recommended_thresholds": report["recommended_thresholds"],
        "all_thresholds_meet_targets": report["all_thresholds_meet_targets"],
        "processing_ms": report["processing_ms"],
        "output": str(args.output),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
