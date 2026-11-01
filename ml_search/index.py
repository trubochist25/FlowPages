from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .catalog import file_sha256, passage_for_embedding
from .embeddings import Embedder
from .models import Book


class VectorIndex:
    def __init__(self, product_ids: np.ndarray, vectors: np.ndarray) -> None:
        if vectors.ndim != 2:
            raise ValueError("Embedding matrix must be two-dimensional")
        if len(product_ids) != len(vectors):
            raise ValueError("Product IDs and embedding matrix have different sizes")
        self.product_ids = product_ids.astype(np.int32, copy=False)
        self.vectors = vectors.astype(np.float32, copy=False)

    @classmethod
    def load(cls, index_path: Path) -> "VectorIndex":
        if not index_path.is_file():
            raise FileNotFoundError(
                f"Search index not found at {index_path}. Run build-index first."
            )
        with np.load(index_path, allow_pickle=False) as data:
            return cls(data["product_ids"], data["vectors"])

    def similarities(self, query_vector: np.ndarray) -> np.ndarray:
        vector = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        if vector.shape[0] != self.vectors.shape[1]:
            raise ValueError("Query and catalogue embedding dimensions do not match")
        return self.vectors @ vector


def build_index(
    books: list[Book],
    embedder: Embedder,
    index_path: Path,
    manifest_path: Path,
    catalog_path: Path,
) -> dict:
    passages = [passage_for_embedding(book) for book in books]
    vectors = embedder.encode_passages(passages)
    product_ids = np.asarray([book.product_id for book in books], dtype=np.int32)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    temp_handle, temp_name = tempfile.mkstemp(
        prefix="book-index-", suffix=".npz", dir=index_path.parent
    )
    os.close(temp_handle)
    temp_path = Path(temp_name)
    try:
        np.savez_compressed(temp_path, product_ids=product_ids, vectors=vectors)
        temp_path.replace(index_path)
    finally:
        temp_path.unlink(missing_ok=True)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_name": embedder.model_name,
        "dimension": int(vectors.shape[1]),
        "books": len(books),
        "catalog_sha256": file_sha256(catalog_path),
        "index": str(index_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
