from __future__ import annotations

import unittest

import numpy as np

from ml_search.catalog import load_catalog, passage_for_embedding
from ml_search.config import Settings
from ml_search.embeddings import HashingEmbedder
from ml_search.index import VectorIndex
from ml_search.recommendations import RecommendationEngine
from ml_search.schemas import RecommendationRequest, RecommendationSignal


class RecommendationEngineTest(unittest.TestCase):
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
        cls.books = books
        cls.engine = RecommendationEngine(
            books,
            VectorIndex(product_ids, vectors),
        )

    def test_empty_or_unknown_history_uses_deterministic_cold_start(self) -> None:
        empty = self.engine.recommend(
            RecommendationRequest(limit=15, random_seed=42, include_debug=True)
        )
        repeated = self.engine.recommend(
            RecommendationRequest(limit=15, random_seed=42)
        )
        unknown = self.engine.recommend(
            RecommendationRequest(
                signals=[
                    RecommendationSignal(product_id=999999, kind="view")
                ],
                limit=15,
                random_seed=42,
            )
        )
        self.assertEqual(len(empty.results), 15)
        self.assertEqual(empty.signals_used, 0)
        self.assertEqual(
            [item.product_id for item in empty.results],
            [item.product_id for item in repeated.results],
        )
        self.assertEqual(
            [item.product_id for item in empty.results],
            [item.product_id for item in unknown.results],
        )
        self.assertTrue(all(item.score_breakdown for item in empty.results))

    def test_strong_actions_are_used_as_seeds_but_not_recommended(self) -> None:
        view, wishlist, cart, purchase = self.books[:4]
        response = self.engine.recommend(
            RecommendationRequest(
                signals=[
                    RecommendationSignal(product_id=view.product_id, kind="view"),
                    RecommendationSignal(
                        product_id=wishlist.product_id, kind="wishlist"
                    ),
                    RecommendationSignal(product_id=cart.product_id, kind="cart"),
                    RecommendationSignal(
                        product_id=purchase.product_id, kind="purchase"
                    ),
                ],
                limit=15,
            )
        )
        product_ids = {result.product_id for result in response.results}
        self.assertTrue(response.results)
        self.assertFalse(
            product_ids.intersection(
                {wishlist.product_id, cart.product_id, purchase.product_id}
            )
        )

    def test_viewed_books_are_rare_and_not_at_the_front(self) -> None:
        viewed = self.books[:20]
        response = self.engine.recommend(
            RecommendationRequest(
                signals=[
                    RecommendationSignal(product_id=book.product_id, kind="view")
                    for book in viewed
                ],
                limit=15,
                include_debug=True,
            )
        )
        revisits = [item for item in response.results if item.already_viewed]
        self.assertLessEqual(len(revisits), 1)
        self.assertFalse(any(item.already_viewed for item in response.results[:4]))
        self.assertTrue(
            all(item.score_breakdown is not None for item in response.results)
        )

    def test_explore_strategy_is_distinct_and_diverse(self) -> None:
        signal = RecommendationSignal(
            product_id=self.books[0].product_id,
            kind="view",
        )
        balanced = self.engine.recommend(
            RecommendationRequest(
                signals=[signal],
                limit=15,
                random_seed=42,
            )
        )
        explore = self.engine.recommend(
            RecommendationRequest(
                signals=[signal],
                limit=15,
                random_seed=42,
                strategy="explore",
                include_debug=True,
            )
        )

        balanced_ids = [item.product_id for item in balanced.results]
        explore_ids = [item.product_id for item in explore.results]
        books_by_id = {book.product_id: book for book in self.books}
        explore_authors = {
            books_by_id[product_id].author for product_id in explore_ids
        }

        self.assertEqual(len(explore_ids), 15)
        self.assertEqual(len(set(explore_ids)), 15)
        self.assertNotEqual(explore_ids, balanced_ids)
        self.assertGreaterEqual(len(explore_authors), 10)
        self.assertTrue(
            all(
                item.score_breakdown
                and "genre_novelty" in item.score_breakdown
                and "random" in item.score_breakdown
                for item in explore.results
            )
        )

    def test_similar_strategy_uses_anchor_without_recommending_it(self) -> None:
        anchor = self.books[0]
        request = RecommendationRequest(
            strategy="similar",
            anchor_product_id=anchor.product_id,
            limit=12,
            random_seed=123,
            include_debug=True,
        )
        response = self.engine.recommend(request)
        repeated = self.engine.recommend(request)
        product_ids = [item.product_id for item in response.results]
        books_by_id = {book.product_id: book for book in self.books}
        authors = {books_by_id[product_id].author for product_id in product_ids}

        self.assertEqual(len(product_ids), 12)
        self.assertEqual(len(set(product_ids)), 12)
        self.assertNotIn(anchor.product_id, product_ids)
        self.assertGreaterEqual(len(authors), 8)
        self.assertEqual(
            product_ids,
            [item.product_id for item in repeated.results],
        )
        self.assertTrue(
            all(
                item.score_breakdown
                and "semantic" in item.score_breakdown
                and "random" in item.score_breakdown
                for item in response.results
            )
        )

    def test_similar_strategy_requires_an_anchor(self) -> None:
        with self.assertRaises(ValueError):
            RecommendationRequest(strategy="similar")


if __name__ == "__main__":
    unittest.main()
