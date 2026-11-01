from __future__ import annotations

import math
import random
import time
from collections import Counter, defaultdict

import numpy as np

from .index import VectorIndex
from .models import Book
from .schemas import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendationResult,
    RecommendationSignal,
)


SIGNAL_WEIGHTS = {
    "view": 1.0,
    "wishlist": 2.4,
    "cart": 3.2,
    "purchase": 4.0,
}

SIGNAL_HALF_LIFE_DAYS = {
    "view": 30.0,
    "wishlist": 90.0,
    "cart": 14.0,
    "purchase": 180.0,
}


class RecommendationEngine:
    """Content-based recommendations over the existing catalogue vectors."""

    def __init__(self, books: list[Book], vector_index: VectorIndex) -> None:
        self.books = books
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
        self._max_genre_frequency = max(
            self._genre_frequency.values(), default=1
        )

    def recommend(self, request: RecommendationRequest) -> RecommendationResponse:
        started = time.perf_counter()
        if request.strategy == "similar":
            return self._similar(request, started)

        signals = [
            signal
            for signal in request.signals
            if signal.product_id in self._index_by_id
        ]
        if not signals:
            return self._cold_start(request, started)

        weighted_seeds = self._weighted_seeds(signals)
        profile = self._profile_vector(weighted_seeds)
        profile_similarities = self.vector_index.similarities(profile)
        seed_indices = np.asarray(
            [self._index_by_id[product_id] for product_id in weighted_seeds],
            dtype=np.int32,
        )
        seed_vectors = self.vector_index.vectors[seed_indices]
        best_seed_similarities = np.max(
            self.vector_index.vectors @ seed_vectors.T,
            axis=1,
        )

        viewed = {
            signal.product_id for signal in signals if signal.kind == "view"
        }
        excluded = {
            signal.product_id
            for signal in signals
            if signal.kind in {"wishlist", "cart", "purchase"}
        }
        preferences = self._metadata_preferences(weighted_seeds)
        rng = random.Random(request.random_seed)
        is_explore = request.strategy == "explore"
        candidates: list[dict] = []
        for index, book in enumerate(self.books):
            if book.product_id in excluded:
                continue

            semantic = self._unit_score(float(profile_similarities[index]))
            nearest_seed = self._unit_score(float(best_seed_similarities[index]))
            metadata = self._metadata_score(book, preferences)
            popularity = math.log1p(book.popularity) / math.log1p(
                self._max_popularity
            )
            rating = self._rating_score(book)
            genre_novelty = self._genre_novelty(book, preferences)
            random_component = rng.random()
            revisit_penalty = (
                0.12 if is_explore else 0.14
            ) if book.product_id in viewed else 0.0
            if is_explore:
                score = (
                    0.48 * semantic
                    + 0.10 * nearest_seed
                    + 0.08 * metadata
                    + 0.14 * genre_novelty
                    + 0.08 * popularity
                    + 0.07 * rating
                    + 0.05 * random_component
                    - revisit_penalty
                )
            else:
                score = (
                    0.70 * semantic
                    + 0.14 * nearest_seed
                    + 0.09 * metadata
                    + 0.04 * popularity
                    + 0.03 * rating
                    - revisit_penalty
                )
            candidates.append(
                {
                    "index": index,
                    "book": book,
                    "score": score,
                    "semantic": semantic,
                    "nearest_seed": nearest_seed,
                    "metadata": metadata,
                    "popularity": popularity,
                    "rating": rating,
                    "genre_novelty": genre_novelty,
                    "random": random_component,
                    "already_viewed": book.product_id in viewed,
                }
            )

        pool_size = min(
            len(candidates),
            max(120, request.limit * 12) if is_explore else max(80, request.limit * 8),
        )
        candidates.sort(key=lambda item: item["score"], reverse=True)
        selected = self._diversify(
            candidates[:pool_size],
            request.limit,
            diversity_weight=0.32 if is_explore else 0.18,
        )
        results = [
            RecommendationResult(
                product_id=item["book"].product_id,
                score=round(float(item["score"]), 6),
                reasons=(
                    self._explore_reasons(item["book"], weighted_seeds)
                    if is_explore
                    else self._reasons(item["book"], weighted_seeds)
                ),
                already_viewed=bool(item["already_viewed"]),
                score_breakdown=(
                    {
                        "semantic": round(float(item["semantic"]), 6),
                        "nearest_seed": round(float(item["nearest_seed"]), 6),
                        "metadata": round(float(item["metadata"]), 6),
                        "popularity": round(float(item["popularity"]), 6),
                        "rating": round(float(item["rating"]), 6),
                        **(
                            {
                                "genre_novelty": round(
                                    float(item["genre_novelty"]), 6
                                ),
                                "random": round(float(item["random"]), 6),
                            }
                            if is_explore
                            else {}
                        ),
                    }
                    if request.include_debug
                    else None
                ),
            )
            for item in selected
        ]
        return RecommendationResponse(
            results=results,
            signals_used=len(signals),
            processing_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def _similar(
        self, request: RecommendationRequest, started: float
    ) -> RecommendationResponse:
        anchor_product_id = request.anchor_product_id
        if anchor_product_id not in self._index_by_id:
            return RecommendationResponse(
                results=[],
                signals_used=0,
                processing_ms=round((time.perf_counter() - started) * 1000, 3),
            )

        anchor_index = self._index_by_id[anchor_product_id]
        anchor_vector = self.vector_index.vectors[anchor_index]
        similarities = self.vector_index.similarities(anchor_vector)
        weighted_seed = {anchor_product_id: 1.0}
        preferences = self._metadata_preferences(weighted_seed)
        rng = random.Random(request.random_seed)
        candidates: list[dict] = []

        for index, book in enumerate(self.books):
            if book.product_id == anchor_product_id:
                continue

            semantic = self._unit_score(float(similarities[index]))
            metadata = self._metadata_score(book, preferences)
            popularity = math.log1p(book.popularity) / math.log1p(
                self._max_popularity
            )
            rating = self._rating_score(book)
            random_component = rng.random()
            score = (
                0.76 * semantic
                + 0.12 * metadata
                + 0.05 * popularity
                + 0.04 * rating
                + 0.03 * random_component
            )
            candidates.append(
                {
                    "index": index,
                    "book": book,
                    "score": score,
                    "semantic": semantic,
                    "metadata": metadata,
                    "popularity": popularity,
                    "rating": rating,
                    "random": random_component,
                    "already_viewed": False,
                }
            )

        pool_size = min(len(candidates), max(64, request.limit * 8))
        candidates.sort(key=lambda item: item["score"], reverse=True)
        selected = self._diversify(
            candidates[:pool_size],
            request.limit,
            diversity_weight=0.14,
        )
        results = [
            RecommendationResult(
                product_id=item["book"].product_id,
                score=round(float(item["score"]), 6),
                reasons=self._reasons(item["book"], weighted_seed),
                score_breakdown=(
                    {
                        "semantic": round(float(item["semantic"]), 6),
                        "metadata": round(float(item["metadata"]), 6),
                        "popularity": round(float(item["popularity"]), 6),
                        "rating": round(float(item["rating"]), 6),
                        "random": round(float(item["random"]), 6),
                    }
                    if request.include_debug
                    else None
                ),
            )
            for item in selected
        ]
        return RecommendationResponse(
            results=results,
            signals_used=0,
            processing_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def _cold_start(
        self, request: RecommendationRequest, started: float
    ) -> RecommendationResponse:
        rng = random.Random(request.random_seed)
        is_explore = request.strategy == "explore"
        candidates: list[dict] = []
        for index, book in enumerate(self.books):
            popularity = math.log1p(book.popularity) / math.log1p(
                self._max_popularity
            )
            rating = self._rating_score(book)
            genre_novelty = self._genre_rarity(book)
            random_component = rng.random()
            if is_explore:
                score = (
                    0.47 * popularity
                    + 0.28 * rating
                    + 0.17 * genre_novelty
                    + 0.08 * random_component
                )
            else:
                score = (
                    0.62 * popularity
                    + 0.33 * rating
                    + 0.05 * random_component
                )
            candidates.append(
                {
                    "index": index,
                    "book": book,
                    "score": score,
                    "semantic": 0.0,
                    "nearest_seed": 0.0,
                    "metadata": 0.0,
                    "popularity": popularity,
                    "rating": rating,
                    "genre_novelty": genre_novelty,
                    "random": random_component,
                    "already_viewed": False,
                }
            )

        pool_size = min(
            len(candidates),
            max(120, request.limit * 12) if is_explore else max(80, request.limit * 8),
        )
        candidates.sort(key=lambda item: item["score"], reverse=True)
        selected = self._diversify(
            candidates[:pool_size],
            request.limit,
            diversity_weight=0.30 if is_explore else 0.08,
        )
        results = [
            RecommendationResult(
                product_id=item["book"].product_id,
                score=round(float(item["score"]), 6),
                reasons=[self._cold_start_reason(item, is_explore)],
                score_breakdown=(
                    {
                        "popularity": round(float(item["popularity"]), 6),
                        "rating": round(float(item["rating"]), 6),
                        **(
                            {
                                "genre_novelty": round(
                                    float(item["genre_novelty"]), 6
                                )
                            }
                            if is_explore
                            else {}
                        ),
                        "random": round(float(item["random"]), 6),
                    }
                    if request.include_debug
                    else None
                ),
            )
            for item in selected
        ]
        return RecommendationResponse(
            results=results,
            signals_used=0,
            processing_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def _weighted_seeds(
        self, signals: list[RecommendationSignal]
    ) -> dict[int, float]:
        weights: defaultdict[int, float] = defaultdict(float)
        for signal in signals:
            recency = 0.5 ** (
                signal.age_days / SIGNAL_HALF_LIFE_DAYS[signal.kind]
            )
            frequency = 1.0 + 0.30 * math.log1p(max(0.0, signal.strength - 1.0))
            weights[signal.product_id] += (
                SIGNAL_WEIGHTS[signal.kind] * recency * frequency
            )
        return dict(weights)

    def _profile_vector(self, weighted_seeds: dict[int, float]) -> np.ndarray:
        profile = np.zeros(self.vector_index.vectors.shape[1], dtype=np.float32)
        for product_id, weight in weighted_seeds.items():
            profile += self.vector_index.vectors[self._index_by_id[product_id]] * weight
        norm = float(np.linalg.norm(profile))
        if norm:
            profile /= norm
        return profile

    def _metadata_preferences(
        self, weighted_seeds: dict[int, float]
    ) -> dict[str, dict[str, float]]:
        preferences: dict[str, defaultdict[str, float]] = {
            "genres": defaultdict(float),
            "themes": defaultdict(float),
            "moods": defaultdict(float),
            "paces": defaultdict(float),
        }
        for product_id, weight in weighted_seeds.items():
            book = self._book_by_id[product_id]
            for value in book.genres:
                preferences["genres"][value] += weight
            for value in book.themes:
                preferences["themes"][value] += weight
            for value in book.moods:
                preferences["moods"][value] += weight
            if book.pace:
                preferences["paces"][book.pace] += weight
        return {key: dict(values) for key, values in preferences.items()}

    @staticmethod
    def _metadata_score(
        book: Book, preferences: dict[str, dict[str, float]]
    ) -> float:
        components = (
            (book.genres, preferences["genres"], 0.40),
            (book.themes, preferences["themes"], 0.30),
            (book.moods, preferences["moods"], 0.20),
            ((book.pace,), preferences["paces"], 0.10),
        )
        score = 0.0
        for values, preferred, component_weight in components:
            maximum = max(preferred.values(), default=0.0)
            matched = max((preferred.get(value, 0.0) for value in values), default=0.0)
            if maximum:
                score += component_weight * matched / maximum
        return min(1.0, score)

    def _genre_novelty(
        self, book: Book, preferences: dict[str, dict[str, float]]
    ) -> float:
        if not book.genres:
            return 0.0
        known_genres = preferences["genres"]
        novelty = [
            self._genre_rarity_value(genre)
            if genre not in known_genres
            else 0.0
            for genre in book.genres
        ]
        return sum(novelty) / len(novelty)

    def _genre_rarity(self, book: Book) -> float:
        if not book.genres:
            return 0.0
        return sum(
            self._genre_rarity_value(genre) for genre in book.genres
        ) / len(book.genres)

    def _genre_rarity_value(self, genre: str) -> float:
        frequency = self._genre_frequency.get(genre, 0)
        return 1.0 - math.log1p(frequency) / math.log1p(
            self._max_genre_frequency
        )

    def _diversify(
        self,
        candidates: list[dict],
        limit: int,
        diversity_weight: float = 0.18,
    ) -> list[dict]:
        selected: list[dict] = []
        remaining = list(candidates)
        revisit_limit = max(1, limit // 10)
        revisits = 0

        while remaining and len(selected) < limit:
            best_position = None
            best_value = -float("inf")
            for position, candidate in enumerate(remaining):
                if candidate["already_viewed"]:
                    if len(selected) < min(4, limit) or revisits >= revisit_limit:
                        continue

                diversity_similarity = 0.0
                if selected:
                    vector = self.vector_index.vectors[candidate["index"]]
                    diversity_similarity = max(
                        self._unit_score(
                            float(
                                vector
                                @ self.vector_index.vectors[item["index"]]
                            )
                        )
                        for item in selected
                    )
                author_penalty = (
                    0.06
                    if any(
                        item["book"].author == candidate["book"].author
                        for item in selected
                    )
                    else 0.0
                )
                series_penalty = (
                    0.05
                    if candidate["book"].series
                    and any(
                        item["book"].series == candidate["book"].series
                        for item in selected
                    )
                    else 0.0
                )
                value = (
                    (1.0 - diversity_weight) * candidate["score"]
                    - diversity_weight * diversity_similarity
                    - author_penalty
                    - series_penalty
                )
                if value > best_value:
                    best_value = value
                    best_position = position

            if best_position is None:
                break
            chosen = remaining.pop(best_position)
            selected.append(chosen)
            if chosen["already_viewed"]:
                revisits += 1
        return selected

    @staticmethod
    def _cold_start_reason(candidate: dict, is_explore: bool = False) -> str:
        if is_explore and candidate.get("genre_novelty", 0.0) >= 0.25:
            return "Необычный жанровый выбор"
        if candidate["rating"] >= candidate["popularity"]:
            return "Высоко оценено читателями"
        return "Популярно среди читателей"

    def _reasons(
        self, book: Book, weighted_seeds: dict[int, float]
    ) -> list[str]:
        seeds = [self._book_by_id[product_id] for product_id in weighted_seeds]
        if book.series and any(seed.series == book.series for seed in seeds):
            return ["Продолжает знакомую вам серию"]
        if any(seed.author == book.author for seed in seeds):
            return ["Автор уже встречался в вашей истории"]
        seed_genres = {genre for seed in seeds for genre in seed.genres}
        shared_genres = [genre for genre in book.genres if genre in seed_genres]
        if shared_genres:
            return [f"Соответствует интересу: {shared_genres[0]}"]
        return ["Похоже на книги из вашей истории"]

    def _explore_reasons(
        self, book: Book, weighted_seeds: dict[int, float]
    ) -> list[str]:
        seeds = [self._book_by_id[product_id] for product_id in weighted_seeds]
        seed_genres = {genre for seed in seeds for genre in seed.genres}
        new_genres = [genre for genre in book.genres if genre not in seed_genres]
        if new_genres:
            return [f"Новый жанр для вас: {new_genres[0]}"]
        return ["Расширяет привычный выбор"]

    @staticmethod
    def _rating_score(book: Book) -> float:
        confidence = book.rating_count / (book.rating_count + 50.0)
        return max(0.0, min(1.0, book.rating / 5.0 * confidence))

    @staticmethod
    def _unit_score(cosine: float) -> float:
        return max(0.0, min(1.0, (cosine + 1.0) / 2.0))
