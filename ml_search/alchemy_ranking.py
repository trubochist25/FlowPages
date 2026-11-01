from __future__ import annotations

import hashlib
import math
import random
import re
import time
from collections import Counter
from collections.abc import Sequence

import numpy as np

from .calibration import (
    ALCHEMY_ANCHOR_CALIBRATION,
    ALCHEMY_QUERY_CALIBRATION,
    SimilarityCalibration,
)
from .embeddings import Embedder
from .index import VectorIndex
from .models import Book
from .schemas import (
    AlchemyIngredient,
    AlchemyNegativeIngredient,
    AlchemyRecommendationResult,
    AlchemyRecommendRequest,
    AlchemyRecommendResponse,
    AlchemyWarning,
    RatingSummary,
)
from .text import normalize_text, tokenize


HARD_EXCLUSION_KINDS = frozenset({"genre", "theme", "mood", "pace"})
GENERIC_THEME_TOKENS = frozenset({"и", "в", "на", "за", "с", "к"})
ANCHOR_QUERY_FILLERS = frozenset(
    {
        "как",
        "но",
        "и",
        "с",
        "со",
        "на",
        "в",
        "по",
        "духе",
        "похожий",
        "похожая",
        "похожее",
        "похоже",
        "похожую",
        "короче",
        "длиннее",
        "больше",
        "меньше",
        "меньшим",
        "количеством",
    }
)
REDUCED_CLAUSE = re.compile(
    r"(?:\bс\s+)?\b(?:меньше|поменьше|меньшим\s+количеством)\b[^,;.]*"
)
NEGATIVE_CLAUSE = re.compile(r"\b(?:без|исключая)\b[^,;.]*")
SPECULATIVE_GENRES = frozenset({"фантастика", "фэнтези", "ужасы"})


class AlchemyRanker:
    """Hybrid, explainable ranking over catalogue embeddings and metadata."""

    def __init__(
        self,
        books: Sequence[Book],
        embedder: Embedder,
        vector_index: VectorIndex,
    ) -> None:
        self.books = tuple(books)
        self.embedder = embedder
        self.vector_index = vector_index
        self._book_by_id = {book.product_id: book for book in books}
        self._index_by_id = {
            int(product_id): index
            for index, product_id in enumerate(vector_index.product_ids)
        }
        self._max_popularity = max((book.popularity for book in books), default=1)
        self._genre_frequency = Counter(
            genre for book in books for genre in book.genres
        )
        self._max_genre_frequency = max(self._genre_frequency.values(), default=1)

    def recommend(self, request: AlchemyRecommendRequest) -> AlchemyRecommendResponse:
        started = time.perf_counter()
        warnings = self._contract_warnings(request)
        strict_candidates = [
            index
            for index, book in enumerate(self.books)
            if self._passes_filters(book, request)
        ]
        anchor_ids = {anchor.product_id for anchor in request.anchors}
        candidates = [
            index
            for index in strict_candidates
            if self.books[index].product_id not in anchor_ids
            and not self._is_hard_excluded(self.books[index], request.negative)
        ]

        if not candidates:
            relaxations = self._relaxation_proposals(
                request,
                had_strict_candidates=bool(strict_candidates),
            )
            warnings.append(
                AlchemyWarning(
                    code="no_candidates",
                    message=(
                        "No catalogue books satisfy every strict filter and exclusion; "
                        "nothing was relaxed automatically."
                    ),
                )
            )
            return AlchemyRecommendResponse(
                total=0,
                relaxations=relaxations,
                warnings=warnings,
                processing_ms=round((time.perf_counter() - started) * 1000, 3),
                state="no_candidates",
            )

        signals = self._semantic_signals(request)
        if request.anchors:
            candidates = self._gate_anchor_candidates(
                request,
                signals,
                candidates,
            )
        anchor_pages = self._weighted_anchor_pages(request)
        rng = random.Random(self._stable_seed(request))
        ranked: list[dict] = []

        for index in candidates:
            book = self.books[index]
            query_semantic = self._value_at(signals["query"], index)
            anchor_semantic, best_anchor_id = self._anchor_score(
                request,
                signals,
                index,
            )
            ingredient_score, matched, unmet = self._ingredient_score(
                book,
                request.positive,
                signals["ingredients"],
                index,
                anchor_pages,
            )
            quality = self._quality_score(
                book,
                request.local_ratings.get(book.product_id),
            )
            avoidance_penalty = self._avoidance_penalty(
                book,
                request.negative,
                signals["negative"],
                index,
                anchor_pages,
            )
            core_score = self._combine_active_signals(
                query_semantic=query_semantic,
                anchor_semantic=anchor_semantic,
                ingredient_score=ingredient_score,
                quality=quality,
                has_query=signals["query"] is not None,
                has_anchors=bool(request.anchors),
                has_ingredients=bool(request.positive),
            )
            core_score = max(0.0, core_score - avoidance_penalty)
            relevance_score = self._combine_relevance_signals(
                query_semantic=query_semantic,
                anchor_semantic=anchor_semantic,
                ingredient_score=ingredient_score,
                has_query=signals["query"] is not None,
                has_anchors=bool(request.anchors),
                has_ingredients=bool(request.positive),
            )
            relevance_score = max(0.0, relevance_score - avoidance_penalty)
            novelty = self._genre_rarity(book)
            adventure = 0.68 * novelty + 0.32 * rng.random()
            exploration_weight = 0.18 * request.surprise
            final_score = (
                (1.0 - exploration_weight) * core_score
                + exploration_weight * adventure
            )
            ranked.append(
                {
                    "index": index,
                    "book": book,
                    "score": max(0.0, min(1.0, final_score)),
                    "relevance": max(0.0, min(1.0, relevance_score)),
                    "core": core_score,
                    "query": query_semantic,
                    "anchor": anchor_semantic,
                    "ingredient": ingredient_score,
                    "quality": quality,
                    "avoidance": avoidance_penalty,
                    "novelty": novelty,
                    "matched": matched,
                    "unmet": unmet,
                    "best_anchor_id": best_anchor_id,
                    "anchor_genre_affinity": self._anchor_genre_affinity(
                        book,
                        request,
                    ),
                }
            )

        ranked.sort(
            key=lambda item: (item["score"], item["quality"], -item["book"].product_id),
            reverse=True,
        )
        pool_size = min(len(ranked), max(80, request.limit * 12))
        selected = self._diversify(
            ranked[:pool_size],
            request.limit,
            request.surprise,
        )
        results = [self._result(item, request) for item in selected]
        relaxations: list[str] = []
        if len(candidates) < request.limit:
            relaxations.append(
                "Ослабьте строгие фильтры, чтобы получить больше вариантов"
            )

        return AlchemyRecommendResponse(
            total=len(candidates),
            results=results,
            relaxations=relaxations,
            warnings=warnings,
            processing_ms=round((time.perf_counter() - started) * 1000, 3),
            state="partial" if len(results) < request.limit else "results",
        )

    def _semantic_signals(self, request: AlchemyRecommendRequest) -> dict:
        texts: list[str] = []
        query_position: int | None = None
        ingredient_positions: list[int] = []
        negative_positions: list[int] = []
        aspect_positions: dict[int, int] = {}

        semantic_query = self._semantic_query_text(request)
        if semantic_query:
            query_position = len(texts)
            texts.append(semantic_query)
        for ingredient in request.positive:
            ingredient_positions.append(len(texts))
            texts.append(ingredient.value)
        for ingredient in request.negative:
            negative_positions.append(len(texts))
            texts.append(ingredient.value)
        for anchor in request.anchors:
            if anchor.aspects:
                aspect_positions[anchor.product_id] = len(texts)
                texts.append("; ".join(anchor.aspects))

        encoded = (
            self.embedder.encode_queries(texts)
            if texts
            else np.empty((0, self.vector_index.vectors.shape[1]), dtype=np.float32)
        )

        def similarities(position: int) -> np.ndarray:
            raw = self.vector_index.similarities(encoded[position])
            return self._calibrate_similarities(
                raw,
                ALCHEMY_QUERY_CALIBRATION,
            )

        query_scores = (
            similarities(query_position) if query_position is not None else None
        )
        ingredient_scores = [similarities(position) for position in ingredient_positions]
        negative_scores = [similarities(position) for position in negative_positions]
        aspect_scores = {
            product_id: similarities(position)
            for product_id, position in aspect_positions.items()
        }
        anchor_scores = {}
        for anchor in request.anchors:
            raw = self.vector_index.similarities(
                self.vector_index.vectors[self._index_by_id[anchor.product_id]]
            )
            anchor_scores[anchor.product_id] = self._calibrate_similarities(
                raw,
                ALCHEMY_ANCHOR_CALIBRATION,
            )
        return {
            "query": query_scores,
            "ingredients": ingredient_scores,
            "negative": negative_scores,
            "aspects": aspect_scores,
            "anchors": anchor_scores,
        }

    def _semantic_query_text(self, request: AlchemyRecommendRequest) -> str:
        if request.residual_query is not None:
            return normalize_text(request.residual_query)

        query = normalize_text(request.query)
        if not query or not request.anchors:
            return query

        query = REDUCED_CLAUSE.sub(" ", query)
        query = NEGATIVE_CLAUSE.sub(" ", query)
        for anchor in request.anchors:
            book = self._book_by_id[anchor.product_id]
            aliases = (book.title, book.source_title)
            for alias in aliases:
                normalized = normalize_text(alias)
                if normalized:
                    query = re.sub(
                        rf"(?<![а-яa-z]){re.escape(normalized)}(?![а-яa-z])",
                        " ",
                        query,
                    )

        meaningful = [
            token
            for token in tokenize(query)
            if token not in ANCHOR_QUERY_FILLERS and len(token) > 2
        ]
        return " ".join(meaningful)

    @staticmethod
    def _calibrate_similarities(
        values: np.ndarray,
        calibration: SimilarityCalibration = ALCHEMY_QUERY_CALIBRATION,
    ) -> np.ndarray:
        return calibration.apply(values)

    def _gate_anchor_candidates(
        self,
        request: AlchemyRecommendRequest,
        signals: dict,
        candidates: list[int],
    ) -> list[int]:
        if not candidates:
            return candidates
        scored = [
            (
                self._anchor_score(request, signals, index)[0],
                self._anchor_genre_affinity(self.books[index], request),
                index,
            )
            for index in candidates
        ]
        threshold = max(0.06, 0.34 - 0.28 * request.surprise)
        cross_genre_extra = max(0.08, 0.18 - 0.10 * request.surprise)
        relevant = [
            index
            for score, affinity, index in scored
            if score >= threshold + cross_genre_extra * (1.0 - affinity)
        ]
        if len(relevant) >= request.limit:
            return relevant
        scored.sort(
            key=lambda item: (
                item[0] + 0.10 * item[1],
                -self.books[item[2]].product_id,
            ),
            reverse=True,
        )
        return [index for _, _, index in scored[: request.limit]]

    def _anchor_genre_affinity(
        self,
        book: Book,
        request: AlchemyRecommendRequest,
    ) -> float:
        candidate = {normalize_text(value) for value in book.genres if value}
        best = 0.0
        for anchor in request.anchors:
            anchor_book = self._book_by_id[anchor.product_id]
            expected = {
                normalize_text(value) for value in anchor_book.genres if value
            }
            primary = (
                normalize_text(anchor_book.genres[0])
                if anchor_book.genres
                else ""
            )
            if primary and primary in candidate:
                best = max(best, 1.0)
            elif candidate & SPECULATIVE_GENRES and expected & SPECULATIVE_GENRES:
                best = max(best, 0.6)
            elif candidate & expected:
                best = max(best, 0.25)
        return best

    @staticmethod
    def _value_at(values: np.ndarray | None, index: int) -> float:
        return float(values[index]) if values is not None else 0.0

    def _anchor_score(
        self,
        request: AlchemyRecommendRequest,
        signals: dict,
        index: int,
    ) -> tuple[float, int | None]:
        if not request.anchors:
            return 0.0, None
        weighted = 0.0
        total_weight = 0.0
        best_value = -1.0
        best_anchor_id: int | None = None
        for anchor in request.anchors:
            score = float(signals["anchors"][anchor.product_id][index])
            anchor_book = self._book_by_id[anchor.product_id]
            metadata = self._anchor_metadata_similarity(
                self.books[index],
                anchor_book,
            )
            score = 0.80 * score + 0.20 * metadata
            aspects = signals["aspects"].get(anchor.product_id)
            if aspects is not None:
                score = 0.78 * score + 0.22 * float(aspects[index])
            weighted += score * anchor.weight
            total_weight += anchor.weight
            if score > best_value:
                best_value = score
                best_anchor_id = anchor.product_id
        return weighted / total_weight, best_anchor_id

    @staticmethod
    def _anchor_metadata_similarity(book: Book, anchor: Book) -> float:
        def coverage(values: Sequence[str], anchor_values: Sequence[str]) -> float:
            expected = {normalize_text(value) for value in anchor_values if value}
            if not expected:
                return 0.0
            actual = {normalize_text(value) for value in values if value}
            return len(actual & expected) / len(expected)

        return (
            0.45 * coverage(book.genres, anchor.genres)
            + 0.30 * coverage(book.themes, anchor.themes)
            + 0.20 * coverage(book.moods, anchor.moods)
            + 0.05 * (normalize_text(book.pace) == normalize_text(anchor.pace))
        )

    def _ingredient_score(
        self,
        book: Book,
        ingredients: Sequence[AlchemyIngredient],
        semantic_scores: Sequence[np.ndarray],
        index: int,
        anchor_pages: float | None,
    ) -> tuple[float, list[str], list[str]]:
        if not ingredients:
            return 0.0, [], []
        weighted = 0.0
        total_weight = 0.0
        matched: list[str] = []
        unmet: list[str] = []
        for ingredient, scores in zip(ingredients, semantic_scores):
            semantic = float(scores[index])
            support = self._ingredient_support(
                book,
                ingredient,
                semantic,
                anchor_pages,
            )
            weighted += support * ingredient.weight
            total_weight += ingredient.weight
            if support >= 0.72:
                matched.append(ingredient.value)
            elif support < 0.42:
                unmet.append(ingredient.value)
        return weighted / total_weight, matched[:8], unmet[:8]

    def _ingredient_support(
        self,
        book: Book,
        ingredient: AlchemyIngredient,
        semantic: float,
        anchor_pages: float | None,
    ) -> float:
        value = normalize_text(ingredient.value)
        semantic_support = max(0.0, min(1.0, (semantic - 0.55) / 0.35))
        if ingredient.kind == "genre":
            exact = self._exact_in(value, book.genres)
            return 1.0 if exact else 0.25 * semantic_support
        if ingredient.kind == "theme":
            metadata = self._theme_support(value, book.themes)
            return max(metadata, 0.45 * semantic_support)
        if ingredient.kind == "mood":
            exact = self._exact_in(value, book.moods)
            return 1.0 if exact else 0.35 * semantic_support
        if ingredient.kind == "pace":
            return 1.0 if value == normalize_text(book.pace) else 0.15 * semantic_support
        if ingredient.kind == "style":
            if "короч" in value and anchor_pages:
                ratio = book.pages / max(1.0, anchor_pages)
                return max(0.0, min(1.0, (1.15 - ratio) / 0.45))
            if "корот" in value:
                return max(0.0, min(1.0, (420.0 - book.pages) / 220.0))
            if "эпич" in value or "масштаб" in value:
                return max(0.0, min(1.0, (book.pages - 280.0) / 360.0))
            return semantic_support
        if ingredient.kind == "content":
            return 1.0 if self._lexical_value_present(value, book) else 0.35 * semantic_support
        if ingredient.kind == "audience":
            return self._audience_support(value, book)
        return semantic_support

    def _avoidance_penalty(
        self,
        book: Book,
        ingredients: Sequence[AlchemyNegativeIngredient],
        semantic_scores: Sequence[np.ndarray],
        index: int,
        anchor_pages: float | None,
    ) -> float:
        penalty = 0.0
        for ingredient, scores in zip(ingredients, semantic_scores):
            if ingredient.mode == "exclude" and ingredient.kind in HARD_EXCLUSION_KINDS:
                continue
            support = self._ingredient_support(
                book,
                ingredient,
                semantic=float(scores[index]),
                anchor_pages=anchor_pages,
            )
            penalty += 0.24 * ingredient.weight * support
        return min(0.5, penalty)

    def _is_hard_excluded(
        self,
        book: Book,
        ingredients: Sequence[AlchemyNegativeIngredient],
    ) -> bool:
        for ingredient in ingredients:
            if ingredient.mode != "exclude" or ingredient.kind not in HARD_EXCLUSION_KINDS:
                continue
            support = self._ingredient_support(book, ingredient, 0.5, None)
            threshold = 0.34 if ingredient.kind == "theme" else 0.6
            if support >= threshold:
                return True
        return False

    def _passes_filters(self, book: Book, request: AlchemyRecommendRequest) -> bool:
        filters = request.filters
        if filters.in_stock and book.quantity <= 0:
            return False
        if filters.price_min is not None and book.price < filters.price_min:
            return False
        if filters.price_max is not None and book.price > filters.price_max:
            return False
        if filters.pages_min is not None and book.pages < filters.pages_min:
            return False
        if filters.pages_max is not None and book.pages > filters.pages_max:
            return False
        if filters.year_min is not None and book.year < filters.year_min:
            return False
        if filters.year_max is not None and book.year > filters.year_max:
            return False
        if filters.authors and not self._exact_in(book.author, filters.authors):
            return False
        if filters.genres and not self._sets_intersect(book.genres, filters.genres):
            return False
        if filters.moods and not self._sets_intersect(book.moods, filters.moods):
            return False
        if filters.paces and not self._exact_in(book.pace, filters.paces):
            return False
        if filters.age_ratings and not self._exact_in(
            book.age_rating, filters.age_ratings
        ):
            return False
        return True

    @staticmethod
    def _combine_active_signals(
        *,
        query_semantic: float,
        anchor_semantic: float,
        ingredient_score: float,
        quality: float,
        has_query: bool,
        has_anchors: bool,
        has_ingredients: bool,
    ) -> float:
        components = [(quality, 0.05)]
        if has_anchors:
            components.append((anchor_semantic, 0.55))
            if has_query:
                components.append((query_semantic, 0.20))
            if has_ingredients:
                components.append((ingredient_score, 0.20))
            total_weight = sum(weight for _, weight in components)
            return sum(value * weight for value, weight in components) / total_weight
        if has_query:
            components.append((query_semantic, 0.45))
        if has_ingredients:
            components.append((ingredient_score, 0.20))
        total_weight = sum(weight for _, weight in components)
        return sum(value * weight for value, weight in components) / total_weight

    @staticmethod
    def _combine_relevance_signals(
        *,
        query_semantic: float,
        anchor_semantic: float,
        ingredient_score: float,
        has_query: bool,
        has_anchors: bool,
        has_ingredients: bool,
    ) -> float:
        components: list[tuple[float, float]] = []
        if has_anchors:
            components.append((anchor_semantic, 0.55))
        if has_query:
            components.append((query_semantic, 0.20 if has_anchors else 0.45))
        if has_ingredients:
            components.append((ingredient_score, 0.20))
        if not components:
            return 0.0
        total_weight = sum(weight for _, weight in components)
        return sum(value * weight for value, weight in components) / total_weight

    def _quality_score(self, book: Book, local: RatingSummary | None) -> float:
        external = max(0.0, min(1.0, book.rating / 5.0))
        if local and local.count > 0:
            local_score = max(0.0, min(1.0, local.value / 5.0))
            local_weight = local.count / (local.count + 20.0)
            rating = (1.0 - local_weight) * external + local_weight * local_score
        else:
            rating = external
        popularity = math.log1p(book.popularity) / math.log1p(self._max_popularity)
        return 0.58 * rating + 0.42 * popularity

    def _genre_rarity(self, book: Book) -> float:
        if not book.genres:
            return 0.5
        return sum(
            1.0
            - math.log1p(self._genre_frequency.get(genre, 0))
            / math.log1p(self._max_genre_frequency)
            for genre in book.genres
        ) / len(book.genres)

    def _diversify(
        self,
        candidates: list[dict],
        limit: int,
        surprise: float,
    ) -> list[dict]:
        selected: list[dict] = []
        remaining = list(candidates)
        diversity = 0.07 + 0.21 * surprise
        while remaining and len(selected) < limit:
            best_position = 0
            best_value = -float("inf")
            for position, candidate in enumerate(remaining):
                similarity = 0.0
                if selected:
                    vector = self.vector_index.vectors[candidate["index"]]
                    similarity = max(
                        max(
                            0.0,
                            min(
                                1.0,
                                (
                                    float(
                                        vector
                                        @ self.vector_index.vectors[item["index"]]
                                    )
                                    + 1.0
                                )
                                / 2.0,
                            ),
                        )
                        for item in selected
                    )
                same_author = any(
                    item["book"].author == candidate["book"].author
                    for item in selected
                )
                same_series = bool(candidate["book"].series) and any(
                    item["book"].series == candidate["book"].series
                    for item in selected
                )
                selection_value = (
                    candidate["score"]
                    - diversity * 0.34 * similarity
                    - (0.04 + 0.05 * surprise if same_author else 0.0)
                    - (0.03 + 0.04 * surprise if same_series else 0.0)
                )
                if selection_value > best_value:
                    best_value = selection_value
                    best_position = position
            selected.append(remaining.pop(best_position))
        return selected

    def _result(
        self,
        item: dict,
        request: AlchemyRecommendRequest,
    ) -> AlchemyRecommendationResult:
        reasons: list[str] = []
        if item["matched"]:
            reasons.append(f"совпадает: {', '.join(item['matched'][:2])}")
        if item["anchor"] >= 0.62 and item["best_anchor_id"] is not None:
            anchor = self._book_by_id[item["best_anchor_id"]]
            reasons.append(f"по духу близка к «{anchor.title}»")
        if item["query"] >= 0.58:
            reasons.append("близка свободному описанию")
        if request.surprise >= 0.65 and item["novelty"] >= 0.55:
            reasons.append("неочевидный выбор из более редкого жанра")
        if item["quality"] >= 0.72:
            reasons.append("сильные оценки и читательский интерес")
        if not reasons:
            reasons.append("лучший баланс оставшихся пожеланий")

        matched_ratio = (
            len(item["matched"])
            / max(1, len(request.positive))
        )
        band = "balanced"
        if request.anchors and item["anchor_genre_affinity"] < 0.35:
            band = "bold"
        elif request.surprise >= 0.65 and item["novelty"] >= 0.45:
            band = "bold"
        elif (
            (request.positive and matched_ratio >= 0.6 and item["core"] >= 0.70)
            or (request.anchors and item["anchor"] >= 0.72 and item["core"] >= 0.68)
            or (
                not request.positive
                and not request.anchors
                and item["query"] >= 0.82
            )
        ):
            band = "close"
        elif item["core"] < 0.32:
            band = "bold"

        breakdown = None
        if request.include_debug:
            breakdown = {
                "query_semantic": round(float(item["query"]), 6),
                "anchor_similarity": round(float(item["anchor"]), 6),
                "ingredient_match": round(float(item["ingredient"]), 6),
                "quality": round(float(item["quality"]), 6),
                "avoidance_penalty": round(float(item["avoidance"]), 6),
                "novelty": round(float(item["novelty"]), 6),
                "core": round(float(item["core"]), 6),
                "relevance": round(float(item["relevance"]), 6),
                "total": round(float(item["score"]), 6),
            }
        return AlchemyRecommendationResult(
            product_id=item["book"].product_id,
            score=round(float(item["score"]), 6),
            relevance_score=round(float(item["relevance"]), 6),
            band=band,
            matched=item["matched"],
            unmet=item["unmet"],
            reasons=[reason[:120] for reason in reasons[:4]],
            score_breakdown=breakdown,
        )

    def _contract_warnings(
        self, request: AlchemyRecommendRequest
    ) -> list[AlchemyWarning]:
        unsupported = sorted(
            {
                ingredient.kind
                for ingredient in request.negative
                if ingredient.mode == "exclude"
                and ingredient.kind not in HARD_EXCLUSION_KINDS
            }
        )
        if not unsupported:
            return []
        return [
            AlchemyWarning(
                code="hard_exclusion_downgraded",
                message=(
                    "Hard exclusion is not backed by structured catalogue data for: "
                    f"{', '.join(unsupported)}; avoid penalties were used instead."
                ),
            )
        ]

    def _relaxation_proposals(
        self,
        request: AlchemyRecommendRequest,
        had_strict_candidates: bool,
    ) -> list[str]:
        proposals: list[str] = []
        filters = request.filters
        if not had_strict_candidates:
            if filters.price_min is not None or filters.price_max is not None:
                proposals.append("Расширить диапазон цены")
            if filters.pages_min is not None or filters.pages_max is not None:
                proposals.append("Расширить допустимый объём книги")
            if filters.year_min is not None or filters.year_max is not None:
                proposals.append("Расширить диапазон годов издания")
            if filters.authors or filters.genres or filters.moods or filters.paces:
                proposals.append("Убрать один из строгих фильтров каталога")
            if filters.age_ratings:
                proposals.append("Выбрать дополнительные возрастные рейтинги")
            if filters.in_stock and any(book.quantity <= 0 for book in self.books):
                proposals.append("Показать также книги не в наличии")
        if any(
            item.mode == "exclude" and item.kind in HARD_EXCLUSION_KINDS
            for item in request.negative
        ):
            proposals.append("Заменить строгое исключение на мягкое избегание")
        if not proposals:
            proposals.append("Упростить рецепт или добавить другое настроение")
        return proposals[:4]

    def _weighted_anchor_pages(self, request: AlchemyRecommendRequest) -> float | None:
        if not request.anchors:
            return None
        total_weight = sum(anchor.weight for anchor in request.anchors)
        return sum(
            self._book_by_id[anchor.product_id].pages * anchor.weight
            for anchor in request.anchors
        ) / total_weight

    @staticmethod
    def _exact_in(value: str, candidates: Sequence[str]) -> bool:
        normalized = normalize_text(value)
        return normalized in {normalize_text(candidate) for candidate in candidates}

    @staticmethod
    def _sets_intersect(left: Sequence[str], right: Sequence[str]) -> bool:
        return bool(
            {normalize_text(value) for value in left}
            & {normalize_text(value) for value in right}
        )

    @staticmethod
    def _theme_support(value: str, themes: Sequence[str]) -> float:
        value_tokens = {
            AlchemyRanker._theme_token_key(token)
            for token in tokenize(value)
            if token not in GENERIC_THEME_TOKENS
        }
        best = 0.0
        for theme in themes:
            normalized = normalize_text(theme)
            if normalized == value:
                return 1.0
            theme_tokens = {
                AlchemyRanker._theme_token_key(token)
                for token in tokenize(normalized)
                if token not in GENERIC_THEME_TOKENS
            }
            if value_tokens and theme_tokens:
                overlap = len(value_tokens & theme_tokens) / len(value_tokens)
                best = max(best, 0.72 * overlap)
        return best

    @staticmethod
    def _theme_token_key(value: str) -> str:
        if len(value) < 5:
            return value
        return value[: min(6, len(value) - 1)]

    @staticmethod
    def _lexical_value_present(value: str, book: Book) -> bool:
        probes = {value}
        for token in tokenize(value):
            if len(token) >= 6:
                probes.add(token[: max(5, len(token) - 3)])
        return any(probe in book.searchable_norm for probe in probes if len(probe) >= 4)

    @staticmethod
    def _audience_support(value: str, book: Book) -> float:
        digits = "".join(character for character in book.age_rating if character.isdigit())
        age = int(digits or 0)
        if "подрост" in value:
            return 1.0 if "Подростковая литература" in book.genres else (0.75 if age <= 16 else 0.0)
        if "дет" in value or "ребен" in value:
            return 1.0 if "Детская литература" in book.genres else (0.7 if age <= 12 else 0.0)
        if "взросл" in value:
            return 1.0 if age >= 16 else 0.2
        return 0.0

    @staticmethod
    def _stable_seed(request: AlchemyRecommendRequest) -> int:
        if request.random_seed is not None:
            return request.random_seed
        payload = request.model_dump_json(exclude={"include_debug"})
        digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "little")


__all__ = ["AlchemyRanker"]
