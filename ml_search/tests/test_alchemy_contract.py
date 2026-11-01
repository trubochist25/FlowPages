from __future__ import annotations

import unittest

from pydantic import ValidationError

from ml_search.alchemy import AlchemyContractError, AlchemyService
from ml_search.app import create_app
from ml_search.schemas import (
    AlchemyAnalyzeRequest,
    AlchemyAnchor,
    AlchemyFilters,
    AlchemyIngredient,
    AlchemyNegativeIngredient,
    AlchemyRecommendRequest,
)


class AlchemySchemaTest(unittest.TestCase):
    def test_valid_recipe_accepts_hybrid_input(self) -> None:
        request = AlchemyRecommendRequest(
            query="камерная тайна для дождливого вечера",
            anchors=[
                AlchemyAnchor(
                    product_id=209,
                    weight=0.7,
                    aspects=["загадка", "структура"],
                )
            ],
            positive=[
                AlchemyIngredient(kind="mood", value="уютная", weight=0.8),
                AlchemyIngredient(kind="mood", value="загадочная"),
            ],
            negative=[
                AlchemyNegativeIngredient(
                    kind="genre",
                    value="мистика",
                    mode="exclude",
                ),
                AlchemyNegativeIngredient(kind="content", value="жестокость"),
            ],
            filters=AlchemyFilters(pages_max=450),
            surprise=0.35,
            limit=12,
        )
        self.assertEqual(request.anchors[0].product_id, 209)
        self.assertEqual(request.negative[1].mode, "avoid")

    def test_recipe_requires_a_creative_input(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyRecommendRequest(filters=AlchemyFilters(pages_max=300))

    def test_recipe_rejects_more_than_three_anchors(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyRecommendRequest(
                anchors=[AlchemyAnchor(product_id=value) for value in range(1, 5)]
            )

    def test_recipe_rejects_duplicate_anchors(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyRecommendRequest(
                anchors=[
                    AlchemyAnchor(product_id=209),
                    AlchemyAnchor(product_id=209),
                ]
            )

    def test_recipe_rejects_duplicate_anchor_aspects(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyAnchor(product_id=209, aspects=["Загадка", "загадка"])

    def test_recipe_rejects_contradictory_ingredients(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyRecommendRequest(
                positive=[AlchemyIngredient(kind="mood", value="уютная")],
                negative=[
                    AlchemyNegativeIngredient(kind="mood", value="УЮТНАЯ")
                ],
            )

    def test_content_exclusion_requires_verified_metadata(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyRecommendRequest(
                query="детектив",
                negative=[
                    AlchemyNegativeIngredient(
                        kind="content",
                        value="жестокость",
                        mode="exclude",
                    )
                ],
            )

    def test_filters_retain_strict_range_validation(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyFilters(pages_min=500, pages_max=200)

    def test_contract_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyAnalyzeRequest(query="уютная книга", unexpected=True)

    def test_sign_only_queries_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AlchemyAnalyzeRequest(query="!!! …")
        with self.assertRaises(ValidationError):
            AlchemyRecommendRequest(query="???")


class AlchemyServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AlchemyService({53, 160, 209, 598})

    def test_analysis_extracts_supported_ingredients(self) -> None:
        response = self.service.analyze(
            AlchemyAnalyzeRequest(query="  Уютная книга для вечера  ")
        )
        self.assertEqual(response.query, "Уютная книга для вечера")
        self.assertEqual(response.normalized_query, "уютная книга для вечера")
        self.assertEqual(response.residual_query, "для вечера")
        self.assertIn("уютная", [item.value for item in response.positive])
        self.assertEqual(response.unresolved_fragments, ["для вечера"])
        self.assertEqual(response.warnings, [])

    def test_recommendation_contract_keeps_full_and_residual_queries(self) -> None:
        request = AlchemyRecommendRequest(
            query="уютная книга для вечера",
            residual_query="для вечера",
            positive=[AlchemyIngredient(kind="mood", value="уютная")],
        )

        self.assertEqual(request.query, "уютная книга для вечера")
        self.assertEqual(request.residual_query, "для вечера")

    def test_service_without_vectors_reports_unavailable_ranking(self) -> None:
        response = self.service.recommend(
            AlchemyRecommendRequest(anchors=[AlchemyAnchor(product_id=598)])
        )
        self.assertEqual(response.total, 0)
        self.assertEqual(response.results, [])
        self.assertEqual(response.warnings[0].code, "ranking_unavailable")
        self.assertEqual(response.state, "unavailable")

    def test_unknown_anchor_is_rejected(self) -> None:
        with self.assertRaises(AlchemyContractError) as context:
            self.service.recommend(
                AlchemyRecommendRequest(anchors=[AlchemyAnchor(product_id=9999)])
            )
        self.assertEqual(context.exception.code, "unknown_anchor")


class AlchemyOpenApiTest(unittest.TestCase):
    def test_alchemy_routes_are_published(self) -> None:
        schema = create_app().openapi()
        self.assertIn("/alchemy/analyze", schema["paths"])
        self.assertIn("/alchemy/recommend", schema["paths"])
        self.assertIn(
            "AlchemyRecommendRequest",
            schema["components"]["schemas"],
        )


if __name__ == "__main__":
    unittest.main()
