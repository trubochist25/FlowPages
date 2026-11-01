from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SimilarityCalibration:
    """A fixed, catalogue-level linear calibration for cosine similarities."""

    name: str
    floor: float
    ceiling: float

    def apply(self, values: np.ndarray) -> np.ndarray:
        if self.ceiling <= self.floor:
            raise ValueError("calibration ceiling must be greater than floor")
        values = np.asarray(values, dtype=np.float32)
        return np.clip(
            (values - self.floor) / (self.ceiling - self.floor),
            0.0,
            1.0,
        ).astype(np.float32, copy=False)

    def as_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "floor": self.floor,
            "ceiling": self.ceiling,
        }


# Fixed against the bundled multilingual-e5-small index. Unlike per-request
# quantiles, these bounds preserve absolute confidence: an unrelated query can
# no longer manufacture a score of 1 merely by being the best weak candidate.
ALCHEMY_QUERY_CALIBRATION = SimilarityCalibration(
    name="alchemy-query-v1",
    floor=0.76,
    ceiling=0.88,
)
ALCHEMY_ANCHOR_CALIBRATION = SimilarityCalibration(
    name="alchemy-anchor-v1",
    floor=0.79,
    ceiling=0.88,
)


__all__ = [
    "ALCHEMY_ANCHOR_CALIBRATION",
    "ALCHEMY_QUERY_CALIBRATION",
    "SimilarityCalibration",
]
