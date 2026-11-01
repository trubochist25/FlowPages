#!/usr/bin/env python3
"""Safely apply verified metadata and SearchText v2 to the catalog.

The command validates every expected old value and every preview entry before
writing.  By default it creates a candidate file.  ``--apply`` atomically
replaces catalog.json after storing an exact backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "book_catalog"
V2 = DATA / "search-text-v2"
DEFAULT_CATALOG = DATA / "catalog.json"
DEFAULT_PREVIEW = V2 / "generation-preview.json"
DEFAULT_PATCH = V2 / "catalog-metadata-patch.json"
DEFAULT_CANDIDATE = V2 / "catalog-v2-candidate.json"
DEFAULT_REPORT = V2 / "catalog-update-report.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=path.parent)
    try:
        with open(handle, "wb", closefd=True) as stream:
            stream.write(payload)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def validate_catalog(catalog: Any) -> list[dict[str, Any]]:
    if not isinstance(catalog, list) or not catalog:
        raise ValueError("catalog must be a non-empty JSON array")
    ids = [int(book.get("id", 0)) for book in catalog]
    if ids != list(range(1, len(catalog) + 1)):
        raise ValueError("catalog IDs must be sequential and start at 1")
    return catalog


def apply_metadata(catalog: list[dict[str, Any]], patch: dict[str, Any]) -> list[int]:
    by_id = {int(book["id"]): book for book in catalog}
    changed: list[int] = []
    seen: set[int] = set()
    for change in patch.get("changes", []):
        catalog_id = int(change["catalogId"])
        if catalog_id in seen:
            raise ValueError(f"duplicate metadata patch for catalogId {catalog_id}")
        seen.add(catalog_id)
        if catalog_id not in by_id:
            raise ValueError(f"metadata patch references unknown catalogId {catalog_id}")
        book = by_id[catalog_id]
        for field, expected in change.get("expected", {}).items():
            if book.get(field) != expected:
                raise ValueError(
                    f"catalogId {catalog_id}: {field} is {book.get(field)!r}, expected {expected!r}"
                )
        before = json.dumps(book, ensure_ascii=False, sort_keys=True)
        for field, value in change.get("set", {}).items():
            book[field] = value
        if json.dumps(book, ensure_ascii=False, sort_keys=True) != before:
            changed.append(catalog_id)
    return changed


def apply_preview(catalog: list[dict[str, Any]], preview: dict[str, Any]) -> list[int]:
    entries = preview.get("entries", [])
    if preview.get("profiles") != len(catalog) or preview.get("valid") != len(catalog):
        raise ValueError("generation preview is incomplete")
    if preview.get("invalid") != 0 or any(not entry.get("ok") for entry in entries):
        raise ValueError("generation preview contains invalid entries")
    by_id = {int(entry["catalogId"]): entry for entry in entries}
    if set(by_id) != set(range(1, len(catalog) + 1)):
        raise ValueError("generation preview catalog IDs do not match the catalog")
    changed: list[int] = []
    for book in catalog:
        catalog_id = int(book["id"])
        search_text = str(by_id[catalog_id].get("searchText", "")).strip()
        if not search_text:
            raise ValueError(f"catalogId {catalog_id}: empty SearchText v2")
        digest = hashlib.sha256(search_text.encode("utf-8")).hexdigest()
        if book.get("searchText") != search_text:
            changed.append(catalog_id)
        book["searchText"] = search_text
        book["searchProfileVersion"] = "search-profile-v2.0"
        book["searchProfileHash"] = digest
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--metadata-patch", type=Path, default=DEFAULT_PATCH)
    parser.add_argument("--output", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--skip-metadata", action="store_true")
    parser.add_argument("--skip-search-text", action="store_true")
    parser.add_argument("--apply", action="store_true", help="replace --catalog atomically after backup")
    args = parser.parse_args()

    catalog = validate_catalog(read_json(args.catalog))
    original_bytes = args.catalog.read_bytes()
    metadata_ids = [] if args.skip_metadata else apply_metadata(catalog, read_json(args.metadata_patch))
    search_text_ids = [] if args.skip_search_text else apply_preview(catalog, read_json(args.preview))
    output_bytes = serialized(catalog).encode("utf-8")

    target = args.catalog if args.apply else args.output
    backup = None
    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = DATA / "backups" / f"search-text-v2-{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup = backup_dir / "catalog.json"
        shutil.copyfile(args.catalog, backup)
    atomic_write(target, output_bytes)

    report = {
        "catalog": str(args.catalog),
        "target": str(target),
        "applied": bool(args.apply),
        "backup": str(backup) if backup else None,
        "books": len(catalog),
        "metadataChanged": metadata_ids,
        "searchTextChanged": len(search_text_ids),
        "beforeSha256": sha256_bytes(original_bytes),
        "afterSha256": sha256_bytes(output_bytes),
    }
    atomic_write(args.report, serialized(report).encode("utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
