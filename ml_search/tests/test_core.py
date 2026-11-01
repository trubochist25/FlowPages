from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from ml_search.catalog import load_catalog, passage_for_embedding
from ml_search.config import Settings, resolve_model_profile
from ml_search.correction import QueryCorrector
from ml_search.embeddings import HashingEmbedder
from ml_search.index import VectorIndex
from ml_search.schemas import (
    AlchemyAnalyzeRequest,
    AlchemyAnchor,
    AlchemyFilters,
    AlchemyIngredient,
    AlchemyNegativeIngredient,
    AlchemyRecommendRequest,
    RatingSummary,
    SearchFilters,
    SearchRequest,
)
from ml_search.search import SearchEngine
from ml_search.reranking import MultiVectorReranker
from ml_search.calibration import ALCHEMY_QUERY_CALIBRATION


class SearchCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = Settings.from_env()
        books = load_catalog(settings.catalog_path, settings.import_report_path)
        embedder = HashingEmbedder()
        vectors = embedder.encode_passages(
            [passage_for_embedding(book) for book in books]
        )
        product_ids = np.asarray(
            [book.product_id for book in books], dtype=np.int32
        )
        cls.engine = SearchEngine(
            books, embedder, VectorIndex(product_ids, vectors)
        )

    def test_search_result_pool_is_capped_before_sort_and_pagination(self) -> None:
        self.assertEqual(self.engine.max_results, 50)
        with patch.object(SearchEngine, '_combine_scores', return_value=0.9):
            for sort in ('relevance', 'price_desc'):
                response = self.engine.search(SearchRequest(query='книга', limit=100, sort=sort))
                self.assertEqual(response.total, 50)
                self.assertEqual(len(response.results), 50)
                page = self.engine.search(SearchRequest(query='книга', limit=10, offset=50, sort=sort))
                self.assertEqual(page.total, 50)
                self.assertEqual(page.results, [])

    def test_multi_vector_reranker_promotes_field_match(self) -> None:
        vectors = {
            name: np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
            for name in MultiVectorReranker.REQUIRED_FIELDS
        }
        reranker = MultiVectorReranker(vectors, alpha=0.60)
        scores = reranker.scores(
            np.asarray([0.0, 1.0], dtype=np.float32),
            [0, 1],
            np.asarray([0.9, 0.8], dtype=np.float32),
        )
        self.assertGreater(scores[1], scores[0])

    def test_multi_vector_index_validates_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fields.npz"
            np.savez(path, **{
                name: np.zeros((2, 3), dtype=np.float32)
                for name in MultiVectorReranker.REQUIRED_FIELDS
            })
            with self.assertRaisesRegex(RuntimeError, "shapes differ"):
                MultiVectorReranker.load(path, expected_books=3, expected_dimension=3)

    def test_natural_language_intent(self) -> None:
        intent = self.engine.analyze(
            "короткий страшный детектив без мистики"
        )
        self.assertEqual(intent.pages.maximum, 250)
        self.assertIn("Детективы", intent.preferred_genres)
        self.assertIn("Ужасы", intent.preferred_genres)
        self.assertTrue(
            {"мистика", "мистики"}.intersection(intent.excluded_terms)
        )

    def test_keyboard_layout_correction(self) -> None:
        intent = self.engine.analyze("ufhhb gjnnh")
        self.assertEqual(intent.corrected_query, "гарри поттер")

    def test_transliteration_correction(self) -> None:
        intent = self.engine.analyze("dostoevskiy")
        self.assertEqual(intent.corrected_query, "достоевский")
        name_intent = self.engine.analyze("harry potter")
        self.assertEqual(name_intent.corrected_query, "гарри поттер")

        ambiguous = {
            "malenkiy princ sent ekzuperi": "маленький принц сент экзюпери",
            "cveti dlya eldzhernona": "цветы для элджернона",
        }
        for query, expected in ambiguous.items():
            with self.subTest(query=query):
                self.assertEqual(
                    self.engine.analyze(query).corrected_query,
                    expected,
                )

    def test_russian_semantic_query_is_not_rewritten(self) -> None:
        query = (
            "учёный собирает живое существо из мёртвых тел а затем "
            "отвергает своё разумное создание"
        )
        self.assertEqual(
            self.engine.analyze(query).corrected_query,
            "ученый собирает живое существо из мертвых тел а затем "
            "отвергает свое разумное создание",
        )

    def test_one_word_title_requires_entity_context(self) -> None:
        cases = (
            ("служащий следит за мыслями граждан", "Мы"),
            ("адвокат защищает темнокожего мужчину", "Муж"),
            ("девушка сначала презирает жениха", "Начала"),
        )
        for query, title in cases:
            with self.subTest(query=query):
                intent = self.engine.analyze(query)
                book = next(book for book in self.engine.books if book.title == title)
                _, entity_match = self.engine._lexical_score(book, intent)
                self.assertIsNone(entity_match)

        intent = self.engine.analyze("Дюна Фрэнк Герберт")
        dune = next(book for book in self.engine.books if book.title == "Дюна")
        _, entity_match = self.engine._lexical_score(dune, intent)
        self.assertEqual(entity_match, "title")

    def test_optional_fuzzy_title_resolver_handles_navigation_typos(self) -> None:
        corrector = QueryCorrector(
            self.engine.books, enable_fuzzy_title_resolver=True
        )
        cases = (
            ("гарри потр философкий камин", "Гарри Поттер и философский камень"),
            ("татуировка дракона", "Девушка с татуировкой дракона"),
        )
        for query, expected_title in cases:
            with self.subTest(query=query):
                resolved = corrector.fuzzy_title_resolver.resolve(query)
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved.title, expected_title)

        for thematic_query in (
            "фэнтези с магией и драконами",
            "размышления о философии жизни",
        ):
            with self.subTest(query=thematic_query):
                self.assertIsNone(
                    corrector.fuzzy_title_resolver.resolve(thematic_query)
                )

    def test_fuzzy_title_resolver_is_disabled_by_default(self) -> None:
        self.assertIsNone(self.engine.corrector.fuzzy_title_resolver)

    def test_title_words_are_not_parsed_as_search_preferences(self) -> None:
        intent = self.engine.analyze("garri potter i filosofskiy kamen")
        self.assertFalse(intent.preferred_genres)
        self.assertFalse(intent.preferred_moods)

    def test_entity_match_dominates_results(self) -> None:
        response = self.engine.search(
            SearchRequest(query="ufhhb gjnnh", limit=5)
        )
        self.assertTrue(response.results)
        self.assertTrue(
            all("гарри поттер" in item.title.lower() for item in response.results)
        )
        mixed = self.engine.search(
            SearchRequest(query="короткий достоевский", limit=5)
        )
        self.assertTrue(
            all("достоевск" in item.author.lower() for item in mixed.results)
        )

    def test_hard_filters_are_strict(self) -> None:
        response = self.engine.search(
            SearchRequest(
                query="детектив",
                filters=SearchFilters(
                    pages_max=250,
                    price_max=700,
                    genres=["Детективы"],
                ),
                limit=100,
            )
        )
        self.assertTrue(response.results)
        self.assertTrue(
            all(
                item.pages <= 250
                and item.price <= 700
                and "Детективы" in item.genres
                for item in response.results
            )
        )

    def test_no_matches_is_reserved_for_objectively_empty_candidate_pool(self) -> None:
        response = self.engine.search(
            SearchRequest(
                query="любая книга",
                filters=SearchFilters(price_max=1),
                limit=10,
            )
        )
        self.assertEqual(response.state, "no_matches")
        self.assertEqual(response.results, [])

    def test_semantic_uncertainty_does_not_claim_catalogue_absence(self) -> None:
        response = self.engine.search(
            SearchRequest(
                query="пайка микросхем bga с температурными профилями",
                limit=10,
            )
        )
        self.assertTrue(response.results)
        self.assertIn(response.state, {"results", "partial"})

    def test_all_interface_filters_are_supported(self) -> None:
        target = self.engine.books[0]
        response = self.engine.search(
            SearchRequest(
                filters=SearchFilters(
                    price_min=target.price,
                    price_max=target.price,
                    authors=[target.author],
                    genres=[target.genres[0]],
                    pages_min=target.pages,
                    pages_max=target.pages,
                    year_min=target.year,
                    year_max=target.year,
                    age_ratings=[target.age_rating],
                    moods=[target.moods[0]],
                    paces=[target.pace],
                ),
                limit=100,
            )
        )
        self.assertTrue(response.results)
        for item in response.results:
            self.assertEqual(item.price, target.price)
            self.assertEqual(item.author, target.author)
            self.assertIn(target.genres[0], item.genres)
            self.assertEqual(item.pages, target.pages)
            self.assertEqual(item.year, target.year)
            self.assertEqual(item.age_rating, target.age_rating)
            self.assertIn(target.moods[0], item.moods)
            self.assertEqual(item.pace, target.pace)

    def test_suggestions_understand_typo(self) -> None:
        response = self.engine.suggest("гарри поттр", limit=5)
        self.assertTrue(response.suggestions)
        self.assertTrue(
            any("Гарри Поттер" in item.label for item in response.suggestions)
        )
        self.assertTrue(
            all(item.image for item in response.suggestions if item.type == "book")
        )

    def test_suggestions_include_genres_and_search_phrases(self) -> None:
        genre_response = self.engine.suggest("детект", limit=8)
        self.assertTrue(
            any(
                item.type == "genre" and item.value == "Детективы"
                for item in genre_response.suggestions
            )
        )

        phrase_response = self.engine.suggest("что-нибудь уют", limit=8)
        self.assertTrue(
            any(
                item.type == "phrase"
                and item.value == "что-нибудь уютное на вечер"
                for item in phrase_response.suggestions
            )
        )

    def test_optional_sorting_is_applied_before_pagination(self) -> None:
        response = self.engine.search(
            SearchRequest(query="", sort="price_desc", limit=1)
        )
        self.assertEqual(
            response.results[0].price,
            max(book.price for book in self.engine.books),
        )

    def test_rating_sources_are_exposed_separately(self) -> None:
        target = self.engine.books[0]
        response = self.engine.search(
            SearchRequest(
                query=target.title,
                local_ratings={
                    target.product_id: RatingSummary(value=5.0, count=20)
                },
                limit=10,
            )
        )
        result = next(
            item for item in response.results if item.product_id == target.product_id
        )
        self.assertEqual(result.external_rating, round(target.rating, 2))
        self.assertEqual(result.external_rating_count, target.rating_count)
        self.assertEqual(result.local_rating, 5.0)
        self.assertEqual(result.local_rating_count, 20)
        self.assertAlmostEqual(
            result.ranking_rating,
            round((target.rating + 5.0) / 2.0, 2),
            places=2,
        )

    def test_rating_and_popularity_keep_their_total_weights(self) -> None:
        baseline = self.engine._combine_scores(
            semantic=0,
            lexical=0,
            metadata=0,
            popularity=0,
            rating=0,
            entity_match=None,
            has_query=True,
            has_metadata_preferences=False,
        )
        rating_only = self.engine._combine_scores(
            semantic=0,
            lexical=0,
            metadata=0,
            popularity=0,
            rating=1,
            entity_match=None,
            has_query=True,
            has_metadata_preferences=False,
        )
        popularity_only = self.engine._combine_scores(
            semantic=0,
            lexical=0,
            metadata=0,
            popularity=1,
            rating=0,
            entity_match=None,
            has_query=True,
            has_metadata_preferences=False,
        )
        self.assertAlmostEqual(rating_only - baseline, 0.02)
        self.assertAlmostEqual(popularity_only - baseline, 0.03)

        browse_rating = self.engine._combine_scores(
            semantic=0,
            lexical=0,
            metadata=0,
            popularity=0,
            rating=1,
            entity_match=None,
            has_query=False,
            has_metadata_preferences=False,
        )
        browse_popularity = self.engine._combine_scores(
            semantic=0,
            lexical=0,
            metadata=0,
            popularity=1,
            rating=0,
            entity_match=None,
            has_query=False,
            has_metadata_preferences=False,
        )
        self.assertAlmostEqual(browse_rating, 0.3)
        self.assertAlmostEqual(browse_popularity, 0.7)

    def test_search_exposes_relevance_separately_from_ranking_score(self) -> None:
        response = self.engine.search(
            SearchRequest(query="Дюна", limit=5, include_debug=True)
        )

        dune = next(item for item in response.results if item.title == "Дюна")
        self.assertEqual(dune.relevance_score, 1.0)
        self.assertIsNotNone(dune.score_breakdown)
        self.assertEqual(
            dune.score_breakdown.relevance,
            dune.relevance_score,
        )

    def test_sign_only_search_stops_before_ranking(self) -> None:
        response = self.engine.search(SearchRequest(query="!!! …", limit=10))

        self.assertEqual(response.state, "invalid_query")
        self.assertEqual(response.total, 0)
        self.assertEqual(response.results, [])

    def test_search_relevance_formula_has_no_commercial_signals(self) -> None:
        relevance = self.engine._combine_relevance_scores(
            residual_semantic=0.8,
            residual_lexical=0.4,
            metadata=0.5,
            entity_match=None,
            has_query=True,
            has_residual=True,
            has_structured_preferences=False,
            has_explicit_filters=False,
        )

        self.assertAlmostEqual(relevance, 0.7)

    def test_local_rating_sort_prioritizes_reviewed_books(self) -> None:
        target = self.engine.books[-1]
        response = self.engine.search(
            SearchRequest(
                sort="rating_local_desc",
                local_ratings={
                    target.product_id: RatingSummary(value=1.0, count=1)
                },
                limit=1,
            )
        )
        self.assertEqual(response.results[0].product_id, target.product_id)

    def test_query_does_not_expose_the_irrelevant_catalogue_tail(self) -> None:
        response = self.engine.search(
            SearchRequest(query="гарри поттер", limit=100)
        )
        self.assertLess(response.total, len(self.engine.books))
        exact_series = [
            item for item in response.results if "гарри поттер" in item.title.lower()
        ]
        self.assertGreaterEqual(len(exact_series), 8)

    def test_rare_search_profile_details_affect_ranking(self) -> None:
        cases = (
            ("антиутопия про слежку и цензуру", "1984"),
            ("триллер про пирокинез", "Поджигатель"),
            ("детская история про сирот и ураган", "Широкое окно"),
        )
        for query, expected_title in cases:
            with self.subTest(query=query):
                response = self.engine.search(SearchRequest(query=query, limit=10))
                self.assertTrue(
                    any(item.title == expected_title for item in response.results)
                )

    def test_alchemy_extracts_emphasis_and_reduction(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(
                query="больше загадки, меньше романтики"
            )
        )
        positive = {(item.kind, item.value): item for item in response.positive}
        negative = {(item.kind, item.value): item for item in response.negative}

        self.assertIn(("theme", "расследование и тайны"), positive)
        self.assertEqual(
            positive[("theme", "расследование и тайны")].weight,
            1.0,
        )
        self.assertIn(("genre", "Романтика"), negative)
        self.assertEqual(negative[("genre", "Романтика")].mode, "avoid")

    def test_alchemy_keeps_content_exclusions_soft(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query="без мистики и жестокости")
        )
        negative = {(item.kind, item.value): item for item in response.negative}

        self.assertEqual(negative[("mood", "мистическая")].mode, "exclude")
        self.assertEqual(negative[("content", "жестокость")].mode, "avoid")
        self.assertIn(
            "unverified_content_avoidance",
            [warning.code for warning in response.warnings],
        )

    def test_alchemy_negation_stops_at_preference_clause_boundaries(self) -> None:
        cases = (
            (
                "Умная научная фантастика о будущем, без мрачности, средний темп",
                ("pace", "средний"),
            ),
            ("без романтики; медленный темп", ("pace", "медленный")),
            ("без мистики. быстрый темп", ("pace", "быстрый")),
            ("без мрачности, и средний темп", ("pace", "средний")),
        )

        for query, expected in cases:
            with self.subTest(query=query):
                response = self.engine.analyze_alchemy(
                    AlchemyAnalyzeRequest(query=query)
                )
                positive = {(item.kind, item.value) for item in response.positive}
                negative = {(item.kind, item.value) for item in response.negative}

                self.assertIn(expected, positive)
                self.assertNotIn(expected, negative)

    def test_alchemy_negation_allows_only_real_qualifiers(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(
                query="без слишком мрачной атмосферы, средний темп"
            )
        )
        positive = {(item.kind, item.value) for item in response.positive}
        negative = {(item.kind, item.value) for item in response.negative}

        self.assertIn(("mood", "мрачная"), negative)
        self.assertIn(("pace", "средний"), positive)
        self.assertNotIn(("pace", "средний"), negative)

    def test_alchemy_extracts_only_explicit_strict_filters(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(
                query=(
                    "детектив от 180 до 320 страниц, до 900 рублей, "
                    "после 2000 года, 16+"
                )
            )
        )

        self.assertEqual(response.filters.pages_min, 180)
        self.assertEqual(response.filters.pages_max, 320)
        self.assertEqual(response.filters.price_max, 900)
        self.assertEqual(response.filters.year_min, 2000)
        self.assertEqual(response.filters.age_ratings, ["16+"])

        soft = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query="короткая книга")
        )
        self.assertIsNone(soft.filters.pages_max)
        self.assertIn("короткая", [item.value for item in soft.positive])

    def test_alchemy_recognizes_single_book_anchor(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query="как Дюна, но короче")
        )

        self.assertEqual([anchor.title for anchor in response.anchors], ["Дюна"])
        self.assertIn("короче", [item.value for item in response.positive])
        self.assertEqual(response.residual_query, "")

    def test_alchemy_understands_less_politics_in_anchor_recipe(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(
                query="как Дюна, но короче и с меньшим количеством политики"
            )
        )

        negative = {(item.kind, item.value): item for item in response.negative}
        self.assertEqual([anchor.title for anchor in response.anchors], ["Дюна"])
        self.assertIn("короче", [item.value for item in response.positive])
        self.assertIn(("theme", "власть и общество"), negative)
        self.assertEqual(
            negative[("theme", "власть и общество")].mode,
            "avoid",
        )
        self.assertEqual(response.unresolved_fragments, [])

    def test_alchemy_recognizes_two_book_anchors_in_order(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query="что-то между Дюной и 1984")
        )

        self.assertEqual(
            [anchor.title for anchor in response.anchors],
            ["Дюна", "1984"],
        )

    def test_alchemy_preserves_unknown_free_text(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query="о стеклодувах Исландии в сезон дождей")
        )

        self.assertEqual(
            response.normalized_query,
            "о стеклодувах исландии в сезон дождей",
        )
        self.assertEqual(
            response.unresolved_fragments,
            ["о стеклодувах исландии в сезон дождей"],
        )
        self.assertEqual(
            response.residual_query,
            "о стеклодувах исландии в сезон дождей",
        )

    def test_search_intent_separates_entities_preferences_and_free_text(self) -> None:
        intent = self.engine.analyze(
            "Стивен Кинг, уютная книга о зимнем отеле до 300 страниц"
        )

        self.assertIn("Стивен Кинг", intent.matched_authors)
        self.assertIn("уютная", intent.preferred_moods)
        self.assertEqual(intent.pages.maximum, 300)
        self.assertNotIn("стивен", intent.taxonomy_query)
        self.assertNotIn("уютн", intent.residual_query)
        self.assertNotIn("300", intent.residual_query)
        self.assertIn("зимнем отеле", intent.residual_query)

    def test_alchemy_ranking_uses_the_explicit_residual_query(self) -> None:
        request = AlchemyRecommendRequest(
            query="уютная книга для вечера",
            residual_query="для вечера",
            positive=[AlchemyIngredient(kind="mood", value="уютная")],
            limit=6,
        )

        semantic_query = self.engine.alchemy_service.ranker._semantic_query_text(
            request
        )
        self.assertEqual(semantic_query, "для вечера")

    def test_alchemy_exposes_relevance_without_quality_or_surprise(self) -> None:
        ranker = self.engine.alchemy_service.ranker
        relevance = ranker._combine_relevance_signals(
            query_semantic=0.7,
            anchor_semantic=0.8,
            ingredient_score=0.6,
            has_query=True,
            has_anchors=True,
            has_ingredients=True,
        )
        low_quality_core = ranker._combine_active_signals(
            query_semantic=0.7,
            anchor_semantic=0.8,
            ingredient_score=0.6,
            quality=0.0,
            has_query=True,
            has_anchors=True,
            has_ingredients=True,
        )
        high_quality_core = ranker._combine_active_signals(
            query_semantic=0.7,
            anchor_semantic=0.8,
            ingredient_score=0.6,
            quality=1.0,
            has_query=True,
            has_anchors=True,
            has_ingredients=True,
        )

        self.assertAlmostEqual(relevance, 0.7368421053)
        self.assertNotEqual(low_quality_core, high_quality_core)

        response = self.engine.recommend_alchemy(
            AlchemyRecommendRequest(
                query="уютная история для вечера",
                residual_query="для вечера",
                positive=[AlchemyIngredient(kind="mood", value="уютная")],
                limit=6,
                include_debug=True,
            )
        )
        self.assertTrue(response.results)
        self.assertEqual(
            response.results[0].relevance_score,
            response.results[0].score_breakdown["relevance"],
        )

    def test_alchemy_similarity_calibration_is_absolute(self) -> None:
        isolated = ALCHEMY_QUERY_CALIBRATION.apply(
            np.asarray([0.82], dtype=np.float32)
        )[0]
        surrounded = ALCHEMY_QUERY_CALIBRATION.apply(
            np.asarray([0.20, 0.82, 0.99], dtype=np.float32)
        )[1]

        self.assertAlmostEqual(float(isolated), 0.5, places=5)
        self.assertAlmostEqual(float(isolated), float(surrounded), places=7)

    def test_alchemy_uses_existing_query_correction(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query="enjyfz rybuf")
        )

        self.assertEqual(response.normalized_query, "уютная книга")
        self.assertIn("уютная", [item.value for item in response.positive])

    def test_alchemy_does_not_treat_plain_title_search_as_anchor(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query="Дюна Фрэнк Герберт")
        )

        self.assertEqual(response.anchors, [])

    def test_alchemy_accepts_byn_prices_with_kopecks(self) -> None:
        for query in ('уютный детектив до 30,50 BYN', 'уютный детектив до 30.50 Br'):
            response = self.engine.analyze_alchemy(AlchemyAnalyzeRequest(query=query))
            self.assertEqual(response.filters.price_max, 30.5)
        response = self.engine.analyze_alchemy(AlchemyAnalyzeRequest(
            query='уютный детектив до 30,50 BYN про потерянную рукопись'
        ))
        self.assertIn('потерянную рукопись', response.residual_query)

    def test_alchemy_accepts_rouble_symbol_in_price_filter(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(query="уютный детектив до 750 ₽")
        )

        self.assertEqual(response.filters.price_max, 750)

    def test_alchemy_reports_limited_english_parser(self) -> None:
        response = self.engine.analyze_alchemy(
            AlchemyAnalyzeRequest(
                query="a quiet mystery for a rainy evening",
                locale="en-GB",
            )
        )

        self.assertEqual(response.positive, [])
        self.assertEqual(response.unresolved_fragments, [response.normalized_query])
        self.assertEqual(response.warnings[0].code, "limited_locale")

    def test_alchemy_ranking_uses_anchor_without_returning_it(self) -> None:
        request = AlchemyRecommendRequest(
            query="эпическая фантастика про власть",
            anchors=[AlchemyAnchor(product_id=598)],
            positive=[AlchemyIngredient(kind="style", value="короче")],
            limit=6,
            random_seed=7,
            include_debug=True,
        )
        response = self.engine.recommend_alchemy(request)

        self.assertEqual(len(response.results), 6)
        self.assertNotIn(598, [item.product_id for item in response.results])
        self.assertNotIn(
            "ranking_not_implemented",
            [warning.code for warning in response.warnings],
        )
        self.assertIsNotNone(response.results[0].score_breakdown)
        dune = next(book for book in self.engine.books if book.product_id == 598)
        result_books = {
            book.product_id: book for book in self.engine.books
        }
        self.assertTrue(
            all(result_books[item.product_id].pages < dune.pages for item in response.results)
        )

    def test_alchemy_strict_filters_and_exclusions_are_hard(self) -> None:
        request = AlchemyRecommendRequest(
            query="динамичный детектив",
            negative=[
                AlchemyNegativeIngredient(
                    kind="genre",
                    value="Романтика",
                    mode="exclude",
                )
            ],
            filters=AlchemyFilters(price_max=900, pages_max=300),
            limit=12,
            random_seed=11,
        )
        response = self.engine.recommend_alchemy(request)
        books = {book.product_id: book for book in self.engine.books}

        self.assertGreater(len(response.results), 0)
        for item in response.results:
            book = books[item.product_id]
            self.assertLessEqual(book.price, 900)
            self.assertLessEqual(book.pages, 300)
            self.assertNotIn("Романтика", book.genres)

    def test_alchemy_exact_ingredient_dominates_anchorless_recipe(self) -> None:
        response = self.engine.recommend_alchemy(
            AlchemyRecommendRequest(
                positive=[AlchemyIngredient(kind="mood", value="уютная")],
                limit=6,
                random_seed=17,
            )
        )
        books = {book.product_id: book for book in self.engine.books}

        self.assertTrue(response.results)
        self.assertTrue(
            all("уютная" in books[item.product_id].moods for item in response.results)
        )
        self.assertTrue(
            all("уютная" in item.matched for item in response.results)
        )

    def test_alchemy_avoid_penalizes_but_does_not_filter(self) -> None:
        shared = {
            "query": "история любви",
            "limit": 6,
            "random_seed": 23,
        }
        avoid = self.engine.recommend_alchemy(
            AlchemyRecommendRequest(
                **shared,
                negative=[
                    AlchemyNegativeIngredient(
                        kind="genre",
                        value="Романтика",
                        mode="avoid",
                    )
                ],
            )
        )
        exclude = self.engine.recommend_alchemy(
            AlchemyRecommendRequest(
                **shared,
                negative=[
                    AlchemyNegativeIngredient(
                        kind="genre",
                        value="Романтика",
                        mode="exclude",
                    )
                ],
            )
        )

        self.assertEqual(avoid.total, len(self.engine.books))
        self.assertLess(exclude.total, avoid.total)

    def test_alchemy_surprise_is_deterministic_and_changes_selection(self) -> None:
        def ids(surprise: float) -> list[int]:
            response = self.engine.recommend_alchemy(
                AlchemyRecommendRequest(
                    query="космическая фантастика",
                    surprise=surprise,
                    random_seed=29,
                    limit=12,
                )
            )
            return [item.product_id for item in response.results]

        conservative = ids(0.0)
        adventurous = ids(1.0)
        self.assertEqual(adventurous, ids(1.0))
        self.assertNotEqual(conservative, adventurous)

    def test_alchemy_impossible_recipe_returns_relaxation_proposals(self) -> None:
        response = self.engine.recommend_alchemy(
            AlchemyRecommendRequest(
                query="любая книга",
                filters=AlchemyFilters(price_max=1),
                limit=6,
            )
        )

        self.assertEqual(response.results, [])
        self.assertEqual(response.total, 0)
        self.assertEqual(response.state, "no_candidates")
        self.assertEqual(response.relaxations, ["Расширить диапазон цены"])
        self.assertEqual(response.warnings[0].code, "no_candidates")

    def test_alchemy_unsupported_hard_exclusion_is_downgraded(self) -> None:
        response = self.engine.recommend_alchemy(
            AlchemyRecommendRequest(
                query="небольшая история",
                negative=[
                    AlchemyNegativeIngredient(
                        kind="style",
                        value="эпическая",
                        mode="exclude",
                    )
                ],
                limit=6,
            )
        )

        self.assertEqual(response.total, len(self.engine.books))
        self.assertIn(
            "hard_exclusion_downgraded",
            [warning.code for warning in response.warnings],
        )


class ModelSelectionTest(unittest.TestCase):
    def test_default_model_uses_its_own_index_directory(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.model_key, "small")
        self.assertEqual(settings.model_dimension, 384)
        self.assertEqual(settings.index_path.parent.name, "multilingual-e5-small")
        self.assertFalse(settings.fuzzy_title_resolver)

    def test_experimental_artifacts_and_title_resolver_are_configurable(self) -> None:
        environment = {
            "ML_SEARCH_MODEL_NAME": "experimental-model",
            "ML_SEARCH_LOCAL_MODEL": "experiment/model",
            "ML_SEARCH_INDEX": "experiment/index.npz",
            "ML_SEARCH_MANIFEST": "experiment/manifest.json",
            "ML_SEARCH_FUZZY_TITLE_RESOLVER": "1",
        }
        with patch.dict("os.environ", environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.model_name, "experimental-model")
        self.assertEqual(settings.local_model_path.name, "model")
        self.assertEqual(settings.index_path.name, "index.npz")
        self.assertEqual(settings.manifest_path.name, "manifest.json")
        self.assertTrue(settings.fuzzy_title_resolver)

    def test_explicit_small_overrides_environment(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            expected = Settings.from_env("small")
        with patch.dict("os.environ", {"ML_SEARCH_MODEL": "base"}, clear=True):
            settings = Settings.from_env("small")

        self.assertEqual(settings, expected)

    def test_full_repository_name_is_accepted_in_configuration(self) -> None:
        profile = resolve_model_profile("intfloat/multilingual-e5-small")
        self.assertEqual(profile.key, "small")

    def test_base_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "choose one of: small"):
            resolve_model_profile("base")

    def test_unknown_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "choose one of: small"):
            resolve_model_profile("large")


if __name__ == "__main__":
    unittest.main()
