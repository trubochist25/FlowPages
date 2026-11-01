from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from .calibration import ALCHEMY_QUERY_CALIBRATION
from .cli import make_embedder
from .config import Settings
from .evaluate_relevance import (
    CONTRAST_PERCENTILES,
    NEGATIVE_QUERIES,
    POSITIVE_QUERIES,
    _alchemy_mode,
    _alchemy_request,
    _has_meaningful_text,
    _search_mode,
    _select_threshold,
)
from .schemas import AlchemyAnalyzeRequest
from .search import SearchEngine


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "ml_search" / "contrast-experiment-report.json"


def _contrast(values: np.ndarray, percentile: int) -> np.ndarray:
    background = float(np.percentile(values, percentile))
    return values * np.maximum(0.0, values - background)


def _report(samples: dict) -> dict:
    return {
        str(percentile): _select_threshold(
            values["positive"],
            values["negative"],
        )
        for percentile, values in sorted(samples.items())
    }


def evaluate(model: str = "small") -> dict:
    settings = Settings.from_env(model)
    embedder = make_embedder(settings, "e5")
    engine = SearchEngine.from_settings(settings, embedder)
    positives = json.loads(POSITIVE_QUERIES.read_text(encoding="utf-8"))
    negatives = json.loads(NEGATIVE_QUERIES.read_text(encoding="utf-8"))["cases"]
    index_by_title: dict[str, list[int]] = defaultdict(list)
    for index, book in enumerate(engine.books):
        index_by_title[book.title].append(index)

    cases: list[dict] = []
    for case in positives:
        intent = engine.analyze(case["query"])
        if _search_mode(case, intent.as_dict()) == "semantic" and intent.residual_query:
            cases.append(
                {
                    "system": "search.semantic",
                    "label": "positive",
                    "text": intent.residual_query,
                    "expected": [
                        index
                        for title in case["expected_titles"]
                        for index in index_by_title.get(title, [])
                    ],
                }
            )
        analysis = engine.analyze_alchemy(AlchemyAnalyzeRequest(query=case["query"]))
        request = _alchemy_request(analysis, seed=1)
        if _alchemy_mode(request) == "freeform" and request.residual_query:
            cases.append(
                {
                    "system": "alchemy.freeform",
                    "label": "positive",
                    "text": request.residual_query,
                    "expected": [
                        index
                        for title in case["expected_titles"]
                        for index in index_by_title.get(title, [])
                    ],
                }
            )

    for case in negatives:
        if "search" in case["targets"]:
            intent = engine.analyze(case["query"])
            if _search_mode(case, intent.as_dict()) == "semantic" and intent.residual_query:
                cases.append(
                    {
                        "system": "search.semantic",
                        "label": "negative",
                        "text": intent.residual_query,
                        "expected": [],
                    }
                )
        if "alchemy" in case["targets"]:
            if not _has_meaningful_text(case["query"]):
                continue
            analysis = engine.analyze_alchemy(
                AlchemyAnalyzeRequest(query=case["query"])
            )
            if analysis.normalized_query or analysis.anchors or analysis.positive:
                request = _alchemy_request(analysis, seed=1)
                if _alchemy_mode(request) == "freeform" and request.residual_query:
                    cases.append(
                        {
                            "system": "alchemy.freeform",
                            "label": "negative",
                            "text": request.residual_query,
                            "expected": [],
                        }
                    )

    texts = list(dict.fromkeys(case["text"] for case in cases))
    vectors = embedder.encode_queries(texts)
    vector_by_text = dict(zip(texts, vectors))
    samples = {
        system: {
            percentile: {"positive": [], "negative": []}
            for percentile in CONTRAST_PERCENTILES
        }
        for system in ("search.semantic", "alchemy.freeform")
    }
    counts = defaultdict(lambda: {"positive": 0, "negative": 0})

    for case in cases:
        raw = engine.vector_index.similarities(vector_by_text[case["text"]])
        absolute = (
            ALCHEMY_QUERY_CALIBRATION.apply(raw)
            if case["system"] == "alchemy.freeform"
            else np.clip((raw + 1.0) / 2.0, 0.0, 1.0)
        )
        counts[case["system"]][case["label"]] += 1
        for percentile in CONTRAST_PERCENTILES:
            adjusted = _contrast(absolute, percentile)
            score = (
                max((float(adjusted[index]) for index in case["expected"]), default=0.0)
                if case["label"] == "positive"
                else float(np.max(adjusted))
            )
            if case["label"] == "positive" and not case["expected"]:
                continue
            samples[case["system"]][percentile][case["label"]].append(score)

    return {
        "model": settings.model_name,
        "catalog_books": len(engine.books),
        "formula": "absolute_score * max(0, absolute_score - query_percentile)",
        "counts": dict(counts),
        "systems": {
            system: _report(values)
            for system, values in samples.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Test catalogue-wide contrast scoring")
    parser.add_argument("--model", default="small")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate(args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
