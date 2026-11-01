from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ml_search.catalog import file_sha256, load_catalog, passage_for_embedding
from ml_search.config import Settings
from ml_search.embeddings import E5Embedder
from ml_search.index import VectorIndex


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "integration_review_v1" / "description_overlay_v1"
MODEL_NAME = "multilingual-e5-small-finetuned-lr1e-5-epoch3"
ADDITIONS = {
    743: (
        " Поисковые детали: потеря работы и профессиональной опоры; "
        "постепенное возвращение к жизни; поддерживающая история о новом начале."
    ),
    38: (
        " Поисковые детали: душный жаркий Петербург летом; тесные комнаты и "
        "улицы усиливают тревогу, лихорадочное состояние и ощущение ловушки."
    ),
    46: (
        " Поисковые детали: семейные разногласия сестёр связаны с взрослением, "
        "разными характерами, любовью, работой и самостоятельностью."
    ),
    76: (
        " Поисковые детали: недоверие и соперничество внутри компании друзей; "
        "скрытые мотивы, соучастие и постепенное разрушение дружбы."
    ),
}


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"Output directory already exists: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    os.environ["ML_SEARCH_OFFLINE"] = "1"
    settings = Settings.from_env("small")
    books = load_catalog(settings.catalog_path, settings.import_report_path)
    source_index = VectorIndex.load(
        ROOT / "comparison" / "index" / "book-index.npz"
    )
    model_path = ROOT / "limited_experiment" / "selected-model"
    embedder = E5Embedder(
        MODEL_NAME,
        settings.model_cache_dir,
        settings.batch_size,
        model_path,
        settings.model_dimension,
    )
    catalog_to_position = {
        book.catalog_id: position for position, book in enumerate(books)
    }
    enriched = [
        replace(books[catalog_to_position[catalog_id]], search_text=(
            books[catalog_to_position[catalog_id]].search_text + addition
        ))
        for catalog_id, addition in ADDITIONS.items()
    ]
    replacement_vectors = embedder.encode_passages(
        [passage_for_embedding(book) for book in enriched]
    )
    vectors = source_index.vectors.copy()
    for (catalog_id, _), vector in zip(ADDITIONS.items(), replacement_vectors):
        vectors[catalog_to_position[catalog_id]] = vector
    index_path = OUTPUT / "book-index.npz"
    np.savez_compressed(
        index_path,
        product_ids=source_index.product_ids,
        vectors=vectors,
    )
    overlay_text = json.dumps(ADDITIONS, ensure_ascii=False, sort_keys=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_name": MODEL_NAME,
        "dimension": int(vectors.shape[1]),
        "books": len(books),
        "catalog_sha256": file_sha256(settings.catalog_path),
        "index": str(index_path.resolve()),
        "base_index": str((ROOT / "comparison" / "index" / "book-index.npz").resolve()),
        "overlaid_catalog_ids": list(ADDITIONS),
        "overlay_sha256": hashlib.sha256(overlay_text.encode("utf-8")).hexdigest(),
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT / "overlay.json").write_text(
        json.dumps(ADDITIONS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=True))


if __name__ == "__main__":
    main()
