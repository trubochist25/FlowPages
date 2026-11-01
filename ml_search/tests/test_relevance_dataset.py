from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from ml_search.calibration import (
    ALCHEMY_ANCHOR_CALIBRATION,
    ALCHEMY_QUERY_CALIBRATION,
)
from ml_search.evaluate_relevance import _contrast_scores, _select_threshold


DATASET = Path(__file__).resolve().parents[1] / "relevance_negative_queries.json"


class RelevanceDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DATASET.read_text(encoding="utf-8"))
        cls.cases = cls.payload["cases"]

    def test_negative_dataset_has_planned_coverage(self) -> None:
        counts = Counter(case["category"] for case in self.cases)

        self.assertGreaterEqual(len(self.cases), 60)
        self.assertGreaterEqual(counts["gibberish"], 10)
        self.assertGreaterEqual(counts["out_of_domain"], 20)
        self.assertGreaterEqual(counts["catalog_gap"], 15)
        self.assertGreaterEqual(counts["too_vague"], 10)

    def test_negative_dataset_contract_is_stable(self) -> None:
        identifiers = [case["id"] for case in self.cases]

        self.assertEqual(len(identifiers), len(set(identifiers)))
        for case in self.cases:
            self.assertTrue(case["query"].strip())
            self.assertTrue(set(case["targets"]).issubset({"search", "alchemy"}))
            self.assertTrue(case["targets"])
            self.assertIn(case["expected_action"], {"reject", "clarify"})

    def test_threshold_selection_keeps_recall_and_rejects_negatives(self) -> None:
        result = _select_threshold(
            positives=[0.72, 0.78, 0.82, 0.87, 0.91, 0.95, 0.96, 0.97, 0.98, 0.99],
            negatives=[0.10, 0.20, 0.30, 0.40, 0.50],
        )

        self.assertGreater(result["threshold"], 0.50)
        self.assertGreaterEqual(result["positive_recall"], 0.90)
        self.assertEqual(result["negative_rejection"], 1.0)
        self.assertTrue(result["meets_targets"])

    def test_alchemy_calibration_ranges_are_fixed_and_distinct(self) -> None:
        self.assertAlmostEqual(
            ALCHEMY_QUERY_CALIBRATION.apply([0.82])[0],
            0.5,
            delta=1e-6,
        )
        self.assertAlmostEqual(
            ALCHEMY_ANCHOR_CALIBRATION.apply([0.835])[0],
            0.5,
            delta=1e-6,
        )
        self.assertNotEqual(
            ALCHEMY_QUERY_CALIBRATION.floor,
            ALCHEMY_ANCHOR_CALIBRATION.floor,
        )

    def test_contrast_scores_measure_excess_over_query_background(self) -> None:
        results = [
            SimpleNamespace(
                product_id=index,
                relevance_score=score,
                score_breakdown=None,
            )
            for index, score in enumerate((0.90, 0.80, 0.70, 0.60), start=1)
        ]

        adjusted = _contrast_scores(results, 50)

        self.assertGreater(adjusted[1], adjusted[2])
        self.assertEqual(adjusted[3], 0.0)
        self.assertEqual(adjusted[4], 0.0)


if __name__ == "__main__":
    unittest.main()
