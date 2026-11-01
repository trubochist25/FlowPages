from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = (
    ROOT
    / "ml_search"
    / "experiments"
    / "e5_finetuning_v1"
    / "integration_review_v1"
    / "new-assessment"
    / "test_queries.annotated.json"
)
ENDPOINT = "http://127.0.0.1:8765"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(ENDPOINT + path, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def first_relevant_rank(ids: list[int], expected: set[int]) -> int | None:
    for rank, catalog_id in enumerate(ids[:5], 1):
        if catalog_id in expected:
            return rank
    return None


def standard_cms_results(cases: list[dict], catalog: list[dict]) -> dict[str, list[dict]]:
    """Reproduce the current OpenCart fallback over its frozen import source.

    The production importer sets sort_order to the catalog sequence, name to title,
    tag to the comma-joined tags, model/sku to BOOK-NNNN and isbn/ean from ISBN.
    The fallback requires every whitespace token to occur in either name or tag.
    """
    output: dict[str, list[dict]] = {}
    for case in cases:
        query = case["query"].strip()
        query_norm = query.casefold()
        words = re.sub(r"\s+", " ", query).strip().split(" ")
        words_norm = [word.casefold() for word in words]
        matches = []
        for book in catalog:
            catalog_id = int(book["id"])
            title = str(book["title"])
            title_norm = title.casefold()
            tag_text = ", ".join(dict.fromkeys(str(value) for value in book.get("tags", [])))[:1000]
            tag_norm = tag_text.casefold()
            model = f"book-{catalog_id:04d}"
            isbn = str(book.get("isbn", "")).casefold()
            if (
                all(word in title_norm for word in words_norm)
                or all(word in tag_norm for word in words_norm)
                or query_norm in {model, isbn}
            ):
                matches.append(
                    {
                        "catalog_id": catalog_id,
                        "product_id": catalog_id,
                        "model": model.upper(),
                        "name": title,
                    }
                )
        output[case["query_id"]] = matches[:5]
    return output


def summarise(rows: list[dict]) -> dict:
    ranks = [row["first_relevant_rank"] for row in rows if row["first_relevant_rank"]]
    distribution = Counter(ranks)
    return {
        "queries": len(rows),
        "hits_at_5": len(ranks),
        "hit_rate_at_5": round(len(ranks) / len(rows), 6) if rows else 0.0,
        "mean_first_relevant_rank_on_hits": round(statistics.mean(ranks), 4) if ranks else None,
        "median_first_relevant_rank_on_hits": statistics.median(ranks) if ranks else None,
        "first_relevant_rank_distribution": {str(rank): distribution.get(rank, 0) for rank in range(1, 6)},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = []
    if dataset and "expected_catalog_ids" in dataset[0]:
        for case in dataset:
            cases.append(
                {
                    "query_id": case["query_id"],
                    "family_id": case.get("family_id", case["query_id"]),
                    "category": case["category"],
                    "query": case["query"],
                    "expected_catalog_ids": [int(value) for value in case["expected_catalog_ids"]],
                    "expected_titles": list(case.get("expected_titles", [])),
                    "criteria": case.get("criteria"),
                }
            )
    else:
        for case in dataset:
            expected = sorted(
                {
                    int(judgment["catalog_id"])
                    for judgment in case.get("judgments", [])
                    if int(judgment.get("grade", 0)) == 2
                }
            )
            if expected:
                cases.append(
                    {
                        "query_id": case["query_id"],
                        "family_id": case["family_id"],
                        "category": case["category"],
                        "query": case["query"],
                        "expected_catalog_ids": expected,
                        "expected_titles": [
                            judgment["title"]
                            for judgment in case.get("judgments", [])
                            if int(judgment.get("grade", 0)) == 2
                        ],
                    }
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    frozen_cases = args.output.with_suffix(".cases.json")
    frozen_cases.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")

    catalog = json.loads(
        (ROOT / "data" / "book_catalog" / "catalog.json").read_text(encoding="utf-8")
    )
    baseline = standard_cms_results(cases, catalog)
    health = request_json("/health")
    import_report = json.loads(
        (ROOT / "data" / "book_catalog" / "import-report.json").read_text(encoding="utf-8")
    )
    first_product_id = int(import_report["firstProductId"])

    detailed = []
    for index, case in enumerate(cases, 1):
        response = request_json(
            "/search",
            {
                "query": case["query"],
                "filters": {},
                "sort": "relevance",
                "limit": 5,
                "offset": 0,
                "include_debug": False,
            },
        )
        ml_rows = response.get("results", [])[:5]
        ml_ids = [int(row["product_id"]) - first_product_id + 1 for row in ml_rows]
        baseline_rows = baseline.get(case["query_id"], [])[:5]
        baseline_ids = [int(row["catalog_id"]) for row in baseline_rows if row.get("catalog_id")]
        expected = set(case["expected_catalog_ids"])
        detailed.append(
            {
                **case,
                "standard_cms": {
                    "catalog_ids": baseline_ids,
                    "titles": [row["name"] for row in baseline_rows],
                    "first_relevant_rank": first_relevant_rank(baseline_ids, expected),
                },
                "ml_system": {
                    "catalog_ids": ml_ids,
                    "titles": [row["title"] for row in ml_rows],
                    "first_relevant_rank": first_relevant_rank(ml_ids, expected),
                    "processing_ms": response.get("processing_ms"),
                },
            }
        )
        print(f"[{index:02d}/{len(cases)}] {case['query_id']}", flush=True)

    systems = {}
    for key in ("standard_cms", "ml_system"):
        rows = [
            {
                "category": item["category"],
                "first_relevant_rank": item[key]["first_relevant_rank"],
            }
            for item in detailed
        ]
        by_category = defaultdict(list)
        for row in rows:
            by_category[row["category"]].append(row)
        systems[key] = {
            "overall": summarise(rows),
            "by_category": {category: summarise(values) for category, values in sorted(by_category.items())},
        }

    result = {
        "experiment": "defense_search_relevance_top5",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "comparison": "standard OpenCart lexical fallback versus active local ML search",
            "top_k": 5,
            "metrics": ["first_relevant_rank", "hit_rate_at_5"],
            "inclusion": "only frozen cases with at least one grade-2 relevant catalog book",
            "standard_search": "deterministic reproduction of catalog/controller/product/search.php fallback and catalog/model/catalog/product.php token matching over the exact imported catalog source",
            "relevance_source": "frozen pre-retrieval editorial judgments with catalog evidence",
            "known_limitation": "queries and judgments were authored by one AI agent and are not independent human relevance assessments",
        },
        "dataset": {
            "path": str(args.dataset.resolve().relative_to(ROOT)),
            "sha256": sha256(args.dataset),
            "included_queries": len(cases),
            "families": len({case["family_id"] for case in cases}),
            "categories": dict(sorted(Counter(case["category"] for case in cases).items())),
        },
        "ml_health": health,
        "systems": systems,
        "details": detailed,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"systems": systems, "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
