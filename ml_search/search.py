from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from .alchemy import AlchemyService
from .catalog import file_sha256, load_catalog
from .config import Settings
from .correction import QueryCorrector
from .embeddings import Embedder
from .index import VectorIndex
from .intent import IntentParser
from .models import Book, SearchIntent, SoftRange
from .recommendations import RecommendationEngine
from .reranking import MultiVectorReranker
from .schemas import (
    AlchemyAnalyzeRequest,
    AlchemyAnalyzeResponse,
    AlchemyRecommendRequest,
    AlchemyRecommendResponse,
    RecommendationRequest,
    RecommendationResponse,
    RatingSummary,
    ScoreBreakdown,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SearchResult,
    Suggestion,
    SuggestResponse,
)
from .text import normalize_text, similarity, token_overlap, tokenize


SUGGESTION_PHRASES = (
    "короткий страшный детектив",
    "что-нибудь уютное на вечер",
    "динамичное приключение",
    "лёгкая романтическая история",
    "мрачный психологический триллер",
    "фантастика о будущем",
    "фэнтези с магией и драконами",
    "классика русской литературы",
    "познавательная книга для детей",
    "книга для подростка",
    "книга до 300 страниц",
    "неспешная атмосферная проза",
    "биография известного человека",
    "книга о саморазвитии",
)


class SearchEngine:
    def __init__(
        self,
        books: list[Book],
        embedder: Embedder,
        vector_index: VectorIndex,
        max_results: int = 50,
        enable_fuzzy_title_resolver: bool = False,
        multi_vector_reranker: MultiVectorReranker | None = None,
    ) -> None:
        if len(books) != len(vector_index.product_ids):
            raise RuntimeError("Catalogue and vector index contain different counts")
        expected = np.asarray([book.product_id for book in books], dtype=np.int32)
        if not np.array_equal(expected, vector_index.product_ids):
            raise RuntimeError("Vector index product mapping is stale")

        self.books = books
        self.embedder = embedder
        self.vector_index = vector_index
        self.max_results = max(1, max_results)
        self.corrector = QueryCorrector(books, enable_fuzzy_title_resolver)
        self.multi_vector_reranker = multi_vector_reranker
        self.intent_parser = IntentParser()
        self._max_popularity = max((book.popularity for book in books), default=1)
        self._authors = sorted({book.author for book in books})
        self._genres = sorted({value for book in books for value in book.genres})
        self._moods = sorted({value for book in books for value in book.moods})
        self._paces = sorted({book.pace for book in books})
        self._profile_token_frequency: Counter[str] = Counter()
        for book in books:
            self._profile_token_frequency.update(set(tokenize(book.search_text)))
        self.recommendation_engine = RecommendationEngine(books, vector_index)
        self.alchemy_service = AlchemyService(
            (book.product_id for book in books),
            books=books,
            embedder=embedder,
            vector_index=vector_index,
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, embedder: Embedder
    ) -> "SearchEngine":
        books = load_catalog(settings.catalog_path, settings.import_report_path)
        manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
        if manifest["model_name"] != embedder.model_name:
            raise RuntimeError(
                "Index was built with a different embedding model: "
                f"{manifest['model_name']}"
            )
        if manifest["catalog_sha256"] != file_sha256(settings.catalog_path):
            raise RuntimeError("Catalogue changed after index creation; rebuild the index")
        index = VectorIndex.load(settings.index_path)
        manifest_dimension = int(manifest["dimension"])
        index_dimension = int(index.vectors.shape[1])
        if manifest_dimension != embedder.dimension or index_dimension != embedder.dimension:
            raise RuntimeError(
                "Embedding dimensions differ between the model, manifest and index: "
                f"{embedder.dimension}, {manifest_dimension}, {index_dimension}"
            )
        reranker = (
            MultiVectorReranker.load(
                settings.multi_vector_index_path,
                len(books),
                embedder.dimension,
                expected_catalog_sha256=manifest["catalog_sha256"],
                expected_model_name=embedder.model_name,
            )
            if settings.multi_vector_reranker
            else None
        )
        return cls(
            books,
            embedder,
            index,
            settings.max_results,
            settings.fuzzy_title_resolver,
            reranker,
        )

    def analyze(self, query: str) -> SearchIntent:
        corrected, variants = self.corrector.correct(query)
        taxonomy_query, matched_titles, matched_authors = (
            self.corrector.split_entities(corrected)
        )
        return self.intent_parser.parse(
            query,
            corrected,
            variants,
            taxonomy_query=taxonomy_query,
            matched_titles=matched_titles,
            matched_authors=matched_authors,
        )

    def recommend(
        self, request: RecommendationRequest
    ) -> RecommendationResponse:
        return self.recommendation_engine.recommend(request)

    def analyze_alchemy(
        self, request: AlchemyAnalyzeRequest
    ) -> AlchemyAnalyzeResponse:
        intent = self.analyze(request.query)
        return self.alchemy_service.analyze(
            request,
            intent=intent,
            taxonomy_query=intent.taxonomy_query,
        )

    def recommend_alchemy(
        self, request: AlchemyRecommendRequest
    ) -> AlchemyRecommendResponse:
        return self.alchemy_service.recommend(request)

    def search(self, request: SearchRequest) -> SearchResponse:
        started = time.perf_counter()
        intent = self.analyze(request.query)
        normalized_input = normalize_text(request.query)
        empty_state = None
        if request.query.strip() and not any(
            character.isalnum() for character in normalized_input
        ):
            empty_state = "invalid_query"
        if empty_state is not None:
            return SearchResponse(
                query=request.query,
                corrected_query=intent.corrected_query,
                correction_applied=False,
                total=0,
                offset=request.offset,
                limit=request.limit,
                processing_ms=round((time.perf_counter() - started) * 1000, 3),
                intent=intent.as_dict(),
                results=[],
                state=empty_state,
            )
        eligible = [
            index
            for index, book in enumerate(self.books)
            if self._passes_filters(book, request.filters)
        ]

        semantic_scores = np.zeros(len(self.books), dtype=np.float32)
        residual_semantic_scores = np.zeros(len(self.books), dtype=np.float32)
        semantic_texts: list[str] = []
        full_query_vector: np.ndarray | None = None
        full_position: int | None = None
        residual_position: int | None = None
        if intent.corrected_query:
            full_position = len(semantic_texts)
            semantic_texts.append(intent.corrected_query)
        if intent.residual_query:
            if intent.residual_query == intent.corrected_query:
                residual_position = full_position
            else:
                residual_position = len(semantic_texts)
                semantic_texts.append(intent.residual_query)
        if semantic_texts:
            vectors = self.embedder.encode_queries(semantic_texts)
            if full_position is not None:
                full_query_vector = vectors[full_position]
                semantic_scores = self.vector_index.similarities(
                    vectors[full_position]
                )
            if residual_position is not None:
                residual_semantic_scores = self.vector_index.similarities(
                    vectors[residual_position]
                )

        ranked: list[tuple[float, SearchResult]] = []
        for index in eligible:
            book = self.books[index]
            semantic = (
                max(0.0, min(1.0, (float(semantic_scores[index]) + 1.0) / 2.0))
                if intent.corrected_query
                else 0.0
            )
            residual_semantic = (
                max(
                    0.0,
                    min(
                        1.0,
                        (float(residual_semantic_scores[index]) + 1.0) / 2.0,
                    ),
                )
                if intent.residual_query
                else 0.0
            )
            lexical, entity_match = self._lexical_score(book, intent)
            residual_lexical = self._residual_lexical_score(
                book, intent.residual_query
            )
            metadata, metadata_reasons = self._metadata_score(book, intent)
            popularity = math.log1p(book.popularity) / math.log1p(
                self._max_popularity
            )
            local_rating = request.local_ratings.get(book.product_id)
            rating = self._rating_score(book, local_rating)
            total = self._combine_scores(
                semantic=semantic,
                lexical=lexical,
                metadata=metadata,
                popularity=popularity,
                rating=rating,
                entity_match=entity_match,
                has_query=bool(intent.corrected_query),
                has_metadata_preferences=self._has_metadata_preferences(intent),
            )
            relevance = self._combine_relevance_scores(
                residual_semantic=residual_semantic,
                residual_lexical=residual_lexical,
                metadata=metadata,
                entity_match=entity_match,
                has_query=bool(intent.corrected_query),
                has_residual=bool(intent.residual_query),
                has_structured_preferences=self._has_metadata_preferences(intent),
                has_explicit_filters=self._has_explicit_filters(request.filters),
            )
            explanation = self._explain(
                book, intent, entity_match, metadata_reasons, request.filters
            )
            breakdown = (
                ScoreBreakdown(
                    total=round(total, 6),
                    relevance=round(relevance, 6),
                    semantic=round(semantic, 6),
                    residual_semantic=round(residual_semantic, 6),
                    lexical=round(lexical, 6),
                    residual_lexical=round(residual_lexical, 6),
                    metadata=round(metadata, 6),
                    popularity=round(popularity, 6),
                    entity_match=entity_match,
                )
                if request.include_debug
                else None
            )
            ranked.append(
                (
                    total,
                    SearchResult(
                        product_id=book.product_id,
                        title=book.title,
                        author=book.author,
                        price=book.price,
                        image=book.image,
                        year=book.year,
                        pages=book.pages,
                        genres=list(book.genres),
                        moods=list(book.moods),
                        pace=book.pace,
                        age_rating=book.age_rating,
                        external_rating=round(book.rating, 2),
                        external_rating_count=book.rating_count,
                        local_rating=(
                            round(local_rating.value, 2) if local_rating else 0.0
                        ),
                        local_rating_count=(local_rating.count if local_rating else 0),
                        ranking_rating=round(rating * 5.0, 2),
                        score=round(total, 6),
                        relevance_score=round(relevance, 6),
                        explanation=explanation,
                        score_breakdown=breakdown,
                    ),
                )
            )

        if (
            self.multi_vector_reranker is not None
            and full_query_vector is not None
            and not (intent.matched_titles or intent.matched_authors)
        ):
            reranked_scores = self.multi_vector_reranker.scores(
                full_query_vector,
                eligible,
                np.asarray([score for score, _ in ranked], dtype=np.float32),
            )
            updated: list[tuple[float, SearchResult]] = []
            for score, (_, result) in zip(reranked_scores, ranked):
                value = float(score)
                result.score = round(value, 6)
                if result.score_breakdown is not None:
                    result.score_breakdown.total = round(value, 6)
                updated.append((value, result))
            ranked = updated

        # Establish a relevant candidate pool before applying a commercial sort.
        # Otherwise an expensive, irrelevant book could rise to the top merely
        # because the customer selected "price descending".
        ranked.sort(
            key=lambda item: (
                item[0],
                self.books[
                    item[1].product_id - self.books[0].product_id
                ].popularity,
            ),
            reverse=True,
        )
        if intent.corrected_query and ranked:
            if self.multi_vector_reranker is not None and not (
                intent.matched_titles or intent.matched_authors
            ):
                # Multi-vector scores are candidate-local and have a different
                # scale. Applying the legacy absolute floor here can discard a
                # valid top-10 result after it has already been reranked.
                ranked = ranked[: self.max_results]
            else:
                relevance_floor = max(0.5, ranked[0][0] - 0.16)
                ranked = [
                    item for item in ranked if item[0] >= relevance_floor
                ][: self.max_results]

        if request.sort == "popularity_desc":
            ranked.sort(
                key=lambda item: (
                    item[1].external_rating_count,
                    item[1].external_rating,
                    item[0],
                ),
                reverse=True,
            )
        elif request.sort == "price_asc":
            ranked.sort(
                key=lambda item: (
                    item[1].price,
                    -item[0],
                    item[1].product_id,
                )
            )
        elif request.sort == "price_desc":
            ranked.sort(
                key=lambda item: (
                    item[1].price,
                    item[0],
                    -item[1].product_id,
                ),
                reverse=True,
            )
        elif request.sort in {"rating_external_desc", "rating_desc"}:
            ranked.sort(
                key=lambda item: (
                    item[1].external_rating,
                    item[1].external_rating_count,
                    item[0],
                ),
                reverse=True,
            )
        elif request.sort == "rating_local_desc":
            ranked.sort(
                key=lambda item: (
                    item[1].local_rating_count > 0,
                    item[1].ranking_rating,
                    item[1].local_rating_count,
                    item[0],
                ),
                reverse=True,
            )
        sliced = [
            result
            for _, result in ranked[request.offset : request.offset + request.limit]
        ]
        elapsed = (time.perf_counter() - started) * 1000
        return SearchResponse(
            query=request.query,
            corrected_query=intent.corrected_query,
            correction_applied=(
                normalize_text(request.query) != intent.corrected_query
            ),
            total=len(ranked),
            offset=request.offset,
            limit=request.limit,
            processing_ms=round(elapsed, 3),
            intent=intent.as_dict(),
            results=sliced,
            state=(
                "no_matches"
                if not ranked
                else "partial"
                if len(ranked) < request.limit
                else "results"
            ),
        )

    def suggest(self, query: str, limit: int = 8) -> SuggestResponse:
        corrected, variants = self.corrector.correct(query)
        if len(normalize_text(corrected)) < 2:
            return SuggestResponse(
                query=query, corrected_query=corrected, suggestions=[]
            )

        suggestions: list[Suggestion] = []
        for book in self.books:
            score = self._suggestion_score(corrected, book.title_norm)
            if score >= 0.55:
                suggestions.append(
                    Suggestion(
                        type="book",
                        value=book.title,
                        label=f"{book.title} — {book.author}",
                        product_id=book.product_id,
                        author=book.author,
                        image=book.image,
                        score=round(score, 5),
                    )
                )
        for author in self._authors:
            score = self._suggestion_score(corrected, normalize_text(author))
            if score >= 0.55:
                suggestions.append(
                    Suggestion(
                        type="author",
                        value=author,
                        label=author,
                        score=round(score * 0.98, 5),
                    )
                )
        for genre in self._genres:
            score = self._suggestion_score(corrected, normalize_text(genre))
            if score >= 0.55:
                suggestions.append(
                    Suggestion(
                        type="genre",
                        value=genre,
                        label=genre,
                        score=round(score * 0.96, 5),
                    )
                )
        for phrase in SUGGESTION_PHRASES:
            score = self._suggestion_score(corrected, normalize_text(phrase))
            if score >= 0.55:
                suggestions.append(
                    Suggestion(
                        type="phrase",
                        value=phrase,
                        label=phrase,
                        score=round(score * 0.94, 5),
                    )
                )

        suggestions.sort(key=lambda item: item.score, reverse=True)
        deduplicated: list[Suggestion] = []
        seen: set[tuple[str, str]] = set()
        for suggestion in suggestions:
            key = (suggestion.type, normalize_text(suggestion.value))
            if key not in seen:
                deduplicated.append(suggestion)
                seen.add(key)
            if len(deduplicated) >= limit:
                break
        return SuggestResponse(
            query=query,
            corrected_query=corrected,
            suggestions=deduplicated,
        )

    def facets(self) -> dict[str, Any]:
        prices = [book.price for book in self.books]
        pages = [book.pages for book in self.books]
        years = [book.year for book in self.books]
        return {
            "price": {"min": min(prices), "max": max(prices)},
            "pages": {"min": min(pages), "max": max(pages)},
            "year": {"min": min(years), "max": max(years)},
            "authors": self._authors,
            "genres": self._genres,
            "age_ratings": sorted(
                {book.age_rating for book in self.books},
                key=self._age_value,
            ),
            "moods": self._moods,
            "paces": self._paces,
        }

    @staticmethod
    def _passes_filters(book: Book, filters: SearchFilters) -> bool:
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

        selected_authors = {normalize_text(value) for value in filters.authors}
        if selected_authors and normalize_text(book.author) not in selected_authors:
            return False
        selected_genres = {normalize_text(value) for value in filters.genres}
        if selected_genres and not selected_genres.intersection(
            normalize_text(value) for value in book.genres
        ):
            return False
        selected_moods = {normalize_text(value) for value in filters.moods}
        if selected_moods and not selected_moods.intersection(
            normalize_text(value) for value in book.moods
        ):
            return False
        selected_paces = {normalize_text(value) for value in filters.paces}
        if selected_paces and normalize_text(book.pace) not in selected_paces:
            return False
        selected_ages = {normalize_text(value) for value in filters.age_ratings}
        if selected_ages and normalize_text(book.age_rating) not in selected_ages:
            return False
        return True

    def _lexical_score(
        self, book: Book, intent: SearchIntent
    ) -> tuple[float, str | None]:
        if not intent.corrected_query:
            return 0.0, None

        variants = intent.query_variants or [intent.corrected_query]
        best_title = 0.0
        best_author = 0.0
        entity_match: str | None = None
        for query in variants:
            query_norm = normalize_text(query)
            title_score, title_match = self.corrector.title_match(
                book, query_norm
            )
            if title_match == "exact_title":
                return 1.0, title_match
            if title_match:
                best_title = max(best_title, title_score)
                entity_match = title_match

            author_score, author_match = self.corrector.author_match(
                book, query_norm
            )
            if author_match == "exact_author":
                return 0.98, author_match
            if author_match:
                best_author = max(best_author, author_score)
                if entity_match is None:
                    entity_match = author_match

            title_aliases = tuple(
                value
                for value in (book.title_norm, book.source_title_norm)
                if value
            )
            title_overlap = max(
                (token_overlap(query_norm, alias) for alias in title_aliases),
                default=0.0,
            )
            author_overlap = token_overlap(query_norm, book.author_norm)

            best_title = max(
                best_title,
                *(
                    0.72 * title_overlap + 0.28 * similarity(query_norm, alias)
                    for alias in title_aliases
                ),
            )
            best_author = max(
                best_author,
                0.78 * author_overlap
                + 0.22 * similarity(query_norm, book.author_norm),
            )

        searchable_overlap = token_overlap(
            intent.corrected_query, book.searchable_norm
        )
        profile_match = self._rare_profile_match(book, intent.corrected_query)
        lexical = max(
            best_title,
            best_author,
            searchable_overlap * 0.65,
            profile_match,
        )
        return min(1.0, lexical), entity_match

    def _rare_profile_match(self, book: Book, query: str) -> float:
        stopwords = {
            "автор", "быстро", "история", "книга", "книгу", "книги",
            "который", "которая", "можно", "найти", "нужна", "нужно",
            "похожая", "похожий", "роман", "самый", "такой", "чтение",
        }
        query_tokens = {
            token
            for token in tokenize(query)
            if len(token) >= 5 and token not in stopwords
        }
        if not query_tokens:
            return 0.0

        profile_tokens = set(tokenize(book.search_text))
        matched = 0
        for query_token in query_tokens:
            candidates = [
                profile_token
                for profile_token in profile_tokens
                if self._same_word_form(query_token, profile_token)
                and self._profile_token_frequency.get(profile_token, 0) <= 12
            ]
            if candidates:
                matched += 1

        if not matched:
            return 0.0
        coverage = matched / len(query_tokens)
        return min(0.92, 0.72 + 0.20 * coverage)

    def _residual_lexical_score(self, book: Book, query: str) -> float:
        if not query:
            return 0.0
        searchable_overlap = token_overlap(query, book.searchable_norm)
        return min(
            1.0,
            max(
                searchable_overlap * 0.65,
                self._rare_profile_match(book, query),
            ),
        )

    @staticmethod
    def _same_word_form(left: str, right: str) -> bool:
        if left == right:
            return True
        shorter = min(len(left), len(right))
        if shorter < 6:
            return False
        common = 0
        for left_char, right_char in zip(left, right):
            if left_char != right_char:
                break
            common += 1
        return common >= max(6, shorter - 2)

    @staticmethod
    def _metadata_score(
        book: Book, intent: SearchIntent
    ) -> tuple[float, list[str]]:
        components: list[tuple[float, float]] = []
        reasons: list[str] = []
        book_genres = {normalize_text(value): value for value in book.genres}
        book_moods = {normalize_text(value): value for value in book.moods}

        if intent.preferred_genres:
            matches = [
                value
                for value in intent.preferred_genres
                if normalize_text(value) in book_genres
            ]
            components.append(
                (len(matches) / len(intent.preferred_genres), 3.0)
            )
            if matches:
                reasons.append(f"жанр: {', '.join(matches)}")

        if intent.preferred_moods:
            matches = [
                value
                for value in intent.preferred_moods
                if normalize_text(value) in book_moods
            ]
            components.append(
                (len(matches) / len(intent.preferred_moods), 2.0)
            )
            if matches:
                reasons.append(f"настроение: {', '.join(matches)}")

        if intent.preferred_paces:
            matched = normalize_text(book.pace) in {
                normalize_text(value) for value in intent.preferred_paces
            }
            components.append((1.0 if matched else 0.0, 1.5))
            if matched:
                reasons.append(f"{book.pace} темп")

        if intent.pages:
            pages_score = SearchEngine._range_score(book.pages, intent.pages, 300)
            components.append((pages_score, 2.0))
            if pages_score >= 0.75:
                reasons.append(f"подходящий объём: {book.pages} стр.")

        if intent.year:
            year_score = SearchEngine._range_score(book.year, intent.year, 40)
            components.append((year_score, 1.0))
            if year_score >= 0.75:
                reasons.append(f"подходящий год: {book.year}")

        if intent.age_max is not None:
            age_score = (
                1.0
                if SearchEngine._age_value(book.age_rating) <= intent.age_max
                else 0.0
            )
            components.append((age_score, 1.0))

        penalties = 0.0
        if any(
            normalize_text(value) in book_genres
            for value in intent.excluded_genres
        ):
            penalties += 0.8
        if any(
            normalize_text(value) in book_moods for value in intent.excluded_moods
        ):
            penalties += 0.8
        for excluded in intent.excluded_terms:
            if SearchEngine._excluded_term_present(excluded, book.searchable_norm):
                penalties += 0.5

        total_weight = sum(weight for _, weight in components)
        base = (
            sum(value * weight for value, weight in components)
            / total_weight
            if components
            else 0.5
        )
        return max(-1.0, min(1.0, base - penalties)), reasons

    @staticmethod
    def _has_metadata_preferences(intent: SearchIntent) -> bool:
        return bool(
            intent.preferred_genres
            or intent.excluded_genres
            or intent.preferred_moods
            or intent.excluded_moods
            or intent.preferred_paces
            or intent.excluded_terms
            or intent.pages
            or intent.year
            or intent.age_max is not None
        )

    @staticmethod
    def _excluded_term_present(term: str, searchable: str) -> bool:
        normalized = normalize_text(term)
        probes = {normalized}
        if len(normalized) >= 6:
            probes.add(normalized[:-1])
        return any(len(probe) >= 4 and probe in searchable for probe in probes)

    @staticmethod
    def _range_score(value: float, preferred: SoftRange, falloff: float) -> float:
        if preferred.minimum is not None and value < preferred.minimum:
            return max(0.0, 1.0 - (preferred.minimum - value) / falloff)
        if preferred.maximum is not None and value > preferred.maximum:
            return max(0.0, 1.0 - (value - preferred.maximum) / falloff)
        if preferred.target is not None:
            return max(0.6, 1.0 - abs(value - preferred.target) / falloff)
        return 1.0

    @staticmethod
    def _rating_score(book: Book, local: RatingSummary | None) -> float:
        """Blend rating sources without changing rating's total ranking weight.

        OpenLibrary is the cold-start prior. FlowPages earns influence as approved
        local reviews accumulate; 20 reviews give both sources equal influence.
        """
        external = max(0.0, min(1.0, book.rating / 5.0))
        if local is None or local.count <= 0:
            return external

        local_score = max(0.0, min(1.0, local.value / 5.0))
        if book.rating_count <= 0 or book.rating <= 0:
            return local_score

        local_weight = local.count / (local.count + 20.0)
        return (1.0 - local_weight) * external + local_weight * local_score

    @staticmethod
    def _combine_scores(
        *,
        semantic: float,
        lexical: float,
        metadata: float,
        popularity: float,
        rating: float,
        entity_match: str | None,
        has_query: bool,
        has_metadata_preferences: bool,
    ) -> float:
        if not has_query:
            return 0.7 * popularity + 0.3 * rating
        if entity_match:
            score = (
                0.25 * semantic
                + 0.60 * lexical
                + 0.10 * metadata
                + 0.03 * popularity
                + 0.02 * rating
            )
            # A confidently recognized title or author is navigational intent.
            # Keep it ahead of books that merely mention the same entity in a
            # rich SearchText. One-word titles reach this branch only when the
            # corrector also finds author evidence.
            entity_floor = {
                "exact_title": 0.99,
                "title": 0.96,
                "fuzzy_title": 0.94,
                "exact_author": 0.98,
                "author": 0.95,
                "fuzzy_author": 0.93,
            }.get(entity_match, 0.93)
            score = max(score, entity_floor)
        elif has_metadata_preferences:
            score = (
                0.70 * semantic
                + 0.23 * lexical
                + 0.02 * metadata
                + 0.03 * popularity
                + 0.02 * rating
            )
        else:
            score = (
                0.70 * semantic
                + 0.25 * lexical
                + 0.03 * popularity
                + 0.02 * rating
            )
        return max(0.0, min(1.0, score))

    @staticmethod
    def _combine_relevance_scores(
        *,
        residual_semantic: float,
        residual_lexical: float,
        metadata: float,
        entity_match: str | None,
        has_query: bool,
        has_residual: bool,
        has_structured_preferences: bool,
        has_explicit_filters: bool,
    ) -> float:
        entity_relevance = {
            "exact_title": 1.0,
            "title": 0.98,
            "fuzzy_title": 0.96,
            "exact_author": 0.99,
            "author": 0.97,
            "fuzzy_author": 0.95,
        }.get(entity_match)
        if entity_relevance is not None:
            return entity_relevance

        textual = (
            0.75 * residual_semantic + 0.25 * residual_lexical
            if has_residual
            else 0.0
        )
        if has_residual and has_structured_preferences:
            relevance = 0.70 * textual + 0.30 * metadata
        elif has_residual:
            relevance = textual
        elif has_structured_preferences:
            relevance = metadata
        elif not has_query and has_explicit_filters:
            relevance = 1.0
        elif not has_query:
            relevance = 1.0
        else:
            relevance = 0.0
        return max(0.0, min(1.0, relevance))

    @staticmethod
    def _has_explicit_filters(filters: SearchFilters) -> bool:
        return bool(
            filters.price_min is not None
            or filters.price_max is not None
            or filters.authors
            or filters.genres
            or filters.pages_min is not None
            or filters.pages_max is not None
            or filters.year_min is not None
            or filters.year_max is not None
            or filters.age_ratings
            or filters.moods
            or filters.paces
        )

    @staticmethod
    def _explain(
        book: Book,
        intent: SearchIntent,
        entity_match: str | None,
        metadata_reasons: list[str],
        filters: SearchFilters,
    ) -> list[str]:
        reasons: list[str] = []
        if entity_match in {"exact_title", "title", "fuzzy_title"}:
            reasons.append("совпадение с названием")
        if entity_match in {"exact_author", "author", "fuzzy_author"}:
            reasons.append("совпадение с автором")
        reasons.extend(metadata_reasons)
        excluded_absent = [
            value
            for value in intent.excluded_terms
            if not SearchEngine._excluded_term_present(
                value, book.searchable_norm
            )
        ]
        if excluded_absent:
            reasons.append(f"без темы: {', '.join(sorted(excluded_absent))}")
        if filters.genres:
            reasons.append("соответствует выбранному жанру")
        if filters.pages_min is not None or filters.pages_max is not None:
            reasons.append(f"проходит фильтр по объёму: {book.pages} стр.")
        if filters.price_min is not None or filters.price_max is not None:
            display_price = f"{book.price:.1f}".replace('.', ',')
            reasons.append(f"проходит фильтр по цене: {display_price} р.")
        if not reasons and intent.corrected_query:
            reasons.append("близка запросу по смыслу")
        if not reasons:
            reasons.append("популярная книга с высоким рейтингом")
        return reasons[:4]

    @staticmethod
    def _suggestion_score(query: str, candidate: str) -> float:
        if candidate.startswith(query):
            return 1.0
        if query in candidate:
            return 0.9
        query_tokens = tokenize(query)
        candidate_tokens = tokenize(candidate)
        if query_tokens and candidate_tokens and candidate_tokens[0].startswith(
            query_tokens[0]
        ):
            return 0.84
        return 0.72 * similarity(query, candidate) + 0.28 * token_overlap(
            query, candidate
        )

    @staticmethod
    def _age_value(value: str) -> int:
        digits = "".join(char for char in value if char.isdigit())
        return int(digits or 0)
