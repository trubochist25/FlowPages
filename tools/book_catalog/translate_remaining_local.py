from __future__ import annotations

import json
import re
from pathlib import Path

import torch
from transformers import MarianMTModel, MarianTokenizer


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "book_catalog"
SOURCE_PATH = DATA / "work-metadata-cache.json"
OUTPUT_PATH = DATA / "work-metadata-ru.json"
MODEL_DIR = DATA / "translation-model" / "opus-mt-en-ru"
MODEL_ID = "Helsinki-NLP/opus-mt-en-ru"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: str) -> str:
    value = re.sub(r"<[^>]*>", " ", value or "")
    value = re.sub(r"\[(.*?)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[*_#`]+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def chunks(value: str, tokenizer: MarianTokenizer, limit: int = 380) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+", clean(value))
    result: list[str] = []
    current: list[str] = []
    for piece in pieces:
        candidate = " ".join(current + [piece])
        if current and len(tokenizer.encode(candidate, add_special_tokens=True)) > limit:
            result.append(" ".join(current))
            current = [piece]
        else:
            current.append(piece)
    if current:
        result.append(" ".join(current))
    return result


def main() -> None:
    source = read_json(SOURCE_PATH)
    translated = read_json(OUTPUT_PATH)
    pending = [
        item for item in source.values()
        if item.get("description") and not translated.get(item["workKey"], {}).get("descriptionRu")
    ]
    print(f"Pending local translations: {len(pending)}")
    if not pending:
        return

    model_source = str(MODEL_DIR) if MODEL_DIR.exists() else MODEL_ID
    tokenizer = MarianTokenizer.from_pretrained(model_source)
    model = MarianMTModel.from_pretrained(model_source)
    if not MODEL_DIR.exists():
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        tokenizer.save_pretrained(MODEL_DIR)
        model.save_pretrained(MODEL_DIR)
    model.eval()

    for index, item in enumerate(pending, start=1):
        source_chunks = chunks(item["description"], tokenizer)
        rendered = []
        for offset in range(0, len(source_chunks), 4):
            batch = source_chunks[offset:offset + 4]
            encoded = tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=450)
            with torch.inference_mode():
                generated = model.generate(**encoded, max_new_tokens=500, num_beams=3)
            rendered.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
        translated[item["workKey"]] = {
            "catalogId": item["catalogId"],
            "workKey": item["workKey"],
            "descriptionRu": clean(" ".join(rendered)),
            "sourceUrl": item["sourceUrl"],
            "translationEngine": MODEL_ID,
        }
        OUTPUT_PATH.write_text(json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if index % 10 == 0 or index == len(pending):
            print(f"Translated locally {index}/{len(pending)}")


if __name__ == "__main__":
    main()
