from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .cli import make_embedder
from .config import Settings
from .models import Book
from .schemas import (
    AlchemyAnchor,
    AlchemyFilters,
    AlchemyIngredient,
    AlchemyNegativeIngredient,
    AlchemyRecommendRequest,
)
from .search import SearchEngine
from .text import normalize_text


DEFAULT_OUTPUT = Settings.from_env().data_dir / "step9-alchemy-evaluation.json"


@dataclass(frozen=True, slots=True)
class RecipeCase:
    name: str
    request: AlchemyRecommendRequest
    focus_kind: str = ""
    focus_value: str = ""
    anchor_id: int = 0


def _frequent(values: list[str], limit: int, minimum: int) -> list[str]:
    return [value for value, count in Counter(values).most_common() if count >= minimum][
        :limit
    ]


def build_meaningful_cases(books: list[Book]) -> list[RecipeCase]:
    dimensions = {
        "genre": _frequent([value for book in books for value in book.genres], 15, 15),
        "mood": _frequent([value for book in books for value in book.moods], 15, 15),
        "theme": _frequent([value for book in books for value in book.themes], 15, 15),
    }
    cases: list[RecipeCase] = []
    for kind, values in dimensions.items():
        for value in values:
            for surprise in (0.05, 0.35):
                cases.append(
                    RecipeCase(
                        name=f"{kind}:{value}:surprise-{surprise}",
                        request=AlchemyRecommendRequest(
                            positive=[
                                AlchemyIngredient(kind=kind, value=value, weight=1.0)
                            ],
                            surprise=surprise,
                            random_seed=len(cases) + 101,
                            include_debug=True,
                            limit=12,
                        ),
                        focus_kind=kind,
                        focus_value=value,
                    )
                )

    paces = _frequent([book.pace for book in books if book.pace], 3, 20)
    for pace in paces:
        for surprise in (0.05, 0.25, 0.45):
            cases.append(
                RecipeCase(
                    name=f"pace:{pace}:surprise-{surprise}",
                    request=AlchemyRecommendRequest(
                        positive=[
                            AlchemyIngredient(kind="pace", value=pace, weight=1.0)
                        ],
                        surprise=surprise,
                        random_seed=len(cases) + 101,
                        include_debug=True,
                        limit=12,
                    ),
                    focus_kind="pace",
                    focus_value=pace,
                )
            )

    anchors = sorted(
        (book for book in books if book.quantity > 0 and book.genres),
        key=lambda book: (book.rating_count, book.popularity, book.rating),
        reverse=True,
    )[:21]
    for book in anchors:
        cases.append(
            RecipeCase(
                name=f"anchor:{book.product_id}:{book.title}",
                request=AlchemyRecommendRequest(
                    anchors=[AlchemyAnchor(product_id=book.product_id, weight=1.0)],
                    surprise=0.25,
                    random_seed=len(cases) + 101,
                    include_debug=True,
                    limit=12,
                ),
                anchor_id=book.product_id,
            )
        )
    return cases


def _supports(book: Book, kind: str, value: str) -> bool:
    expected = normalize_text(value)
    if kind == "genre":
        candidates = book.genres
    elif kind == "mood":
        candidates = book.moods
    elif kind == "theme":
        candidates = book.themes
    elif kind == "pace":
        candidates = (book.pace,)
    else:
        return False
    return expected in {normalize_text(candidate) for candidate in candidates}


def _anchor_related(book: Book, anchor: Book) -> bool:
    return bool(set(book.genres) & set(anchor.genres)) or (
        bool(book.series) and book.series == anchor.series
    ) or (bool(book.author) and book.author == anchor.author)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[position]


def evaluate_meaningful(
    engine: SearchEngine, books_by_id: dict[int, Book], cases: list[RecipeCase]
) -> tuple[list[dict], list[float], list[str]]:
    rows: list[dict] = []
    latencies: list[float] = []
    grounding_failures: list[str] = []
    for case in cases:
        response = engine.recommend_alchemy(case.request)
        latencies.append(response.processing_ms)
        top = response.results[:3]
        real_books = [books_by_id[item.product_id] for item in top if item.product_id in books_by_id]
        if case.anchor_id:
            anchor = books_by_id[case.anchor_id]
            supported = sum(_anchor_related(book, anchor) for book in real_books)
        else:
            supported = sum(
                _supports(book, case.focus_kind, case.focus_value)
                for book in real_books
            )
        meaningful = len(top) == 3 and len(real_books) == 3 and supported >= 2
        for item in response.results:
            if item.product_id not in books_by_id:
                grounding_failures.append(f"{case.name}:unknown-product:{item.product_id}")
            if not item.reasons:
                grounding_failures.append(f"{case.name}:missing-reason:{item.product_id}")
            if item.score_breakdown is None or not all(
                math.isfinite(value) for value in item.score_breakdown.values()
            ):
                grounding_failures.append(f"{case.name}:missing-score-data:{item.product_id}")
        rows.append(
            {
                "name": case.name,
                "meaningful": meaningful,
                "supported_top3": supported,
                "top_product_ids": [item.product_id for item in top],
                "processing_ms": response.processing_ms,
            }
        )
    return rows, latencies, grounding_failures


def evaluate_strict_exclusions(
    engine: SearchEngine, books: list[Book], books_by_id: dict[int, Book]
) -> dict:
    dimensions = {
        "genre": _frequent([value for book in books for value in book.genres], 10, 20),
        "mood": _frequent([value for book in books for value in book.moods], 10, 20),
        "theme": _frequent([value for book in books for value in book.themes], 10, 20),
        "pace": _frequent([book.pace for book in books if book.pace], 3, 20),
    }
    positive = {
        "genre": AlchemyIngredient(kind="mood", value="вдумчивая"),
        "mood": AlchemyIngredient(kind="genre", value="Классическая литература"),
        "theme": AlchemyIngredient(kind="mood", value="атмосферная"),
        "pace": AlchemyIngredient(kind="genre", value="Фэнтези"),
    }
    rows = []
    violations = []
    latencies = []
    for kind, values in dimensions.items():
        for value in values:
            request = AlchemyRecommendRequest(
                positive=[positive[kind]],
                negative=[
                    AlchemyNegativeIngredient(
                        kind=kind, value=value, weight=1.0, mode="exclude"
                    )
                ],
                surprise=0.35,
                random_seed=len(rows) + 701,
                include_debug=True,
                limit=12,
            )
            response = engine.recommend_alchemy(request)
            latencies.append(response.processing_ms)
            case_violations = [
                item.product_id
                for item in response.results
                if item.product_id not in books_by_id
                or _supports(books_by_id[item.product_id], kind, value)
            ]
            if case_violations:
                violations.append(
                    {"kind": kind, "value": value, "product_ids": case_violations}
                )
            rows.append(
                {
                    "kind": kind,
                    "value": value,
                    "results": len(response.results),
                    "violations": case_violations,
                }
            )
    return {"cases": rows, "violations": violations, "latencies": latencies}


def evaluate_filters(
    engine: SearchEngine, books: list[Book], books_by_id: dict[int, Book]
) -> dict:
    genres = _frequent([value for book in books for value in book.genres], 10, 25)
    rows = []
    violations = []
    latencies = []
    for index, genre in enumerate(genres):
        maximum = 260 + (index % 5) * 80
        request = AlchemyRecommendRequest(
            positive=[AlchemyIngredient(kind="genre", value=genre, weight=1.0)],
            filters=AlchemyFilters(pages_max=maximum, in_stock=True),
            surprise=0.2,
            random_seed=901 + index,
            include_debug=True,
            limit=12,
        )
        response = engine.recommend_alchemy(request)
        latencies.append(response.processing_ms)
        case_violations = [
            item.product_id
            for item in response.results
            if item.product_id not in books_by_id
            or books_by_id[item.product_id].pages > maximum
            or books_by_id[item.product_id].quantity <= 0
        ]
        if case_violations:
            violations.append(
                {"genre": genre, "pages_max": maximum, "product_ids": case_violations}
            )
        rows.append(
            {
                "genre": genre,
                "pages_max": maximum,
                "results": len(response.results),
                "violations": case_violations,
            }
        )
    return {"cases": rows, "violations": violations, "latencies": latencies}


def evaluate_contradictions() -> dict:
    values = [
        ("genre", "Фэнтези"),
        ("genre", "Детективы"),
        ("genre", "Фантастика"),
        ("mood", "уютная"),
        ("mood", "мрачная"),
        ("mood", "напряжённая"),
        ("theme", "власть и общество"),
        ("theme", "личный выбор"),
        ("theme", "любовь и отношения"),
        ("pace", "быстрый"),
        ("pace", "средний"),
        ("pace", "медленный"),
    ]
    rejected = []
    accepted = []
    for kind, value in values:
        try:
            AlchemyRecommendRequest(
                positive=[AlchemyIngredient(kind=kind, value=value)],
                negative=[AlchemyNegativeIngredient(kind=kind, value=value.upper())],
            )
        except ValidationError:
            rejected.append(f"{kind}:{value}")
        else:
            accepted.append(f"{kind}:{value}")
    return {"cases": len(values), "rejected": rejected, "accepted": accepted}


def evaluate_empty_states(engine: SearchEngine) -> dict:
    filters = (
        AlchemyFilters(price_min=999999, in_stock=True),
        AlchemyFilters(pages_min=99999, in_stock=True),
        AlchemyFilters(year_min=2999, in_stock=True),
        AlchemyFilters(price_max=1, in_stock=True),
        AlchemyFilters(pages_max=1, in_stock=True),
    )
    rows = []
    failures = []
    latencies = []
    for index, strict_filter in enumerate(filters):
        response = engine.recommend_alchemy(
            AlchemyRecommendRequest(
                positive=[AlchemyIngredient(kind="mood", value="уютная")],
                filters=strict_filter,
                random_seed=1101 + index,
                include_debug=True,
                limit=12,
            )
        )
        latencies.append(response.processing_ms)
        explained = (
            not response.results
            and any(warning.code == "no_candidates" for warning in response.warnings)
            and bool(response.relaxations)
        )
        if not explained:
            failures.append(index)
        rows.append(
            {
                "case": index + 1,
                "explained": explained,
                "warnings": [warning.code for warning in response.warnings],
                "relaxations": response.relaxations,
            }
        )
    return {"cases": rows, "failures": failures, "latencies": latencies}


def evaluate(model: str) -> dict:
    settings = Settings.from_env(model)
    started = time.perf_counter()
    embedder = make_embedder(settings, "e5")
    engine = SearchEngine.from_settings(settings, embedder)
    load_ms = (time.perf_counter() - started) * 1000
    books = list(engine.books)
    books_by_id = {book.product_id: book for book in books}

    warmup = AlchemyRecommendRequest(
        positive=[AlchemyIngredient(kind="genre", value="Фантастика")],
        random_seed=1,
        limit=12,
    )
    engine.recommend_alchemy(warmup)

    cases = build_meaningful_cases(books)
    rows, meaningful_latencies, grounding_failures = evaluate_meaningful(
        engine, books_by_id, cases
    )
    exclusions = evaluate_strict_exclusions(engine, books, books_by_id)
    strict_filters = evaluate_filters(engine, books, books_by_id)
    contradictions = evaluate_contradictions()
    empty_states = evaluate_empty_states(engine)
    all_latencies = (
        meaningful_latencies
        + exclusions["latencies"]
        + strict_filters["latencies"]
        + empty_states["latencies"]
    )
    meaningful_count = sum(row["meaningful"] for row in rows)
    meaningful_rate = meaningful_count / len(rows)
    summary = {
        "model": settings.model_name,
        "catalog_books": len(books),
        "load_ms": round(load_ms, 3),
        "meaningful_recipes": len(rows),
        "meaningful_top3_count": meaningful_count,
        "meaningful_top3_rate": round(meaningful_rate, 4),
        "strict_exclusion_cases": len(exclusions["cases"]),
        "strict_exclusion_violations": len(exclusions["violations"]),
        "strict_filter_cases": len(strict_filters["cases"]),
        "strict_filter_violations": len(strict_filters["violations"]),
        "contradiction_cases": contradictions["cases"],
        "contradictions_rejected": len(contradictions["rejected"]),
        "unexplained_empty_states": len(empty_states["failures"]),
        "metadata_grounding_failures": len(grounding_failures),
        "mean_processing_ms": round(statistics.fmean(all_latencies), 3),
        "median_processing_ms": round(statistics.median(all_latencies), 3),
        "p95_processing_ms": round(_percentile(all_latencies, 0.95), 3),
        "max_processing_ms": round(max(all_latencies), 3),
    }
    checks = {
        "at_least_100_recipes": len(rows) >= 100,
        "meaningful_top3_at_least_90_percent": meaningful_rate >= 0.9,
        "strict_exclusions_always_hold": not exclusions["violations"],
        "strict_filters_always_hold": not strict_filters["violations"],
        "contradictions_always_rejected": not contradictions["accepted"],
        "no_unexplained_empty_state": not empty_states["failures"],
        "all_outputs_grounded": not grounding_failures,
        "p95_processing_within_800_ms": _percentile(all_latencies, 0.95) <= 800,
    }
    return {
        "summary": summary,
        "checks": checks,
        "meaningful_results": rows,
        "strict_exclusions": {
            "cases": exclusions["cases"],
            "violations": exclusions["violations"],
        },
        "strict_filters": {
            "cases": strict_filters["cases"],
            "violations": strict_filters["violations"],
        },
        "contradictions": contradictions,
        "empty_states": {
            "cases": empty_states["cases"],
            "failures": empty_states["failures"],
        },
        "grounding_failures": grounding_failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Book Alchemy acceptance targets")
    parser.add_argument("--model", default="small")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate(args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"summary": report["summary"], "checks": report["checks"]}, ensure_ascii=False, indent=2))
    return 0 if all(report["checks"].values()) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
