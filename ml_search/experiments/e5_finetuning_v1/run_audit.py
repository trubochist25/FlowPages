"""Read-only audit of the original model; never evaluates dev/test sets."""
from pathlib import Path
import os
import sys
import json
import hashlib
import collections
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
os.environ["ML_SEARCH_OFFLINE"] = "1"
from ml_search.config import Settings
from ml_search.cli import make_embedder
from ml_search.search import SearchEngine
from ml_search.schemas import SearchRequest

OUT = Path(__file__).parent
def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    settings = Settings.from_env("small")
    model = make_embedder(settings, "e5")
    engine = SearchEngine.from_settings(settings, model)
    books = engine.books
    cases = json.loads((OUT / "audit_cases.json").read_text(encoding="utf-8"))
    tokenizer = model._model.tokenizer
    limit = model._model.max_seq_length
    token_rows = []
    for book in books:
        text = "passage: " + book.search_text
        encoded = tokenizer(text, truncation=False, return_offsets_mapping=True)
        tokens = encoded["input_ids"]
        offset = tokenizer(text, truncation=True, max_length=limit, return_offsets_mapping=True)["offset_mapping"]
        end = max((b for a, b in offset), default=0)
        token_rows.append({"catalog_id":book.catalog_id,"title":book.title,"tokens":len(tokens),
                           "truncated":len(tokens)>limit,"retained_end_character":end,
                           "lost_tail":text[end:] if len(tokens)>limit else ""})
    lengths = np.array([r["tokens"] for r in token_rows])
    write("description-lengths.json", {"max_seq_length":limit,"books":len(books),
        "min":int(lengths.min()),"median":float(np.median(lengths)),"p95":float(np.percentile(lengths,95)),
        "max":int(lengths.max()),"truncated":sum(r["truncated"] for r in token_rows),"results":token_rows})
    intents = [engine.analyze(case["query"]) for case in cases]
    texts = sorted({t for case,intent in zip(cases,intents) for t in
                    (case["query"],intent.corrected_query,intent.residual_query) if t})
    vectors = model.encode_queries(texts)
    cache = dict(zip(texts,vectors))
    class Cached:
        model_name=model.model_name
        dimension=model.dimension
        def encode_queries(self,texts): return np.stack([cache[t] for t in texts])
    engine.embedder = Cached()
    rows=[]
    for number,(case,intent) in enumerate(zip(cases,intents),1):
        raw = engine.vector_index.similarities(cache[case["query"]])
        corrected = engine.vector_index.similarities(cache[intent.corrected_query])
        target = next(i for i,b in enumerate(books) if b.catalog_id==case["book_id"])
        target_book = books[target]
        assert case["evidence"] in target_book.search_text, (number,case["evidence"])
        scores=[]
        for i,b in enumerate(books):
            lexical,entity = engine._lexical_score(b,intent)
            metadata,reasons = engine._metadata_score(b,intent)
            popularity = np.log1p(b.popularity)/np.log1p(engine._max_popularity)
            rating = engine._rating_score(b,None)
            args = dict(semantic=float(np.clip((corrected[i]+1)/2,0,1)),lexical=lexical,
                        metadata=metadata,popularity=float(popularity),rating=rating,entity_match=entity,
                        has_query=True,has_metadata_preferences=engine._has_metadata_preferences(intent))
            total = engine._combine_scores(**args)
            stages={k:engine._combine_scores(**{**args,k:0.0}) for k in ("lexical","metadata","popularity","rating")}
            scores.append({**args,"total":total,"metadata_reasons":reasons,"ablations":stages})
        def order(values):
            return sorted(range(len(books)),key=lambda i:(values[i],books[i].popularity),reverse=True)
        def rank(values): return order(values).index(target)+1
        full_order=order([s["total"] for s in scores])
        floor=max(.5,scores[full_order[0]]["total"]-.16)
        pool=[i for i in full_order if scores[i]["total"]>=floor][:engine.max_results]
        response=engine.search(SearchRequest(query=case["query"],limit=50,include_debug=True))
        assert [books[i].product_id for i in pool]==[r.product_id for r in response.results], number
        parser_flags=[]
        if "История" in intent.preferred_genres:
            parser_flags.append("Слово «история» распознано как жанр «История», хотя речь о художественном повествовании.")
        if intent.matched_titles or intent.matched_authors:
            parser_flags.append("Найдено название/автор внутри запроса без явного навигационного намерения; требуется проверка сущности.")
        if "без быстрого темпа" in case["query"] and "быстрый" in intent.preferred_paces:
            parser_flags.append("Отрицание темпа разобрано как предпочтение быстрого темпа.")
        rows.append({"audit_id":f"A{number:02}",**case,"title":target_book.title,
            "profile":target_book.search_text,"intent":intent.as_dict(),"parser_flags":parser_flags,
            "raw_semantic_rank":rank(raw),"corrected_semantic_rank":rank(corrected),
            "full_rank_before_pool":full_order.index(target)+1,
            "returned_rank":pool.index(target)+1 if target in pool else None,
            "pool_size":len(pool),"pool_floor":floor,"target_scores":scores[target],
            "rank_without_signal":{k:rank([s["ablations"][k] for s in scores]) for k in ("lexical","metadata","popularity","rating")},
            "semantic_top10":[{"catalog_id":books[i].catalog_id,"title":books[i].title,"cosine":float(corrected[i]),"profile":books[i].search_text} for i in order(corrected)[:10]],
            "full_top10":[{"catalog_id":books[i].catalog_id,"title":books[i].title,"scores":scores[i],"profile":books[i].search_text} for i in full_order[:10]],
            "description_tokens":token_rows[target]["tokens"],"truncated":token_rows[target]["truncated"]})
    write("audit-results.json",{"model":model.model_name,"catalog_sha256":hashlib.sha256(settings.catalog_path.read_bytes()).hexdigest(),
                              "cases":len(rows),"reconstruction_matches":len(rows),"rows":rows})
    for r in rows:
        print(r["audit_id"],r["title"],r["support"],r["raw_semantic_rank"],r["corrected_semantic_rank"],r["full_rank_before_pool"],r["returned_rank"],r["parser_flags"],flush=True)
    print("Token lengths", {k:v for k,v in json.loads((OUT/'description-lengths.json').read_text(encoding='utf-8')).items() if k!='results'})

if __name__=="__main__": main()
