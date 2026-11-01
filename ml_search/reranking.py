from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


class MultiVectorReranker:
    """Blend the main rank with the best matching semantic field of each book."""

    REQUIRED_FIELDS = ("plot", "annotation", "structured", "taxonomy")

    def __init__(self, vectors: dict[str, np.ndarray], alpha: float = 0.60) -> None:
        self.vectors = vectors
        self.alpha = alpha

    @classmethod
    def load(
        cls,
        path: Path,
        expected_books: int,
        expected_dimension: int,
        alpha: float = 0.60,
        expected_catalog_sha256: str | None = None,
        expected_model_name: str | None = None,
    ) -> "MultiVectorReranker":
        if not path.is_file():
            raise RuntimeError(f"Multi-vector index is missing: {path}")
        if expected_catalog_sha256 is not None or expected_model_name is not None:
            manifest_path = path.with_name(f"{path.stem}.manifest.json")
            if not manifest_path.is_file():
                raise RuntimeError(f"Multi-vector manifest is missing: {manifest_path}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                expected_catalog_sha256 is not None
                and manifest.get("catalog_sha256") != expected_catalog_sha256
            ):
                raise RuntimeError("Multi-vector index was built for a different catalogue")
            if (
                expected_model_name is not None
                and manifest.get("model_name") != expected_model_name
            ):
                raise RuntimeError("Multi-vector index was built with a different model")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if manifest.get("index_sha256") != digest:
                raise RuntimeError("Multi-vector index checksum differs from its manifest")
        with np.load(path) as data:
            missing = [name for name in cls.REQUIRED_FIELDS if name not in data.files]
            if missing:
                raise RuntimeError(f"Multi-vector index lacks fields: {', '.join(missing)}")
            vectors = {name: np.asarray(data[name], dtype=np.float32) for name in cls.REQUIRED_FIELDS}
        expected_shape = (expected_books, expected_dimension)
        invalid = {name: matrix.shape for name, matrix in vectors.items() if matrix.shape != expected_shape}
        if invalid:
            raise RuntimeError(
                f"Multi-vector index shapes differ from {expected_shape}: {invalid}"
            )
        return cls(vectors, alpha)

    def scores(
        self,
        query_vector: np.ndarray,
        book_positions: list[int],
        base_scores: np.ndarray,
    ) -> np.ndarray:
        if not book_positions:
            return base_scores
        positions = np.asarray(book_positions, dtype=np.int32)
        base = np.asarray(base_scores, dtype=np.float32)
        field_score = np.maximum.reduce(
            [self.vectors[name][positions] @ query_vector for name in self.REQUIRED_FIELDS]
        )
        base_range = float(np.ptp(base))
        field_range = float(np.ptp(field_score))
        base_scaled = (base - float(base.min())) / max(base_range, 1e-6)
        field_scaled = (field_score - float(field_score.min())) / max(field_range, 1e-6)
        return (1.0 - self.alpha) * base_scaled + self.alpha * field_scaled
