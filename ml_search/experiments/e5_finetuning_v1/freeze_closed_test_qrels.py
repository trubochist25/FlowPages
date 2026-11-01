from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ASSESSMENT = ROOT / "integration_review_v1" / "new-assessment"
DRAFT = ASSESSMENT / "test_queries.draft.json"
OUTPUT = ASSESSMENT / "test_queries.annotated.json"
MANIFEST = ASSESSMENT / "closed-test-freeze-manifest.json"
CATALOG = ROOT.parents[2] / "data" / "book_catalog" / "catalog.json"

# Grades were chosen from catalog profiles and keyword candidates without running
# the selected search configuration. 2 = good, 1 = partial. Missing families are
# catalog-supported no-match judgments.
QRELS: dict[str, list[tuple[int, int]]] = {
    "NEW-F01": [(659, 2)],
    "NEW-F03": [(622, 2), (27, 1)],
    "NEW-F04": [(326, 2), (267, 1)],
    "NEW-F05": [(464, 2), (140, 1)],
    "NEW-F09": [(592, 2)],
    "NEW-F10": [(178, 2), (842, 1)],
    "NEW-F11": [(575, 2)],
    "NEW-F13": [(228, 2)],
    "NEW-F14": [(746, 1)],
    "NEW-F16": [(872, 2)],
    "NEW-F19": [(613, 2), (225, 1)],
    "NEW-F20": [(924, 1)],
    "NEW-F21": [(203, 2)],
    "NEW-F22": [(92, 2)],
    "NEW-F24": [(40, 1)],
    "NEW-F26": [(423, 1)],
    "NEW-F29": [(279, 2)],
    "NEW-F30": [(743, 1)],
    "NEW-F31": [(177, 2), (599, 1)],
    "NEW-F32": [(184, 2)],
    "NEW-F33": [(343, 2)],
    "NEW-F35": [(707, 2), (368, 1)],
    "NEW-F36": [(42, 2), (193, 2), (544, 2), (238, 1)],
    "NEW-F38": [(262, 2), (266, 1)],
    "NEW-F40": [(57, 2)],
    "NEW-F41": [(282, 2), (748, 2)],
    "NEW-F43": [(464, 2)],
    "NEW-F44": [(37, 2)],
    "NEW-F15": [],
    "NEW-F28": [],
    "NEW-F46": [],
    "NEW-F47": [],
    "NEW-F49": [],
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUTPUT.exists() or MANIFEST.exists():
        raise RuntimeError("Closed-test qrels are already frozen")
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    policy = json.loads((ASSESSMENT / "split-policy.json").read_text(encoding="utf-8"))
    if digest(DRAFT) != policy["freeze_draft_sha256"][DRAFT.name]:
        raise RuntimeError("Closed-test draft changed after its original freeze")
    catalog = {book["id"]: book for book in json.loads(CATALOG.read_text(encoding="utf-8"))}
    families = {row["family_id"] for row in draft}
    if families != set(QRELS):
        raise RuntimeError(f"Qrel families differ from draft: {families ^ set(QRELS)}")
    annotated = []
    for row in draft:
        judgments = []
        for catalog_id, grade in QRELS[row["family_id"]]:
            book = catalog[catalog_id]
            judgments.append({
                "catalog_id": catalog_id,
                "title": book["title"],
                "author": book["author"],
                "grade": grade,
                "label": "хорошо подходит" if grade == 2 else "частично подходит",
                "reason": (
                    "Каталожный профиль подтверждает основное намерение запроса."
                    if grade == 2
                    else "Профиль подтверждает часть намерения, но не все обязательные условия."
                ),
                "evidence": book["searchText"],
                "evidence_source": f"data/book_catalog/catalog.json#id={catalog_id}",
                "profile_sha256": hashlib.sha256(book["searchText"].encode("utf-8")).hexdigest(),
            })
        copy = dict(row)
        copy.update({
            "judgments": judgments,
            "expected_empty": not judgments,
            "annotation_status": "agent_editorial_frozen_before_closed_test_retrieval",
            "model_evaluation_performed": False,
            "intent_criterion": row["query"],
            "unjudged_policy": "unknown_not_negative",
        })
        annotated.append(copy)
    OUTPUT.write_text(json.dumps(annotated, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_before_first_selected_configuration_retrieval",
        "queries": len(annotated),
        "families": len(families),
        "families_with_grade2": sum(any(grade == 2 for _, grade in QRELS[family]) for family in families),
        "families_partial_only": sum(bool(QRELS[family]) and not any(grade == 2 for _, grade in QRELS[family]) for family in families),
        "families_expected_empty": sum(not QRELS[family] for family in families),
        "draft_sha256": digest(DRAFT),
        "annotated_sha256": digest(OUTPUT),
        "catalog_sha256": digest(CATALOG),
        "selected_configuration": json.loads((ROOT / "multivector_integration_v1" / "DECISION.json").read_text(encoding="utf-8"))["configuration"],
        "limitations": [
            "The queries and judgments were authored by the same AI agent.",
            "Judgments are sparse and based on catalog search profiles, not full books.",
            "Keyword candidate generation was used before annotation; selected-model retrieval was not used.",
            "This is not independent human relevance assessment or real-user traffic.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
