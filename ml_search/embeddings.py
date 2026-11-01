from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from .text import char_ngrams, tokenize


class Embedder(Protocol):
    model_name: str
    dimension: int

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray: ...

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray: ...


class E5Embedder:
    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        batch_size: int = 32,
        local_model_path: Path | None = None,
        expected_dimension: int | None = None,
    ) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_XET_CACHE", str(cache_dir / "xet"))
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        try:
            from sentence_transformers import SentenceTransformer
            import torch
        except ImportError as error:
            raise RuntimeError(
                "sentence-transformers is not installed; run "
                "`python -m pip install -r ml_search/requirements.txt`"
            ) from error

        default_threads = max(1, min(4, os.cpu_count() or 1))
        torch.set_num_threads(
            int(os.getenv("ML_SEARCH_TORCH_THREADS", str(default_threads)))
        )
        self.model_name = model_name
        self.batch_size = batch_size
        self._lock = threading.Lock()
        load_target = (
            str(local_model_path)
            if local_model_path
            and (local_model_path / "model.safetensors").is_file()
            else model_name
        )
        self._model = SentenceTransformer(
            load_target,
            cache_folder=str(cache_dir),
            device="cpu",
            local_files_only=os.getenv("ML_SEARCH_OFFLINE", "0") == "1",
        )
        dimension_getter = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        self.dimension = int(dimension_getter())
        if expected_dimension is not None and self.dimension != expected_dimension:
            raise RuntimeError(
                f"Embedding model {model_name} has dimension {self.dimension}; "
                f"expected {expected_dimension}. Check ML_SEARCH_LOCAL_MODEL."
            )

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode([f"query: {text}" for text in texts])

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode([f"passage: {text}" for text in texts])

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        with self._lock:
            return np.asarray(
                self._model.encode(
                    list(texts),
                    batch_size=self.batch_size,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=len(texts) > self.batch_size,
                ),
                dtype=np.float32,
            )


class HashingEmbedder:
    """Deterministic lightweight backend for tests, never the production default."""

    def __init__(self, dimension: int = 384) -> None:
        self.model_name = "hashing-test-backend"
        self.dimension = dimension

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            features = [*tokenize(text), *char_ngrams(text, 3, 4)]
            for feature in features:
                digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
                value = int.from_bytes(digest, "little")
                column = value % self.dimension
                sign = 1.0 if value & 1 else -1.0
                matrix[row, column] += sign
            norm = float(np.linalg.norm(matrix[row]))
            if norm:
                matrix[row] /= norm
        return matrix
